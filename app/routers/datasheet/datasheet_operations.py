from fastapi import APIRouter, HTTPException, Query
from typing import Optional
import json

from app.models import Rate, Quota
from app.schemas.datasheet import (
    DatasheetBaseRequest,
    DimensionResult, CaseResult,
    DatasheetMinTimeResponse, DatasheetMinTimeResultItem,
    DatasheetCapacityAtResponse, DatasheetCapacityAtResultItem,
    DatasheetCapacityDuringResponse, DatasheetCapacityDuringResultItem,
    DatasheetQuotaExhaustionResponse, DatasheetQuotaExhaustionResultItem,
    DatasheetIdleTimePeriodResponse, DatasheetIdleTimePeriodResultItem,
    DatasheetRatesResponse, DatasheetRatesResultItem,
    DatasheetQuotasResponse, DatasheetQuotasResultItem,
    DatasheetLimitsResponse, DatasheetLimitsResultItem,
    EvaluateDatasheetRequest,
)
from app.services.datasheet_evaluator_service import DatasheetEvaluatorService
from app.utils.yaml_utils import load_yaml_source

router = APIRouter()
evaluator_service = DatasheetEvaluatorService()

_PROVIDER_MODE_QUERY = Query(False, description="Provider-centric semantics: capacity is counted at the end of each period window instead of the start. Default: False (client-centric).")
_MAX_BUDGET_QUERY   = Query(None, description="Optional budget. Elastic quotas (overage_cost) are expanded after paying the plan price.")
_EXCLUDE_PLAN_QUERY = Query(False, description="If True, treat max_budget as pure overage budget (plan price already covered).")


def _build_request(base: DatasheetBaseRequest, operation: str, operation_params: dict) -> EvaluateDatasheetRequest:
    return EvaluateDatasheetRequest(
        datasheet_source=base.datasheet_source,
        plan_names=base.plan_names,
        endpoint_path=base.endpoint_path,
        alias=base.alias,
        operation=operation,
        operation_params=operation_params,
    )


def _group_dimensions(result) -> dict:
    """Groups a flat List[DimensionResult] into Dict[dimension, List[CaseResult]]."""
    if not isinstance(result, list) or not result or not isinstance(result[0], DimensionResult):
        return {"requests": [CaseResult(capacity_request_factor=None, value=result)]}
    grouped: dict = {}
    for dr in result:
        grouped.setdefault(dr.dimension, []).append(
            CaseResult(capacity_request_factor=dr.workload_factor, value=dr.value)
        )
    return grouped


def _parse_crf(capacity_unit: Optional[str], capacity_request_factor: Optional[str]) -> Optional[dict]:
    """
    Parses capacity_request_factor into Dict[str, float] for the service.

    Accepts:
      - JSON dict string: '{"emails": 500, "MBs": 0.256}'  → multi-unit CRF
      - Plain number string: "500" (requires capacity_unit)  → single-unit CRF
    Endpoints whose workload does not include a given unit simply ignore that CRF key.
    """
    if not capacity_request_factor:
        return None
    try:
        parsed = json.loads(capacity_request_factor)
        if isinstance(parsed, dict):
            return {k: float(v) for k, v in parsed.items()}
        if isinstance(parsed, (int, float)) and capacity_unit:
            return {capacity_unit: float(parsed)}
        return None
    except (json.JSONDecodeError, ValueError):
        pass
    try:
        val = float(capacity_request_factor)
        if capacity_unit:
            return {capacity_unit: val}
    except ValueError:
        raise ValueError(
            f"capacity_request_factor must be a number or a JSON dict, got: {capacity_request_factor!r}"
        )
    return None


@router.post("/min-time", response_model=DatasheetMinTimeResponse, response_model_exclude_none=True)
def get_min_time(
    request: DatasheetBaseRequest,
    capacity_goal: int = Query(..., description="Number of units to reach"),
    capacity_unit: Optional[str] = Query(None, description="Unit dimension to filter results (e.g. 'emails', 'requests'). Returns all if omitted."),
    capacity_request_factor: Optional[str] = Query(None, description="Fixed workload per unit. Plain number (e.g. '500') requires capacity_unit. JSON dict (e.g. '{\"emails\":500,\"MBs\":0.256}') sets multiple units at once."),
    max_budget: Optional[float] = _MAX_BUDGET_QUERY,
    exclude_plan_price: bool = _EXCLUDE_PLAN_QUERY,
    provider_mode: bool = _PROVIDER_MODE_QUERY,
):
    yaml_data = load_yaml_source(request.datasheet_source)
    try:
        raw = evaluator_service.evaluate(
            yaml_data,
            _build_request(request, "min_time", {"capacity_goal": capacity_goal}),
            capacity_unit=capacity_unit,
            capacity_request_factor=_parse_crf(capacity_unit, capacity_request_factor),
            provider_mode=provider_mode,
            max_budget=max_budget,
            exclude_plan_price=exclude_plan_price,
        )
        return DatasheetMinTimeResponse(
            capacity_goal=capacity_goal,
            results={
                plan: [DatasheetMinTimeResultItem(endpoint=r.endpoint, alias=r.alias, dimensions=_group_dimensions(r.result)) for r in items]
                for plan, items in raw.items()
            },
        )
    except (ValueError, KeyError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/capacity-at", response_model=DatasheetCapacityAtResponse, response_model_exclude_none=True)
def get_capacity_at(
    request: DatasheetBaseRequest,
    time: str = Query(..., description="Time instant (e.g. '1h', '1day')"),
    capacity_unit: Optional[str] = Query(None, description="Unit dimension to filter results (e.g. 'emails', 'requests'). Returns all if omitted."),
    capacity_request_factor: Optional[str] = Query(None, description="Fixed workload per unit. Plain number (e.g. '500') requires capacity_unit. JSON dict (e.g. '{\"emails\":500,\"MBs\":0.256}') sets multiple units at once."),
    max_budget: Optional[float] = _MAX_BUDGET_QUERY,
    exclude_plan_price: bool = _EXCLUDE_PLAN_QUERY,
    provider_mode: bool = _PROVIDER_MODE_QUERY,
):
    yaml_data = load_yaml_source(request.datasheet_source)
    try:
        raw = evaluator_service.evaluate(
            yaml_data,
            _build_request(request, "capacity_at", {"time": time}),
            capacity_unit=capacity_unit,
            capacity_request_factor=_parse_crf(capacity_unit, capacity_request_factor),
            provider_mode=provider_mode,
            max_budget=max_budget,
            exclude_plan_price=exclude_plan_price,
        )
        return DatasheetCapacityAtResponse(
            time=time,
            results={
                plan: [DatasheetCapacityAtResultItem(endpoint=r.endpoint, alias=r.alias, dimensions=_group_dimensions(r.result)) for r in items]
                for plan, items in raw.items()
            },
        )
    except (ValueError, KeyError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/capacity-during", response_model=DatasheetCapacityDuringResponse, response_model_exclude_none=True)
def get_capacity_during(
    request: DatasheetBaseRequest,
    end_instant: str = Query(..., description="End time instant (e.g. '1day')"),
    start_instant: Optional[str] = Query("0ms", description="Start time instant (e.g. '0ms')"),
    capacity_unit: Optional[str] = Query(None, description="Unit dimension to filter results (e.g. 'emails', 'requests'). Returns all if omitted."),
    capacity_request_factor: Optional[str] = Query(None, description="Fixed workload per unit. Plain number (e.g. '500') requires capacity_unit. JSON dict (e.g. '{\"emails\":500,\"MBs\":0.256}') sets multiple units at once."),
    max_budget: Optional[float] = _MAX_BUDGET_QUERY,
    exclude_plan_price: bool = _EXCLUDE_PLAN_QUERY,
    provider_mode: bool = _PROVIDER_MODE_QUERY,
):
    yaml_data = load_yaml_source(request.datasheet_source)
    try:
        raw = evaluator_service.evaluate(
            yaml_data,
            _build_request(request, "capacity_during", {"end_instant": end_instant, "start_instant": start_instant}),
            capacity_unit=capacity_unit,
            capacity_request_factor=_parse_crf(capacity_unit, capacity_request_factor),
            provider_mode=provider_mode,
            max_budget=max_budget,
            exclude_plan_price=exclude_plan_price,
        )
        return DatasheetCapacityDuringResponse(
            start_instant=start_instant,
            end_instant=end_instant,
            results={
                plan: [DatasheetCapacityDuringResultItem(endpoint=r.endpoint, alias=r.alias, dimensions=_group_dimensions(r.result)) for r in items]
                for plan, items in raw.items()
            },
        )
    except (ValueError, KeyError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/quota-exhaustion-threshold", response_model=DatasheetQuotaExhaustionResponse, response_model_exclude_none=True)
def get_quota_exhaustion_threshold(
    request: DatasheetBaseRequest,
    capacity_unit: Optional[str] = Query(None, description="Unit dimension to filter results (e.g. 'emails', 'requests'). Returns all if omitted."),
    capacity_request_factor: Optional[str] = Query(None, description="Fixed workload per unit. Plain number (e.g. '500') requires capacity_unit. JSON dict (e.g. '{\"emails\":500,\"MBs\":0.256}') sets multiple units at once."),
    max_budget: Optional[float] = _MAX_BUDGET_QUERY,
    exclude_plan_price: bool = _EXCLUDE_PLAN_QUERY,
    provider_mode: bool = _PROVIDER_MODE_QUERY,
):
    yaml_data = load_yaml_source(request.datasheet_source)
    try:
        raw = evaluator_service.evaluate(
            yaml_data,
            _build_request(request, "quota_exhaustion_threshold", {}),
            capacity_unit=capacity_unit,
            capacity_request_factor=_parse_crf(capacity_unit, capacity_request_factor),
            provider_mode=provider_mode,
            max_budget=max_budget,
            exclude_plan_price=exclude_plan_price,
        )
        return DatasheetQuotaExhaustionResponse(
            results={
                plan: [DatasheetQuotaExhaustionResultItem(endpoint=r.endpoint, alias=r.alias, dimensions=_group_dimensions(r.result)) for r in items]
                for plan, items in raw.items()
            }
        )
    except (ValueError, KeyError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/idle-time-period", response_model=DatasheetIdleTimePeriodResponse, response_model_exclude_none=True)
def get_idle_time_period(
    request: DatasheetBaseRequest,
    capacity_unit: Optional[str] = Query(None, description="Unit dimension to filter results (e.g. 'emails', 'requests'). Returns all if omitted."),
    capacity_request_factor: Optional[str] = Query(None, description="Fixed workload per unit. Plain number (e.g. '500') requires capacity_unit. JSON dict (e.g. '{\"emails\":500,\"MBs\":0.256}') sets multiple units at once."),
    max_budget: Optional[float] = _MAX_BUDGET_QUERY,
    exclude_plan_price: bool = _EXCLUDE_PLAN_QUERY,
    provider_mode: bool = _PROVIDER_MODE_QUERY,
):
    yaml_data = load_yaml_source(request.datasheet_source)
    try:
        raw = evaluator_service.evaluate(
            yaml_data,
            _build_request(request, "idle_time_period", {}),
            capacity_unit=capacity_unit,
            capacity_request_factor=_parse_crf(capacity_unit, capacity_request_factor),
            provider_mode=provider_mode,
            max_budget=max_budget,
            exclude_plan_price=exclude_plan_price,
        )
        return DatasheetIdleTimePeriodResponse(
            results={
                plan: [DatasheetIdleTimePeriodResultItem(endpoint=r.endpoint, alias=r.alias, dimensions=_group_dimensions(r.result)) for r in items]
                for plan, items in raw.items()
            }
        )
    except (ValueError, KeyError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/rates", response_model=DatasheetRatesResponse, response_model_exclude_none=True)
def get_rates(request: DatasheetBaseRequest):
    yaml_data = load_yaml_source(request.datasheet_source)
    try:
        raw = evaluator_service.evaluate(yaml_data, _build_request(request, "rates", {}))
        return DatasheetRatesResponse(
            results={
                plan: [DatasheetRatesResultItem(endpoint=r.endpoint, alias=r.alias, rates=r.result) for r in items]
                for plan, items in raw.items()
            }
        )
    except (ValueError, KeyError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/quotas", response_model=DatasheetQuotasResponse, response_model_exclude_none=True)
def get_quotas(request: DatasheetBaseRequest):
    yaml_data = load_yaml_source(request.datasheet_source)
    try:
        raw = evaluator_service.evaluate(yaml_data, _build_request(request, "quotas", {}))
        return DatasheetQuotasResponse(
            results={
                plan: [DatasheetQuotasResultItem(endpoint=r.endpoint, alias=r.alias, quotas=r.result) for r in items]
                for plan, items in raw.items()
            }
        )
    except (ValueError, KeyError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/limits", response_model=DatasheetLimitsResponse, response_model_exclude_none=True)
def get_limits(request: DatasheetBaseRequest):
    yaml_data = load_yaml_source(request.datasheet_source)
    try:
        raw = evaluator_service.evaluate(yaml_data, _build_request(request, "limits", {}))
        return DatasheetLimitsResponse(
            results={
                plan: [
                    DatasheetLimitsResultItem(
                        endpoint=r.endpoint,
                        alias=r.alias,
                        rates=[l for l in r.result if isinstance(l, Rate)],
                        quotas=[l for l in r.result if isinstance(l, Quota)],
                    )
                    for r in items
                ]
                for plan, items in raw.items()
            }
        )
    except (ValueError, KeyError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
