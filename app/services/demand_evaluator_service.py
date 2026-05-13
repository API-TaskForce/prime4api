from typing import Optional, Dict, List, Tuple

from app.engine.evaluators.bounded_rate import BoundedRate
from app.engine.plotters.bounded_rate_plotter import BoundedRatePlotter
from app.engine.plotters import CapacityCurvePoints
from app.engine.time_models import TimeDuration, TimeUnit
from app.models import Rate, Quota
from app.schemas.demand import DemandInput, DemandVerdict
from app.utils.time_utils import parse_time_string_to_duration


_VERDICT_PRIORITY = {"NO": 0, "DEPENDS": 1, "YES": 2}


def _worst_verdict(a: DemandVerdict, b: DemandVerdict) -> DemandVerdict:
    return a if _VERDICT_PRIORITY.get(a.verdict, 1) <= _VERDICT_PRIORITY.get(b.verdict, 2) else b


class DemandEvaluatorService:

    def _effective_crf(
        self,
        demand: DemandInput,
        capacity_request_factor: Optional[Dict[str, float]],
    ) -> Optional[Dict[str, float]]:
        return demand.demand_crf if demand.demand_crf else capacity_request_factor

    def _translate_to_dim(
        self,
        demand: DemandInput,
        target_dim: str,
        effective_crf: Optional[Dict[str, float]],
    ) -> Optional[Tuple[Optional[List[Rate]], Optional[List[Quota]]]]:
        """
        Translates demand rate and quotas into target_dim.

        Rules:
          - unit == target_dim          → use as-is
          - unit == "requests"          → multiply by effective_crf[target_dim] (or return None if missing)
          - unit is something else      → return None (orthogonal dimension — can't evaluate)
        Quotas in units other than target_dim and "requests" are silently ignored for this dimension.

        Returns (rates, quotas) or None when evaluation is impossible for this dimension.
        """
        factor = (effective_crf or {}).get(target_dim)
        rates: List[Rate] = []
        quotas: List[Quota] = []

        if demand.rate:
            dr = demand.rate
            if dr.unit == target_dim:
                rates.append(Rate(value=dr.value, unit=dr.unit, period=dr.period))
            elif dr.unit == "requests":
                if factor is None:
                    return None  # CRF required
                rates.append(Rate(value=dr.value * factor, unit=target_dim, period=dr.period))
            else:
                return None  # Orthogonal unit — not evaluable for this dimension

            # Implicit quota from duration
            if demand.duration:
                dur_ms = parse_time_string_to_duration(demand.duration).to_milliseconds()
                period_ms = parse_time_string_to_duration(dr.period).to_milliseconds()
                implicit_qty = dr.value * (dur_ms / period_ms)
                if dr.unit == target_dim:
                    quotas.append(Quota(value=implicit_qty, unit=target_dim, period=demand.duration))
                elif dr.unit == "requests":
                    quotas.append(Quota(value=implicit_qty * factor, unit=target_dim, period=demand.duration))

        if demand.quota:
            for dq in demand.quota:
                if dq.unit == target_dim:
                    quotas.append(Quota(value=dq.value, unit=dq.unit, period=dq.period))
                elif dq.unit == "requests":
                    if factor is None:
                        return None  # CRF required
                    quotas.append(Quota(value=dq.value * factor, unit=target_dim, period=dq.period))
                # quotas in other units are silently ignored for this dimension

        if not rates and not quotas:
            return None

        return (rates or None, quotas or None)

    def _critical_times(self, br: BoundedRate, td_ms: float) -> List[float]:
        """Returns the union of quota period boundaries and exhaustion times for br, clamped to td_ms."""
        times = {0.0, td_ms}
        for limit in br.limits[1:]:
            p_ms = limit.period.to_milliseconds()
            k = 1
            while k * p_ms <= td_ms:
                times.add(float(k * p_ms))
                k += 1
        thresholds = br.quota_exhaustion_threshold(display=False)
        for limit, td in thresholds:
            p_ms = limit.period.to_milliseconds()
            t_ast_ms = 0 if isinstance(td, str) else td.to_milliseconds()
            k = 0
            while k * p_ms < td_ms:
                t = k * p_ms + t_ast_ms
                if t <= td_ms:
                    times.add(float(t))
                k += 1
        return sorted(times)

    def evaluate(
        self,
        plan_rates: List[Rate],
        plan_quotas: List[Quota],
        demand: DemandInput,
        target_dim: str,
        capacity_request_factor: Optional[Dict[str, float]],
        time_interval: str,
        provider_mode: bool = False,
    ) -> DemandVerdict:
        """
        Returns a DemandVerdict for one (plan scenario, demand) pair.
        Both plan and demand are already in target_dim (plan via get_curve_scenarios CRF,
        demand via _translate_to_dim).
        Checks at the union of plan + demand inflection times for accuracy.
        """
        eff_crf = self._effective_crf(demand, capacity_request_factor)
        translated = self._translate_to_dim(demand, target_dim, eff_crf)

        if translated is None:
            if demand.rate and demand.rate.unit not in ("requests", target_dim):
                reason = "unit_mismatch"
                msg = f"Demand unit '{demand.rate.unit}' cannot be mapped to plan dimension '{target_dim}'."
            else:
                reason = "crf_required"
                msg = f"Provide demand_crf or capacity_request_factor with key '{target_dim}' to compare in this dimension."
            return DemandVerdict(verdict="DEPENDS", reason=reason, detail={"message": msg})

        d_rates, d_quotas = translated

        try:
            plan_br = BoundedRate(rate=plan_rates or None, quota=plan_quotas or None, provider_mode=provider_mode)
        except ValueError as e:
            raise ValueError(f"Invalid plan limits: {e}")

        try:
            demand_br = BoundedRate(rate=d_rates, quota=d_quotas, provider_mode=provider_mode)
        except ValueError as e:
            return DemandVerdict(verdict="DEPENDS", reason="invalid_demand", detail={"error": str(e)})

        td_ms = parse_time_string_to_duration(time_interval).to_milliseconds()
        plan_period_ms = plan_br.limits[0].period.to_milliseconds()

        # Sample at the union of plan + demand inflection times (critical points)
        check_times = set(self._critical_times(plan_br, td_ms))
        check_times.update(self._critical_times(demand_br, td_ms))
        # Fill gaps with uniform samples capped at 2000 total
        n_uniform = max(0, 2000 - len(check_times))
        if n_uniform > 0:
            step = td_ms / n_uniform
            check_times.update(i * step for i in range(n_uniform + 1))
        check_times = sorted(check_times)

        for t_ms in check_times:
            t_dur = TimeDuration(t_ms, TimeUnit.MILLISECOND)
            p_cap = plan_br.capacity_at(t_dur)
            d_cap = demand_br.capacity_at(t_dur)
            if d_cap > p_cap + 1e-9:
                p_first = plan_br.capacity_at(TimeDuration(plan_period_ms, TimeUnit.MILLISECOND))
                d_first = demand_br.capacity_at(TimeDuration(plan_period_ms, TimeUnit.MILLISECOND))
                reason = "rate_exceeded" if d_first > p_first + 1e-9 else "quota_exceeded"
                return DemandVerdict(
                    verdict="NO",
                    reason=reason,
                    detail={
                        "first_violation_at_ms": round(t_ms),
                        "plan_capacity": round(p_cap, 2),
                        "demand_capacity": round(d_cap, 2),
                    },
                )

        return DemandVerdict(verdict="YES")

    def evaluate_all(
        self,
        plan_rates: List[Rate],
        plan_quotas: List[Quota],
        demands: List[DemandInput],
        target_dim: str,
        capacity_request_factor: Optional[Dict[str, float]],
        time_interval: str,
        provider_mode: bool = False,
    ) -> Dict[str, DemandVerdict]:
        """Evaluates all demands against one plan scenario. Returns {label: verdict}."""
        return {
            d.label: self.evaluate(
                plan_rates, plan_quotas, d, target_dim,
                capacity_request_factor, time_interval, provider_mode,
            )
            for d in demands
        }

    def get_demand_curve_points(
        self,
        demand: DemandInput,
        target_dim: str,
        capacity_request_factor: Optional[Dict[str, float]],
        time_interval: str,
        provider_mode: bool = False,
    ) -> Optional[CapacityCurvePoints]:
        """Returns inflection-point capacity curve for the demand in target_dim, or None if not translatable."""
        eff_crf = self._effective_crf(demand, capacity_request_factor)
        translated = self._translate_to_dim(demand, target_dim, eff_crf)
        if translated is None:
            return None
        d_rates, d_quotas = translated
        try:
            demand_br = BoundedRate(rate=d_rates, quota=d_quotas, provider_mode=provider_mode)
            plotter = BoundedRatePlotter(demand_br)
            return plotter.inflection_point_capacity_curve(time_interval)
        except ValueError:
            return None

    def worst_verdict_across_plans(
        self,
        verdicts_by_plan: List[Dict[str, DemandVerdict]],
    ) -> Dict[str, DemandVerdict]:
        """
        Given verdicts from multiple plan scenarios (same dimension), returns the
        worst verdict per demand label. Used in chart rendering where a demand
        must fit ALL plan curves to be considered YES.
        """
        merged: Dict[str, DemandVerdict] = {}
        for vd in verdicts_by_plan:
            for label, v in vd.items():
                merged[label] = _worst_verdict(merged[label], v) if label in merged else v
        return merged
