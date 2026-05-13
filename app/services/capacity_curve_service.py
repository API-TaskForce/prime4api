from typing import List, Optional, Union

from app.engine.evaluators import BoundedRate
from app.engine.plotters import (
    BoundedRatePlotter,
    CapacityCurvePoints,
    QuotaPlotter,
    RatePlotter,
)
from app.models import Quota, Rate
from app.utils.plotly_renderer import render_capacity_curve_html
from app.utils.time_utils import parse_time_string_to_duration, select_best_time_unit

class CapacityCurveService:

    # ── GETTERS DE PUNTOS (para endpoints /data/*) ────────────────────────────
    def get_accumulated_capacity_curve(
        self,
        time_interval: str,
        rate: Optional[Union[Rate, List[Rate]]] = None,
        quota: Optional[Union[Quota, List[Quota]]] = None,
        provider_mode: bool = False,
    ) -> CapacityCurvePoints:
        try:
            plotter = self._dispatch_plotter(rate, quota, provider_mode)
            return plotter.accumulated_capacity_curve(time_interval).downsample()
        except ValueError as e:
            raise ValueError(f"Error calculating accumulated capacity curve: {e}")

    def get_inflection_point_capacity_curve(
        self,
        time_interval: str,
        rate: Optional[Union[Rate, List[Rate]]] = None,
        quota: Optional[Union[Quota, List[Quota]]] = None,
        provider_mode: bool = False,
    ) -> CapacityCurvePoints:
        try:
            br = self._build_bounded_rate(rate, quota, provider_mode)
            plotter = BoundedRatePlotter(br)
            return plotter.inflection_point_capacity_curve(time_interval)
        except ValueError as e:
            raise ValueError(f"Error calculating inflection point capacity curve: {e}")

    # ── RENDERERS HTML (para endpoints /chart/*) ──────────────────────────────

    def render_accumulated_curve_html(
        self,
        time_interval: str,
        rate: Optional[Union[Rate, List[Rate]]] = None,
        quota: Optional[Union[Quota, List[Quota]]] = None,
        provider_mode: bool = False,
    ) -> str:
        try:
            points = self.get_accumulated_capacity_curve(time_interval, rate, quota, provider_mode)
            unit_label, divisor = self._time_axis_params(time_interval)
            return render_capacity_curve_html(
                points = points,
                title = f"Accumulated Capacity Curve - {time_interval}",
                line_shape = "hv",
                x_unit_label = unit_label,
                x_scale_divisor=divisor
            )
        except ValueError as e:
            raise ValueError(f"Error rendering accumulated capacity curve: {e}")

    def render_inflection_point_curve_html(
        self,
        time_interval: str,
        rate: Optional[Union[Rate, List[Rate]]] = None,
        quota: Optional[Union[Quota, List[Quota]]] = None,
        provider_mode: bool = False,
    ) -> str:
        try:
            points = self.get_inflection_point_capacity_curve(time_interval, rate, quota, provider_mode)
            unit_label, divisor = self._time_axis_params(time_interval)
            return render_capacity_curve_html(
                points = points,
                title = f"Capacity Curve - {time_interval}",
                line_shape = "linear",
                x_unit_label = unit_label,
                x_scale_divisor=divisor
            )
        except ValueError as e:
            raise ValueError(f"Error rendering inflection point capacity curve: {e}")

    def _build_bounded_rate(
        self,
        rate: Optional[Union[Rate, List[Rate]]],
        quota: Optional[Union[Quota, List[Quota]]],
        provider_mode: bool = False,
    ) -> BoundedRate:
        try:
            return BoundedRate(rate, quota, provider_mode=provider_mode)
        except ValueError as e:
            raise ValueError(f"Error creating BoundedRate: {e}")

    def _time_axis_params(self, time_interval: str):
        td = parse_time_string_to_duration(time_interval)
        t_ms = td.to_milliseconds()
        best = select_best_time_unit(t_ms)
        divisor = best.unit.to_milliseconds()
        unit_label = best.unit.value
        return unit_label, divisor
    
    def _dispatch_plotter(
        self,
        rate: Optional[Union[Rate, List[Rate]]],
        quota: Optional[Union[Quota, List[Quota]]],
        provider_mode: bool = False,
    ):
        rates = [rate] if isinstance(rate, Rate) else (rate or [])
        quotas = [quota] if isinstance(quota, Quota) else (quota or [])

        if not provider_mode:
            if len(rates) == 1 and len(quotas) == 0:
                return RatePlotter(rates[0])
            if len(quotas) == 1 and len(rates) == 0:
                return QuotaPlotter(quotas[0])

        br = self._build_bounded_rate(rate, quota, provider_mode)
        return BoundedRatePlotter(br)