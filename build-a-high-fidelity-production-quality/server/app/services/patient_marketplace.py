from app.config.settings import settings
from app.services.inventory_intelligence import evaluate_batch

OFFER_RISKS = {"AT_RISK_90_DAYS", "AT_RISK_60_DAYS"}
BLOCKED_BATCH_STATUSES = {"inactive", "discontinued", "expired", "charity_fallback", "critical_30_days"}


def eligible_offers(cur, search: str = "", node_id: str | None = None, limit: int = 100) -> list[dict]:
    """Return current eligible offers from MySQL; never trusts cached or client prices."""
    where = ["LOWER(n.node_type) IN ('pharmacy','retail pharmacy','retail_pharmacy')",
             "LOWER(n.verification_status) IN ('verified','approved','active')",
             "b.quantity > b.reserved_quantity", "b.expiry_date > CURDATE()",
             "DATEDIFF(b.expiry_date,CURDATE()) BETWEEN 31 AND 90",
             "LOWER(b.batch_status) NOT IN ('inactive','discontinued','expired','charity_fallback','critical_30_days')"]
    params: list = []
    if search.strip():
        term = "%" + search.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        where.append("(b.medicine_name LIKE %s OR b.medicine_id LIKE %s OR COALESCE(d.form,'') LIKE %s)")
        params.extend([term, term, term])
    if node_id:
        where.append("b.node_id=%s")
        params.append(node_id)
    cur.execute(f"""SELECT b.batch_id,b.medicine_id,b.medicine_name,b.batch_number,b.node_id,b.quantity,
        b.reserved_quantity,(b.quantity-b.reserved_quantity) AS available_quantity,b.unit_price_inr,
        b.manufacturing_date,b.expiry_date,b.batch_status,n.node_name AS pharmacy_name,n.city,n.state,d.form,
        COALESCE(s.quantity_30d,0) AS quantity_30d,CURDATE() AS today
        FROM medicine_batches b JOIN pharmacy_nodes n ON n.node_id=b.node_id
        LEFT JOIN (SELECT batch_id,pharmacy_id,SUM(quantity_sold) AS quantity_30d FROM sales
          WHERE sale_date>=DATE_SUB(CURDATE(),INTERVAL 29 DAY) AND sale_date<=CURDATE()
          GROUP BY batch_id,pharmacy_id) s ON s.batch_id=b.batch_id AND s.pharmacy_id=b.node_id
        LEFT JOIN (SELECT medicine_id,MIN(form) AS form FROM clinic_demand GROUP BY medicine_id) d ON d.medicine_id=b.medicine_id
        WHERE {' AND '.join(where)} ORDER BY b.expiry_date ASC,n.node_name,b.batch_id LIMIT %s""", (*params, limit))
    offers = []
    for row in cur.fetchall():
        available = int(row["available_quantity"] or 0)
        if available <= 0:
            continue
        risk = evaluate_batch({**row, "quantity": available}, row["quantity_30d"], row["today"], settings.restock_days_threshold)
        if risk["risk_status"] not in OFFER_RISKS or risk["discount_percentage"] not in (30, 50):
            continue
        offer = {
            "batch_id": row["batch_id"], "medicine_id": row["medicine_id"], "medicine_name": row["medicine_name"],
            "form": row["form"], "node_id": row["node_id"], "pharmacy_name": row["pharmacy_name"],
            "city": row["city"], "state": row["state"], "available_quantity": available,
            "original_price": float(row["unit_price_inr"]), "discount_percent": risk["discount_percentage"],
            "offer_price": risk["offer_price"], "expiry_date": row["expiry_date"].isoformat(),
            "days_remaining": risk["days_left"], "risk_status": risk["risk_status"],
            "maximum_request_quantity": min(settings.max_user_order_quantity, available),
        }
        offers.append(offer)
    offers.sort(key=lambda offer: (offer["offer_price"], offer["days_remaining"],
                                   str(offer["city"] or "").casefold(), str(offer["pharmacy_name"]).casefold()))
    return offers
