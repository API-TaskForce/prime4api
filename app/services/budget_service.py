from typing import List, Optional, Tuple

from app.engine.evaluators.bounded_rate import BoundedRate
from app.engine.time_models import TimeDuration, TimeUnit
from app.models import Rate, Quota
from app.utils.time_utils import format_time_with_unit


class BudgetService:

    # ── Primitive helpers ─────────────────────────────────────────────────────

    def overage_rate_per_unit(self, quota: Quota) -> Optional[float]:
        """Cost per single unit of overage, or None if the quota has no overage."""
        if not quota.overage_cost:
            return None
        return quota.overage_cost.price / quota.overage_cost.value

    def cost_at(self, quota: Quota, demand: float) -> float:
        """Overage cost to consume `demand` units against a single quota."""
        rate = self.overage_rate_per_unit(quota)
        if rate is None:
            return 0.0
        return max(0.0, demand - quota.value) * rate

    def total_overage_cost(self, quotas: List[Quota], demand: float) -> float:
        """Total overage cost across all elastic quotas for the given demand."""
        return sum(self.cost_at(q, demand) for q in quotas)

    def cost_curve_points(
        self, quotas: List[Quota], plan_price: float, x_max: float
    ) -> Tuple[List[float], List[float]]:
        """
        Piecewise-linear cost curve from 0 to x_max.
        Breakpoints at 0, every quota.value (kink where overage starts), and x_max.
        Returns (xs, ys).
        """
        elastic = [
            (q.value, self.overage_rate_per_unit(q))
            for q in quotas
            if q.overage_cost
        ]
        xs = sorted({0.0, x_max} | {qv for qv, _ in elastic if 0 < qv < x_max})

        def _total(x: float) -> float:
            return plan_price + sum(max(0.0, x - qv) * rate for qv, rate in elastic)

        return xs, [_total(x) for x in xs]

    def expand_quota(self, quota: Quota, remaining_budget: float) -> Quota:
        """Quota with value expanded as far as the full remaining_budget allows."""
        rate = self.overage_rate_per_unit(quota)
        if rate is None or rate <= 0:
            return quota
        extra_units = remaining_budget / rate
        return Quota(
            value=quota.value + extra_units,
            unit=quota.unit,
            period=quota.period,
            overage_cost=quota.overage_cost,
        )

    def expand_quotas(
        self,
        quotas: List[Quota],
        plan_price: float,
        max_budget: float,
        exclude_plan_price: bool = False,
    ) -> Tuple[List[Quota], float, bool]:
        """
        Expands every elastic quota using the full remaining budget.
        Returns (expanded_quotas, remaining_budget, affordable).
        affordable=False means the plan price alone exceeds max_budget.
        """
        remaining = max_budget if exclude_plan_price else max_budget - plan_price
        if remaining < -1e-9:
            return quotas, 0.0, False
        remaining = max(0.0, remaining)
        expanded = [
            self.expand_quota(q, remaining) if q.overage_cost else q
            for q in quotas
        ]
        return expanded, remaining, True

    # ── BoundedRate helpers ───────────────────────────────────────────────────

    def _min_time(
        self,
        rates: List[Rate],
        quotas: List[Quota],
        capacity: float,
        provider_mode: bool,
    ) -> Tuple[Optional[float], Optional[str]]:
        """Returns (ms, display_str) or (None, None) on error."""
        try:
            br = BoundedRate(rate=rates or None, quota=quotas or None, provider_mode=provider_mode)
            result = br.min_time(capacity, display=False)
            if isinstance(result, str):  # "0s"
                return 0.0, result
            ms = result.to_milliseconds()
            return ms, format_time_with_unit(result)
        except Exception:
            return None, None

    def _reachable_in_period(
        self,
        rates: List[Rate],
        quotas: List[Quota],
        desired_capacity: float,
        billing_period_ms: float,
        provider_mode: bool,
    ) -> Tuple[bool, Optional[str]]:
        """
        Returns (reachable, reason).
        reason is None when reachable, 'budget_limit' or 'rate_limit' otherwise.
        """
        try:
            br = BoundedRate(rate=rates or None, quota=quotas or None, provider_mode=provider_mode)
            cap = float(br.capacity_at(TimeDuration(billing_period_ms, TimeUnit.MILLISECOND)))
            if cap >= desired_capacity - 1e-9:
                return True, None
        except Exception:
            return False, "rate_limit"

        # Not reachable — distinguish by trying with a quota large enough to never bind
        try:
            unlimited = [
                Quota(value=desired_capacity * 1_000, unit=q.unit, period=q.period)
                if q.overage_cost else q
                for q in quotas
            ]
            br2 = BoundedRate(rate=rates or None, quota=unlimited or None, provider_mode=provider_mode)
            cap2 = float(br2.capacity_at(TimeDuration(billing_period_ms, TimeUnit.MILLISECOND)))
            reason = "budget_limit" if cap2 >= desired_capacity - 1e-9 else "rate_limit"
        except Exception:
            reason = "rate_limit"

        return False, reason

    # ── Recommendation ────────────────────────────────────────────────────────

    def compute_recommendation(
        self,
        plan_name: str,
        endpoint: str,
        alias: Optional[str],
        dimension: str,
        plan_price: float,
        billing_period_ms: float,
        currency: str,
        quotas: List[Quota],
        rates: List[Rate],
        desired_capacity: float,
        max_budget: Optional[float],
        exclude_plan_price: bool,
        provider_mode: bool,
        no_overage: bool = False,
    ) -> dict:
        overage = self.total_overage_cost(quotas, desired_capacity)
        total_cost = plan_price + overage

        if no_overage and overage > 1e-9:
            return {
                "plan": plan_name, "endpoint": endpoint, "alias": alias, "dimension": dimension,
                "base_cost": round(plan_price, 4), "overage_cost": round(overage, 4),
                "total_cost": round(total_cost, 4), "currency": currency,
                "affordable": False, "budget_surplus": None,
                "unreachable": True, "unreachable_reason": "overage_required",
                "time_to_capacity_ms": None, "time_to_capacity": None,
            }

        if max_budget is not None:
            affordable = total_cost <= max_budget + 1e-9
            if not affordable:
                # Can't reach desired_capacity within this budget — no point computing time.
                # Covers both plan_price > max_budget and overage pushing total over budget.
                return {
                    "plan": plan_name, "endpoint": endpoint, "alias": alias, "dimension": dimension,
                    "base_cost": round(plan_price, 4), "overage_cost": round(overage, 4),
                    "total_cost": round(total_cost, 4), "currency": currency,
                    "affordable": False, "budget_surplus": None,
                    "unreachable": True, "unreachable_reason": "budget_limit",
                    "time_to_capacity_ms": None, "time_to_capacity": None,
                }
            # affordable=True → plan_price ≤ total_cost ≤ max_budget → remaining ≥ 0
            expanded_quotas, _, _ = self.expand_quotas(
                quotas, plan_price, max_budget, exclude_plan_price
            )
        else:
            affordable = True
            if no_overage:
                expanded_quotas = quotas  # quota already covers desired_capacity (overage == 0)
            else:
                # Expand each elastic quota just enough to cover desired_capacity.
                # cost_at(q, desired_capacity) is exactly the overage budget needed per quota.
                expanded_quotas = [
                    self.expand_quota(q, self.cost_at(q, desired_capacity)) if q.overage_cost else q
                    for q in quotas
                ]

        budget_surplus = round(max_budget - total_cost, 4) if max_budget is not None else None

        reachable, reason = self._reachable_in_period(
            rates, expanded_quotas, desired_capacity, billing_period_ms, provider_mode
        )

        if not reachable:
            return {
                "plan": plan_name, "endpoint": endpoint, "alias": alias, "dimension": dimension,
                "base_cost": round(plan_price, 4), "overage_cost": round(overage, 4),
                "total_cost": round(total_cost, 4), "currency": currency,
                "affordable": affordable, "budget_surplus": budget_surplus,
                "unreachable": True, "unreachable_reason": reason,
                "time_to_capacity_ms": None, "time_to_capacity": None,
            }

        t_ms, t_display = self._min_time(rates, expanded_quotas, desired_capacity, provider_mode)
        return {
            "plan": plan_name, "endpoint": endpoint, "alias": alias, "dimension": dimension,
            "base_cost": round(plan_price, 4), "overage_cost": round(overage, 4),
            "total_cost": round(total_cost, 4), "currency": currency,
            "affordable": affordable, "budget_surplus": budget_surplus,
            "unreachable": False, "unreachable_reason": None,
            "time_to_capacity_ms": round(t_ms) if t_ms is not None else None,
            "time_to_capacity": t_display,
        }
