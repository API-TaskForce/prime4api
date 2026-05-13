from fastapi import APIRouter, HTTPException, Query
from typing import Optional, List

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
from app.models import Quota
from app.services import BasicOperationsService
from app.services.budget_service import BudgetService

router = APIRouter()
service = BasicOperationsService()
budget_service = BudgetService()

_PROVIDER_MODE_QUERY = Query(False, description="Provider-centric semantics: capacity is counted at the end of each period window instead of the start. Default: False (client-centric).")
_MAX_BUDGET_QUERY = Query(None, description="Optional budget for overage. Quotas with overage_cost are expanded to the full budget (no plan price deducted for direct operations).")


def _apply_budget(quota, max_budget: Optional[float]):
    """Expands quotas with overage_cost using max_budget as the full remaining budget."""
    if max_budget is None:
        return quota
    quotas: List[Quota] = [quota] if isinstance(quota, Quota) else (quota or [])
    expanded, _, _ = budget_service.expand_quotas(quotas, plan_price=0.0, max_budget=max_budget, exclude_plan_price=True)
    return expanded if len(expanded) != 1 else expanded[0] if isinstance(quota, Quota) else expanded


@router.post("/min-time", response_model=MinTimeResponse)
def get_min_time(
    request: BoundedRateRequest,
    capacity_goal: int = Query(..., description="Capacity goal"),
    max_budget: Optional[float] = _MAX_BUDGET_QUERY,
    provider_mode: bool = _PROVIDER_MODE_QUERY,
):
    try:
        quota = _apply_budget(request.quota, max_budget)
        min_time = service.calculate_min_time(capacity_goal, request.rate, quota, provider_mode=provider_mode)
        return MinTimeResponse(capacity_goal=capacity_goal, min_time=min_time)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/capacity-at", response_model=CapacityAtResponse)
def get_capacity_at(
    request: BoundedRateRequest,
    time: str = Query(..., description="Time instant (e.g. '1h', '1day')"),
    max_budget: Optional[float] = _MAX_BUDGET_QUERY,
    provider_mode: bool = _PROVIDER_MODE_QUERY,
):
    try:
        quota = _apply_budget(request.quota, max_budget)
        capacity = service.calculate_capacity_at(time, request.rate, quota, provider_mode=provider_mode)
        return CapacityAtResponse(time=time, capacity=capacity)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/capacity-during", response_model=CapacityDuringResponse)
def get_capacity_during(
    request: BoundedRateRequest,
    end_instant: str = Query(..., description="End time instant (e.g. '1day')"),
    start_instant: Optional[str] = Query("0ms", description="Start time instant (e.g. '0ms')"),
    max_budget: Optional[float] = _MAX_BUDGET_QUERY,
    provider_mode: bool = _PROVIDER_MODE_QUERY,
):
    try:
        quota = _apply_budget(request.quota, max_budget)
        capacity = service.calculate_capacity_during(end_instant, request.rate, quota, start_instant, provider_mode=provider_mode)
        return CapacityDuringResponse(start_instant=start_instant, end_instant=end_instant, capacity=capacity)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/quota-exhaustion-threshold", response_model=QuotaExhaustionThresholdResponse)
def get_quota_exhaustion_threshold(
    request: BoundedRateRequest,
    max_budget: Optional[float] = _MAX_BUDGET_QUERY,
    provider_mode: bool = _PROVIDER_MODE_QUERY,
):
    try:
        quota = _apply_budget(request.quota, max_budget)
        results = service.calculate_quota_exhaustion_threshold(request.rate, quota, provider_mode=provider_mode)
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
def get_idle_time_period(
    request: BoundedRateRequest,
    max_budget: Optional[float] = _MAX_BUDGET_QUERY,
    provider_mode: bool = _PROVIDER_MODE_QUERY,
):
    try:
        quota = _apply_budget(request.quota, max_budget)
        results = service.calculate_idle_time_period(request.rate, quota, provider_mode=provider_mode)
        items = [IdleTimePeriodItem(**r) for r in results]
        return IdleTimePeriodResponse(idle_times=items)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))