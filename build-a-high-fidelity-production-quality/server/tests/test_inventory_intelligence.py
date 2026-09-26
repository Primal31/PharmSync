from datetime import date, timedelta

from app.services.inventory_intelligence import evaluate_batch


def batch(days_left: int, quantity: int = 40, price: float = 25):
    return {
        "batch_id": "B-TEST", "medicine_id": "MED-TEST", "medicine_name": "Test medicine",
        "batch_number": "LOT-TEST", "node_id": "N-TEST", "quantity": quantity,
        "unit_price_inr": price, "expiry_date": date.today() + timedelta(days=days_left),
        "batch_status": "active",
    }


def test_restock_when_projected_coverage_is_below_threshold():
    row = evaluate_batch(batch(180, quantity=8), quantity_30d=30, today=date.today(), restock_threshold=15)
    assert row["daily_velocity"] == 1
    assert row["estimated_days_of_stock"] == 8
    assert row["restock_recommended"] is True


def test_high_velocity_with_healthy_coverage():
    row = evaluate_batch(batch(180, quantity=40), quantity_30d=300, today=date.today())
    assert row["projected_remaining"] <= 0
    assert row["risk_status"] == "HEALTHY"


def test_discount_stages_and_charity_threshold():
    at_82 = evaluate_batch(batch(82), 2, date.today())
    at_55 = evaluate_batch(batch(55), 2, date.today())
    at_25 = evaluate_batch(batch(25), 2, date.today())
    assert (at_82["discount_percentage"], at_82["offer_price"]) == (30, 17.5)
    assert (at_55["discount_percentage"], at_55["offer_price"]) == (50, 12.5)
    assert at_25["stock_status"] == "CHARITY_FALLBACK"
    assert at_25["discount_percentage"] == 0


def test_expired_and_zero_sales_dead_stock():
    expired = evaluate_batch(batch(-5), 0, date.today())
    dead_stock = evaluate_batch(batch(70), 0, date.today())
    assert expired["risk_status"] == "EXPIRED"
    assert expired["discount_percentage"] == 0
    assert dead_stock["daily_velocity"] == 0
    assert dead_stock["risk_status"] == "AT_RISK_90_DAYS"
    assert dead_stock["projected_remaining"] == 40
    assert dead_stock["restock_recommended"] is False


def test_discount_does_not_hide_batch_that_is_projected_to_sell_through():
    row = evaluate_batch(batch(82), 1500, date.today())
    assert row["risk_status"] == "HEALTHY"
    assert row["discount_percentage"] == 30
