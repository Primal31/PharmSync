from datetime import date, timedelta

from app.services.p2p_matching import _is_verified, _name_key, build_opportunities, node_distance_km, opportunity_id


def test_distance_calculation_and_missing_coordinates():
    assert node_distance_km(12.9716, 77.5946, 12.9352, 77.6245) == 5.18
    assert node_distance_km(None, 77.0, 12.0, 78.0) is None
    assert node_distance_km(91, 0, 0, 0) is None


def test_match_id_is_stable_and_quantity_sensitive():
    first = opportunity_id("N1", "N2", "B1", "D1", 5)
    assert first == opportunity_id("N1", "N2", "B1", "D1", 5)
    assert len(first) == 32 and first.startswith("M")
    assert first != opportunity_id("N1", "N2", "B1", "D1", 6)


def test_product_normalization_and_verified_node_values():
    assert _name_key("  Amlodipine   5MG ") == _name_key("amlodipine 5mg")
    assert _name_key("Amlodipine 5mg") != _name_key("Amlodipine 10mg")
    assert _is_verified("Verified") and _is_verified("approved")
    assert not _is_verified("pending")


class MatchingCursor:
    def __init__(self, sources, demands, reservations=()):
        self.sources, self.demands, self.reservations = sources, demands, list(reservations)
        self.rows = []

    def execute(self, query, _params=None):
        if "SELECT CURDATE()" in query:
            self.rows = [{"today": date.today()}]
        elif "FROM medicine_batches b JOIN pharmacy_nodes n" in query:
            self.rows = [dict(row) for row in self.sources]
        elif "FROM clinic_demand d JOIN pharmacy_nodes n" in query:
            self.rows = [dict(row) for row in self.demands]
        elif "FROM transfer_manifests WHERE demand_id IS NOT NULL" in query:
            self.rows = [dict(row) for row in self.reservations]
        else:
            raise AssertionError(f"Unexpected query in matching test: {query}")

    def fetchone(self):
        return self.rows[0]

    def fetchall(self):
        return self.rows


def source(batch_id, node, qty, expiry_days):
    return {"batch_id": batch_id, "medicine_id": "MED-A", "medicine_name": "Amlodipine 5mg",
            "batch": "AML", "batch_number": batch_id, "node_id": node, "quantity": qty,
            "unit_price_inr": 25, "manufacturing_date": date.today() - timedelta(days=20),
            "expiry_date": date.today() + timedelta(days=expiry_days), "batch_status": "active",
            "storage_condition": "Ambient", "source_pharmacy_name": f"Pharmacy {node}",
            "source_node_type": "Pharmacy", "source_city": "Bengaluru", "source_state": "KA",
            "source_latitude": 12.97, "source_longitude": 77.59, "source_verification": "Verified",
            "quantity_30d": 2}


def demand(demand_id, qty, priority="high"):
    return {"demand_id": demand_id, "clinic_id": f"C-{demand_id}", "medicine_id": "MED-A",
            "medicine_name": "amLODIPine  5mg", "form": "Tablet", "current_stock": 0,
            "daily_demand": 3, "required_quantity": qty, "shortage_quantity": qty,
            "priority": priority, "destination_clinic_name": f"Clinic {demand_id}",
            "destination_node_type": "Clinic", "destination_city": "Bengaluru",
            "destination_state": "KA", "destination_latitude": 12.94, "destination_longitude": 77.62,
            "destination_verification": "Verified"}


def test_matcher_caps_allocation_and_prefers_earlier_expiry():
    cursor = MatchingCursor([source("B-EARLY", "P1", 40, 70), source("B-LATER", "P2", 40, 80)],
                            [demand("D1", 50, "critical"), demand("D2", 50, "normal")])
    rows = build_opportunities(cursor)
    assert [(row["demand_id"], row["batch_id"], row["suggested_transfer_quantity"]) for row in rows] == [
        ("D1", "B-EARLY", 40), ("D1", "B-LATER", 10), ("D2", "B-LATER", 30)]
    assert sum(row["suggested_transfer_quantity"] for row in rows if row["batch_id"] == "B-LATER") == 40


def test_matcher_reserves_pending_requests_and_excludes_unverified_sources():
    sources = [source("B1", "P1", 40, 70), source("B2", "P2", 100, 75)]
    sources[1]["source_verification"] = "Pending"
    rows = build_opportunities(MatchingCursor(sources, [demand("D1", 40)],
                                [{"batch_id": "B1", "demand_id": "D1", "quantity": 15}]))
    assert len(rows) == 1
    assert rows[0]["batch_id"] == "B1"
    assert rows[0]["suggested_transfer_quantity"] == 25
