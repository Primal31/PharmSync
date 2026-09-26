from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from mysql.connector import Error as MySQLError
from fastapi.exceptions import RequestValidationError
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from app.config.settings import settings
from app.database.connection import get_connection
from app.routes import auth, inventory, sales, scanner, agent, transfers, medicines, orders, analytics
from app.services.inventory_agent import run_agent

@asynccontextmanager
async def lifespan(_app: FastAPI):
    if not settings.jwt_secret or settings.jwt_secret.startswith(("YOUR_", "REPLACE_")):
        raise RuntimeError("Set a secure JWT_SECRET in server/.env before starting the PharmSync API.")
    try:
        conn=get_connection()
    except Exception as exc:
        raise RuntimeError(f"Unable to connect to MySQL at {settings.db_host}:{settings.db_port}/{settings.db_name}. Check MySQL and server/.env. {exc}") from exc
    try:
        conn.ping(reconnect=True, attempts=1, delay=0)
        print("MySQL connected successfully")
    finally: conn.close()
    scheduler = AsyncIOScheduler(timezone="Asia/Kolkata")
    scheduler.add_job(run_agent, "cron", hour=settings.inventory_agent_hour, minute=settings.inventory_agent_minute,
                      id="pharmsync-inventory-intelligence", replace_existing=True, max_instances=1, coalesce=True)
    scheduler.start()
    print(f"Inventory Intelligence Agent scheduled daily at {settings.inventory_agent_hour:02d}:{settings.inventory_agent_minute:02d} Asia/Kolkata")
    try:
        yield
    finally:
        scheduler.shutdown(wait=False)

app=FastAPI(title="PharmSync API",version="4.0.0",lifespan=lifespan)
app.add_middleware(CORSMiddleware,allow_origins=settings.client_origins,allow_credentials=True,allow_methods=["GET","POST","PUT","DELETE","PATCH","OPTIONS"],allow_headers=["Authorization","Content-Type"])
app.include_router(auth.router);app.include_router(inventory.router);app.include_router(sales.router);app.include_router(scanner.router);app.include_router(agent.router);app.include_router(transfers.router);app.include_router(medicines.router);app.include_router(orders.orders_router);app.include_router(orders.pharmacy_router)
app.include_router(analytics.router)

@app.exception_handler(HTTPException)
async def http_error(_request: Request, exc: HTTPException):
    return JSONResponse(status_code=exc.status_code,content={"success":False,"message":str(exc.detail),"detail":exc.detail})

@app.exception_handler(RequestValidationError)
async def validation_error(_request: Request, _exc: RequestValidationError):
    message="Please check the submitted fields and try again."
    return JSONResponse(status_code=422,content={"success":False,"message":message,"detail":message})

@app.get("/api/health")
def health(): return {"success":True,"service":"pharmsync-api","backend":"fastapi"}

@app.exception_handler(MySQLError)
async def mysql_error(_request: Request, exc: MySQLError):
    print(f"MySQL operation failed: {exc.errno}")
    return JSONResponse(status_code=503,content={"success":False,"message":"MySQL database connection unavailable."})

@app.exception_handler(Exception)
async def unexpected_error(_request: Request, exc: Exception):
    print(f"Unhandled API error: {type(exc).__name__}")
    return JSONResponse(status_code=500,content={"success":False,"message":"Unable to complete your request right now."})
