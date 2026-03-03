from fastapi import APIRouter, HTTPException, Query

from app.schemas import BoundedRateRequest, MinTimeResponse
from app.services import BasicOperationsService

router = APIRouter()
service = BasicOperationsService()

@router.post("/min-time", response_model=MinTimeResponse)
def get_min_time(request: BoundedRateRequest, capacity_goal: int = Query(..., description="Capacity goal")):
    try:
        min_time = service.calculate_min_time(capacity_goal, request.rate, request.quota)
        return MinTimeResponse(capacity_goal=capacity_goal, min_time=min_time)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))