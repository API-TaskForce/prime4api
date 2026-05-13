from fastapi import APIRouter, HTTPException, Query, Response
from typing import Optional, List
import json

from app.schemas.datasheet import DatasheetBaseRequest, DatasheetCurveSeries, DatasheetCurveDataResponse
from app.schemas.datasheet import EvaluateDatasheetRequest
from app.services.datasheet_evaluator_service import DatasheetEvaluatorService
from app.services.capacity_curve_service import CapacityCurveService
from app.services.budget_service import BudgetService
from app.models import Quota
from app.utils.yaml_utils import load_yaml_source
from app.utils.plotly_renderer import render_multi_curve_html
from app.utils.time_utils import parse_time_string_to_duration, select_best_time_unit

router = APIRouter()
evaluator_service = DatasheetEvaluatorService()
curve_service = CapacityCurveService()
budget_service = BudgetService()

_CURVE_QUERY = dict(description="Time window for the curve (e.g. '1day', '1month')")
_UNIT_QUERY  = dict(description="Filter to a single dimension (e.g. 'emails', 'requests'). Returns all if omitted.")
_CRF_QUERY   = dict(description="Fixed workload per unit. Plain number (e.g. '500') requires capacity_unit. JSON dict (e.g. '{\"emails\":500,\"MBs\":0.256}') sets multiple units at once.")
_PROVIDER_MODE_QUERY = Query(False, description="Provider-centric semantics: capacity is counted at the end of each period window instead of the start. Default: False (client-centric).")
_MAX_BUDGET_QUERY = Query(None, description="Optional budget. Elastic quotas (those with overage_cost) are expanded as far as the budget allows after paying the plan price.")
_EXCLUDE_PLAN_QUERY = Query(False, description="If True, treat max_budget as pure overage budget (plan price already covered).")


def _build_nav_request(base: DatasheetBaseRequest) -> EvaluateDatasheetRequest:
    return EvaluateDatasheetRequest(
        datasheet_source=base.datasheet_source,
        plan_names=base.plan_names,
        endpoint_path=base.endpoint_path,
        alias=base.alias,
        operation="__nav__",
        operation_params={},
    )


def _parse_crf(capacity_unit: Optional[str], capacity_request_factor: Optional[str]) -> Optional[dict]:
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


def _time_axis_params(time_interval: str):
    td = parse_time_string_to_duration(time_interval)
    best = select_best_time_unit(td.to_milliseconds())
    return best.unit.value, best.unit.to_milliseconds()


def _series_label(sc: dict) -> str:
    crf = f" | CRF={sc['crf']}" if sc["crf"] is not None else ""
    alias = f" [{sc['alias']}]" if sc["alias"] else ""
    return f"{sc['plan']} / {sc['endpoint']}{alias} — {sc['dimension']}{crf}"


def _get_curve_points(sc: dict, time_interval: str, curve_type: str, provider_mode: bool = False):
    rates  = sc["rates"]  if sc["rates"]  else None
    quotas = sc["quotas"] if sc["quotas"] else None
    if curve_type == "accumulated":
        return curve_service.get_accumulated_capacity_curve(time_interval, rates, quotas, provider_mode=provider_mode)
    return curve_service.get_inflection_point_capacity_curve(time_interval, rates, quotas, provider_mode=provider_mode)


def _apply_budget_to_scenarios(yaml_data: dict, scenarios: list, max_budget: Optional[float], exclude_plan_price: bool) -> list:
    """Expands elastic quotas in every scenario using plan-level pricing."""
    if max_budget is None:
        return scenarios
    result = []
    for sc in scenarios:
        pricing = evaluator_service.get_plan_pricing(yaml_data, sc["plan"])
        expanded, _, _ = budget_service.expand_quotas(
            sc["quotas"], pricing["price"], max_budget, exclude_plan_price
        )
        result.append({**sc, "quotas": expanded})
    return result


def _render_chart(base, time_interval, capacity_unit, capacity_request_factor, curve_type, line_shape,
                  provider_mode: bool = False, max_budget: Optional[float] = None, exclude_plan_price: bool = False):
    data = _render_data(base, time_interval, capacity_unit, capacity_request_factor, curve_type,
                        provider_mode, max_budget, exclude_plan_price)

    series_list = [
        {
            "plan":          s.plan,
            "endpoint":      s.endpoint,
            "alias":         s.alias,
            "dimension":     s.dimension,
            "workload_unit": s.workload_unit,
            "crf":           s.capacity_request_factor,
            "rates":         s.rates,
            "quotas":        s.quotas,
            "t_ms":          s.t_ms,
            "capacity":      s.capacity,
        }
        for s in data.series
    ]

    if not series_list:
        raise ValueError("No valid curves could be generated for the given parameters.")

    x_unit_label, x_scale_divisor = _time_axis_params(time_interval)
    budget_tag = f" | budget ${max_budget}" if max_budget is not None else ""
    title = f"{'Accumulated' if curve_type == 'accumulated' else 'Inflection Point'} Capacity Curve — {time_interval}{budget_tag}"
    return render_multi_curve_html(series_list, title, line_shape, x_unit_label, x_scale_divisor)


def _render_data(base, time_interval, capacity_unit, capacity_request_factor, curve_type,
                 provider_mode: bool = False, max_budget: Optional[float] = None, exclude_plan_price: bool = False):
    yaml_data = load_yaml_source(base.datasheet_source)
    scenarios = evaluator_service.get_curve_scenarios(
        yaml_data,
        _build_nav_request(base),
        capacity_unit=capacity_unit,
        capacity_request_factor=_parse_crf(capacity_unit, capacity_request_factor),
    )
    scenarios = _apply_budget_to_scenarios(yaml_data, scenarios, max_budget, exclude_plan_price)

    series = []
    for sc in scenarios:
        try:
            pts = _get_curve_points(sc, time_interval, curve_type, provider_mode)
            series.append(DatasheetCurveSeries(
                plan=sc["plan"],
                endpoint=sc["endpoint"],
                alias=sc["alias"],
                dimension=sc["dimension"],
                workload_unit=sc.get("workload_unit"),
                capacity_request_factor=sc["crf"],
                rates=sc["rates"],
                quotas=sc["quotas"],
                t_ms=pts.t_ms,
                capacity=pts.capacity,
            ))
        except Exception as e:
            print(f"[WARNING] Skipping data for {_series_label(sc)}: {e}")

    return DatasheetCurveDataResponse(
        time_interval=time_interval,
        curve_type=curve_type,
        series=series,
    )


# ══════════════════════════════════════════════════════════════════════════════
# /data/*
# ══════════════════════════════════════════════════════════════════════════════

@router.post("/data/accumulated", response_model=DatasheetCurveDataResponse, response_model_exclude_none=True,
             summary="Accumulated capacity curve — raw data points (datasheet)")
def get_accumulated_data(
    request: DatasheetBaseRequest,
    time_interval: str = Query(..., **_CURVE_QUERY),
    capacity_unit: Optional[str] = Query(None, **_UNIT_QUERY),
    capacity_request_factor: Optional[str] = Query(None, **_CRF_QUERY),
    max_budget: Optional[float] = _MAX_BUDGET_QUERY,
    exclude_plan_price: bool = _EXCLUDE_PLAN_QUERY,
    provider_mode: bool = _PROVIDER_MODE_QUERY,
):
    try:
        return _render_data(request, time_interval, capacity_unit, capacity_request_factor, "accumulated",
                            provider_mode, max_budget, exclude_plan_price)
    except (ValueError, KeyError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/data/inflection", response_model=DatasheetCurveDataResponse, response_model_exclude_none=True,
             summary="Inflection point capacity curve — raw data points (datasheet)")
def get_inflection_data(
    request: DatasheetBaseRequest,
    time_interval: str = Query(..., **_CURVE_QUERY),
    capacity_unit: Optional[str] = Query(None, **_UNIT_QUERY),
    capacity_request_factor: Optional[str] = Query(None, **_CRF_QUERY),
    max_budget: Optional[float] = _MAX_BUDGET_QUERY,
    exclude_plan_price: bool = _EXCLUDE_PLAN_QUERY,
    provider_mode: bool = _PROVIDER_MODE_QUERY,
):
    try:
        return _render_data(request, time_interval, capacity_unit, capacity_request_factor, "inflection",
                            provider_mode, max_budget, exclude_plan_price)
    except (ValueError, KeyError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ══════════════════════════════════════════════════════════════════════════════
# /chart/*
# ══════════════════════════════════════════════════════════════════════════════

@router.post(
    "/chart/accumulated",
    responses={200: {"content": {"text/html": {}}, "description": "Interactive Plotly chart (multi-curve)."}},
    summary="Accumulated capacity curve — interactive HTML chart (datasheet)",
)
def get_accumulated_chart(
    request: DatasheetBaseRequest,
    time_interval: str = Query(..., **_CURVE_QUERY),
    capacity_unit: Optional[str] = Query(None, **_UNIT_QUERY),
    capacity_request_factor: Optional[str] = Query(None, **_CRF_QUERY),
    max_budget: Optional[float] = _MAX_BUDGET_QUERY,
    exclude_plan_price: bool = _EXCLUDE_PLAN_QUERY,
    provider_mode: bool = _PROVIDER_MODE_QUERY,
):
    try:
        html = _render_chart(request, time_interval, capacity_unit, capacity_request_factor, "accumulated", "hv",
                             provider_mode, max_budget, exclude_plan_price)
        return Response(content=html, media_type="text/html")
    except (ValueError, KeyError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/chart/inflection",
    responses={200: {"content": {"text/html": {}}, "description": "Interactive Plotly chart (inflection, multi-curve)."}},
    summary="Inflection point capacity curve — interactive HTML chart (datasheet)",
)
def get_inflection_chart(
    request: DatasheetBaseRequest,
    time_interval: str = Query(..., **_CURVE_QUERY),
    capacity_unit: Optional[str] = Query(None, **_UNIT_QUERY),
    capacity_request_factor: Optional[str] = Query(None, **_CRF_QUERY),
    max_budget: Optional[float] = _MAX_BUDGET_QUERY,
    exclude_plan_price: bool = _EXCLUDE_PLAN_QUERY,
    provider_mode: bool = _PROVIDER_MODE_QUERY,
):
    try:
        html = _render_chart(request, time_interval, capacity_unit, capacity_request_factor, "inflection", "linear",
                             provider_mode, max_budget, exclude_plan_price)
        return Response(content=html, media_type="text/html")
    except (ValueError, KeyError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
