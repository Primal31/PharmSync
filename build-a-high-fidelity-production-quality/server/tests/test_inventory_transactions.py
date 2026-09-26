from datetime import date, timedelta

from app.routes import inventory, sales
from app.routes.sales import SaleItem, SaleRequest
from app.schemas.scanner import RestockRequest


class FakeCursor:
    def __init__(self, batch):
        self.batch = batch
        self.one = None
        self.statements = []
        self.inserted_sales = []

    def execute(self, sql, params=()):
        self.statements.append((sql, params))
        if sql.startswith("SELECT batch_id,medicine_id,medicine_name,batch_number,node_id,quantity"):
            self.one = self.batch
        elif sql.startswith("SELECT batch_id,quantity FROM medicine_batches"):
            self.one = {"batch_id": self.batch["batch_id"], "quantity": self.batch["quantity"]}
        elif sql.startswith("UPDATE medicine_batches SET quantity=quantity-%s"):
            self.batch["quantity"] -= params[0]
        elif sql.startswith("UPDATE medicine_batches SET quantity=quantity+%s"):
            self.batch["quantity"] += params[0]
        elif sql.startswith("INSERT INTO sales"):
            self.inserted_sales.append(params)

    def fetchone(self):
        return self.one

    def close(self):
        pass


class FakeConnection:
    def __init__(self, cursor):
        self.cur = cursor
        self.committed = False
        self.rolled_back = False

    def cursor(self, **_kwargs):
        return self.cur

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def close(self):
        pass


def test_sale_decrements_locked_batch_and_inserts_sale(monkeypatch):
    batch = {"batch_id": "B-TEST", "medicine_id": "MED-TEST", "medicine_name": "Test medicine",
             "batch_number": "LOT-TEST", "node_id": "N-TEST", "quantity": 40,
             "unit_price_inr": 25, "batch_status": "active", "days_remaining": 180}
    cur = FakeCursor(batch)
    conn = FakeConnection(cur)
    monkeypatch.setattr(sales, "pharmacy_node", lambda _user: {"node_id": "N-TEST"})
    monkeypatch.setattr(sales, "get_connection", lambda: conn)
    monkeypatch.setattr(sales, "audit", lambda *_args: None)
    response = sales.create_sale(SaleRequest(items=[SaleItem(batch_id="B-TEST", quantity=5)]), user={})
    assert batch["quantity"] == 35
    assert len(cur.inserted_sales) == 1
    assert cur.inserted_sales[0][5] == 5
    assert conn.committed is True
    assert conn.rolled_back is False
    assert response["sales"][0]["total_amount_inr"] == 125


def test_restock_adds_quantity_to_matching_batch_without_insert(monkeypatch):
    batch = {"batch_id": "B-TEST", "quantity": 40}
    cur = FakeCursor(batch)
    conn = FakeConnection(cur)
    monkeypatch.setattr(inventory, "pharmacy_node", lambda _user: {"node_id": "N-TEST"})
    monkeypatch.setattr(inventory, "get_connection", lambda: conn)
    monkeypatch.setattr(inventory, "audit", lambda *_args: None)
    body = RestockRequest(medicine_id="MED-TEST", medicine_name="Test medicine", batch="TST",
                          batch_number="LOT-TEST", quantity=20, unit_price=25,
                          manufacture_date=date.today().isoformat(),
                          expiry_date=(date.today()+timedelta(days=180)).isoformat())
    response = inventory.restock(body, user={})
    assert response["result"] == "updated"
    assert response["batch"]["quantity"] == 60
    assert batch["quantity"] == 60
    assert not any(sql.startswith("INSERT INTO medicine_batches") for sql, _ in cur.statements)
    assert conn.committed is True
