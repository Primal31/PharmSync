from datetime import date
from uuid import uuid4

from app.config.settings import settings
from app.database.connection import get_connection
from app.services.inventory_intelligence import evaluate_batch


AGENT_NAME = "Inventory Intelligence Agent"


def calculate_for_node(cur, node_id: str, today: date | None = None) -> list[dict]:
    if today is None:
        cur.execute("SELECT CURDATE() AS today")
        today = cur.fetchone()["today"]
    cur.execute("""SELECT b.batch_id,b.medicine_id,b.medicine_name,b.batch,b.batch_number,b.node_id,
        (b.quantity-COALESCE(b.reserved_quantity,0)) AS quantity,b.quantity AS on_hand_quantity,
        COALESCE(b.reserved_quantity,0) AS reserved_quantity,
        b.unit_price_inr,b.manufacturing_date,b.expiry_date,b.batch_status,
        COALESCE(s.quantity_30d,0) quantity_30d
        FROM medicine_batches b
        LEFT JOIN (
          SELECT batch_id,SUM(quantity_sold) quantity_30d FROM sales
          WHERE pharmacy_id=%s AND sale_date>=DATE_SUB(CURDATE(),INTERVAL 29 DAY) AND sale_date<=CURDATE()
          GROUP BY batch_id
        ) s ON s.batch_id=b.batch_id
        WHERE b.node_id=%s AND LOWER(b.batch_status) NOT IN ('inactive','discontinued')
        ORDER BY b.medicine_id,b.expiry_date,b.batch_id""", (node_id, node_id))
    return [evaluate_batch(row, row.pop("quantity_30d", 0), today, settings.restock_days_threshold) for row in cur.fetchall()]


def run_agent(node_id: str | None = None) -> dict:
    conn = get_connection()
    try:
        cur = conn.cursor(dictionary=True)
        if node_id:
            nodes = [node_id]
        else:
            cur.execute("SELECT node_id FROM pharmacy_nodes WHERE LOWER(node_type)='pharmacy'")
            nodes = [row["node_id"] for row in cur.fetchall()]
        summary = {"success": True, "processed_batches": 0, "restock_alerts": 0, "expiry_risk_batches": 0,
                   "discount_30_percent": 0, "discount_50_percent": 0, "charity_fallback": 0, "expired": 0}
        for current_node in nodes:
            rows = calculate_for_node(cur, current_node)
            summary["processed_batches"] += len(rows)
            seen = set()
            if rows:
                ids = [str(row["batch_id"]) for row in rows]
                placeholders = ",".join(["%s"] * len(ids))
                cur.execute(f"SELECT action,entity_id,message FROM audit_logs WHERE agent_name=%s AND entity_type='medicine_batch' AND entity_id IN ({placeholders}) AND action IN ('RESTOCK_RECOMMENDED','EXPIRY_RISK_DETECTED','DISCOUNT_ACTIVATED','CHARITY_FALLBACK_TRIGGERED','BATCH_EXPIRED')", (AGENT_NAME, *ids))
                seen = {(row["action"], row["entity_id"]) for row in cur.fetchall()}
            for row in rows:
                status = row["stock_status"]
                summary["restock_alerts"] += int(row["restock_recommended"])
                summary["expiry_risk_batches"] += int(row["risk_status"] in {"AT_RISK_90_DAYS", "AT_RISK_60_DAYS", "CRITICAL_30_DAYS"})
                summary["discount_30_percent"] += int(row["discount_percentage"] == 30)
                summary["discount_50_percent"] += int(row["discount_percentage"] == 50)
                summary["charity_fallback"] += int(status == "CHARITY_FALLBACK")
                summary["expired"] += int(status == "EXPIRED")
                old_status = str(row.get("batch_status") or "").upper()
                status_changed = old_status != status
                if status_changed:
                    cur.execute("UPDATE medicine_batches SET batch_status=%s WHERE node_id=%s AND batch_id=%s", (status, current_node, row["batch_id"]))
                # Audit distinct actionable outputs, but only insert a given batch/action/message once.
                events = []
                if row["restock_recommended"]:
                    events.append(("RESTOCK_RECOMMENDED", f"{row['medicine_name']} stock is estimated to last {round(row['estimated_days_of_stock'])} days at the current sales velocity."))
                if row["stock_status"] == "CHARITY_FALLBACK" and row["quantity"] > 0:
                    events.append(("CHARITY_FALLBACK_TRIGGERED", f"{row['medicine_name']} batch {row['batch_number']} reached the 30-day expiry threshold and was flagged for charity redistribution."))
                elif row["stock_status"] == "EXPIRED":
                    events.append(("BATCH_EXPIRED", f"{row['medicine_name']} batch {row['batch_number']} passed its expiry date and is blocked from sale."))
                elif row["risk_status"] in {"AT_RISK_90_DAYS", "AT_RISK_60_DAYS", "CRITICAL_30_DAYS"}:
                    events.append(("EXPIRY_RISK_DETECTED", f"{row['medicine_name']} has {row['days_left']} days remaining and approximately {row['projected_remaining']:.1f} units are projected to remain at current sales velocity."))
                if row["discount_percentage"]:
                    events.append(("DISCOUNT_ACTIVATED", f"{row['medicine_name']} batch {row['batch_id']} entered the {row['discount_percentage']}% discount stage."))
                for action, message in events:
                    stage_change = status_changed and action in {"EXPIRY_RISK_DETECTED", "DISCOUNT_ACTIVATED"}
                    _audit_once(cur, action, row["batch_id"], message, seen, force=stage_change)
        conn.commit()
        cur.close()
        return summary
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _audit_once(cur, action: str, entity_id: str, message: str, seen: set, force: bool = False) -> None:
    key = (action, str(entity_id))
    if key in seen and not force:
        return
    cur.execute("INSERT INTO audit_logs(log_id,`timestamp`,agent_name,action,entity_type,entity_id,status,message) VALUES(%s,NOW(),%s,%s,'medicine_batch',%s,'SUCCESS',%s)",
                ("LOG" + uuid4().hex[:20].upper(), AGENT_NAME, action, str(entity_id), message))
    seen.add(key)
