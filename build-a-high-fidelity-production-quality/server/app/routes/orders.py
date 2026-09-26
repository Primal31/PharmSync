from decimal import Decimal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.config.settings import settings
from app.database.connection import connection, get_connection
from app.middleware.auth import current_user, require_patient, require_retail
from app.routes.inventory import audit, pharmacy_node
from app.services.inventory_intelligence import evaluate_batch
from app.services.patient_marketplace import OFFER_RISKS
from app.services.order_rules import allowed_transition, available_stock, quantity_limit_message

orders_router = APIRouter(prefix="/api/orders", tags=["medicine orders"])
pharmacy_router = APIRouter(prefix="/api/pharmacy/orders", tags=["pharmacy order management"])


class CreateOrder(BaseModel):
    batch_id: str = Field(min_length=1, max_length=32)
    quantity: int = Field(gt=0)


class StatusChange(BaseModel):
    status: str


def _status(value):
    return str(value or "").upper().replace(" ", "_")


def _order_select():
    return """SELECT o.order_id,o.user_id,o.node_id,o.batch_id,o.medicine_id,o.medicine_name,o.quantity,
        o.original_unit_price,o.discount_percent,o.discounted_unit_price,o.total_amount,o.status,o.created_at,o.updated_at,
        n.node_name AS pharmacy_name,n.city,n.state,u.full_name AS patient_name
        FROM medicine_orders o JOIN pharmacy_nodes n ON n.node_id=o.node_id JOIN users u ON u.id=o.user_id"""


def _audit_order(cur, action, order_id, message):
    audit(cur, action, "medicine_order", order_id, message)


@orders_router.post("", status_code=201)
def create_order(body: CreateOrder, user=Depends(require_patient)):
    limit_error = quantity_limit_message(body.quantity, settings.max_user_order_quantity)
    if limit_error:
        raise HTTPException(400, limit_error)
    conn = get_connection()
    try:
        conn.start_transaction()
        cur = conn.cursor(dictionary=True)
        cur.execute("""SELECT b.batch_id,b.medicine_id,b.medicine_name,b.node_id,b.quantity,b.reserved_quantity,
            b.unit_price_inr,b.manufacturing_date,b.expiry_date,b.batch_status,n.node_name,n.verification_status,
            COALESCE(s.quantity_30d,0) AS quantity_30d,CURDATE() AS today
            FROM medicine_batches b JOIN pharmacy_nodes n ON n.node_id=b.node_id
            LEFT JOIN (SELECT batch_id,pharmacy_id,SUM(quantity_sold) AS quantity_30d FROM sales
              WHERE sale_date>=DATE_SUB(CURDATE(),INTERVAL 29 DAY) AND sale_date<=CURDATE()
              GROUP BY batch_id,pharmacy_id) s ON s.batch_id=b.batch_id AND s.pharmacy_id=b.node_id
            WHERE b.batch_id=%s FOR UPDATE""", (body.batch_id,))
        batch = cur.fetchone()
        if not batch:
            raise HTTPException(404, "This medicine offer is no longer available.")
        if str(batch["verification_status"]).casefold() not in {"verified", "approved", "active"}:
            raise HTTPException(409, "This pharmacy is not currently verified for marketplace requests.")
        status = str(batch["batch_status"] or "").casefold()
        available = available_stock(batch["quantity"], batch["reserved_quantity"])
        if status in {"inactive", "discontinued", "expired", "charity_fallback", "critical_30_days"} or available < body.quantity:
            raise HTTPException(409, "This medicine offer no longer has enough eligible stock.")
        assessed = evaluate_batch({**batch, "quantity": available}, batch["quantity_30d"], batch["today"], settings.restock_days_threshold)
        if assessed["risk_status"] not in OFFER_RISKS:
            raise HTTPException(409, "This medicine is no longer eligible for a discounted marketplace request.")
        unit = Decimal(str(assessed["offer_price"])).quantize(Decimal("0.01"))
        original = Decimal(str(batch["unit_price_inr"])).quantize(Decimal("0.01"))
        total = (unit * body.quantity).quantize(Decimal("0.01"))
        order_id = "O" + uuid4().hex[:24].upper()
        cur.execute("UPDATE medicine_batches SET reserved_quantity=reserved_quantity+%s WHERE batch_id=%s AND quantity-reserved_quantity>=%s",
                    (body.quantity, body.batch_id, body.quantity))
        if cur.rowcount != 1:
            raise HTTPException(409, "This medicine offer no longer has enough available stock.")
        cur.execute("""INSERT INTO medicine_orders(order_id,user_id,node_id,batch_id,medicine_id,medicine_name,quantity,
            original_unit_price,discount_percent,discounted_unit_price,total_amount,status)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'PENDING')""",
            (order_id, user["id"], batch["node_id"], batch["batch_id"], batch["medicine_id"], batch["medicine_name"],
             body.quantity, original, assessed["discount_percentage"], unit, total))
        _audit_order(cur, "MEDICINE_ORDER_CREATED", order_id,
                     f"Patient {user['id']} requested {body.quantity} strips of {batch['medicine_name']} from {batch['node_name']}; stock reserved.")
        conn.commit()
        cur.execute(_order_select() + " WHERE o.order_id=%s", (order_id,))
        order = cur.fetchone(); cur.close()
        return {"success": True, "message": "Your medicine request has been sent to the pharmacy and is awaiting confirmation.", "order": order}
    except HTTPException:
        conn.rollback(); raise
    except Exception:
        conn.rollback(); raise
    finally:
        conn.close()


@orders_router.get("/my")
def my_orders(user=Depends(require_patient)):
    with connection() as conn:
        cur = conn.cursor(dictionary=True)
        cur.execute(_order_select() + " WHERE o.user_id=%s ORDER BY o.created_at DESC,o.order_id DESC LIMIT 250", (user["id"],))
        rows = cur.fetchall(); cur.close()
    return {"success": True, "orders": rows}


@orders_router.get("/{order_id}")
def order_detail(order_id: str, user=Depends(current_user)):
    with connection() as conn:
        cur = conn.cursor(dictionary=True)
        cur.execute(_order_select() + " WHERE o.order_id=%s LIMIT 1", (order_id,))
        row = cur.fetchone(); cur.close()
    if not row:
        raise HTTPException(404, "Medicine order not found.")
    if user["role"] == "patient" and int(row["user_id"]) != int(user["id"]):
        raise HTTPException(404, "Medicine order not found.")
    if user["role"] == "retail_chemist":
        node = pharmacy_node(user)
        if row["node_id"] != node["node_id"]:
            raise HTTPException(404, "Medicine order not found.")
    else:
        raise HTTPException(403, "This order is not available to your account type.")
    return {"success": True, "order": row}


@orders_router.post("/{order_id}/cancel")
def cancel_order(order_id: str, user=Depends(require_patient)):
    conn = get_connection()
    try:
        conn.start_transaction(); cur = conn.cursor(dictionary=True)
        cur.execute("SELECT * FROM medicine_orders WHERE order_id=%s AND user_id=%s FOR UPDATE", (order_id, user["id"]))
        order = cur.fetchone()
        if not order:
            raise HTTPException(404, "Medicine order not found.")
        if _status(order["status"]) not in {"PENDING", "CONFIRMED"}:
            raise HTTPException(409, "Only pending or confirmed requests can be cancelled.")
        cur.execute("SELECT quantity,reserved_quantity FROM medicine_batches WHERE batch_id=%s AND node_id=%s FOR UPDATE", (order["batch_id"], order["node_id"]))
        batch = cur.fetchone()
        if not batch or int(batch["reserved_quantity"]) < int(order["quantity"]):
            raise HTTPException(409, "The stock reservation could not be safely released. Contact the pharmacy.")
        cur.execute("UPDATE medicine_batches SET reserved_quantity=reserved_quantity-%s WHERE batch_id=%s", (order["quantity"], order["batch_id"]))
        cur.execute("UPDATE medicine_orders SET status='CANCELLED' WHERE order_id=%s AND status=%s", (order_id, order["status"]))
        if cur.rowcount != 1:
            raise HTTPException(409, "The order status changed. Refresh and try again.")
        _audit_order(cur, "ORDER_CANCELLED", order_id, f"Patient {user['id']} cancelled {order['medicine_name']}; reserved stock released.")
        conn.commit(); cur.close()
        return {"success": True, "order_id": order_id, "status": "CANCELLED"}
    except HTTPException:
        conn.rollback(); raise
    except Exception:
        conn.rollback(); raise
    finally:
        conn.close()


@pharmacy_router.get("")
def pharmacy_orders(user=Depends(require_retail)):
    node = pharmacy_node(user)
    with connection() as conn:
        cur = conn.cursor(dictionary=True)
        cur.execute(_order_select() + " WHERE o.node_id=%s ORDER BY FIELD(o.status,'PENDING','CONFIRMED','READY_FOR_PICKUP','COMPLETED','CANCELLED'),o.created_at DESC LIMIT 500", (node["node_id"],))
        rows = cur.fetchall(); cur.close()
    return {"success": True, "orders": rows, "pending_count": sum(_status(row["status"]) == "PENDING" for row in rows)}


@pharmacy_router.patch("/{order_id}/status")
def update_order_status(order_id: str, body: StatusChange, user=Depends(require_retail)):
    node = pharmacy_node(user)
    target = _status(body.status)
    conn = get_connection()
    try:
        conn.start_transaction(); cur = conn.cursor(dictionary=True)
        cur.execute("SELECT * FROM medicine_orders WHERE order_id=%s AND node_id=%s FOR UPDATE", (order_id, node["node_id"]))
        order = cur.fetchone()
        if not order:
            raise HTTPException(404, "Medicine order not found for this pharmacy.")
        current = _status(order["status"])
        action = allowed_transition(current, target)
        if not action:
            raise HTTPException(409, "This order status transition is not allowed.")
        if target == "CONFIRMED" and quantity_limit_message(int(order["quantity"]), settings.max_user_order_quantity):
            raise HTTPException(409, f"This order exceeds the current maximum of {settings.max_user_order_quantity} strips per medicine.")
        cur.execute("SELECT quantity,reserved_quantity,unit_price_inr,manufacturing_date,expiry_date,batch_status,medicine_id,medicine_name FROM medicine_batches WHERE batch_id=%s AND node_id=%s FOR UPDATE", (order["batch_id"], node["node_id"]))
        batch = cur.fetchone()
        quantity = int(order["quantity"])
        if not batch or int(batch["reserved_quantity"]) < quantity or int(batch["quantity"]) < quantity:
            raise HTTPException(409, "The reserved stock is no longer valid. Contact the patient before proceeding.")
        if target == "CONFIRMED":
            if (batch["expiry_date"] <= __import__("datetime").date.today()
                    or str(batch["batch_status"]).casefold() in {"inactive", "discontinued", "expired", "charity_fallback", "critical_30_days"}):
                raise HTTPException(409, "This medicine batch is no longer eligible. Cancel the request to release its reservation.")
            cur.execute("SELECT COALESCE(SUM(quantity_sold),0) AS quantity_30d FROM sales WHERE batch_id=%s AND pharmacy_id=%s AND sale_date>=DATE_SUB(CURDATE(),INTERVAL 29 DAY) AND sale_date<=CURDATE()", (order["batch_id"], node["node_id"]))
            sold = cur.fetchone()["quantity_30d"]
            cur.execute("SELECT CURDATE() AS today")
            # Include this order's own reservation when reevaluating unsold expiry risk.
            assess_qty = int(batch["quantity"]) - int(batch["reserved_quantity"]) + quantity
            risk = evaluate_batch({**batch, "quantity": assess_qty}, sold, cur.fetchone()["today"], settings.restock_days_threshold)
            if risk["risk_status"] not in OFFER_RISKS:
                raise HTTPException(409, "This batch is no longer in an eligible discounted expiry stage. Cancel the request to release its reservation.")
        if target == "CANCELLED":
            cur.execute("UPDATE medicine_batches SET reserved_quantity=reserved_quantity-%s WHERE batch_id=%s AND reserved_quantity>=%s", (quantity, order["batch_id"], quantity))
            if cur.rowcount != 1:
                raise HTTPException(409, "The stock reservation could not be safely released.")
        elif target == "COMPLETED":
            cur.execute("UPDATE medicine_batches SET quantity=quantity-%s,reserved_quantity=reserved_quantity-%s WHERE batch_id=%s AND node_id=%s AND quantity>=%s AND reserved_quantity>=%s", (quantity, quantity, order["batch_id"], node["node_id"], quantity, quantity))
            if cur.rowcount != 1:
                raise HTTPException(409, "Stock changed before completion; no inventory was deducted.")
            sale_id = "S" + uuid4().hex[:20].upper()
            cur.execute("""INSERT INTO sales(sale_id,order_id,sale_date,pharmacy_id,batch_id,medicine_id,medicine_name,
                quantity_sold,unit_price_inr,total_amount_inr)
                VALUES(%s,%s,CURDATE(),%s,%s,%s,%s,%s,%s,%s)""",
                (sale_id, order_id, node["node_id"], order["batch_id"], order["medicine_id"], order["medicine_name"],
                 quantity, order["discounted_unit_price"], order["total_amount"]))
            audit(cur, "SALE_CREATED", "sale", sale_id, f"Completed patient medicine order {order_id}; {quantity} units of {order['medicine_name']} sold.")
        cur.execute("UPDATE medicine_orders SET status=%s WHERE order_id=%s AND status=%s", (target, order_id, order["status"]))
        if cur.rowcount != 1:
            raise HTTPException(409, "The order status changed. Refresh and try again.")
        _audit_order(cur, action, order_id, f"Pharmacy {node['node_name']} changed order for {order['medicine_name']} ({quantity} strips) from {current} to {target}.")
        conn.commit(); cur.close()
        return {"success": True, "order_id": order_id, "status": target}
    except HTTPException:
        conn.rollback(); raise
    except Exception:
        conn.rollback(); raise
    finally:
        conn.close()
