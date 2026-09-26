from datetime import date


def evaluate_batch(batch: dict, quantity_30d: float, today: date, restock_threshold: float = 15) -> dict:
    """Pure, deterministic Step 5 calculations for one live inventory batch."""
    days_left = (batch["expiry_date"] - today).days
    quantity = float(batch["quantity"] or 0)
    velocity = float(quantity_30d or 0) / 30
    days_of_stock = quantity / velocity if velocity > 0 else None
    projected_sales = velocity * max(days_left, 0)
    projected_remaining = quantity - projected_sales

    if days_left <= 0:
        risk_status, stock_status, discount = "EXPIRED", "EXPIRED", 0
    else:
        if days_left <= 30 and quantity > 0:
            risk_status = "CRITICAL_30_DAYS"
        elif projected_remaining <= 0 or days_left > 90:
            risk_status = "HEALTHY"
        elif days_left <= 60:
            risk_status = "AT_RISK_60_DAYS"
        else:
            risk_status = "AT_RISK_90_DAYS"
        discount = 0 if quantity <= 0 or days_left <= 30 else (50 if days_left <= 60 else 30 if days_left <= 90 else 0)
        stock_status = "CHARITY_FALLBACK" if days_left <= 30 and quantity > 0 else risk_status if risk_status != "HEALTHY" else "ACTIVE"

    restock = velocity > 0 and days_of_stock <= restock_threshold
    unit_price = float(batch.get("unit_price_inr") or 0)
    return {
        **batch,
        "quantity_30d": float(quantity_30d or 0),
        "days_left": days_left,
        "daily_velocity": velocity,
        "estimated_days_of_stock": days_of_stock,
        "projected_sales": projected_sales,
        "projected_remaining": projected_remaining,
        "risk_status": risk_status,
        "discount_percentage": discount,
        "offer_price": round(unit_price * (1 - discount / 100), 2),
        "stock_status": stock_status,
        "restock_recommended": restock,
    }


def status_message(row: dict) -> tuple[str, str] | None:
    batch_id = str(row["batch_id"])
    name = row["medicine_name"]
    if row["restock_recommended"]:
        days = round(row["estimated_days_of_stock"])
        return "RESTOCK_RECOMMENDED", f"{name} stock is estimated to last {days} days at the current sales velocity."
    if row["stock_status"] == "CHARITY_FALLBACK" and row["quantity"] > 0:
        return "CHARITY_FALLBACK_TRIGGERED", f"{name} batch {row['batch_number']} reached the 30-day expiry threshold and was flagged for charity redistribution."
    if row["risk_status"] in {"AT_RISK_90_DAYS", "AT_RISK_60_DAYS", "CRITICAL_30_DAYS"}:
        return "EXPIRY_RISK_DETECTED", f"{name} has {row['days_left']} days remaining and approximately {row['projected_remaining']:.1f} units are projected to remain at current sales velocity."
    if row["discount_percentage"]:
        return "DISCOUNT_ACTIVATED", f"{name} batch {batch_id} entered the {row['discount_percentage']}% discount stage."
    return None
