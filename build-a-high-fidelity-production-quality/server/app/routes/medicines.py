from fastapi import APIRouter, Depends, Query
from app.config.settings import settings
from app.database.connection import connection
from app.middleware.auth import require_patient
from app.services.patient_marketplace import eligible_offers

router = APIRouter(prefix="/api/medicines", tags=["patient marketplace"])


@router.get("/pharmacies")
def verified_pharmacies(user=Depends(require_patient)):
    with connection() as conn:
        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT node_id,node_name,city,state FROM pharmacy_nodes WHERE LOWER(node_type) IN ('pharmacy','retail pharmacy','retail_pharmacy') AND LOWER(verification_status) IN ('verified','approved','active') ORDER BY node_name,node_id LIMIT 1000")
        rows = cur.fetchall(); cur.close()
    return {"success": True, "pharmacies": rows}


@router.get("")
def search_medicines(search: str = Query(default="", max_length=120), node_id: str | None = Query(default=None, max_length=32), user=Depends(require_patient)):
    with connection() as conn:
        cur = conn.cursor(dictionary=True)
        offers = eligible_offers(cur, search, node_id)
        cur.close()
    return {"success": True, "offers": offers, "count": len(offers), "maximum_request_quantity": settings.max_user_order_quantity}


@router.get("/{medicine_id}/alternatives")
def medicine_alternatives(medicine_id: str, node_id: str | None = Query(default=None, max_length=32), user=Depends(require_patient)):
    with connection() as conn:
        cur = conn.cursor(dictionary=True)
        offers = eligible_offers(cur, medicine_id)
        cur.close()
    alternatives = [offer for offer in offers if offer["medicine_id"] == medicine_id and offer["node_id"] != node_id]
    return {"success": True, "medicine_id": medicine_id, "alternatives": alternatives}


@router.get("/{medicine_id}")
def medicine_detail(medicine_id: str, user=Depends(require_patient)):
    with connection() as conn:
        cur = conn.cursor(dictionary=True)
        offers = eligible_offers(cur, medicine_id)
        cur.close()
    exact = [offer for offer in offers if offer["medicine_id"] == medicine_id]
    return {"success": True, "medicine_id": medicine_id, "offers": exact}
