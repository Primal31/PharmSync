"""Deterministic PharmSync network supply/demand matching and distance helpers."""
from datetime import date
from hashlib import sha256
from math import asin, cos, radians, sin, sqrt

from app.config.settings import settings
from app.services.inventory_intelligence import evaluate_batch

ELIGIBLE_RISK = {"AT_RISK_90_DAYS", "AT_RISK_60_DAYS"}
PRIORITY_ORDER = {"critical": 0, "high": 1, "urgent": 1, "medium": 2, "normal": 3, "low": 4}


def node_distance_km(lat1, lon1, lat2, lon2) -> float | None:
    """Return rounded Haversine distance only when all coordinates are valid."""
    coords = (lat1, lon1, lat2, lon2)
    if any(value is None for value in coords):
        return None
    try:
        lat1, lon1, lat2, lon2 = (float(value) for value in coords)
    except (TypeError, ValueError):
        return None
    if not (-90 <= lat1 <= 90 and -90 <= lat2 <= 90 and -180 <= lon1 <= 180 and -180 <= lon2 <= 180):
        return None
    dlat, dlon = radians(lat2-lat1), radians(lon2-lon1)
    h = sin(dlat/2)**2 + cos(radians(lat1))*cos(radians(lat2))*sin(dlon/2)**2
    return round(6371.0088 * 2 * asin(sqrt(min(1.0, h))), 2)


def opportunity_id(source_id: str, destination_id: str, batch_id: str, demand_id: str, quantity: int) -> str:
    raw = "|".join((source_id, destination_id, batch_id, demand_id, str(quantity)))
    return "M" + sha256(raw.encode("utf-8")).hexdigest()[:31].upper()


def _name_key(value) -> str:
    return " ".join(str(value or "").casefold().split())


def _is_verified(value) -> bool:
    return str(value or "").strip().casefold() in {"verified", "approved", "active"}


def _source_rows(cur, today: date) -> list[dict]:
    cur.execute("""SELECT b.batch_id,b.medicine_id,b.medicine_name,b.batch,b.batch_number,b.node_id,
        (b.quantity-COALESCE(b.reserved_quantity,0)) AS quantity,b.quantity AS on_hand_quantity,
        COALESCE(b.reserved_quantity,0) AS reserved_quantity,
        b.unit_price_inr,b.manufacturing_date,b.expiry_date,b.batch_status,b.storage_condition,
        n.node_name AS source_pharmacy_name,n.node_type AS source_node_type,n.city AS source_city,
        n.state AS source_state,n.latitude AS source_latitude,n.longitude AS source_longitude,
        n.verification_status AS source_verification,COALESCE(s.quantity_30d,0) AS quantity_30d
        FROM medicine_batches b JOIN pharmacy_nodes n ON n.node_id=b.node_id
        LEFT JOIN (SELECT batch_id,pharmacy_id,SUM(quantity_sold) AS quantity_30d FROM sales
          WHERE sale_date>=DATE_SUB(CURDATE(),INTERVAL 29 DAY) AND sale_date<=CURDATE()
          GROUP BY batch_id,pharmacy_id) s ON s.batch_id=b.batch_id AND s.pharmacy_id=b.node_id
        WHERE LOWER(n.node_type) IN ('pharmacy','retail pharmacy','retail_pharmacy')
          AND LOWER(n.verification_status) IN ('verified','approved','active')
          AND b.quantity>0 AND LOWER(b.batch_status) NOT IN ('inactive','discontinued','expired','charity_fallback')
        ORDER BY b.medicine_id,b.expiry_date,b.batch_id""")
    output = []
    for row in cur.fetchall():
        sales_30d = row.pop("quantity_30d", 0)
        assessed = evaluate_batch(row, sales_30d, today, settings.restock_days_threshold)
        if (assessed["risk_status"] not in ELIGIBLE_RISK or assessed["days_left"] <= 30
                or assessed["projected_remaining"] <= 0 or assessed["quantity"] <= 0
                or not _is_verified(assessed.get("source_verification"))):
            continue
        output.append(assessed)
    return output


def _demand_rows(cur) -> list[dict]:
    cur.execute("""SELECT d.demand_id,d.clinic_id,d.medicine_id,d.medicine_name,d.form,d.current_stock,
        d.daily_demand,d.required_quantity,d.shortage_quantity,d.priority,n.node_name AS destination_clinic_name,
        n.node_type AS destination_node_type,n.city AS destination_city,n.state AS destination_state,
        n.latitude AS destination_latitude,n.longitude AS destination_longitude,
        n.verification_status AS destination_verification
        FROM clinic_demand d JOIN pharmacy_nodes n ON n.node_id=d.clinic_id
        WHERE d.shortage_quantity>0
          AND LOWER(n.node_type) IN ('clinic','phc','clinic/phc','healthcare organization','healthcare')
          AND LOWER(n.verification_status) IN ('verified','approved','active')
        ORDER BY d.medicine_id,d.clinic_id,d.demand_id""")
    return cur.fetchall()


def _open_requests(cur) -> list[dict]:
    cur.execute("""SELECT source_pharmacy_id,destination_clinic_id,batch_id,demand_id,quantity
        FROM transfer_manifests WHERE demand_id IS NOT NULL
        AND LOWER(REPLACE(status,' ','_'))='pending_approval'""")
    return cur.fetchall()


def build_opportunities(cur, scope_node_id: str | None = None) -> list[dict]:
    """Allocate verified shortage against risk-eligible inventory, without overbooking either side."""
    cur.execute("SELECT CURDATE() AS today")
    today = cur.fetchone()["today"]
    sources = _source_rows(cur, today)
    demands = _demand_rows(cur)
    source_left = {str(row["batch_id"]): int(row["quantity"]) for row in sources}
    demand_left = {str(row["demand_id"]): int(float(row["shortage_quantity"])) for row in demands}
    for request in _open_requests(cur):
        bid, did = str(request["batch_id"]), str(request["demand_id"])
        if bid in source_left:
            source_left[bid] = max(0, source_left[bid] - int(request["quantity"]))
        if did in demand_left:
            demand_left[did] = max(0, demand_left[did] - int(request["quantity"]))

    sources_by_medicine: dict[str, list[dict]] = {}
    for source in sources:
        sources_by_medicine.setdefault(str(source["medicine_id"]), []).append(source)
    demands.sort(key=lambda d: (PRIORITY_ORDER.get(str(d["priority"]).casefold(), 9),
                                -float(d["shortage_quantity"] or 0), str(d["demand_id"])))

    matches = []
    for demand in demands:
        remaining_demand = demand_left.get(str(demand["demand_id"]), 0)
        if remaining_demand <= 0:
            continue
        candidates = []
        for source in sources_by_medicine.get(str(demand["medicine_id"]), []):
            if source["node_id"] == demand["clinic_id"] or source_left.get(str(source["batch_id"]), 0) <= 0:
                continue
            # The existing batch schema has no dosage-form column; use exact product ID
            # plus normalized dataset medicine name as the available compatibility check.
            if _name_key(source["medicine_name"]) != _name_key(demand["medicine_name"]):
                continue
            distance = node_distance_km(source.get("source_latitude"), source.get("source_longitude"),
                                        demand.get("destination_latitude"), demand.get("destination_longitude"))
            candidates.append((source, distance))
        candidates.sort(key=lambda pair: (pair[0]["days_left"], pair[1] is None,
                                          pair[1] if pair[1] is not None else float("inf"),
                                          str(pair[0]["node_id"]), str(pair[0]["batch_id"])))
        for source, distance in candidates:
            if remaining_demand <= 0:
                break
            batch_id, demand_id = str(source["batch_id"]), str(demand["demand_id"])
            qty = min(source_left[batch_id], remaining_demand)
            if qty <= 0:
                continue
            source_left[batch_id] -= qty
            remaining_demand -= qty
            matches.append({
                "match_id": opportunity_id(str(source["node_id"]), str(demand["clinic_id"]), batch_id, demand_id, qty),
                "demand_id": demand_id,
                "source_pharmacy_id": source["node_id"], "source_pharmacy_name": source["source_pharmacy_name"],
                "source_city": source["source_city"], "source_state": source["source_state"],
                "destination_clinic_id": demand["clinic_id"], "destination_clinic_name": demand["destination_clinic_name"],
                "destination_city": demand["destination_city"], "destination_state": demand["destination_state"],
                "medicine_id": source["medicine_id"], "medicine_name": source["medicine_name"],
                "form": demand["form"], "batch_id": batch_id, "batch_number": source["batch_number"],
                "available_quantity": int(source["quantity"]), "allocatable_quantity": int(qty),
                "shortage_quantity": float(demand["shortage_quantity"]), "current_stock": float(demand["current_stock"]),
                "daily_demand": float(demand["daily_demand"]), "suggested_transfer_quantity": int(qty),
                "days_left": int(source["days_left"]), "daily_velocity": float(source["daily_velocity"]),
                "projected_remaining": float(source["projected_remaining"]), "expiry_status": source["risk_status"],
                "distance_kilometer": distance, "priority": demand["priority"], "status": "SUGGESTED",
                "reason": (f"Expiry-risk inventory at {source['source_pharmacy_name']} has {source['days_left']} days left; "
                           f"{demand['destination_clinic_name']} has an active shortage of {float(demand['shortage_quantity']):g} units."),
            })
    if scope_node_id:
        matches = [m for m in matches if m["source_pharmacy_id"] == scope_node_id or m["destination_clinic_id"] == scope_node_id]
    return matches


def get_opportunity(cur, match_id: str, scope_node_id: str | None = None) -> dict | None:
    return next((m for m in build_opportunities(cur, scope_node_id) if m["match_id"] == match_id), None)
