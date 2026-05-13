from fastapi import FastAPI
from app.routers.bounded_rate.basic_operations import router as bounded_rate_router
from app.routers.bounded_rate.capacity_curves import router as capacity_curves_router
from app.routers.datasheet.evaluate import router as datasheet_mcp_router
from app.routers.datasheet.datasheet_operations import router as datasheet_router
from app.routers.datasheet.capacity_curves import router as datasheet_curves_router
from app.routers.datasheet.datasheet_navigation import router as datasheet_nav_router
from app.routers.datasheet.demand_evaluation import router as demand_eval_router
from app.routers.datasheet.budget_operations import router as budget_router
import uvicorn

# 1. Instanciamos la aplicación pura
app = FastAPI(
    title="PRIME4API",
    description="Motor de cálculo y evaluación de datasheets de APIs",
    version="0.1.0"
)

# 2. Endpoint de salud (Health Check) - El único permitido en main.py
@app.get("/")
def health_check():
    return {"status": "ok", "message": "PRIME4API is alive and ready."}

# 3. Aquí es donde "enchufaremos" las rutas reales más adelante

app.include_router(bounded_rate_router, prefix="/api/v1/bounded-rate", tags=["Bounded Rate"])
app.include_router(capacity_curves_router, prefix="/api/v1/capacity-curves", tags=["Capacity Curves"])
app.include_router(datasheet_router, prefix="/api/v1/datasheet", tags=["Datasheet"])
app.include_router(datasheet_curves_router, prefix="/api/v1/datasheet/capacity-curves", tags=["Datasheet Capacity Curves"])
app.include_router(datasheet_nav_router, prefix="/api/v1/datasheet/nav", tags=["Datasheet Navigation"])
app.include_router(datasheet_mcp_router, prefix="/api/v1/datasheet/mcp", tags=["Datasheet MCP Server Tool"])
app.include_router(demand_eval_router, prefix="/api/v1/datasheet/demand-evaluation", tags=["Datasheet Demand Evaluation"])
app.include_router(budget_router, prefix="/api/v1/datasheet/budget", tags=["Datasheet Budget"])

def start_dev():
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)
