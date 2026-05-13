from collections import defaultdict
from typing import Dict, Optional
import json

from fastapi import APIRouter, HTTPException, Query, Response

from app.engine.evaluators.bounded_rate import BoundedRate
from app.engine.plotters.bounded_rate_plotter import BoundedRatePlotter
from app.engine.time_models import TimeDuration, TimeUnit
from app.schemas.budget import BudgetRecommendationRequest, PlanRecommendation, BudgetRecommendationResponse
from app.schemas.datasheet import EvaluateDatasheetRequest
from app.services.budget_service import BudgetService
from app.services.datasheet_evaluator_service import DatasheetEvaluatorService
from app.utils.plotly_renderer import render_budget_recommendation_html
from app.utils.time_utils import parse_time_string_to_duration
from app.utils.yaml_utils import load_yaml_source

router = APIRouter()
evaluator_service = DatasheetEvaluatorService()
budget_service = BudgetService()

_CAPACITY_QUERY     = Query(...,  description="Desired capacity to reach within one billing period (e.g. 200000).")
_UNIT_QUERY         = Query(...,  description="Capacity unit (e.g. 'requests', 'emails').")
_MAX_BUDGET_QUERY   = Query(None, description="Maximum total budget. Plans whose total_cost exceeds this are marked affordable=False.")
_EXCLUDE_PLAN_QUERY = Query(False, description="If True, treat max_budget as pure overage budget (plan price already covered).")
_CRF_QUERY          = Query(None, description="Capacity Request Factor. Plain number or JSON dict (e.g. '{\"emails\":500}').")
_PROVIDER_QUERY     = Query(False, description="Provider-centric semantics. Default: False.")
_NO_OVERAGE_QUERY   = Query(False, description="If True, only consider plans whose included quota already covers desired_capacity (no overage charges). Plans requiring overage are marked unreachable with reason 'overage_required'.")
_TIME_HORIZON_QUERY = Query(None, description="Override the time axis of the capacity-vs-time chart (e.g. '2h', '1day'). If omitted, auto-zooms to the slowest reachable plan × 1.2, capped at the billing period.")


def _build_nav_request(req: BudgetRecommendationRequest) -> EvaluateDatasheetRequest:
    return EvaluateDatasheetRequest(
        datasheet_source=req.datasheet_source,
        plan_names=req.plan_names,
        endpoint_path=req.endpoint_path,
        alias=req.alias,
        operation="__nav__",
        operation_params={},
    )


def _parse_crf(capacity_unit: Optional[str], crf_str: Optional[str]) -> Optional[dict]:
    if not crf_str:
        return None
    try:
        parsed = json.loads(crf_str)
        if isinstance(parsed, dict):
            return {k: float(v) for k, v in parsed.items()}
        if isinstance(parsed, (int, float)) and capacity_unit:
            return {capacity_unit: float(parsed)}
        return None
    except (json.JSONDecodeError, ValueError):
        pass
    try:
        val = float(crf_str)
        if capacity_unit:
            return {capacity_unit: val}
    except ValueError:
        raise ValueError(f"capacity_request_factor must be a number or JSON dict, got: {crf_str!r}")
    return None


def _build_results(
    yaml_data: dict,
    req: BudgetRecommendationRequest,
    desired_capacity: float,
    capacity_unit: str,
    crf: Optional[dict],
    max_budget: Optional[float],
    exclude_plan_price: bool,
    provider_mode: bool,
    no_overage: bool = False,
) -> tuple:
    """Returns (results: list[dict], currency: str)."""
    scenarios = evaluator_service.get_curve_scenarios(
        yaml_data,
        _build_nav_request(req),
        capacity_unit=capacity_unit,
        capacity_request_factor=crf,
    )
    # drop request-only shadow rows
    scenarios = [sc for sc in scenarios if not (sc["dimension"] == "requests" and sc.get("workload_unit"))]

    currency = yaml_data.get("currency", "USD")

    # Group by (plan, ep_key, dim) — worst case across CRF variants
    from app.schemas.budget import PlanRecommendation as _PR  # noqa: F401
    groups: Dict[tuple, list] = defaultdict(list)
    for sc in scenarios:
        alias = f" [{sc['alias']}]" if sc.get("alias") else ""
        ep_key = f"{sc['endpoint']}{alias}"
        groups[(sc["plan"], ep_key, sc["dimension"], sc.get("alias"))].append(sc)

    results = []
    for (plan_name, ep_key, dim, alias), sc_list in groups.items():
        pricing = evaluator_service.get_plan_pricing(yaml_data, plan_name)
        plan_price = pricing["price"]
        billing_period_ms = pricing["period_ms"]

        # Aggregate: pick worst recommendation across CRF variants for this (plan, ep, dim)
        best = None
        for sc in sc_list:
            rec = budget_service.compute_recommendation(
                plan_name=plan_name,
                endpoint=sc["endpoint"],
                alias=sc.get("alias"),
                dimension=dim,
                plan_price=plan_price,
                billing_period_ms=billing_period_ms,
                currency=currency,
                quotas=sc["quotas"],
                rates=sc["rates"],
                desired_capacity=desired_capacity,
                max_budget=max_budget,
                exclude_plan_price=exclude_plan_price,
                provider_mode=provider_mode,
                no_overage=no_overage,
            )
            if best is None:
                best = rec
            else:
                # Worst: unreachable > not affordable > highest cost
                if rec["unreachable"] and not best["unreachable"]:
                    best = rec
                elif not rec["unreachable"] and not best["unreachable"]:
                    if rec["total_cost"] > best["total_cost"]:
                        best = rec
        if best:
            results.append(best)

    results.sort(key=lambda r: (r["unreachable"], not r["affordable"], r["total_cost"]))
    return results, currency


# ── Analytics ─────────────────────────────────────────────────────────────────

@router.post(
    "/recommendation",
    response_model=BudgetRecommendationResponse,
    response_model_exclude_none=True,
    summary="Budget recommendation — best plan(s) for a desired capacity",
)
def budget_recommendation(
    request: BudgetRecommendationRequest,
    desired_capacity: float = _CAPACITY_QUERY,
    capacity_unit: str = _UNIT_QUERY,
    max_budget: Optional[float] = _MAX_BUDGET_QUERY,
    exclude_plan_price: bool = _EXCLUDE_PLAN_QUERY,
    capacity_request_factor: Optional[str] = _CRF_QUERY,
    provider_mode: bool = _PROVIDER_QUERY,
    no_overage: bool = _NO_OVERAGE_QUERY,
):
    try:
        crf = _parse_crf(capacity_unit, capacity_request_factor)
        yaml_data = load_yaml_source(request.datasheet_source)
        results, currency = _build_results(
            yaml_data, request, desired_capacity, capacity_unit,
            crf, max_budget, exclude_plan_price, provider_mode, no_overage,
        )
        return BudgetRecommendationResponse(
            desired_capacity=desired_capacity,
            capacity_unit=capacity_unit,
            max_budget=max_budget,
            exclude_plan_price=exclude_plan_price,
            currency=currency,
            results=[PlanRecommendation(**r) for r in results],
        )
    except (ValueError, KeyError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def _build_cost_curves(
    yaml_data: dict,
    req: BudgetRecommendationRequest,
    desired_capacity: float,
    capacity_unit: str,
    crf: Optional[dict],
) -> list:
    """
    Returns list of curve dicts:
      { label, plan, xs, ys, quota_limit }
    One entry per (plan, ep_key, dim) group — uses the first CRF scenario's quotas.
    x_max = desired_capacity * 1.5 so the chart shows a bit beyond the target.
    """
    scenarios = evaluator_service.get_curve_scenarios(
        yaml_data,
        _build_nav_request(req),
        capacity_unit=capacity_unit,
        capacity_request_factor=crf,
    )
    scenarios = [sc for sc in scenarios if not (sc["dimension"] == "requests" and sc.get("workload_unit"))]

    x_max = desired_capacity * 1.5
    seen: set = set()
    curves = []
    for sc in scenarios:
        alias = f" [{sc['alias']}]" if sc.get("alias") else ""
        key = (sc["plan"], sc["endpoint"] + alias, sc["dimension"])
        if key in seen:
            continue
        seen.add(key)
        pricing = evaluator_service.get_plan_pricing(yaml_data, sc["plan"])
        xs, ys = budget_service.cost_curve_points(sc["quotas"], pricing["price"], x_max)
        # quota_limit: the smallest elastic quota value (the first kink)
        elastic_vals = sorted(q.value for q in sc["quotas"] if q.overage_cost)
        curves.append({
            "label": f"{sc['plan']}{alias}",
            "plan": sc["plan"],
            "xs": xs,
            "ys": ys,
            "quota_limit": elastic_vals[0] if elastic_vals else None,
        })
    return curves


def _build_cap_time_curves(
    yaml_data: dict,
    req: BudgetRecommendationRequest,
    desired_capacity: float,
    capacity_unit: str,
    crf: Optional[dict],
    max_budget: Optional[float],
    exclude_plan_price: bool,
    provider_mode: bool,
    horizon_ms: Optional[float] = None,
) -> list:
    """
    Returns list of capacity-vs-time curve dicts:
      { label, plan, t_ms, capacity, billing_period_ms }
    Quotas are expanded the same way as compute_recommendation so the curves
    reflect what's actually achievable within the budget (or to desired_capacity).
    """
    scenarios = evaluator_service.get_curve_scenarios(
        yaml_data,
        _build_nav_request(req),
        capacity_unit=capacity_unit,
        capacity_request_factor=crf,
    )
    scenarios = [sc for sc in scenarios if not (sc["dimension"] == "requests" and sc.get("workload_unit"))]

    seen: set = set()
    curves = []
    for sc in scenarios:
        alias = f" [{sc['alias']}]" if sc.get("alias") else ""
        key = (sc["plan"], sc["endpoint"] + alias, sc["dimension"])
        if key in seen:
            continue
        seen.add(key)

        pricing = evaluator_service.get_plan_pricing(yaml_data, sc["plan"])
        billing_period_ms = pricing["period_ms"]
        plan_price = pricing["price"]

        if max_budget is not None:
            quotas, _, budget_ok = budget_service.expand_quotas(
                sc["quotas"], plan_price, max_budget, exclude_plan_price
            )
            if not budget_ok:
                continue
        else:
            quotas = [
                budget_service.expand_quota(q, budget_service.cost_at(q, desired_capacity))
                if q.overage_cost else q
                for q in sc["quotas"]
            ]

        try:
            plot_ms = min(horizon_ms, billing_period_ms) if horizon_ms else billing_period_ms
            br = BoundedRate(rate=sc["rates"] or None, quota=quotas or None, provider_mode=provider_mode)
            plotter = BoundedRatePlotter(br)
            pts = plotter.inflection_point_capacity_curve(
                TimeDuration(plot_ms, TimeUnit.MILLISECOND)
            )
            curves.append({
                "label": f"{sc['plan']}{alias}",
                "plan": sc["plan"],
                "t_ms": pts.t_ms,
                "capacity": pts.capacity,
                "billing_period_ms": billing_period_ms,
            })
        except Exception as e:
            print(f"[WARNING] cap_time_curves skipping {sc['plan']}/{sc['endpoint']}: {e}")

    return curves


# ── Chart ─────────────────────────────────────────────────────────────────────

@router.post(
    "/recommendation/chart",
    responses={200: {"content": {"text/html": {}}, "description": "Cost vs capacity curves per plan."}},
    summary="Budget recommendation — interactive HTML cost-vs-capacity chart",
)
def budget_recommendation_chart(
    request: BudgetRecommendationRequest,
    desired_capacity: float = _CAPACITY_QUERY,
    capacity_unit: str = _UNIT_QUERY,
    max_budget: Optional[float] = _MAX_BUDGET_QUERY,
    exclude_plan_price: bool = _EXCLUDE_PLAN_QUERY,
    capacity_request_factor: Optional[str] = _CRF_QUERY,
    provider_mode: bool = _PROVIDER_QUERY,
    no_overage: bool = _NO_OVERAGE_QUERY,
    time_horizon: Optional[str] = _TIME_HORIZON_QUERY,
):
    try:
        crf = _parse_crf(capacity_unit, capacity_request_factor)
        yaml_data = load_yaml_source(request.datasheet_source)
        results, currency = _build_results(
            yaml_data, request, desired_capacity, capacity_unit,
            crf, max_budget, exclude_plan_price, provider_mode, no_overage,
        )
        if not results:
            raise ValueError("No results to render.")

        # Compute time horizon for capacity-vs-time chart
        if time_horizon:
            horizon_ms = parse_time_string_to_duration(time_horizon).to_milliseconds()
        else:
            reachable_times = [
                r["time_to_capacity_ms"] for r in results
                if not r["unreachable"] and r.get("time_to_capacity_ms")
            ]
            horizon_ms = max(reachable_times) * 1.2 if reachable_times else None

        cost_curves = _build_cost_curves(yaml_data, request, desired_capacity, capacity_unit, crf)
        cap_time_curves = _build_cap_time_curves(
            yaml_data, request, desired_capacity, capacity_unit,
            crf, max_budget, exclude_plan_price, provider_mode, horizon_ms,
        )
        html = render_budget_recommendation_html(
            results=results,
            cost_curves=cost_curves,
            cap_time_curves=cap_time_curves,
            desired_capacity=desired_capacity,
            capacity_unit=capacity_unit,
            currency=currency,
            max_budget=max_budget,
        )
        return Response(content=html, media_type="text/html")
    except (ValueError, KeyError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
