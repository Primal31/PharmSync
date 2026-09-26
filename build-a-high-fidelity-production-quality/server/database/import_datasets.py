"""Idempotent initial CSV import for the supplied PharmSync dataset archive."""
import argparse, csv, hashlib, sys
from datetime import date, datetime
from pathlib import Path
SERVER_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVER_DIR))
from app.config.settings import SERVER_DIR
from app.database.connection import get_connection

DATA_DIR = SERVER_DIR / "database" / "datasets"
FILES = ["pharmacy_nodes.csv", "medicine_batches.csv", "clinic_demand.csv", "charity_organizations.csv", "sales.csv", "transfer_manifests.csv", "donations.csv", "audit_logs.csv"]

def read_csv(name):
    path = DATA_DIR / name
    if not path.exists(): raise ValueError(f"Missing dataset file: {path}")
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if not reader.fieldnames: raise ValueError(f"{name}: missing header row")
        return reader.fieldnames, list(reader)

def required(rows, name, fields):
    issues=[]
    for index,row in enumerate(rows,2):
        for field in fields:
            if not str(row.get(field," ")).strip(): issues.append(f"{name}:{index}: missing required {field}")
    return issues

def number(rows,name,fields,integer=()):
    issues=[]
    for index,row in enumerate(rows,2):
        for field in fields:
            value=str(row.get(field," ")).strip()
            if not value: continue
            try:
                parsed=float(value)
                if field in integer and (not parsed.is_integer() or parsed<0): raise ValueError()
            except ValueError: issues.append(f"{name}:{index}: invalid numeric {field}={value!r}")
    return issues

def dates(rows,name,fields):
    issues=[]
    for index,row in enumerate(rows,2):
        for field in fields:
            try: date.fromisoformat(row[field].strip())
            except (ValueError,KeyError): issues.append(f"{name}:{index}: invalid date {field}={row.get(field)!r}")
    return issues

def validate(data):
    errors=[]
    specs={
        "pharmacy_nodes.csv":(["node_id","node_name","node_type","city","state","verification_status"],[],[],[]),
        "medicine_batches.csv":(["batch_id","medicine_id","medicine_name","batch_number","node_id","manufacturing_date","expiry_date","batch_status"],["quantity","unit_price_inr"],["quantity"],["manufacturing_date","expiry_date"]),
        "clinic_demand.csv":(["demand_id","clinic_id","medicine_id","medicine_name","form","priority"],["current_stock","daily_demand","required_quantity","shortage_quantity"],[],[]),
        "charity_organizations.csv":(["charity_id","node_id","organization_name","city","state","verification_status","service_type"],[],[],[]),
        "sales.csv":(["sale_id","sale_date","pharmacy_id","batch_id","medicine_id","medicine_name"],["quantity_sold","unit_price_inr","total_amount_inr"],["quantity_sold"],["sale_date"]),
        "transfer_manifests.csv":(["transfer_id","transfer_date","source_pharmacy_id","destination_clinic_id","batch_id","medicine_id","medicine_name","status"],["quantity","distance_km"],["quantity"],["transfer_date"]),
        "donations.csv":(["donation_id","donation_date","donor_pharmacy_id","charity_id","medicine_id","medicine_name","status"],["quantity"],["quantity"],["donation_date"]),
        "audit_logs.csv":(["log_id","timestamp","agent_name","action","entity_type","entity_id","message"],[],[],[]),
    }
    for name,rows in data.items():
        req,nums,ints,ds=specs[name];errors += required(rows,name,req);errors += number(rows,name,nums,ints);errors += dates(rows,name,ds)
    for name,key in [("pharmacy_nodes.csv","node_id"),("medicine_batches.csv","batch_id"),("sales.csv","sale_id"),("transfer_manifests.csv","transfer_id"),("clinic_demand.csv","demand_id"),("charity_organizations.csv","charity_id"),("donations.csv","donation_id"),("audit_logs.csv","log_id")]:
        seen=set()
        for index,row in enumerate(data[name],2):
            value=row.get(key)
            if value in seen: errors.append(f"{name}:{index}: duplicate {key}={value}")
            seen.add(value)
    nodes={r["node_id"] for r in data["pharmacy_nodes.csv"]}; batches={r["batch_id"]:r for r in data["medicine_batches.csv"]}; charities={r["charity_id"] for r in data["charity_organizations.csv"]}
    for file,field in [("medicine_batches.csv","node_id"),("sales.csv","pharmacy_id"),("clinic_demand.csv","clinic_id"),("transfer_manifests.csv","source_pharmacy_id"),("transfer_manifests.csv","destination_clinic_id"),("donations.csv","donor_pharmacy_id")]:
        for i,row in enumerate(data[file],2):
            if row[field] not in nodes: errors.append(f"{file}:{i}: {field} {row[field]} is not in pharmacy_nodes.csv")
    for i,row in enumerate(data["sales.csv"],2):
        batch=batches.get(row["batch_id"])
        if not batch: errors.append(f"sales.csv:{i}: batch_id {row['batch_id']} not found")
        elif batch["node_id"]!=row["pharmacy_id"] or batch["medicine_id"]!=row["medicine_id"]: errors.append(f"sales.csv:{i}: pharmacy or medicine does not match its batch")
    for i,row in enumerate(data["clinic_demand.csv"],2):
        if row["clinic_id"] in nodes and nodes and not any(n["node_id"]==row["clinic_id"] and n["node_type"].lower()=="clinic" for n in data["pharmacy_nodes.csv"]): errors.append(f"clinic_demand.csv:{i}: clinic_id is not a clinic node")
    for i,row in enumerate(data["donations.csv"],2):
        if row["charity_id"] not in charities: errors.append(f"donations.csv:{i}: charity_id {row['charity_id']} not found")
    return errors

def upsert(conn,table,columns,rows,key):
    if not rows:return
    cols=",".join(f"`{c}`" for c in columns);marks=",".join(["%s"]*len(columns));updates=",".join(f"`{c}`=VALUES(`{c}`)" for c in columns if c!=key)
    cursor=conn.cursor()
    cursor.executemany(f"INSERT INTO `{table}` ({cols}) VALUES ({marks}) ON DUPLICATE KEY UPDATE {updates}", [tuple(row.get(col) for col in columns) for row in rows]);cursor.close()

def main():
    parser=argparse.ArgumentParser();parser.add_argument("--dry-run",action="store_true");args=parser.parse_args()
    try:
        data={name:read_csv(name)[1] for name in FILES}
        errors=validate(data)
        if errors:
            print("Dataset validation failed:");print("\n".join(errors));return 2
        print("Dataset validation passed"+(" (dry run; database not modified)." if args.dry_run else "."))
        for name,rows in data.items():print(f"{name}: {len(rows)} valid rows")
        nodes=data["pharmacy_nodes.csv"];known={n["node_id"] for n in nodes};supplements=[]
        for charity in data["charity_organizations.csv"]:
            if charity["node_id"] not in known:
                supplements.append({"node_id":charity["node_id"],"node_name":charity["organization_name"],"node_type":"Charity","city":charity["city"],"state":charity["state"],"address":None,"latitude":None,"longitude":None,"verification_status":charity["verification_status"]});known.add(charity["node_id"])
        print(f"Supplemental charity nodes: {len(supplements)}")
        if args.dry_run:return 0
        conn=get_connection()
        try:
            for name in FILES:
                digest=hashlib.sha256((DATA_DIR/name).read_bytes()).hexdigest()
                cur=conn.cursor();cur.execute("SELECT 1 FROM dataset_imports WHERE dataset_name=%s AND sha256=%s",(name,digest));already=cur.fetchone();cur.close();conn.commit()
                if already: print(f"Skipping unchanged {name}");continue
                conn.start_transaction()
                if name=="pharmacy_nodes.csv":
                    rows=nodes+supplements;cols=["node_id","node_name","node_type","city","state","address","latitude","longitude","verification_status"]
                    upsert(conn,"pharmacy_nodes",cols,rows,"node_id")
                elif name=="medicine_batches.csv":
                    upsert(conn,"medicine_batches",["batch_id","medicine_id","medicine_name","batch_number","node_id","quantity","unit_price_inr","manufacturing_date","expiry_date","batch_status"],data[name],"batch_id")
                elif name=="clinic_demand.csv":upsert(conn,"clinic_demand",["demand_id","clinic_id","medicine_id","medicine_name","form","current_stock","daily_demand","required_quantity","shortage_quantity","priority"],data[name],"demand_id")
                elif name=="charity_organizations.csv":upsert(conn,"charity_organizations",["charity_id","node_id","organization_name","city","state","verification_status","service_type","contact_email","contact_phone"],data[name],"charity_id")
                elif name=="sales.csv":upsert(conn,"sales",["sale_id","sale_date","pharmacy_id","batch_id","medicine_id","medicine_name","quantity_sold","unit_price_inr","total_amount_inr"],data[name],"sale_id")
                elif name=="transfer_manifests.csv":upsert(conn,"transfer_manifests",["transfer_id","transfer_date","source_pharmacy_id","destination_clinic_id","batch_id","medicine_id","medicine_name","quantity","status","decision_reason","distance_km"],data[name],"transfer_id")
                elif name=="donations.csv":upsert(conn,"donations",["donation_id","donation_date","donor_pharmacy_id","charity_id","medicine_id","medicine_name","quantity","status","reason"],data[name],"donation_id")
                elif name=="audit_logs.csv":
                    rows=[{**r,"timestamp":r["timestamp"].replace("T"," "),"status":r.get("status") or "IMPORTED"} for r in data[name]]
                    upsert(conn,"audit_logs",["log_id","timestamp","agent_name","action","entity_type","entity_id","status","message"],rows,"log_id")
                cur=conn.cursor();cur.execute("INSERT INTO dataset_imports(dataset_name,sha256,row_count) VALUES(%s,%s,%s) ON DUPLICATE KEY UPDATE row_count=VALUES(row_count)",(name,digest,len(data[name])));cur.close();conn.commit();print(f"Imported {name}")
        except Exception:conn.rollback();raise
        finally:conn.close()
        return 0
    except Exception as exc:print(str(exc),file=sys.stderr);return 1

if __name__=="__main__":raise SystemExit(main())
