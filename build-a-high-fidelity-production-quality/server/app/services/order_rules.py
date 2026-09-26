PHARMACY_TRANSITIONS = {
    ("PENDING", "CONFIRMED"): "ORDER_CONFIRMED",
    ("PENDING", "CANCELLED"): "ORDER_CANCELLED",
    ("CONFIRMED", "READY_FOR_PICKUP"): "ORDER_READY_FOR_PICKUP",
    ("CONFIRMED", "CANCELLED"): "ORDER_CANCELLED",
    ("READY_FOR_PICKUP", "COMPLETED"): "ORDER_COMPLETED",
}


def quantity_limit_message(quantity: int, maximum: int) -> str | None:
    if quantity <= 0:
        return "Quantity must be greater than zero."
    if quantity > maximum:
        return f"You can request a maximum of {maximum} strips per medicine per order."
    return None


def allowed_transition(current: str, target: str) -> str | None:
    return PHARMACY_TRANSITIONS.get((str(current).upper(), str(target).upper()))


def available_stock(on_hand: int, reserved: int) -> int:
    return max(0, int(on_hand) - int(reserved))
