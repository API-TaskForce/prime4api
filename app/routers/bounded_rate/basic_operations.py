from fastapi import APIRouter, HTTPException, Query
from typing import Optional

from app.schemas import (
    BoundedRateRequest,
    MinTimeResponse,
    CapacityAtResponse,
    CapacityDuringResponse,
    QuotaExhaustionThresholdResponse,
    QuotaExhaustionThresholdItem,
    RatesResponse,
    QuotasResponse,
    LimitsResponse,
    IdleTimePeriodResponse,
    IdleTimePeriodItem,
)
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


@router.post("/capacity-at", response_model=CapacityAtResponse)
def get_capacity_at(request: BoundedRateRequest, time: str = Query(..., description="Time instant (e.g. '1h', '1day')")):
    try:
        capacity = service.calculate_capacity_at(time, request.rate, request.quota)
        return CapacityAtResponse(time=time, capacity=capacity)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/capacity-during", response_model=CapacityDuringResponse)
def get_capacity_during(
    request: BoundedRateRequest,
    end_instant: str = Query(..., description="End time instant (e.g. '1day')"),
    start_instant: Optional[str] = Query("0ms", description="Start time instant (e.g. '0ms')"),
):
    try:
        capacity = service.calculate_capacity_during(end_instant, request.rate, request.quota, start_instant)
        return CapacityDuringResponse(start_instant=start_instant, end_instant=end_instant, capacity=capacity)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/quota-exhaustion-threshold", response_model=QuotaExhaustionThresholdResponse)
def get_quota_exhaustion_threshold(request: BoundedRateRequest):
    try:
        results = service.calculate_quota_exhaustion_threshold(request.rate, request.quota)
        items = [QuotaExhaustionThresholdItem(**r) for r in results]
        return QuotaExhaustionThresholdResponse(thresholds=items)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/rates", response_model=RatesResponse)
def get_rates(request: BoundedRateRequest):
    try:
        rates = service.get_rates(request.rate, request.quota)
        return RatesResponse(rates=rates)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/quotas", response_model=QuotasResponse)
def get_quotas(request: BoundedRateRequest):
    try:
        quotas = service.get_quotas(request.rate, request.quota)
        return QuotasResponse(quotas=quotas)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/limits", response_model=LimitsResponse)
def get_limits(request: BoundedRateRequest):
    try:
        rates = service.get_rates(request.rate, request.quota)
        quotas = service.get_quotas(request.rate, request.quota)
        return LimitsResponse(rates=rates, quotas=quotas)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/idle-time-period", response_model=IdleTimePeriodResponse)
def get_idle_time_period(request: BoundedRateRequest):
    try:
        results = service.calculate_idle_time_period(request.rate, request.quota)
        items = [IdleTimePeriodItem(**r) for r in results]
        return IdleTimePeriodResponse(idle_times=items)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))