from uuid import uuid4
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from app.database.connection import connection, get_connection
from app.middleware.auth import require_retail
from app.routes.inventory import audit, pharmacy_node

router=APIRouter(prefix="/api/sales",tags=["sales"])

class SaleItem(BaseModel):
    batch_id: str
    quantity: int = Field(gt=0)
class SaleRequest(BaseModel):
    items: list[SaleItem] = Field(min_length=1,max_length=50)

@router.get("/summary")
def get_sales_summary(user=Depends(require_retail)):
    return get_sales(search="", user=user)

@router.get("")
def get_sales(search: str = "", user=Depends(require_retail)):
    node=pharmacy_node(user)
    with connection() as conn:
        cur=conn.cursor(dictionary=True)
        cur.execute("SELECT COUNT(*) todaysSales,COALESCE(SUM(quantity_sold),0) totalUnitsSold,COALESCE(SUM(total_amount_inr),0) salesRevenue FROM sales WHERE pharmacy_id=%s AND sale_date=CURDATE()",(node["node_id"],));summary=cur.fetchone()
        cur.execute("SELECT sale_id,sale_date,batch_id,medicine_id,medicine_name,quantity_sold,unit_price_inr,total_amount_inr FROM sales WHERE pharmacy_id=%s ORDER BY sale_date DESC,sale_id DESC LIMIT 100",(node["node_id"],));recent=cur.fetchall()
        cur.execute("SELECT medicine_id,MAX(medicine_name) medicine_name,SUM(quantity_sold) quantity_sold_30d,SUM(quantity_sold)/30 daily_sales_velocity FROM sales WHERE pharmacy_id=%s AND sale_date>=DATE_SUB(CURDATE(),INTERVAL 30 DAY) AND sale_date<=CURDATE() GROUP BY medicine_id ORDER BY daily_sales_velocity DESC LIMIT 20",(node["node_id"],));velocity=cur.fetchall()
        if search.strip():
            term=f"%{search.strip()}%"
            cur.execute("SELECT sale_id,sale_date,pharmacy_id,batch_id,medicine_id,medicine_name,quantity_sold,unit_price_inr,total_amount_inr FROM sales WHERE pharmacy_id=%s AND (medicine_name LIKE %s OR medicine_id LIKE %s OR batch_id LIKE %s OR sale_id LIKE %s) ORDER BY sale_date DESC,sale_id DESC LIMIT 250",(node["node_id"],term,term,term,term));recent=cur.fetchall()
        cur.close()
    return {"success":True,"pharmacy":node,"summary":summary,"recent":recent,"velocity":velocity,"rows":recent}

@router.post("",status_code=201)
def create_sale(body: SaleRequest,user=Depends(require_retail)):
    node=pharmacy_node(user)
    quantities={}
    for item in body.items: quantities[item.batch_id]=quantities.get(item.batch_id,0)+item.quantity
    conn=None
    try:
        conn=get_connection();cur=conn.cursor(dictionary=True);completed=[]
        for batch_id,quantity in sorted(quantities.items()):
            cur.execute("SELECT batch_id,medicine_id,medicine_name,batch_number,node_id,quantity,COALESCE(reserved_quantity,0) reserved_quantity,unit_price_inr,batch_status,DATEDIFF(expiry_date,CURDATE()) days_remaining FROM medicine_batches WHERE node_id=%s AND batch_id=%s FOR UPDATE",(node["node_id"],batch_id));batch=cur.fetchone()
            if not batch: raise HTTPException(404,f"Batch {batch_id} was not found in this pharmacy.")
            if batch["days_remaining"]<=30 or batch["batch_status"].lower() in {"expired","inactive","discontinued","charity_fallback"}: raise HTTPException(409,f"Batch {batch['batch_number']} is at charity fallback or expired and is not available for commercial sale.")
            available=int(batch["quantity"])-int(batch.get("reserved_quantity") or 0)
            if quantity>available: raise HTTPException(409,f"Insufficient stock. Only {available} units are available for {batch['medicine_name']}.")
            discount=50 if batch["days_remaining"]<=60 else 30 if batch["days_remaining"]<=90 else 0
            unit=round(float(batch["unit_price_inr"])*(1-discount/100),2);total=round(unit*quantity,2);sale_id="S"+uuid4().hex[:20].upper()
            cur.execute("UPDATE medicine_batches SET quantity=quantity-%s WHERE node_id=%s AND batch_id=%s",(quantity,node["node_id"],batch_id))
            cur.execute("INSERT INTO sales(sale_id,sale_date,pharmacy_id,batch_id,medicine_id,medicine_name,quantity_sold,unit_price_inr,total_amount_inr) VALUES(%s,CURDATE(),%s,%s,%s,%s,%s,%s,%s)",(sale_id,node["node_id"],batch_id,batch["medicine_id"],batch["medicine_name"],quantity,unit,total))
            audit(cur,"SALE_CREATED","sale",sale_id,f"Sold {quantity} units of {batch['medicine_name']}, batch {batch['batch_number']}.")
            completed.append({"sale_id":sale_id,"batch_id":batch_id,"medicine_id":batch["medicine_id"],"medicine_name":batch["medicine_name"],"quantity_sold":quantity,"discount_percentage":discount,"unit_price_inr":unit,"total_amount_inr":total})
        conn.commit();cur.close()
        return {"success":True,"sales":completed,"total":round(sum(row["total_amount_inr"] for row in completed),2)}
    except Exception:
        if conn: conn.rollback()
        raise
    finally:
        if conn: conn.close()
