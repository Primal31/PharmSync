from datetime import date
from decimal import Decimal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.database.connection import connection, get_connection
from app.config.settings import settings
from app.middleware.auth import current_user
from app.routes.inventory import pharmacy_node
from app.services.inventory_intelligence import evaluate_batch
from app.services.p2p_matching import ELIGIBLE_RISK, build_opportunities, get_opportunity, opportunity_id

router = APIRouter(prefix="/api/transfers", tags=["P2P redistribution"])
RETAIL = "retail_chemist"
CLINIC = "clinic_phc"
CHARITY = "charity_ngo"
PENDING = "PENDING_APPROVAL"
ACTIVE_TRANSFER_STATES = {"pending_approval", "approved", "in_transit", "received"}


class TransferStatusBody(BaseModel):
    status: str = Field(min_length=1, max_length=40)


def _node_for(user, expected_role: str | None = None) -> str:
    if expected_role and user["role"] != expected_role:
        raise HTTPException(403, "This transfer action is not available for your account type.")
    if user["role"] == CHARITY:
        raise HTTPException(403, "Charity redistribution is a separate workflow from P2P transfers.")
    node_id = user.get("node_id")
    if not node_id:
        raise HTTPException(409, "Your account is not linked to a verified network node. Ask a PharmSync administrator to link your account.")
    return str(node_id)


def _user_scope(user, expected_role: str | None = None) -> str:
    if expected_role and user["role"] != expected_role:
        raise HTTPException(403, "This transfer action is not available for your account type.")
    if user["role"] not in {RETAIL, CLINIC}:
        raise HTTPException(403, "P2P transfers are available to verified pharmacies and clinics.")
    node_id = _node_for(user)
    if user["role"] == RETAIL:
        return pharmacy_node(user)["node_id"]
    with connection() as conn:
        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT node_id,node_type,verification_status FROM pharmacy_nodes WHERE node_id=%s LIMIT 1", (node_id,))
        node = cur.fetchone(); cur.close()
    if not node or str(node["node_type"]).casefold() not in {"clinic", "phc", "clinic/phc", "healthcare organization", "healthcare"}:
        raise HTTPException(409, "Your account is not linked to an active clinic or healthcare node.")
    if str(node["verification_status"]).casefold() not in {"verified", "approved", "active"}:
        raise HTTPException(403, "Your healthcare node must be verified before reviewing transfer opportunities.")
    return node_id


def _audit(cur, action: str, transfer_id: str, message: str) -> None:
    cur.execute("INSERT INTO audit_logs(log_id,`timestamp`,agent_name,action,entity_type,entity_id,status,message) VALUES(%s,NOW(),'P2P Redistribution',%s,'transfer',%s,'SUCCESS',%s)",
                ("LOG" + uuid4().hex[:20].upper(), action, transfer_id, message))


def _status_key(value: str) -> str:
    return str(value or "").strip().casefold().replace(" ", "_").replace("-", "_")


def _get_scoped_transfer(cur, transfer_id: str, node_id: str) -> dict:
    cur.execute("""SELECT t.*,s.node_name AS source_pharmacy_name,d.node_name AS destination_clinic_name
        FROM transfer_manifests t JOIN pharmacy_nodes s ON s.node_id=t.source_pharmacy_id
        JOIN pharmacy_nodes d ON d.node_id=t.destination_clinic_id
        WHERE t.transfer_id=%s AND (t.source_pharmacy_id=%s OR t.destination_clinic_id=%s) LIMIT 1 FOR UPDATE""",
        (transfer_id, node_id, node_id))
    row = cur.fetchone()
    if not row:
        raise HTTPException(404, "Transfer not found for this network node.")
    return row


def _approve_locked(cur, transfer: dict, actor_node: str) -> dict:
    transfer_id = str(transfer["transfer_id"])
    source_id, destination_id = str(transfer["source_pharmacy_id"]), str(transfer["destination_clinic_id"])
    batch_id, demand_id = str(transfer["batch_id"]), str(transfer["demand_id"] or "")
    quantity = int(transfer["quantity"])
    if actor_node != source_id:
        raise HTTPException(403, "Only the source pharmacy can approve this transfer.")
    if _status_key(transfer["status"]) != "pending_approval":
        raise HTTPException(409, "This transfer is no longer awaiting approval.")
    if not demand_id:
        raise HTTPException(409, "This legacy transfer has no linked demand record and cannot use the new approval flow.")

    cur.execute("""SELECT b.batch_id,b.medicine_id,b.medicine_name,b.batch,b.batch_number,b.node_id,b.quantity,
        COALESCE(b.reserved_quantity,0) AS reserved_quantity,
        b.unit_price_inr,b.manufacturing_date,b.expiry_date,b.batch_status,b.storage_condition,
        n.node_name AS source_pharmacy_name,n.node_type AS source_node_type,n.verification_status AS source_verification,
        n.latitude AS source_latitude,n.longitude AS source_longitude
        FROM medicine_batches b JOIN pharmacy_nodes n ON n.node_id=b.node_id
        WHERE b.batch_id=%s AND b.node_id=%s FOR UPDATE""", (batch_id, source_id))
    source = cur.fetchone()
    cur.execute("""SELECT d.demand_id,d.clinic_id,d.medicine_id,d.medicine_name,d.form,d.current_stock,
        d.daily_demand,d.required_quantity,d.shortage_quantity,d.priority,
        n.node_name AS destination_clinic_name,n.node_type AS destination_node_type,
        n.verification_status AS destination_verification,n.latitude AS destination_latitude,n.longitude AS destination_longitude
        FROM clinic_demand d JOIN pharmacy_nodes n ON n.node_id=d.clinic_id
        WHERE d.demand_id=%s FOR UPDATE""", (demand_id,))
    demand = cur.fetchone()
    if not source or not demand:
        raise HTTPException(409, "This redistribution opportunity is no longer available.")
    if demand["clinic_id"] != destination_id or source["medicine_id"] != demand["medicine_id"]:
        raise HTTPException(409, "The batch and destination demand no longer match.")
    if " ".join(str(source["medicine_name"]).casefold().split()) != " ".join(str(demand["medicine_name"]).casefold().split()):
        raise HTTPException(409, "The source batch product does not match the clinic demand record.")
    if not str(source["source_node_type"]).casefold() in {"pharmacy", "retail pharmacy", "retail_pharmacy"} or str(source["source_verification"]).casefold() not in {"verified", "approved", "active"}:
        raise HTTPException(403, "The source pharmacy must be verified before transferring stock.")
    if str(demand["destination_node_type"]).casefold() not in {"clinic", "phc", "clinic/phc", "healthcare organization", "healthcare"} or str(demand["destination_verification"]).casefold() not in {"verified", "approved", "active"}:
        raise HTTPException(403, "The destination must be a verified healthcare node.")
    source_available = int(source["quantity"]) - int(source["reserved_quantity"] or 0)
    if source_available < quantity:
        raise HTTPException(409, f"This opportunity is no longer available. Only {source_available} units remain available at the source.")

    cur.execute("""SELECT COALESCE(SUM(quantity),0) AS reserved FROM transfer_manifests
        WHERE demand_id=%s AND transfer_id<>%s AND LOWER(REPLACE(status,' ','_'))='pending_approval' FOR UPDATE""",
        (demand_id, transfer_id))
    reserved_other = int(cur.fetchone()["reserved"] or 0)
    shortage_units = int(float(demand["shortage_quantity"] or 0)) - reserved_other
    if shortage_units < quantity:
        raise HTTPException(409, "This opportunity is no longer available. The clinic shortage has changed or is already reserved.")
    if quantity <= 0:
        raise HTTPException(409, "Transfer quantity must be greater than zero.")

    cur.execute("SELECT COALESCE(SUM(quantity_sold),0) AS quantity_30d FROM sales WHERE batch_id=%s AND pharmacy_id=%s AND sale_date>=DATE_SUB(CURDATE(),INTERVAL 29 DAY) AND sale_date<=CURDATE()", (batch_id, source_id))
    sales_30d = cur.fetchone()["quantity_30d"]
    cur.execute("SELECT CURDATE() AS today")
    assessed = evaluate_batch({**source, "quantity": source_available}, sales_30d, cur.fetchone()["today"], settings.restock_days_threshold)
    if (assessed["risk_status"] not in ELIGIBLE_RISK or assessed["days_left"] <= 30
            or assessed["projected_remaining"] <= 0 or assessed["stock_status"] in {"CHARITY_FALLBACK", "EXPIRED"}):
        raise HTTPException(409, "This batch no longer qualifies for normal P2P redistribution.")
    if assessed["days_left"] <= 0:
        raise HTTPException(409, "Expired medicine cannot be transferred.")
    if opportunity_id(source_id, destination_id, batch_id, demand_id, quantity) != str(transfer["match_id"]):
        raise HTTPException(409, "This redistribution opportunity has changed. Refresh and review the current match.")

    new_source_quantity = int(source["quantity"]) - quantity
    cur.execute("UPDATE medicine_batches SET quantity=quantity-%s WHERE node_id=%s AND batch_id=%s AND quantity-reserved_quantity>=%s",
                (quantity, source_id, batch_id, quantity))
    if cur.rowcount != 1:
        raise HTTPException(409, "Source stock changed before approval. Refresh and try again.")

    cur.execute("""SELECT batch_id,medicine_name,manufacturing_date,expiry_date,quantity
        FROM medicine_batches WHERE node_id=%s AND medicine_id=%s AND batch_number=%s FOR UPDATE""",
        (destination_id, source["medicine_id"], source["batch_number"]))
    destination_batch = cur.fetchone()
    if destination_batch:
        if (" ".join(str(destination_batch["medicine_name"]).casefold().split()) != " ".join(str(source["medicine_name"]).casefold().split())
                or destination_batch["manufacturing_date"] != source["manufacturing_date"]
                or destination_batch["expiry_date"] != source["expiry_date"]):
            raise HTTPException(409, "The destination has a different lot record with this batch number. Resolve the batch details before transfer.")
        cur.execute("UPDATE medicine_batches SET quantity=quantity+%s WHERE node_id=%s AND batch_id=%s", (quantity, destination_id, destination_batch["batch_id"]))
        destination_batch_id = destination_batch["batch_id"]
    else:
        destination_batch_id = "T" + uuid4().hex[:24].upper()
        cur.execute("""INSERT INTO medicine_batches(batch_id,medicine_id,medicine_name,batch,batch_number,node_id,
            quantity,unit_price_inr,manufacturing_date,expiry_date,storage_condition,batch_status)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'active')""",
            (destination_batch_id, source["medicine_id"], source["medicine_name"], source["batch"], source["batch_number"],
             destination_id, quantity, source["unit_price_inr"], source["manufacturing_date"], source["expiry_date"], source["storage_condition"]))
    cur.execute("UPDATE clinic_demand SET current_stock=current_stock+%s,shortage_quantity=GREATEST(shortage_quantity-%s,0) WHERE demand_id=%s AND clinic_id=%s AND shortage_quantity>=%s",
                (quantity, quantity, demand_id, destination_id, quantity))
    if cur.rowcount != 1:
        raise HTTPException(409, "Clinic demand changed before approval. The stock operation was cancelled.")
    reason = (f"Expiry-risk source: {assessed['risk_status']} with {assessed['days_left']} days remaining and "
              f"{assessed['projected_remaining']:.1f} units projected at current sales velocity. "
              f"Destination demand {demand_id} ({demand['priority']}) had a {float(demand['shortage_quantity']):g}-unit shortage.")
    cur.execute("UPDATE transfer_manifests SET status='APPROVED',decision_reason=%s WHERE transfer_id=%s AND LOWER(REPLACE(status,' ','_'))='pending_approval'",
                (reason, transfer_id))
    if cur.rowcount != 1:
        raise HTTPException(409, "This transfer has already been approved or changed.")
    _audit(cur, "TRANSFER_APPROVED", transfer_id,
           f"Approved {quantity} units of {source['medicine_name']} from {source['source_pharmacy_name']} to {demand['destination_clinic_name']}; destination batch {destination_batch_id}.")
    return {"transfer_id": transfer_id, "status": "APPROVED", "quantity": quantity,
            "source_quantity_remaining": new_source_quantity, "destination_batch_id": destination_batch_id,
            "reason": reason}


@router.get("/opportunities")
def opportunities(user=Depends(current_user)):
    node_id = _user_scope(user)
    with connection() as conn:
        cur = conn.cursor(dictionary=True)
        rows = build_opportunities(cur, node_id)
        cur.close()
    return {"success": True, "role": user["role"], "matches": rows,
            "message": None if rows else "No redistribution opportunities detected."}


@router.get("/opportunities/{match_id}")
def opportunity_detail(match_id: str, user=Depends(current_user)):
    node_id = _user_scope(user)
    with connection() as conn:
        cur = conn.cursor(dictionary=True)
        match = get_opportunity(cur, match_id, node_id)
        cur.close()
    if not match:
        raise HTTPException(404, "This redistribution opportunity is no longer available.")
    return {"success": True, "match": match}


@router.post("/opportunities/{match_id}/request", status_code=201)
def request_opportunity(match_id: str, user=Depends(current_user)):
    node_id = _user_scope(user, CLINIC)
    conn = get_connection()
    try:
        conn.start_transaction()
        cur = conn.cursor(dictionary=True)
        match = get_opportunity(cur, match_id, node_id)
        if not match or match["destination_clinic_id"] != node_id:
            raise HTTPException(404, "This redistribution opportunity is no longer available for your clinic.")
        cur.execute("SELECT transfer_id,status FROM transfer_manifests WHERE match_id=%s FOR UPDATE", (match_id,))
        existing = cur.fetchone()
        if existing:
            raise HTTPException(409, "This redistribution opportunity has already been requested or reviewed.")
        transfer_id = "T" + uuid4().hex[:24].upper()
        cur.execute("""INSERT INTO transfer_manifests(transfer_id,match_id,demand_id,transfer_date,source_pharmacy_id,
            destination_clinic_id,batch_id,medicine_id,medicine_name,quantity,status,decision_reason,distance_km)
            VALUES(%s,%s,%s,CURDATE(),%s,%s,%s,%s,%s,%s,'PENDING_APPROVAL',%s,%s)""",
            (transfer_id, match_id, match["demand_id"], match["source_pharmacy_id"], match["destination_clinic_id"],
             match["batch_id"], match["medicine_id"], match["medicine_name"], match["suggested_transfer_quantity"],
             match["reason"], match["distance_kilometer"]))
        _audit(cur, "TRANSFER_MATCH_CREATED", transfer_id,
               f"Clinic {match['destination_clinic_name']} requested {match['suggested_transfer_quantity']} units of {match['medicine_name']} from {match['source_pharmacy_name']}.")
        conn.commit(); cur.close()
        return {"success": True, "transfer_id": transfer_id, "status": PENDING,
                "message": "Transfer request sent to the source pharmacy for approval."}
    except HTTPException:
        conn.rollback(); raise
    except Exception as exc:
        conn.rollback()
        if getattr(exc, "errno", None) == 1062:
            raise HTTPException(409, "This redistribution opportunity has already been requested.")
        raise
    finally:
        conn.close()


@router.post("/opportunities/{match_id}/approve")
def approve_suggested_opportunity(match_id: str, user=Depends(current_user)):
    node_id = _user_scope(user, RETAIL)
    conn = get_connection()
    try:
        conn.start_transaction()
        cur = conn.cursor(dictionary=True)
        match = get_opportunity(cur, match_id, node_id)
        if not match or match["source_pharmacy_id"] != node_id:
            raise HTTPException(404, "This redistribution opportunity is no longer available for your pharmacy.")
        cur.execute("SELECT transfer_id,status FROM transfer_manifests WHERE match_id=%s FOR UPDATE", (match_id,))
        if cur.fetchone():
            raise HTTPException(409, "This opportunity has already been requested or reviewed. Use the transfer queue.")
        transfer_id = "T" + uuid4().hex[:24].upper()
        cur.execute("""INSERT INTO transfer_manifests(transfer_id,match_id,demand_id,transfer_date,source_pharmacy_id,
            destination_clinic_id,batch_id,medicine_id,medicine_name,quantity,status,decision_reason,distance_km)
            VALUES(%s,%s,%s,CURDATE(),%s,%s,%s,%s,%s,%s,'PENDING_APPROVAL',%s,%s)""",
            (transfer_id, match_id, match["demand_id"], match["source_pharmacy_id"], match["destination_clinic_id"],
             match["batch_id"], match["medicine_id"], match["medicine_name"], match["suggested_transfer_quantity"],
             match["reason"], match["distance_kilometer"]))
        _audit(cur, "TRANSFER_MATCH_CREATED", transfer_id, f"A verified P2P opportunity was reviewed by {match['source_pharmacy_name']}.")
        cur.execute("SELECT * FROM transfer_manifests WHERE transfer_id=%s FOR UPDATE", (transfer_id,))
        result = _approve_locked(cur, cur.fetchone(), node_id)
        conn.commit(); cur.close()
        return {"success": True, **result}
    except HTTPException:
        conn.rollback(); raise
    except Exception as exc:
        conn.rollback()
        if getattr(exc, "errno", None) == 1062:
            raise HTTPException(409, "This opportunity has already been approved or requested.")
        raise
    finally:
        conn.close()


@router.get("/demand")
def clinic_demand(user=Depends(current_user)):
    node_id = _user_scope(user, CLINIC)
    with connection() as conn:
        cur = conn.cursor(dictionary=True)
        cur.execute("""SELECT demand_id,clinic_id,medicine_id,medicine_name,form,current_stock,daily_demand,
            required_quantity,shortage_quantity,priority FROM clinic_demand WHERE clinic_id=%s
            ORDER BY CASE LOWER(priority) WHEN 'critical' THEN 0 WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END,
            shortage_quantity DESC,demand_id""", (node_id,))
        rows = cur.fetchall(); cur.close()
    return {"success": True, "demands": rows}


@router.get("/charity-fallback")
def charity_fallback_inventory(user=Depends(current_user)):
    node_id = _user_scope(user, RETAIL)
    with connection() as conn:
        cur = conn.cursor(dictionary=True)
        cur.execute("""SELECT b.batch_id,b.medicine_id,b.medicine_name,b.batch_number,b.quantity,b.expiry_date,
            DATEDIFF(b.expiry_date,CURDATE()) AS days_left,n.node_name AS pharmacy_name,
            CASE WHEN n.verification_status IN ('Verified','verified','Approved','approved') THEN 'REVIEW_REQUIRED' ELSE 'NODE_UNVERIFIED' END AS eligibility_status
            FROM medicine_batches b JOIN pharmacy_nodes n ON n.node_id=b.node_id
            WHERE b.node_id=%s AND LOWER(b.batch_status)='charity_fallback' AND b.quantity>0
            ORDER BY b.expiry_date,b.batch_id""", (node_id,))
        rows = cur.fetchall(); cur.close()
    return {"success": True, "batches": rows}


@router.get("/summary")
def transfer_summary(user=Depends(current_user)):
    node_id = _user_scope(user)
    with connection() as conn:
        cur = conn.cursor(dictionary=True)
        matches = build_opportunities(cur, node_id)
        cur.execute("""SELECT COUNT(*) AS transfer_count,
            SUM(CASE WHEN LOWER(REPLACE(status,' ','_')) IN ('pending','pending_approval') THEN 1 ELSE 0 END) AS pending_transfers,
            SUM(CASE WHEN LOWER(REPLACE(status,' ','_'))='completed' THEN 1 ELSE 0 END) AS completed_transfers,
            SUM(CASE WHEN LOWER(REPLACE(status,' ','_'))='approved' THEN 1 ELSE 0 END) AS approved_transfers,
            SUM(CASE WHEN LOWER(REPLACE(status,' ','_'))='completed' THEN quantity ELSE 0 END) AS units_redistributed,
            SUM(CASE WHEN LOWER(REPLACE(status,' ','_'))='completed' AND decision_reason LIKE 'Expiry-risk source:%' THEN quantity ELSE 0 END) AS units_redirected_from_expiry_risk
            FROM transfer_manifests WHERE source_pharmacy_id=%s OR destination_clinic_id=%s""", (node_id,node_id))
        counts = cur.fetchone()
        if user["role"] == CLINIC:
            cur.execute("SELECT COUNT(DISTINCT demand_id) AS high_priority_shortages FROM clinic_demand WHERE clinic_id=%s AND shortage_quantity>0 AND LOWER(priority) IN ('critical','high')", (node_id,))
            high = cur.fetchone()["high_priority_shortages"] or 0
        else:
            high = len({m["demand_id"] for m in matches if str(m.get("priority", "")).casefold() in {"critical", "high"}})
        risk_count = len({m["batch_id"] for m in matches})
        pending_status = {"transfer_count":0,"pending_transfers":0,"completed_transfers":0,"approved_transfers":0,"units_redistributed":0,"units_redirected_from_expiry_risk":0}
        summary = {key: int(counts.get(key) or 0) for key in pending_status}
        summary.update({"redistribution_opportunities": len(matches), "high_priority_shortages": int(high),
                        "expiry_risk_stock": risk_count, "total_transfer_opportunities": len(matches)})
        cur.close()
    return {"success": True, "summary": summary}


@router.get("/analytics")
def transfer_analytics(user=Depends(current_user)):
    node_id = _user_scope(user)
    with connection() as conn:
        cur = conn.cursor(dictionary=True)
        scope = "(source_pharmacy_id=%s OR destination_clinic_id=%s) AND LOWER(REPLACE(status,' ','_'))='completed'"
        cur.execute(f"SELECT medicine_id,medicine_name,SUM(quantity) AS units FROM transfer_manifests WHERE {scope} GROUP BY medicine_id,medicine_name ORDER BY units DESC LIMIT 5", (node_id,node_id))
        medicines = cur.fetchall()
        cur.execute(f"SELECT t.source_pharmacy_id AS node_id,n.node_name AS name,SUM(t.quantity) AS units FROM transfer_manifests t JOIN pharmacy_nodes n ON n.node_id=t.source_pharmacy_id WHERE (t.source_pharmacy_id=%s OR t.destination_clinic_id=%s) AND LOWER(REPLACE(t.status,' ','_'))='completed' GROUP BY t.source_pharmacy_id,n.node_name ORDER BY units DESC LIMIT 5", (node_id,node_id))
        sources = cur.fetchall()
        cur.execute(f"SELECT t.destination_clinic_id AS node_id,n.node_name AS name,SUM(t.quantity) AS units FROM transfer_manifests t JOIN pharmacy_nodes n ON n.node_id=t.destination_clinic_id WHERE (t.source_pharmacy_id=%s OR t.destination_clinic_id=%s) AND LOWER(REPLACE(t.status,' ','_'))='completed' GROUP BY t.destination_clinic_id,n.node_name ORDER BY units DESC LIMIT 5", (node_id,node_id))
        destinations = cur.fetchall(); cur.close()
    summary = transfer_summary(user)["summary"]
    return {"success": True, "summary": summary,
            "top_medicines": [{"medicine_id":r["medicine_id"],"medicine_name":r["medicine_name"],"units":int(r["units"])} for r in medicines],
            "top_source_pharmacies": [{"node_id":r["node_id"],"name":r["name"],"units":int(r["units"])} for r in sources],
            "top_destination_clinics": [{"node_id":r["node_id"],"name":r["name"],"units":int(r["units"])} for r in destinations]}


@router.get("")
def list_transfers(user=Depends(current_user)):
    node_id = _user_scope(user)
    with connection() as conn:
        cur = conn.cursor(dictionary=True)
        cur.execute("""SELECT t.transfer_id,t.match_id,t.demand_id,t.transfer_date,t.source_pharmacy_id,
            s.node_name AS source_pharmacy_name,t.destination_clinic_id,d.node_name AS destination_clinic_name,
            t.batch_id,t.medicine_id,t.medicine_name,t.quantity,t.status,t.decision_reason,t.distance_km
            FROM transfer_manifests t JOIN pharmacy_nodes s ON s.node_id=t.source_pharmacy_id
            JOIN pharmacy_nodes d ON d.node_id=t.destination_clinic_id
            WHERE t.source_pharmacy_id=%s OR t.destination_clinic_id=%s
            ORDER BY t.transfer_date DESC,t.transfer_id DESC LIMIT 250""", (node_id,node_id))
        rows = cur.fetchall(); cur.close()
    return {"success": True, "transfers": rows}


@router.post("/{transfer_id}/approve")
def approve_requested_transfer(transfer_id: str, user=Depends(current_user)):
    node_id = _user_scope(user, RETAIL)
    conn = get_connection()
    try:
        conn.start_transaction(); cur = conn.cursor(dictionary=True)
        transfer = _get_scoped_transfer(cur, transfer_id, node_id)
        result = _approve_locked(cur, transfer, node_id)
        conn.commit(); cur.close()
        return {"success": True, **result}
    except HTTPException:
        conn.rollback(); raise
    except Exception:
        conn.rollback(); raise
    finally:
        conn.close()


@router.post("/{transfer_id}/reject")
def reject_transfer(transfer_id: str, user=Depends(current_user)):
    node_id = _user_scope(user, RETAIL)
    conn = get_connection()
    try:
        conn.start_transaction(); cur = conn.cursor(dictionary=True)
        transfer = _get_scoped_transfer(cur, transfer_id, node_id)
        if transfer["source_pharmacy_id"] != node_id:
            raise HTTPException(403, "Only the source pharmacy can reject this transfer.")
        if _status_key(transfer["status"]) != "pending_approval":
            raise HTTPException(409, "Only a transfer awaiting approval can be rejected.")
        cur.execute("UPDATE transfer_manifests SET status='REJECTED',decision_reason=CONCAT(COALESCE(decision_reason,''),' Rejected by source pharmacy.') WHERE transfer_id=%s AND LOWER(REPLACE(status,' ','_'))='pending_approval'", (transfer_id,))
        if cur.rowcount != 1:
            raise HTTPException(409, "This transfer has already changed.")
        _audit(cur, "TRANSFER_REJECTED", transfer_id, f"Transfer request for {transfer['medicine_name']} was rejected by the source pharmacy.")
        conn.commit(); cur.close()
        return {"success": True, "transfer_id": transfer_id, "status": "REJECTED"}
    except HTTPException:
        conn.rollback(); raise
    except Exception:
        conn.rollback(); raise
    finally:
        conn.close()


@router.patch("/{transfer_id}/status")
def change_transfer_status(transfer_id: str, body: TransferStatusBody, user=Depends(current_user)):
    node_id = _user_scope(user)
    target = body.status.strip().upper().replace(" ", "_")
    conn = get_connection()
    try:
        conn.start_transaction(); cur = conn.cursor(dictionary=True)
        transfer = _get_scoped_transfer(cur, transfer_id, node_id)
        current = _status_key(transfer["status"])
        transitions = {
            ("approved", "IN_TRANSIT"): (RETAIL, "TRANSFER_IN_TRANSIT"),
            ("in_transit", "RECEIVED"): (CLINIC, "TRANSFER_RECEIVED"),
            ("received", "COMPLETED"): (CLINIC, "TRANSFER_COMPLETED"),
            ("pending_approval", "CANCELLED"): (CLINIC, "TRANSFER_CANCELLED"),
        }
        transition = transitions.get((current, target))
        if not transition:
            raise HTTPException(409, "This transfer status transition is not allowed.")
        expected_role, action = transition
        if user["role"] != expected_role:
            raise HTTPException(403, "Your role is not authorized for this transfer status change.")
        expected_node = transfer["source_pharmacy_id"] if expected_role == RETAIL else transfer["destination_clinic_id"]
        if node_id != expected_node:
            raise HTTPException(403, "This transfer does not belong to your network node.")
        cur.execute("UPDATE transfer_manifests SET status=%s WHERE transfer_id=%s AND status=%s", (target,transfer_id,transfer["status"]))
        if cur.rowcount != 1:
            raise HTTPException(409, "This transfer has already changed.")
        _audit(cur, action, transfer_id, f"Transfer {transfer_id} changed from {transfer['status']} to {target}.")
        conn.commit(); cur.close()
        return {"success": True, "transfer_id": transfer_id, "status": target}
    except HTTPException:
        conn.rollback(); raise
    except Exception:
        conn.rollback(); raise
    finally:
        conn.close()


@router.get("/{transfer_id}")
def transfer_detail(transfer_id: str, user=Depends(current_user)):
    node_id = _user_scope(user)
    with connection() as conn:
        cur = conn.cursor(dictionary=True)
        row = _get_scoped_transfer(cur, transfer_id, node_id)
        cur.close()
    return {"success": True, "transfer": row}
