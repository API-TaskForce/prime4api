from concurrent.futures import ThreadPoolExecutor
from typing import List, Tuple, Union

from app.engine import TimeDuration, TimeUnit
from app.engine.evaluators import BoundedRate
from app.engine.plotters.curve_models import CapacityCurvePoints
from app.utils.time_utils import parse_time_string_to_duration

class BoundedRatePlotter:

    def __init__(self, br: BoundedRate):
        self.br = br


    def accumulated_capacity_curve(self, time_interval: Union[str, TimeDuration]) -> CapacityCurvePoints:

        if isinstance(time_interval, str):
            time_interval = parse_time_string_to_duration(time_interval)
        
        t_max_ms = int(time_interval.to_milliseconds())
        step = int(self.br.limits[0].period.to_milliseconds())

        t_values = list(range(0, t_max_ms + 1, step))

        if not t_values or t_values[-1] != t_max_ms:
            t_values.append(t_max_ms)
        
        if len(t_values) == 1 and t_max_ms > 0:
            t_values.append(t_max_ms)
        
        def _eval(t: int) -> float:
            return float(self.br.capacity_at(TimeDuration(t, TimeUnit.MILLISECOND)))

        with ThreadPoolExecutor() as executor:
            capacity_values = list(executor.map(_eval, t_values))
        
        return CapacityCurvePoints(t_ms=[float(t) for t in t_values], capacity=capacity_values)

    
    def inflection_point_capacity_curve(self, time_interval: Union[str, TimeDuration]) -> CapacityCurvePoints:
    
        if isinstance(time_interval, str):
            time_interval = parse_time_string_to_duration(time_interval)
        
        sim_ms = int(time_interval.to_milliseconds())

        def _capacity(t_ms: int) -> float:
            return float(self.br.capacity_at(TimeDuration(t_ms, TimeUnit.MILLISECOND)))

        quotas = self.br.limits[1:]
        if not quotas:
            return CapacityCurvePoints(
                t_ms=[0.0, float(sim_ms)],
                capacity=[_capacity(0), _capacity(sim_ms)]
            )
        
        thresholds_raw = self.br.quota_exhaustion_threshold(display=False)

        thresholds_ms_list: List[int] = []
        for _limit, td in thresholds_raw:
            if isinstance(td, str):
                thresholds_ms_list.append(0)
            else:
                thresholds_ms_list.append(int(td.to_milliseconds()))

        points: List[Tuple[float, float]] = []

        base_period_ms = int(self.br.limits[0].period.to_milliseconds())

        for idx, quota in enumerate(quotas):
            period_ms = int(quota.period.to_milliseconds())
            t_ast_ms = thresholds_ms_list[idx]
            k = 0
            while True:
                window_start_ms = k * period_ms
                if window_start_ms >= sim_ms:
                    break

                # Punto inicio de ventana
                points.append((float(window_start_ms), _capacity(window_start_ms)))

                # Último batch completo del rate antes de que la cuota recorte.
                # La rampa sólo es una recta desde el inicio de ventana hasta el
                # exhaustion si la cuota es múltiplo exacto de la capacidad del
                # rate; si no, el último batch se recorta y ahí hay un codo real.
                if base_period_ms > 0 and t_ast_ms > base_period_ms:
                    last_full_ms = window_start_ms + t_ast_ms - base_period_ms
                    if last_full_ms < sim_ms:
                        points.append((float(last_full_ms), _capacity(last_full_ms)))

                # Punto de exhaustion (clamped a sim_ms)
                exhaustion_ms = min(window_start_ms + t_ast_ms, sim_ms)
                points.append((float(exhaustion_ms), _capacity(exhaustion_ms)))

                # Punto fin de ventana / plateau (mismo cap que exhaustion)
                window_end_ms = min((k + 1) * period_ms, sim_ms)
                points.append((float(window_end_ms), _capacity(exhaustion_ms)))

                if window_end_ms >= sim_ms:
                    break
                k += 1
        
        if not any(t == 0.0 for t, _ in points):
            points.append((0.0, _capacity(0)))
        
        final_cap = _capacity(sim_ms)
        if not any(t == float(sim_ms) for t, _ in points):
            points.append((float(sim_ms), final_cap))
        
        points.append((float(sim_ms), final_cap))

        seen = {}
        for t, c in points:
            if t not in seen:
                seen[t] = c
        time_sorted = sorted(seen.items(), key=lambda x: x[0])

        def _prune_collinear(pts: List[Tuple[float, float]]) -> List[Tuple[float, float]]:
            """Descarta los puntos que no cambian la pendiente (incluye mesetas)."""
            if len(pts) <= 2:
                return list(pts)
            pruned = [pts[0]]
            for curr, nxt in zip(pts[1:], pts[2:]):
                prev = pruned[-1]
                # Área del triángulo prev-curr-nxt: 0 ⇒ los tres alineados
                cross = (curr[0] - prev[0]) * (nxt[1] - prev[1]) - (curr[1] - prev[1]) * (nxt[0] - prev[0])
                if abs(cross) < 1e-6:
                    continue
                pruned.append(curr)
            pruned.append(pts[-1])
            return pruned

        pruned = _prune_collinear(time_sorted)

        return CapacityCurvePoints(
            t_ms=[t for t, _ in pruned],
            capacity=[c for _, c in pruned],
        )
        
        
        
        

        


