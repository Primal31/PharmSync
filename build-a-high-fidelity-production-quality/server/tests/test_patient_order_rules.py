from app.services.order_rules import allowed_transition, available_stock, quantity_limit_message


def test_configured_patient_limit_accepts_two_and_rejects_three_or_more():
    assert quantity_limit_message(1, 2) is None
    assert quantity_limit_message(2, 2) is None
    assert quantity_limit_message(3, 2) == "You can request a maximum of 2 strips per medicine per order."
    assert quantity_limit_message(100, 2) == "You can request a maximum of 2 strips per medicine per order."
    assert quantity_limit_message(0, 2) == "Quantity must be greater than zero."


def test_stock_reservations_protect_pos_and_concurrent_orders():
    assert available_stock(3, 0) == 3
    assert available_stock(3, 2) == 1
    assert available_stock(3, 4) == 0


def test_pharmacy_status_flow_rejects_invalid_transitions():
    assert allowed_transition("PENDING", "CONFIRMED") == "ORDER_CONFIRMED"
    assert allowed_transition("CONFIRMED", "READY_FOR_PICKUP") == "ORDER_READY_FOR_PICKUP"
    assert allowed_transition("READY_FOR_PICKUP", "COMPLETED") == "ORDER_COMPLETED"
    assert allowed_transition("PENDING", "CANCELLED") == "ORDER_CANCELLED"
    assert allowed_transition("CONFIRMED", "CANCELLED") == "ORDER_CANCELLED"
    assert allowed_transition("COMPLETED", "PENDING") is None
    assert allowed_transition("CANCELLED", "CONFIRMED") is None
