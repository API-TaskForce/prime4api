from collections import defaultdict
from typing import Dict, List, Optional
import json

from fastapi import APIRouter, HTTPException, Query, Response

from app.schemas.datasheet import EvaluateDatasheetRequest
from app.schemas.demand import (
    DatasheetDemandRequest,
    DatasheetDemandAnalyticsResponse,
    DemandEndpointResult,
    DemandVerdict,
)
from app.services.budget_service import BudgetService
from app.services.capacity_curve_service import CapacityCurveService
from app.services.datasheet_evaluator_service import DatasheetEvaluatorService
from app.services.demand_evaluator_service import DemandEvaluatorService
from app.utils.plotly_renderer import render_demand_evaluation_html
from app.utils.time_utils import parse_time_string_to_duration, select_best_time_unit
from app.utils.yaml_utils import load_yaml_source

router = APIRouter()
evaluator_service = DatasheetEvaluatorService()
demand_service = DemandEvaluatorService()
curve_service = CapacityCurveService()
budget_service = BudgetService()

_CURVE_QUERY    = dict(description="Comparison horizon (e.g. '1month', '1day')")
_UNIT_QUERY     = dict(description="Filter to a single dimension (e.g. 'emails', 'MBs'). Returns all if omitted.")
_CRF_QUERY      = dict(description="Plan CRF and default demand CRF. Plain number (e.g. '500') requires capacity_unit. JSON dict (e.g. '{\"emails\":500,\"MBs\":0.256}') sets multiple units at once.")
_PROVIDER_QUERY = Query(False, description="Provider-centric semantics: capacity counted at end of period window. Default: False.")
_MAX_BUDGET_QUERY  = Query(None, description="Optional budget. Elastic quotas are expanded after paying the plan price.")
_EXCLUDE_PLAN_QUERY = Query(False, description="If True, treat max_budget as pure overage budget (plan price already covered).")


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


def _build_nav_request(req: DatasheetDemandRequest) -> EvaluateDatasheetRequest:
    return EvaluateDatasheetRequest(
        datasheet_source=req.datasheet_source,
        plan_names=req.plan_names,
        endpoint_path=req.endpoint_path,
        alias=req.alias,
        operation="__nav__",
        operation_params={},
    )


def _time_axis_params(time_interval: str):
    td = parse_time_string_to_duration(time_interval)
    best = select_best_time_unit(td.to_milliseconds())
    return best.unit.value, best.unit.to_milliseconds()


def _plan_label(sc: dict) -> str:
    alias = f" [{sc['alias']}]" if sc.get("alias") else ""
    crf = f" CRF={sc['crf']}" if sc.get("crf") is not None else ""
    return f"{sc['plan']} / {sc['endpoint']}{alias} — {sc['dimension']}{crf}"


def _get_scenarios(req: DatasheetDemandRequest, yaml_data: dict,
                   capacity_unit: Optional[str], crf: Optional[dict],
                   max_budget: Optional[float] = None, exclude_plan_price: bool = False) -> list:
    scenarios = evaluator_service.get_curve_scenarios(
        yaml_data,
        _build_nav_request(req),
        capacity_unit=capacity_unit,
        capacity_request_factor=crf,
    )
    scenarios = [sc for sc in scenarios if not (sc["dimension"] == "requests" and sc.get("workload_unit"))]
    if max_budget is not None:
        expanded = []
        for sc in scenarios:
            pricing = evaluator_service.get_plan_pricing(yaml_data, sc["plan"])
            new_quotas, _, _ = budget_service.expand_quotas(
                sc["quotas"], pricing["price"], max_budget, exclude_plan_price
            )
            expanded.append({**sc, "quotas": new_quotas})
        return expanded
    return scenarios


# ── Analytics ─────────────────────────────────────────────────────────────────

@router.post(
    "",
    response_model=DatasheetDemandAnalyticsResponse,
    response_model_exclude_none=True,
    summary="Demand evaluation — analytical verdict (YES / NO / DEPENDS) per plan endpoint × demand",
)
def demand_evaluation_analytics(
    request: DatasheetDemandRequest,
    time_interval: str = Query(..., **_CURVE_QUERY),
    capacity_unit: Optional[str] = Query(None, **_UNIT_QUERY),
    capacity_request_factor: Optional[str] = Query(None, **_CRF_QUERY),
    max_budget: Optional[float] = _MAX_BUDGET_QUERY,
    exclude_plan_price: bool = _EXCLUDE_PLAN_QUERY,
    provider_mode: bool = _PROVIDER_QUERY,
):
    try:
        crf = _parse_crf(capacity_unit, capacity_request_factor)
        yaml_data = load_yaml_source(request.datasheet_source)
        scenarios = _get_scenarios(request, yaml_data, capacity_unit, crf, max_budget, exclude_plan_price)

        key_map: Dict[tuple, DemandEndpointResult] = {}
        for sc in scenarios:
            key = (sc["plan"], sc["endpoint"], sc.get("alias"), sc["dimension"])
            verdicts = demand_service.evaluate_all(
                plan_rates=sc["rates"],
                plan_quotas=sc["quotas"],
                demands=request.demands,
                target_dim=sc["dimension"],
                capacity_request_factor=crf,
                time_interval=time_interval,
                provider_mode=provider_mode,
            )
            if key not in key_map:
                key_map[key] = DemandEndpointResult(
                    plan=sc["plan"],
                    endpoint=sc["endpoint"],
                    alias=sc.get("alias"),
                    dimension=sc["dimension"],
                    verdicts=verdicts,
                )
            else:
                from app.services.demand_evaluator_service import _worst_verdict
                for label, v in verdicts.items():
                    key_map[key].verdicts[label] = _worst_verdict(key_map[key].verdicts.get(label, v), v)

        return DatasheetDemandAnalyticsResponse(
            time_interval=time_interval,
            results=list(key_map.values()),
        )

    except (ValueError, KeyError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Chart ─────────────────────────────────────────────────────────────────────

@router.post(
    "/chart",
    responses={200: {"content": {"text/html": {}}, "description": "Demand evaluation chart (plan curves vs demand curves)."}},
    summary="Demand evaluation — interactive HTML chart (plan capacity vs demand curves)",
)
def demand_evaluation_chart(
    request: DatasheetDemandRequest,
    time_interval: str = Query(..., **_CURVE_QUERY),
    capacity_unit: Optional[str] = Query(None, **_UNIT_QUERY),
    capacity_request_factor: Optional[str] = Query(None, **_CRF_QUERY),
    max_budget: Optional[float] = _MAX_BUDGET_QUERY,
    exclude_plan_price: bool = _EXCLUDE_PLAN_QUERY,
    provider_mode: bool = _PROVIDER_QUERY,
):
    try:
        crf = _parse_crf(capacity_unit, capacity_request_factor)
        yaml_data = load_yaml_source(request.datasheet_source)
        scenarios = _get_scenarios(request, yaml_data, capacity_unit, crf, max_budget, exclude_plan_price)

        if not scenarios:
            raise ValueError("No plan scenarios found for the given filters.")

        x_unit_label, x_scale_divisor = _time_axis_params(time_interval)

        # Group scenarios by (plan, ep_key, dim) to build per-plan verdicts and navigation
        scene_groups: Dict[tuple, list] = defaultdict(list)
        for sc in scenarios:
            alias = f" [{sc['alias']}]" if sc.get("alias") else ""
            ep_key = f"{sc['endpoint']}{alias}"
            scene_groups[(sc["plan"], ep_key, sc["dimension"])].append(sc)

        # Cache demand curve points per (dim, label) — same points regardless of plan
        demand_pts_cache: dict = {}

        # chart_data: plan → ep_key → dim → {"plan_curves": [...], "demand_curves": [...]}
        chart_data: Dict[str, dict] = {}

        for (plan, ep_key, dim), sc_list in scene_groups.items():
            plan_curves = []
            for sc in sc_list:
                try:
                    pts = curve_service.get_inflection_point_capacity_curve(
                        time_interval, sc["rates"], sc["quotas"], provider_mode=provider_mode,
                    )
                    crf_label = f"CRF={sc['crf']}" if sc.get("crf") is not None else None
                    plan_curves.append({"label": crf_label, "t_ms": pts.t_ms, "capacity": pts.capacity})
                except Exception as e:
                    print(f"[WARNING] Skipping plan curve {plan}/{ep_key}/{dim}: {e}")

            if not plan_curves:
                continue

            verdicts_per_scenario = [
                demand_service.evaluate_all(
                    plan_rates=sc["rates"],
                    plan_quotas=sc["quotas"],
                    demands=request.demands,
                    target_dim=dim,
                    capacity_request_factor=crf,
                    time_interval=time_interval,
                    provider_mode=provider_mode,
                )
                for sc in sc_list
            ]
            worst = demand_service.worst_verdict_across_plans(verdicts_per_scenario)

            demand_curves = []
            for demand in request.demands:
                cache_key = (dim, demand.label)
                if cache_key not in demand_pts_cache:
                    demand_pts_cache[cache_key] = demand_service.get_demand_curve_points(
                        demand=demand,
                        target_dim=dim,
                        capacity_request_factor=crf,
                        time_interval=time_interval,
                        provider_mode=provider_mode,
                    )
                pts_d = demand_pts_cache[cache_key]
                if pts_d is None:
                    continue
                v = worst.get(demand.label, DemandVerdict(verdict="DEPENDS"))
                demand_curves.append({
                    "label": demand.label,
                    "verdict": v.verdict,
                    "reason": v.reason,
                    "t_ms": pts_d.t_ms,
                    "capacity": pts_d.capacity,
                })

            chart_data.setdefault(plan, {}).setdefault(ep_key, {})[dim] = {
                "plan_curves": plan_curves,
                "demand_curves": demand_curves,
            }

        if not chart_data:
            raise ValueError("No valid plan curves could be generated.")

        html = render_demand_evaluation_html(
            chart_data=chart_data,
            title=f"Demand Evaluation — {time_interval}",
            x_unit_label=x_unit_label,
            x_scale_divisor=x_scale_divisor,
        )
        return Response(content=html, media_type="text/html")

    except (ValueError, KeyError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
