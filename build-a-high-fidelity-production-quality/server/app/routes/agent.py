from fastapi import APIRouter, Depends
from app.middleware.auth import require_retail
from app.routes.inventory import pharmacy_node
from app.services.inventory_agent import run_agent

router = APIRouter(prefix="/api/agent", tags=["inventory agent"])


@router.post("/inventory/run")
def run_inventory_agent(user=Depends(require_retail)):
    node = pharmacy_node(user)
    return run_agent(node["node_id"])
