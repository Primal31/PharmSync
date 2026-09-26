"""Step 8 read-only analytics backed by the existing PharmSync MySQL tables."""
from datetime import date, datetime, timedelta
import json
import re
from urllib.request import Request, urlopen

from fastapi import APIRouter, Depends, HTTPException, Query

from app.config.settings import settings
from app.database.connection import connection
from app.middleware.auth import current_user
from app.routes.inventory import pharmacy_node
from app.services.inventory_intelligence import evaluate_batch
from app.services.p2p_matching import build_opportunities

router = APIRouter(prefix="/api/analytics", tags=["network analytics"])
VALID_ROLES = {"retail_chemist", "clinic_phc", "charity_ngo"}


def _scope(user):
    role = user["role"]
    if role not in VALID_ROLES:
        raise HTTPException(403, "Analytics are not available for this account type.")
    node = user.get("node_id")
    if role in {"retail_chemist", "clinic_phc", "charity_ngo"} and not node:
        raise HTTPException(409, "Your account is not linked to a PharmSync network node.")
    if role == "retail_chemist":
        node = pharmacy_node(user)["node_id"]
    return role, str(node)


def _period(period: str, start: date | None, end: date | None):
    if period not in {"7d", "30d", "90d", "custom"}:
        raise HTTPException(422, "Choose a 7d, 30d, 90d, or custom analytics period.")
    today = date.today()
    if period == "custom":
        if not start or not end or start > end or (end - start).days > 366:
            raise HTTPException(422, "Custom dates must be valid, ordered, and no more than 366 days apart.")
        return start, end
    days = int(period[:-1])
    return today - timedelta(days=days - 1), today


def _money(value):
    return round(float(value or 0), 2)


def _integer(value):
    return int(value or 0)


def _load_snapshot(cur, role, node_id, start, end):
    # Pharmacies see their own stock. Clinics and charities receive network supply
    # summaries; they do not receive pharmacy sales or patient identities.
    own_inventory = role == "retail_chemist"
    if own_inventory:
        where_node = "WHERE b.node_id=%s"
    elif role == "charity_ngo":
        where_node = "WHERE LOWER(n.verification_status) IN ('verified','approved','active') AND DATEDIFF(b.expiry_date,CURDATE()) BETWEEN 1 AND 30 AND b.quantity>0"
    else:
        where_node = "WHERE LOWER(n.verification_status) IN ('verified','approved','active')"
    node_args = (node_id,) if own_inventory else ()
    cur.execute(f"""SELECT b.batch_id,b.medicine_id,b.medicine_name,b.batch_number,b.node_id,
        n.node_name AS pharmacy_name,n.city,n.state,b.quantity,b.reserved_quantity,
        b.unit_price_inr,b.expiry_date,b.batch_status,
        COALESCE(s.quantity_30d,0) AS quantity_30d,CURDATE() AS today
        FROM medicine_batches b JOIN pharmacy_nodes n ON n.node_id=b.node_id
        LEFT JOIN (SELECT batch_id,pharmacy_id,SUM(quantity_sold) quantity_30d FROM sales
          WHERE sale_date>=DATE_SUB(CURDATE(),INTERVAL 29 DAY) AND sale_date<=CURDATE()
          GROUP BY batch_id,pharmacy_id) s ON s.batch_id=b.batch_id AND s.pharmacy_id=b.node_id
        {where_node} ORDER BY b.expiry_date ASC,b.medicine_name ASC,b.batch_id ASC""", node_args)
    raw = cur.fetchall()
    assessed = []
    for row in raw:
        available = max(0, _integer(row["quantity"]) - _integer(row.get("reserved_quantity")))
        assessed.append(evaluate_batch({**row, "quantity": available}, row["quantity_30d"], row["today"], settings.restock_days_threshold))

    if role == "retail_chemist":
        sales_scope, sales_args = "pharmacy_id=%s", (node_id, start, end)
        orders_scope, order_args = "node_id=%s", (node_id, start, end)
        transfer_scope, transfer_args = "(source_pharmacy_id=%s OR destination_clinic_id=%s)", (node_id, node_id, start, end)
        demand_scope, demand_args = "clinic_id=%s", (node_id,)
        donation_scope, donation_args = "donor_pharmacy_id=%s", (node_id, start, end)
    elif role == "clinic_phc":
        sales_scope, sales_args = "1=0", (start, end)
        orders_scope, order_args = "1=0", (start, end)
        transfer_scope, transfer_args = "destination_clinic_id=%s", (node_id, start, end)
        demand_scope, demand_args = "clinic_id=%s", (node_id,)
        donation_scope, donation_args = "1=0", (start, end)
    else:
        sales_scope, sales_args = "1=0", (start, end)
        orders_scope, order_args = "1=0", (start, end)
        transfer_scope, transfer_args = "1=0", (start, end)
        demand_scope, demand_args = "1=0", ()
        donation_scope, donation_args = "charity_id IN (SELECT charity_id FROM charity_organizations WHERE node_id=%s)", (node_id, start, end)

    cur.execute(f"""SELECT COUNT(*) sales_count,COALESCE(SUM(quantity_sold),0) units_sold,
        COALESCE(SUM(total_amount_inr),0) revenue FROM sales WHERE {sales_scope} AND sale_date BETWEEN %s AND %s""", sales_args)
    sales = cur.fetchone()
    cur.execute(f"""SELECT COUNT(*) total_orders,
        SUM(status='PENDING') pending_orders,SUM(status='CONFIRMED') confirmed_orders,
        SUM(status='READY_FOR_PICKUP') ready_orders,SUM(status='COMPLETED') completed_orders,
        SUM(status='CANCELLED') cancelled_orders,
        SUM(status IN ('PENDING','CONFIRMED','READY_FOR_PICKUP')) active_orders,
        COALESCE(SUM(CASE WHEN status='COMPLETED' THEN quantity ELSE 0 END),0) completed_quantity,
        COALESCE(SUM(CASE WHEN status='COMPLETED' AND discount_percent>0 THEN quantity ELSE 0 END),0) completed_discounted_quantity,
        SUM(discount_percent>0) discounted_order_count,
        COALESCE(SUM(CASE WHEN discount_percent>0 THEN quantity ELSE 0 END),0) discounted_order_units
        FROM medicine_orders WHERE {orders_scope} AND DATE(created_at) BETWEEN %s AND %s""", order_args)
    orders = cur.fetchone()
    cur.execute(f"""SELECT COUNT(*) transfer_count,
        SUM(LOWER(REPLACE(status,' ','_')) IN ('pending_approval','pending')) pending_count,
        SUM(LOWER(REPLACE(status,' ','_'))='approved') approved_count,
        SUM(LOWER(REPLACE(status,' ','_'))='in_transit') in_transit_count,
        SUM(LOWER(REPLACE(status,' ','_')) IN ('received','completed')) completed_count,
        SUM(LOWER(REPLACE(status,' ','_')) IN ('rejected','cancelled')) cancelled_count,
        COALESCE(SUM(CASE WHEN LOWER(REPLACE(status,' ','_')) IN ('received','completed') THEN quantity ELSE 0 END),0) units_redistributed
        FROM transfer_manifests WHERE {transfer_scope} AND transfer_date BETWEEN %s AND %s""", transfer_args)
    transfers = cur.fetchone()
    completed_state="LOWER(REPLACE(status,' ','_')) IN ('received','completed')"
    cur.execute(f"""SELECT medicine_id,medicine_name,COALESCE(SUM(quantity),0) units FROM transfer_manifests
        WHERE {transfer_scope} AND transfer_date BETWEEN %s AND %s AND {completed_state}
        GROUP BY medicine_id,medicine_name ORDER BY units DESC LIMIT 8""",transfer_args)
    top_transferred=cur.fetchall()
    cur.execute(f"""SELECT t.source_pharmacy_id node_id,n.node_name name,SUM(t.quantity) units
        FROM transfer_manifests t JOIN pharmacy_nodes n ON n.node_id=t.source_pharmacy_id
        WHERE {transfer_scope.replace('source_pharmacy_id','t.source_pharmacy_id').replace('destination_clinic_id','t.destination_clinic_id')} AND t.transfer_date BETWEEN %s AND %s AND {completed_state.replace('status','t.status')}
        GROUP BY t.source_pharmacy_id,n.node_name ORDER BY units DESC LIMIT 8""",transfer_args)
    source_nodes=cur.fetchall()
    cur.execute(f"""SELECT t.destination_clinic_id node_id,n.node_name name,SUM(t.quantity) units
        FROM transfer_manifests t JOIN pharmacy_nodes n ON n.node_id=t.destination_clinic_id
        WHERE {transfer_scope.replace('source_pharmacy_id','t.source_pharmacy_id').replace('destination_clinic_id','t.destination_clinic_id')} AND t.transfer_date BETWEEN %s AND %s AND {completed_state.replace('status','t.status')}
        GROUP BY t.destination_clinic_id,n.node_name ORDER BY units DESC LIMIT 8""",transfer_args)
    destination_nodes=cur.fetchall()
    cur.execute(f"SELECT COUNT(*) demand_rows,COALESCE(SUM(shortage_quantity),0) shortage_units FROM clinic_demand WHERE {demand_scope} AND shortage_quantity>0", demand_args)
    demand = cur.fetchone()
    cur.execute(f"SELECT COALESCE(SUM(quantity),0) donated_units,COUNT(*) donations FROM donations WHERE {donation_scope} AND donation_date BETWEEN %s AND %s AND LOWER(status) IN ('completed','received','donated')", donation_args)
    donations = cur.fetchone()

    # Network shape is aggregated and contains no personal or pharmacy sales data.
    cur.execute("""SELECT COUNT(*) connected_nodes,
        SUM(LOWER(node_type) IN ('pharmacy','retail pharmacy','retail_pharmacy')) pharmacy_nodes,
        SUM(LOWER(node_type) IN ('clinic','phc','clinic/phc','healthcare organization','healthcare')) clinic_nodes
        FROM pharmacy_nodes WHERE LOWER(verification_status) IN ('verified','approved','active')""")
    network_nodes = cur.fetchone()
    cur.execute("""SELECT COUNT(DISTINCT node_id) supply_nodes FROM medicine_batches
        WHERE quantity>COALESCE(reserved_quantity,0) AND expiry_date>CURDATE()
        AND LOWER(batch_status) NOT IN ('inactive','discontinued','expired','charity_fallback','critical_30_days')""")
    supply_nodes = cur.fetchone()
    cur.execute("SELECT COUNT(DISTINCT clinic_id) demand_nodes,COALESCE(SUM(shortage_quantity),0) network_shortage_units FROM clinic_demand WHERE shortage_quantity>0")
    network_demand = cur.fetchone()
    cur.execute("""SELECT medicine_id,medicine_name,COALESCE(SUM(shortage_quantity),0) shortage_units,
        COUNT(DISTINCT clinic_id) clinic_count FROM clinic_demand WHERE shortage_quantity>0
        GROUP BY medicine_id,medicine_name ORDER BY shortage_units DESC LIMIT 8""")
    top_demand=cur.fetchall()
    cur.execute("""SELECT s.medicine_id,s.medicine_name,s.available_units,COALESCE(d.shortage_units,0) shortage_units,
        GREATEST(s.available_units-COALESCE(d.shortage_units,0),0) potential_surplus_units
        FROM (SELECT b.medicine_id,b.medicine_name,SUM(b.quantity-COALESCE(b.reserved_quantity,0)) available_units
          FROM medicine_batches b JOIN pharmacy_nodes n ON n.node_id=b.node_id
          WHERE LOWER(n.node_type) IN ('pharmacy','retail pharmacy','retail_pharmacy')
            AND LOWER(n.verification_status) IN ('verified','approved','active') AND b.expiry_date>CURDATE()
            AND b.quantity>COALESCE(b.reserved_quantity,0)
            AND LOWER(b.batch_status) NOT IN ('inactive','discontinued','expired','charity_fallback','critical_30_days')
          GROUP BY b.medicine_id,b.medicine_name) s
        LEFT JOIN (SELECT medicine_id,SUM(shortage_quantity) shortage_units FROM clinic_demand
          WHERE shortage_quantity>0 GROUP BY medicine_id) d ON d.medicine_id=s.medicine_id
        WHERE s.available_units>COALESCE(d.shortage_units,0)
        ORDER BY potential_surplus_units DESC LIMIT 8""")
    surplus_medicines=cur.fetchall()
    cur.execute("SELECT COUNT(DISTINCT node_id) order_nodes FROM medicine_orders WHERE status IN ('PENDING','CONFIRMED','READY_FOR_PICKUP')")
    order_nodes = cur.fetchone()
    cur.execute("SELECT COUNT(DISTINCT source_pharmacy_id)+COUNT(DISTINCT destination_clinic_id) transfer_node_ends FROM transfer_manifests WHERE LOWER(REPLACE(status,' ','_')) IN ('pending_approval','approved','in_transit','received')")
    transfer_nodes = cur.fetchone()

    if own_inventory:
        cur.execute("""SELECT medicine_id,medicine_name,SUM(quantity_sold) units FROM sales
            WHERE pharmacy_id=%s AND sale_date BETWEEN %s AND %s
            GROUP BY medicine_id,medicine_name ORDER BY units DESC LIMIT 8""", (node_id,start,end))
        top_sold = cur.fetchall()
        cur.execute("""SELECT medicine_id,medicine_name,COUNT(*) requests,SUM(quantity) units
            FROM medicine_orders WHERE node_id=%s AND DATE(created_at) BETWEEN %s AND %s
            GROUP BY medicine_id,medicine_name ORDER BY requests DESC LIMIT 8""", (node_id,start,end))
        top_requested = cur.fetchall()
        cur.execute("""SELECT medicine_id,medicine_name,COUNT(*) requests,COALESCE(SUM(quantity),0) units
            FROM medicine_orders WHERE node_id=%s AND discount_percent>0 AND DATE(created_at) BETWEEN %s AND %s
            GROUP BY medicine_id,medicine_name ORDER BY requests DESC LIMIT 8""", (node_id,start,end))
        discounted_requests=cur.fetchall()
        cur.execute("""SELECT n.node_name AS pharmacy_name,COUNT(*) orders,COALESCE(SUM(o.quantity),0) units
            FROM medicine_orders o JOIN pharmacy_nodes n ON n.node_id=o.node_id
            WHERE o.node_id=%s AND DATE(o.created_at) BETWEEN %s AND %s
            GROUP BY o.node_id,n.node_name""", (node_id,start,end))
        orders_by_pharmacy = cur.fetchall()
        cur.execute("""SELECT COALESCE(SUM(quantity),0) units,COUNT(*) batches,
            COALESCE(SUM((quantity-reserved_quantity)*unit_price_inr),0) original_value,
            COALESCE(SUM((quantity-reserved_quantity)*unit_price_inr*0.7),0) discounted_value
            FROM medicine_batches WHERE node_id=%s AND DATEDIFF(expiry_date,CURDATE()) BETWEEN 61 AND 90
            AND quantity>reserved_quantity AND LOWER(batch_status) NOT IN ('expired','inactive','discontinued')""", (node_id,))
        d30 = cur.fetchone()
        cur.execute("""SELECT COALESCE(SUM(quantity),0) units,COUNT(*) batches,
            COALESCE(SUM((quantity-reserved_quantity)*unit_price_inr),0) original_value,
            COALESCE(SUM((quantity-reserved_quantity)*unit_price_inr*0.5),0) discounted_value
            FROM medicine_batches WHERE node_id=%s AND DATEDIFF(expiry_date,CURDATE()) BETWEEN 31 AND 60
            AND quantity>reserved_quantity AND LOWER(batch_status) NOT IN ('expired','inactive','discontinued')""", (node_id,))
        d50 = cur.fetchone()
    elif role == "clinic_phc":
        top_sold=[]; top_requested=[]; orders_by_pharmacy=[]; discounted_requests=[]
        cur.execute("""SELECT COALESCE(SUM(quantity),0) units,COUNT(*) batches,
            COALESCE(SUM((quantity-reserved_quantity)*unit_price_inr),0) original_value,COALESCE(SUM((quantity-reserved_quantity)*unit_price_inr*0.7),0) discounted_value
            FROM medicine_batches WHERE DATEDIFF(expiry_date,CURDATE()) BETWEEN 61 AND 90 AND quantity>reserved_quantity
            AND LOWER(batch_status) NOT IN ('expired','inactive','discontinued')""")
        d30=cur.fetchone()
        cur.execute("""SELECT COALESCE(SUM(quantity),0) units,COUNT(*) batches,
            COALESCE(SUM((quantity-reserved_quantity)*unit_price_inr),0) original_value,COALESCE(SUM((quantity-reserved_quantity)*unit_price_inr*0.5),0) discounted_value
            FROM medicine_batches WHERE DATEDIFF(expiry_date,CURDATE()) BETWEEN 31 AND 60 AND quantity>reserved_quantity
            AND LOWER(batch_status) NOT IN ('expired','inactive','discontinued')""")
        d50=cur.fetchone()
    else:
        top_sold=[]; top_requested=[]; orders_by_pharmacy=[]; discounted_requests=[]
        d30={"units":0,"batches":0,"original_value":0,"discounted_value":0}
        d50={"units":0,"batches":0,"original_value":0,"discounted_value":0}

    if own_inventory:
        opportunities = build_opportunities(cur, node_id)
        actual_donations={"units":donations.get("donated_units"),"records":donations.get("donations")}
    else:
        opportunities=build_opportunities(cur, node_id) if role == "clinic_phc" else []
        own_batch_summary={"active_batches":len([b for b in assessed if b["days_left"]>0 and str(b.get("batch_status") or "").casefold() not in {"inactive","discontinued"}]),"units":sum(b["quantity"] for b in assessed if b["days_left"]>0 and str(b.get("batch_status") or "").casefold() not in {"inactive","discontinued"})}
        if role=="charity_ngo":
            actual_donations={"units":donations.get("donated_units"),"records":donations.get("donations")}
        else: actual_donations={"units":0,"records":0}

    tracked=[b for b in assessed if str(b.get("batch_status") or "").casefold() not in {"inactive","discontinued"}]
    active = [b for b in tracked if b["days_left"] > 0 and b["quantity"] > 0]
    if own_inventory:
        own_batch_summary={"active_batches":len([b for b in assessed if b["days_left"]>0 and str(b.get("batch_status") or "").casefold() not in {"inactive","discontinued"}]),"units":sum(int(b["quantity"]) for b in assessed if b["days_left"]>0 and str(b.get("batch_status") or "").casefold() not in {"inactive","discontinued"})}
    risk_codes={"AT_RISK_90_DAYS","AT_RISK_60_DAYS","CRITICAL_30_DAYS"}
    health_keys=["HEALTHY","AT_RISK_90_DAYS","AT_RISK_60_DAYS","CRITICAL_30_DAYS","EXPIRED"]
    health={key:{"batches":0,"units":0} for key in health_keys}
    for b in tracked:
        key=b["risk_status"]
        if key in health:
            health[key]["batches"]+=1
            health[key]["units"]+=int(b["quantity"])
        # charity fallback is the sell/redistribution stage for critical batches.
        if b["stock_status"]=="CHARITY_FALLBACK":
            health["CRITICAL_30_DAYS"]["units"] += 0
    total_health_units=sum(v["units"] for v in health.values())
    for value in health.values(): value["percentage"] = round(100*value["units"]/total_health_units,1) if total_health_units else 0
    expiry_rows=[b for b in tracked if b["risk_status"]!="HEALTHY" or b["stock_status"]=="CHARITY_FALLBACK"]
    velocity_rows=[]
    for b in tracked:
        if b["quantity"]<=0: continue
        velocity=b["daily_velocity"]
        movement="NO_SALES" if velocity<=0 else "FAST_MOVING" if velocity>=settings.velocity_fast_units_per_day else "SLOW_MOVING" if velocity<settings.velocity_slow_units_per_day else "NORMAL"
        velocity_rows.append({**b,"movement_category":movement})
    velocity_rows.sort(key=lambda x:(x["daily_velocity"],x["medicine_name"].casefold()),reverse=True)
    restock=[b for b in tracked if b["restock_recommended"] and b["days_left"]>0 and str(b.get("batch_status") or "").casefold() not in {"expired"}]
    d30_rows=[b for b in active if b["discount_percentage"]==30]
    d50_rows=[b for b in active if b["discount_percentage"]==50]
    charity_rows=[b for b in active if b["stock_status"]=="CHARITY_FALLBACK"]
    fallback={"units":sum(int(b["quantity"]) for b in charity_rows),"batches":len(charity_rows)}
    expired_rows=[b for b in tracked if b["risk_status"]=="EXPIRED"]
    if not own_inventory:
        # A network aggregate for clinic/charity accounts; they are not given seller sales.
        health_summary={key:{"batches":0,"units":0} for key in health_keys}
        for b in tracked:
            health_summary[b["risk_status"]]["batches"]+=1
            health_summary[b["risk_status"]]["units"]+=int(b["quantity"])
        health=health_summary
        total_health_units=sum(x["units"] for x in health.values())
        for value in health.values(): value["percentage"]=round(100*value["units"]/total_health_units,1) if total_health_units else 0
        # Keep detailed supply offers available to connected clinics, but avoid leaking sales velocity.
        velocity_rows=[]; restock=[]

    summary={
        "total_active_batches":_integer(own_batch_summary.get("active_batches")),
        "total_units":_integer(own_batch_summary.get("units")),
        "expiry_risk_units":sum(health.get(k,{}).get("units",0) for k in risk_codes),
        "active_discounts":len(d30_rows)+len(d50_rows),"restock_alerts":len(restock),
        "redistribution_opportunities":len(opportunities),
        "units_redistributed":_integer(transfers.get("units_redistributed")),
        "active_orders":_integer(orders.get("active_orders")),
    }
    if not own_inventory:
        summary.update({"total_active_batches":_integer(own_batch_summary.get("active_batches")),"total_units":_integer(own_batch_summary.get("units")),"active_discounts":len(d30_rows)+len(d50_rows),"restock_alerts":0,"active_orders":0})
    return {
        "scope":{"role":role,"node_id":node_id,"period_start":start.isoformat(),"period_end":end.isoformat(),"inventory_is_current_snapshot":True},
        "summary":summary,
        "inventory_health":{"categories":health,"total_units":total_health_units,"batches":len(tracked)},
        "velocity":{"period_days":30,"fast_threshold_units_per_day":settings.velocity_fast_units_per_day,"slow_threshold_units_per_day":settings.velocity_slow_units_per_day,"rows":velocity_rows[:100]},
        "restock":{"threshold_days":settings.restock_days_threshold,"count":len(restock),"rows":restock[:100]},
        "expiry_risk":{"count":len(expiry_rows),"rows":expiry_rows[:100]},
        "discounts":{"discount_30":{"batches":_integer(d30.get("batches")),"units":_integer(d30.get("units")),"original_value":_money(d30.get("original_value")),"discounted_value":_money(d30.get("discounted_value")),"rows":d30_rows[:100]},"discount_50":{"batches":_integer(d50.get("batches")),"units":_integer(d50.get("units")),"original_value":_money(d50.get("original_value")),"discounted_value":_money(d50.get("discounted_value")),"rows":d50_rows[:100]},"charity_fallback":{"batches":_integer(fallback.get("batches")),"units":_integer(fallback.get("units")),"rows":charity_rows[:100]},"expired":{"batches":len(expired_rows),"units":sum(int(b["quantity"]) for b in expired_rows)}},
        "sales":{"records":_integer(sales.get("sales_count")),"units":_integer(sales.get("units_sold")),"revenue":_money(sales.get("revenue")),"top_medicines":top_sold},
        "redistribution":{"opportunities":len(opportunities),"pending":_integer(transfers.get("pending_count")),"approved":_integer(transfers.get("approved_count")),"in_transit":_integer(transfers.get("in_transit_count")),"completed":_integer(transfers.get("completed_count")),"cancelled":_integer(transfers.get("cancelled_count")),"units_redistributed":_integer(transfers.get("units_redistributed")),"status_distribution":{"pending_approval":_integer(transfers.get("pending_count")),"approved":_integer(transfers.get("approved_count")),"in_transit":_integer(transfers.get("in_transit_count")),"completed":_integer(transfers.get("completed_count")),"cancelled_or_rejected":_integer(transfers.get("cancelled_count"))}},
        "redistribution_details":{"top_medicines":top_transferred,"source_nodes":source_nodes,"destination_nodes":destination_nodes},
        "orders":{"total":_integer(orders.get("total_orders")),"pending":_integer(orders.get("pending_orders")),"confirmed":_integer(orders.get("confirmed_orders")),"ready_for_pickup":_integer(orders.get("ready_orders")),"completed":_integer(orders.get("completed_orders")),"cancelled":_integer(orders.get("cancelled_orders")),"active":_integer(orders.get("active_orders")),"completed_quantity":_integer(orders.get("completed_quantity")),"discounted_order_count":_integer(orders.get("discounted_order_count")),"discounted_order_units":_integer(orders.get("discounted_order_units")),"top_medicines":top_requested,"discounted_medicines":discounted_requests,"by_pharmacy":orders_by_pharmacy},
        "network":{"verified_nodes":_integer(network_nodes.get("connected_nodes")),"pharmacy_nodes":_integer(network_nodes.get("pharmacy_nodes")),"clinic_nodes":_integer(network_nodes.get("clinic_nodes")),"supply_nodes":_integer(supply_nodes.get("supply_nodes")),"demand_nodes":_integer(network_demand.get("demand_nodes")),"network_shortage_units":_integer(network_demand.get("network_shortage_units")),"nodes_with_active_orders":_integer(order_nodes.get("order_nodes")),"active_transfer_node_ends":_integer(transfer_nodes.get("transfer_node_ends")),"own_demand_rows":_integer(demand.get("demand_rows")),"own_shortage_units":_integer(demand.get("shortage_units")),"top_demand_medicines":top_demand,"potential_surplus_medicines":surplus_medicines},
        "impact":{"expiry_risk_units":sum(health.get(k,{}).get("units",0) for k in risk_codes),"discount_30_units":_integer(d30.get("units")),"discount_50_units":_integer(d50.get("units")),"charity_fallback_units":_integer(fallback.get("units")),"redistributed_units":_integer(transfers.get("units_redistributed")),"completed_discounted_sales_units":_integer(orders.get("completed_quantity")),"actual_donated_units":_integer(actual_donations.get("units")),"donation_records":_integer(actual_donations.get("records"))},
        "generated_at":datetime.now().astimezone().isoformat(),
    }


def _deterministic_insights(data):
    s=data["summary"]; expiry=data["expiry_risk"]; restock=data["restock"]
    insights=[]
    if restock["count"]:
        row=restock["rows"][0]
        insights.append({"type":"RESTOCK","observation":f"{restock['count']} restock recommendation(s) meet the configured {restock['threshold_days']:g}-day coverage threshold.","why_it_matters":"These batches have limited estimated cover based on trailing 30-day sales; zero-sales items are excluded from restock alerts.","recommended_action":f"Review {row['medicine_name']} at {row.get('pharmacy_name','your node')}: approximately {row['estimated_days_of_stock']:.1f} days of stock are estimated at current sales velocity."})
    near=[x for x in expiry["rows"] if x["days_left"]<=60 and x["days_left"]>30]
    if near:
        row=min(near,key=lambda x:x["days_left"])
        insights.append({"type":"EXPIRY","observation":f"{len(near)} batch(es) are within the 31–60 day discount window.","why_it_matters":"The Step 5 rule assigns a 50% offer in this window; the discounted inventory remains a current snapshot.","recommended_action":f"Review {row['medicine_name']} batch {row['batch_number']} with {row['days_left']} days remaining."})
    if s["redistribution_opportunities"]:
        insights.append({"type":"REDISTRIBUTION","observation":f"{s['redistribution_opportunities']} valid redistribution opportunity(ies) are currently calculated from eligible stock and active clinic shortages.","why_it_matters":"These are suggested matches, not completed transfers.","recommended_action":"Open P2P Transfers and review the current demand, stock, and eligibility before acting."})
    charity_units=data.get("impact",{}).get("charity_fallback_units",0)
    if charity_units:
        insights.append({"type":"CHARITY","observation":f"{charity_units} available unit(s) are currently flagged in charity fallback.","why_it_matters":"The stock has reached the defined final redistribution window; this is a flag, not proof of donation.","recommended_action":"Review batch eligibility and prepare for the later verified charity handoff workflow."})
    if not insights:
        insights.append({"type":"NETWORK","observation":"No current restock or near-expiry action was identified in the data available to this account.","why_it_matters":"Inventory values represent the current MySQL snapshot; selected time filters affect dated activity only.","recommended_action":"Refresh after inventory, sales, patient orders, or transfers change."})
    return insights


def _ai_insights(metrics, fallback):
    provider=settings.ai_provider
    if provider not in {"gemini","huggingface"}:
        return {"provider":"none","fallback":True,"insights":fallback}
    prompt=("You are PharmSync's analytics explainer. Use only the supplied JSON facts; do not invent names, quantities, statuses, dates, prices, or causal claims. "
            "Return JSON only: {\"insights\":[{\"type\":\"RESTOCK|EXPIRY|REDISTRIBUTION|MARKETPLACE|CHARITY|NETWORK\",\"observation\":\"...\",\"why_it_matters\":\"...\",\"recommended_action\":\"...\"}]}. "
            "At most 4 concise insights. Do not recommend database changes. Metrics: "+json.dumps(metrics,default=str))
    try:
        if provider=="gemini" and settings.gemini_api_key:
            from google import genai
            from google.genai import types
            client=genai.Client(api_key=settings.gemini_api_key)
            response=client.models.generate_content(model=settings.gemini_model,contents=prompt,config=types.GenerateContentConfig(response_mime_type="application/json",temperature=0.1))
            parsed=json.loads(response.text or "{}")
        elif provider=="huggingface" and settings.huggingface_api_key:
            payload=json.dumps({"inputs":prompt,"parameters":{"max_new_tokens":500,"return_full_text":False}}).encode()
            req=Request(f"https://api-inference.huggingface.co/models/{settings.huggingface_model}",data=payload,headers={"Authorization":f"Bearer {settings.huggingface_api_key}","Content-Type":"application/json"},method="POST")
            with urlopen(req,timeout=12) as response: body=json.loads(response.read().decode())
            generated=body[0]["generated_text"] if isinstance(body,list) else body.get("generated_text","")
            match=re.search(r"\{.*\}",generated,re.S)
            parsed=json.loads(match.group(0)) if match else {}
        else:
            raise ValueError("AI provider key not configured")
        rows=parsed.get("insights",[])
        valid=[]
        allowed={"RESTOCK","EXPIRY","REDISTRIBUTION","MARKETPLACE","CHARITY","NETWORK"}
        for row in rows[:4]:
            if isinstance(row,dict) and row.get("type") in allowed and all(isinstance(row.get(k),str) for k in ("observation","why_it_matters","recommended_action")):
                valid.append({k:row[k][:500] for k in ("type","observation","why_it_matters","recommended_action")})
        if not valid: raise ValueError("AI response had no valid insight objects")
        return {"provider":provider,"fallback":False,"insights":valid}
    except Exception:
        return {"provider":provider,"fallback":True,"insights":fallback}


def _intent(question):
    q=question.casefold()
    if any(w in q for w in ("expiry", "expiring", "expire", "risk")): return "expiry_risk"
    if any(w in q for w in ("restock", "stockout", "run out", "running out")): return "restock"
    if any(w in q for w in ("redistribut", "transferred", "transfer", "p2p")): return "redistribution"
    if any(w in q for w in ("demand", "shortage", "requested")): return "demand"
    if any(w in q for w in ("charity", "donat")): return "charity"
    if any(w in q for w in ("discount", "offer")): return "discounts"
    if any(w in q for w in ("order", "patient")): return "orders"
    return "summary"


def _build(user, period, start, end, with_ai=False):
    role,node=_scope(user); from_date,to_date=_period(period,start,end)
    with connection() as conn:
        cur=conn.cursor(dictionary=True)
        result=_load_snapshot(cur,role,node,from_date,to_date)
        cur.close()
    fallback=_deterministic_insights(result)
    result["insights"]=_ai_insights({"summary":result["summary"],"expiry_risk_count":result["expiry_risk"]["count"],"restock_count":result["restock"]["count"],"discounts":result["impact"],"network":result["network"]},fallback) if with_ai else {"provider":"none","fallback":True,"insights":fallback}
    return result


@router.get("/dashboard")
def dashboard(period: str=Query("30d"), start: date|None=None, end: date|None=None, user=Depends(current_user)):
    return {"success":True,**_build(user,period,start,end,with_ai=True)}


@router.get("/summary")
def summary(period: str=Query("30d"), start: date|None=None, end: date|None=None, user=Depends(current_user)):
    data=_build(user,period,start,end)
    return {"success":True,"scope":data["scope"],"summary":data["summary"],"sales":data["sales"],"orders":data["orders"],"redistribution":data["redistribution"],"impact":data["impact"]}


@router.get("/{section}")
def analytics_section(section: str, period: str=Query("30d"), start: date|None=None, end: date|None=None, user=Depends(current_user)):
    if section not in {"inventory-health","velocity","restock","expiry-risk","discounts","redistribution","orders","network","impact","insights"}:
        raise HTTPException(404,"Analytics section not found.")
    data=_build(user,period,start,end,with_ai=section=="insights")
    key=section.replace("-", "_")
    return {"success":True,"scope":data["scope"],"data":data[key]}


@router.post("/query")
def query_analytics(body: dict, period: str=Query("30d"), start: date|None=None, end: date|None=None, user=Depends(current_user)):
    question=body.get("question")
    if not isinstance(question,str) or not question.strip() or len(question)>500:
        raise HTTPException(422,"Enter an analytics question up to 500 characters.")
    data=_build(user,period,start,end); intent=_intent(question)
    fields={"expiry_risk":("Expiry risk",data["expiry_risk"]),"restock":("Restock recommendations",data["restock"]),"redistribution":("Redistribution activity",data["redistribution"]),"demand":("Network demand",data["network"]),"charity":("Charity fallback and verified donation records",data["impact"]),"discounts":("Discount inventory",data["discounts"]),"orders":("Patient orders",data["orders"]),"summary":("Current analytics summary",data["summary"])}
    title,payload=fields[intent]
    # Query intent is an allowlisted selector over already-computed SQL results; no model can provide SQL.
    return {"success":True,"intent":intent,"title":title,"period":data["scope"],"result":payload,"answer":f"{title} is based on the current MySQL records for the selected scope and period."}
