from datetime import date
from decimal import Decimal
from uuid import uuid4
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from app.database.connection import connection, get_connection
from app.config.settings import settings
from app.middleware.auth import require_retail
from app.schemas.scanner import RestockRequest
from app.services.inventory_agent import calculate_for_node, run_agent

router = APIRouter(prefix="/api/inventory", tags=["inventory"])

@router.get("/intelligence")
def inventory_intelligence(user=Depends(require_retail)):
    node = pharmacy_node(user)
    with connection() as conn:
        cur = conn.cursor(dictionary=True)
        rows = calculate_for_node(cur, node["node_id"])
        cur.close()
    return {"success": True, "restock_days_threshold": settings.restock_days_threshold, "batches": rows,
            "offers": [{"batch_id": r["batch_id"], "medicine_name": r["medicine_name"], "available_quantity": r["quantity"],
                        "normal_price": float(r["unit_price_inr"] or 0), "discount_percentage": r["discount_percentage"],
                        "offer_price": r["offer_price"], "days_left": r["days_left"], "expiry_status": r["risk_status"]}
                       for r in rows if r["quantity"] > 0 and r["discount_percentage"] > 0]}

@router.get("/intelligence/summary")
def inventory_intelligence_summary(user=Depends(require_retail)):
    node = pharmacy_node(user)
    with connection() as conn:
        cur = conn.cursor(dictionary=True)
        rows = calculate_for_node(cur, node["node_id"])
        cur.close()
    summary = {"total_batches": len(rows), "total_stock": sum(int(r["quantity"] or 0) for r in rows), "healthy_batches": 0, "restock_alerts": 0, "expiry_risk_batches": 0,
               "critical_batches": 0, "discount_30_percent_count": 0, "discount_50_percent_count": 0,
               "charity_fallback_count": 0, "expired_count": 0}
    for row in rows:
        summary["healthy_batches"] += int(row["risk_status"] == "HEALTHY")
        summary["restock_alerts"] += int(row["restock_recommended"])
        summary["expiry_risk_batches"] += int(row["risk_status"] in {"AT_RISK_90_DAYS", "AT_RISK_60_DAYS", "CRITICAL_30_DAYS"})
        summary["critical_batches"] += int(row["risk_status"] == "CRITICAL_30_DAYS")
        summary["discount_30_percent_count"] += int(row["discount_percentage"] == 30)
        summary["discount_50_percent_count"] += int(row["discount_percentage"] == 50)
        summary["charity_fallback_count"] += int(row["stock_status"] == "CHARITY_FALLBACK")
        summary["expired_count"] += int(row["stock_status"] == "EXPIRED")
    return {"success": True, "summary": summary}

@router.get("/alerts")
def inventory_alerts(user=Depends(require_retail)):
    node = pharmacy_node(user)
    with connection() as conn:
        cur = conn.cursor(dictionary=True)
        rows = calculate_for_node(cur, node["node_id"])
        cur.close()
    return {"success": True,
            "restock_alerts": [r for r in rows if r["restock_recommended"]],
            "expiry_alerts": [r for r in rows if r["risk_status"] in {"AT_RISK_90_DAYS", "AT_RISK_60_DAYS", "CRITICAL_30_DAYS"}],
            "discount_alerts": [r for r in rows if r["discount_percentage"] > 0],
            "charity_fallback_alerts": [r for r in rows if r["stock_status"] == "CHARITY_FALLBACK"]}

def pharmacy_node(user):
    node_id = user.get("node_id")
    if not node_id:
        raise HTTPException(409, "This account is not linked to a pharmacy node. Ask your PharmSync administrator to link it to the correct pharmacy_nodes.node_id.")
    with connection() as conn:
        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT node_id,node_name,node_type,city,state,address,latitude,longitude,verification_status FROM pharmacy_nodes WHERE node_id=%s AND LOWER(node_type)='pharmacy' LIMIT 1", (node_id,))
        node = cur.fetchone()
        cur.close()
    if not node:
        raise HTTPException(409, "This account is not linked to an active pharmacy node.")
    return node

def audit(cur, action, entity_type, entity_id, message):
    cur.execute("INSERT INTO audit_logs(log_id,`timestamp`,agent_name,action,entity_type,entity_id,status,message) VALUES(%s,NOW(),'PharmSync API',%s,%s,%s,'SUCCESS',%s)", ("LOG" + uuid4().hex[:20].upper(), action, entity_type, str(entity_id), message))

@router.get("")
def get_inventory(search: str = "", view: str | None = None, sellable: bool = False, user=Depends(require_retail)):
    node = pharmacy_node(user)
    where = ["b.node_id=%s"]
    params = [node["node_id"]]
    if search.strip():
        like = "%" + search.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        where.append("(b.medicine_name LIKE %s OR b.medicine_id LIKE %s OR b.batch LIKE %s OR b.batch_id LIKE %s OR b.batch_number LIKE %s)")
        params += [like] * 5
    if sellable or view == "pos":
        where.append("b.quantity-COALESCE(b.reserved_quantity,0)>0 AND LOWER(b.batch_status) IN ('active','available','at_risk_90_days','at_risk_60_days') AND DATEDIFF(b.expiry_date,CURDATE())>30")
    with connection() as conn:
        cur = conn.cursor(dictionary=True)
        cur.execute(f"""SELECT b.batch_id,b.medicine_id,b.medicine_name,b.batch,b.batch_number,b.node_id,b.quantity,
          COALESCE(b.reserved_quantity,0) AS reserved_quantity,(b.quantity-COALESCE(b.reserved_quantity,0)) AS available_quantity,
          b.unit_price_inr,b.manufacturing_date,b.expiry_date,b.batch_status,b.storage_condition,
          DATEDIFF(b.expiry_date,CURDATE()) AS days_remaining,COALESCE(v.quantity_30d/30,0) AS daily_sales_velocity,
          CASE WHEN b.quantity-COALESCE(b.reserved_quantity,0)>0 AND DATEDIFF(b.expiry_date,CURDATE()) BETWEEN 31 AND 60 THEN 50
               WHEN b.quantity-COALESCE(b.reserved_quantity,0)>0 AND DATEDIFF(b.expiry_date,CURDATE()) BETWEEN 61 AND 90 THEN 30 ELSE 0 END AS discount_percentage,
          ROUND(b.unit_price_inr * (1 - CASE WHEN b.quantity>0 AND DATEDIFF(b.expiry_date,CURDATE()) BETWEEN 31 AND 60 THEN 0.5
               WHEN b.quantity>0 AND DATEDIFF(b.expiry_date,CURDATE()) BETWEEN 61 AND 90 THEN 0.3 ELSE 0 END),2) AS offer_price
          FROM medicine_batches b LEFT JOIN (SELECT batch_id,SUM(quantity_sold) quantity_30d FROM sales
          WHERE pharmacy_id=%s AND sale_date>=DATE_SUB(CURDATE(),INTERVAL 29 DAY) AND sale_date<=CURDATE() GROUP BY batch_id) v ON v.batch_id=b.batch_id
          WHERE {' AND '.join(where)} ORDER BY b.expiry_date,b.medicine_name,b.batch_id""", (node["node_id"], *params))
        batches = cur.fetchall()
        cur.execute("SELECT COALESCE(SUM(quantity),0) totalStock,COALESCE(SUM(quantity*unit_price_inr),0) inventoryValue,COALESCE(SUM(CASE WHEN expiry_date>=CURDATE() AND expiry_date<=DATE_ADD(CURDATE(),INTERVAL 90 DAY) AND LOWER(batch_status) IN ('active','available','at_risk_90_days','at_risk_60_days','critical_30_days','charity_fallback') THEN quantity ELSE 0 END),0) nearExpiryStock,COALESCE(SUM(reserved_quantity),0) reservedStock FROM medicine_batches WHERE node_id=%s", (node["node_id"],))
        summary = cur.fetchone()
        cur.execute("SELECT COUNT(*) transferOpportunities FROM transfer_manifests WHERE source_pharmacy_id=%s AND LOWER(status) IN ('pending','offered','open','created')", (node["node_id"],))
        summary["transferOpportunities"] = cur.fetchone()["transferOpportunities"]
        cur.close()
    return {"success": True, "pharmacy": node, "summary": summary, "batches": batches}

@router.get("/batches/{batch_id}")
def get_batch(batch_id: str, user=Depends(require_retail)):
    node = pharmacy_node(user)
    with connection() as conn:
        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT *,DATEDIFF(expiry_date,CURDATE()) days_remaining FROM medicine_batches WHERE node_id=%s AND batch_id=%s", (node["node_id"], batch_id))
        row = cur.fetchone()
        cur.close()
    if not row: raise HTTPException(404, "Medicine batch not found.")
    return {"success": True, "batch": row}

@router.post("/restock")
def restock(body: RestockRequest, user=Depends(require_retail)):
    node = pharmacy_node(user)
    try:
        manufacture = date.fromisoformat(body.manufacture_date)
        expiry = date.fromisoformat(body.expiry_date)
    except ValueError: raise HTTPException(400, "Enter valid manufacturing and expiry dates.")
    if expiry <= manufacture: raise HTTPException(400, "Expiry date must be after the manufacturing date.")
    if manufacture > date.today(): raise HTTPException(400, "Manufacturing date cannot be in the future.")
    if expiry <= date.today(): raise HTTPException(400, "Expired medicine cannot be added to available inventory.")
    if not body.medicine_id.strip() or not body.medicine_name.strip() or not body.batch_number.strip():
        raise HTTPException(400, "Medicine ID, medicine name, and batch number are required.")
    if not Decimal(str(body.unit_price)).is_finite() or Decimal(str(body.unit_price)) > Decimal("9999999999.99"):
        raise HTTPException(400, "Enter a valid unit purchase price.")
    if body.storage_condition not in {"Ambient Room Temperature", "Cold Chain", "Unknown"}:
        raise HTTPException(400, "Choose Ambient Room Temperature, Cold Chain, or Unknown.")
    status = body.batch_status.lower()
    if status not in {"active", "available", "expired", "inactive", "discontinued"}:
        raise HTTPException(400, "Choose a valid batch status.")
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor(dictionary=True)
        medicine_id = body.medicine_id.strip()
        if body.gtin:
            cur.execute("SELECT medicine_id FROM medicines WHERE gtin=%s FOR UPDATE", (body.gtin,))
            catalog_match = cur.fetchone()
            if catalog_match:
                medicine_id = catalog_match["medicine_id"]
                cur.execute("UPDATE medicines SET medicine_name=%s,generic_name=%s,strength=%s,dosage_form=%s,manufacturer=%s WHERE medicine_id=%s", (body.medicine_name.strip(), (body.generic_name or "").strip() or None, (body.strength or "").strip() or None, (body.dosage_form or "").strip() or None, (body.manufacturer or "").strip() or None, medicine_id))
            else:
                cur.execute("SELECT gtin FROM medicines WHERE medicine_id=%s FOR UPDATE", (medicine_id,))
                id_match = cur.fetchone()
                if id_match and id_match["gtin"] and id_match["gtin"] != body.gtin:
                    raise HTTPException(409, "This PharmSync medicine ID is already linked to a different GTIN.")
                if id_match:
                    cur.execute("UPDATE medicines SET gtin=%s,medicine_name=%s,generic_name=%s,strength=%s,dosage_form=%s,manufacturer=%s WHERE medicine_id=%s", (body.gtin, body.medicine_name.strip(), (body.generic_name or "").strip() or None, (body.strength or "").strip() or None, (body.dosage_form or "").strip() or None, (body.manufacturer or "").strip() or None, medicine_id))
                else:
                    cur.execute("INSERT INTO medicines(medicine_id,gtin,medicine_name,generic_name,strength,dosage_form,manufacturer) VALUES(%s,%s,%s,%s,%s,%s,%s)", (medicine_id, body.gtin, body.medicine_name.strip(), (body.generic_name or "").strip() or None, (body.strength or "").strip() or None, (body.dosage_form or "").strip() or None, (body.manufacturer or "").strip() or None))
        cur.execute("SELECT batch_id,quantity FROM medicine_batches WHERE node_id=%s AND medicine_id=%s AND batch_number=%s FOR UPDATE", (node["node_id"], medicine_id, body.batch_number.strip()))
        existing = cur.fetchone()
        if existing:
            cur.execute("UPDATE medicine_batches SET quantity=quantity+%s,medicine_name=%s,batch=%s,unit_price_inr=%s,manufacturing_date=%s,expiry_date=%s,storage_condition=%s,batch_status=%s WHERE node_id=%s AND batch_id=%s", (body.quantity, body.medicine_name.strip(), (body.batch or "").strip() or None, Decimal(str(body.unit_price)), manufacture, expiry, body.storage_condition, status, node["node_id"], existing["batch_id"]))
            batch_id = existing["batch_id"]
            new_quantity = int(existing["quantity"]) + body.quantity
            message = f"{body.quantity} units of {body.medicine_name.strip()} added to batch {body.batch_number.strip()}."
            result = "updated"
        else:
            batch_id = "B" + uuid4().hex[:20].upper()
            cur.execute("INSERT INTO medicine_batches(batch_id,medicine_id,medicine_name,batch,batch_number,node_id,quantity,unit_price_inr,manufacturing_date,expiry_date,storage_condition,batch_status) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)", (batch_id, medicine_id, body.medicine_name.strip(), (body.batch or "").strip() or None, body.batch_number.strip(), node["node_id"], body.quantity, Decimal(str(body.unit_price)), manufacture, expiry, body.storage_condition, status))
            new_quantity = body.quantity
            message = f"{body.quantity} units of {body.medicine_name.strip()} added to batch {body.batch_number.strip()}."
            result = "created"
        audit(cur, "INVENTORY_RESTOCKED", "medicine_batch", batch_id, message)
        conn.commit()
        cur.close()
        return {"success": True, "result": result, "quantity_added": body.quantity, "batch": {"batch_id": batch_id, "medicine_id": medicine_id, "medicine_name": body.medicine_name, "batch": body.batch, "batch_number": body.batch_number, "node_id": node["node_id"], "quantity": new_quantity, "unit_price_inr": body.unit_price, "manufacturing_date": manufacture.isoformat(), "expiry_date": expiry.isoformat(), "storage_condition": body.storage_condition, "batch_status": status}}
    except Exception as exc:
        if conn: conn.rollback()
        if getattr(exc, "errno", None) == 1062: raise HTTPException(409, "This batch already exists. Refresh inventory and try again.")
        raise
    finally:
        if conn: conn.close()

@router.get("/restock-check")
def restock_check(medicine_id: str = Query(min_length=1), batch_number: str = Query(min_length=1), user=Depends(require_retail)):
    node = pharmacy_node(user)
    with connection() as conn:
        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT batch_id,medicine_id,medicine_name,batch_number,quantity,COALESCE(reserved_quantity,0) reserved_quantity,unit_price_inr,expiry_date,batch_status FROM medicine_batches WHERE node_id=%s AND medicine_id=%s AND batch_number=%s LIMIT 1", (node["node_id"], medicine_id.strip(), batch_number.strip()))
        existing = cur.fetchone()
        cur.close()
    return {"success": True, "exists": bool(existing), "batch": existing}

class BatchUpdate(BaseModel):
    medicine_id: str | None = None
    medicine_name: str | None = None
    batch_number: str | None = None
    quantity: int | None = Field(default=None, ge=0)
    unit_price_inr: float | None = Field(default=None, ge=0)
    manufacturing_date: str | None = None
    expiry_date: str | None = None
    batch_status: str | None = None

class BatchCreate(BaseModel):
    medicine_id: str = Field(min_length=1,max_length=32)
    medicine_name: str = Field(min_length=1,max_length=180)
    batch_number: str = Field(min_length=1,max_length=80)
    quantity: int = Field(gt=0)
    unit_price_inr: float = Field(ge=0)
    manufacturing_date: str
    expiry_date: str
    batch_status: str = "active"

@router.post("/batches",status_code=201)
def create_batch(body: BatchCreate,user=Depends(require_retail)):
    node=pharmacy_node(user)
    try:
        manufacture=date.fromisoformat(body.manufacturing_date);expiry=date.fromisoformat(body.expiry_date)
    except ValueError:raise HTTPException(400,"Enter valid manufacturing and expiry dates.")
    if expiry<manufacture:raise HTTPException(400,"Expiry date cannot be before the manufacture date.")
    if body.batch_status.lower() not in {"active","available","expired","inactive","discontinued"}:raise HTTPException(400,"Choose a valid batch status.")
    batch_id="B"+uuid4().hex[:20].upper()
    with connection() as conn:
        cur=conn.cursor()
        cur.execute("INSERT INTO medicine_batches(batch_id,medicine_id,medicine_name,batch_number,node_id,quantity,unit_price_inr,manufacturing_date,expiry_date,batch_status) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",(batch_id,body.medicine_id.strip(),body.medicine_name.strip(),body.batch_number.strip(),node["node_id"],body.quantity,Decimal(str(body.unit_price_inr)),manufacture,expiry,body.batch_status.lower()))
        audit(cur,"INVENTORY_CREATED","medicine_batch",batch_id,f"Batch {batch_id} added to node {node['node_id']}.")
        conn.commit();cur.close()
    return {"success":True,"batch":{"batch_id":batch_id,"node_id":node["node_id"],**body.model_dump()}}

@router.put("/batches/{batch_id}")
def update_batch(batch_id: str, body: BatchUpdate, user=Depends(require_retail)):
    node = pharmacy_node(user)
    values = body.model_dump(exclude_none=True)
    if not values: raise HTTPException(400,"No fields to update.")
    valid = {"medicine_id","medicine_name","batch_number","quantity","unit_price_inr","manufacturing_date","expiry_date","batch_status"}
    fields = {k:v for k,v in values.items() if k in valid}
    if "manufacturing_date" in fields: fields["manufacturing_date"] = date.fromisoformat(fields["manufacturing_date"])
    if "expiry_date" in fields: fields["expiry_date"] = date.fromisoformat(fields["expiry_date"])
    with connection() as conn:
        cur=conn.cursor(dictionary=True)
        cur.execute("SELECT * FROM medicine_batches WHERE node_id=%s AND batch_id=%s FOR UPDATE",(node["node_id"],batch_id)); old=cur.fetchone()
        if not old: raise HTTPException(404,"Medicine batch not found.")
        if "quantity" in fields and int(fields["quantity"]) < int(old.get("reserved_quantity") or 0):
            raise HTTPException(409,"Quantity cannot be adjusted below the units reserved for patient orders.")
        fields={k:v for k,v in fields.items() if k in valid}
        assignments=",".join(f"{key}=%s" for key in fields)
        cur.execute(f"UPDATE medicine_batches SET {assignments} WHERE node_id=%s AND batch_id=%s",tuple(fields.values())+(node["node_id"],batch_id))
        action="STOCK_ADJUSTED" if "quantity" in fields and int(fields["quantity"]) != int(old["quantity"]) else "INVENTORY_UPDATED"
        audit(cur,action,"medicine_batch",batch_id,f"Batch {batch_id} updated.")
        conn.commit();cur.close()
    return {"success":True}

@router.delete("/batches/{batch_id}")
def delete_batch(batch_id: str, user=Depends(require_retail)):
    node=pharmacy_node(user)
    with connection() as conn:
        cur=conn.cursor(dictionary=True)
        cur.execute("SELECT batch_id FROM medicine_batches WHERE node_id=%s AND batch_id=%s FOR UPDATE",(node["node_id"],batch_id))
        if not cur.fetchone(): raise HTTPException(404,"Medicine batch not found.")
        cur.execute("SELECT reserved_quantity FROM medicine_batches WHERE node_id=%s AND batch_id=%s FOR UPDATE", (node["node_id"],batch_id))
        if int(cur.fetchone()["reserved_quantity"] or 0) > 0:
            raise HTTPException(409,"This batch has units reserved for patient orders and cannot be deleted.")
        cur.execute("SELECT sale_id FROM sales WHERE batch_id=%s LIMIT 1",(batch_id,))
        if cur.fetchone(): raise HTTPException(409,"This batch has sales history and cannot be removed.")
        cur.execute("DELETE FROM medicine_batches WHERE node_id=%s AND batch_id=%s",(node["node_id"],batch_id))
        audit(cur,"INVENTORY_UPDATED","medicine_batch",batch_id,"Batch removed from inventory.")
        conn.commit();cur.close()
    return {"success":True}

@router.get("/velocity")
def velocity(user=Depends(require_retail)):
    node=pharmacy_node(user)
    with connection() as conn:
        cur=conn.cursor(dictionary=True)
        cur.execute("SELECT batch_id,MAX(medicine_name) medicine_name,SUM(quantity_sold) quantity_sold_30d,SUM(quantity_sold)/30 daily_sales_velocity FROM sales WHERE pharmacy_id=%s AND sale_date>=DATE_SUB(CURDATE(),INTERVAL 30 DAY) AND sale_date<=CURDATE() GROUP BY batch_id ORDER BY daily_sales_velocity DESC",(node["node_id"],));rows=cur.fetchall();cur.close()
    return {"success":True,"windowDays":30,"rows":rows}

