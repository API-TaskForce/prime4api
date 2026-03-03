from typing import Optional
from app.utils import format_time_with_unit
from app.utils import parse_time_string_to_duration
from app.engine import TimeUnit
from app.engine import TimeDuration
from typing import Union, List
import numpy as np
from app.models import Rate, Quota


class BoundedRate:
    def __init__(
        self,
        rate: Union[Rate, List[Rate], None] = None,
        quota: Union[Quota, List[Quota], None] = None,
    ):
        rates = [rate] if isinstance(rate, Rate) else (rate or [])
        quotas = [quota] if isinstance(quota, Quota) else (quota or [])

        if not rates and not quotas:
            raise ValueError("At least one rate or quota must be provided")

        all_candidates = rates + quotas
        all_candidates.sort(key=lambda x: x.period.to_milliseconds())

        self.limits = [all_candidates[0]]

        for candidate in all_candidates[1:]:
            base = self.limits[0]
            if candidate.value <= base.value:
                print(f"[WARNING] Limit omitted (value <= base): {candidate}")
                continue

            base_capacity = base.value * (
                candidate.period.to_milliseconds() / base.period.to_milliseconds()
            )
            if candidate.value > base_capacity:
                print(f"[WARNING] Limit omitted (exceeds base capacity): {candidate}")
                continue

            temp_br = object.__new__(BoundedRate)
            temp_br.limits = self.limits.copy()

            capacity = temp_br.capacity_at(candidate.period)

            if capacity >= candidate.value:
                self.limits.append(candidate)
            else:
                print(f"[WARNING] Limit omitted as unreachable: {candidate}")

        self.rates = [l for l in self.limits if isinstance(l, Rate)]
        self.quotas = [l for l in self.limits if isinstance(l, Quota)]


    def capacity_at(self, time_simulation: TimeDuration):

        if isinstance(time_simulation, str):
            time_simulation = parse_time_string_to_duration(time_simulation)
        
        if time_simulation.unit != TimeUnit.MILLISECOND:
            t_milliseconds = time_simulation.to_milliseconds()
        else:
            t_milliseconds = time_simulation.value
        def _calculate_capacity(t_milliseconds, limits_length):
            if limits_length >= len(self.limits):
                raise ValueError("Try with length = {}".format(len(self.limits) - 1))

            value, period = self.limits[limits_length].value, self.limits[limits_length].period.to_milliseconds()

            if limits_length == 0:
                c = value * np.floor((t_milliseconds / period) + 1)
            else:
                ni = np.floor(t_milliseconds / period)  # determines which interval number (ni) 't' belongs to
                qvalue = value * ni  # capacity due to quota
                aux = t_milliseconds - ni * period  # auxiliary variable
                cprevious = _calculate_capacity(aux, limits_length - 1)
                ramp = min(cprevious, value)  # capacity due to ramp
                c = qvalue + ramp

            return c

        if time_simulation.unit != TimeUnit.MILLISECOND:
            t_milliseconds = time_simulation.to_milliseconds()
        else:
            t_milliseconds = time_simulation.value

        return _calculate_capacity(t_milliseconds, len(self.limits) - 1)


    def capacity_during(self, end_instant: Union[str, TimeDuration], start_instant: Union[str, TimeDuration] = "0ms") -> float:
        if isinstance(end_instant, str):
            end_instant = parse_time_string_to_duration(end_instant)
        if isinstance(start_instant, str):
            start_instant = parse_time_string_to_duration(start_instant)

        end_instant_milliseconds = end_instant.to_milliseconds()
        start_instant_milliseconds = start_instant.to_milliseconds()

        if end_instant_milliseconds <= start_instant_milliseconds:
            raise ValueError("end_instant must be greater than start_instant")

        capacity_at_end = self.capacity_at(TimeDuration(end_instant_milliseconds, TimeUnit.MILLISECOND))
        capacity_at_start = self.capacity_at(TimeDuration(start_instant_milliseconds, TimeUnit.MILLISECOND))

        return capacity_at_end - capacity_at_start


    def min_time(self, capacity_goal: int, return_unit: Optional[TimeUnit] = None, display=True) -> Union[str, TimeDuration]:
        if not isinstance(capacity_goal, int):
            raise TypeError("capacity_goal must be an integer number of requests")
        if capacity_goal < 0:
            raise ValueError("The 'capacity goal' should be greater or equal to 0.")

        T = 0
        for limit in reversed(self.limits[1:]):
            if capacity_goal <= 0:
                break
            nu = np.floor(capacity_goal / limit.value)
            delta = (capacity_goal == nu * limit.value)
            n_i = int(nu - 1 if delta else nu)
            T += n_i * limit.period.to_milliseconds()
            capacity_goal -= n_i * limit.value

        base = self.limits[0]
        c_r = base.value
        if capacity_goal > c_r:
            from math import ceil
            batches = ceil(capacity_goal / c_r)
            p_r_ms = base.period.to_milliseconds()
            T += (batches - 1) * p_r_ms

        result_duration = TimeDuration(int(T), TimeUnit.MILLISECOND)
        if T == 0:
            return "0s"

        if return_unit is None:
            return_unit = base.period.unit
        duration_desired = result_duration.to_desired_time_unit(return_unit)
        return format_time_with_unit(duration_desired) if display else duration_desired


    def quota_exhaustion_threshold(self,display=True) -> List[Union[str, TimeDuration]]:
        exhaustion_thresholds = []

        # Iterar sobre los límites superiores (todos excepto el base)
        for limit in self.limits[1:]:
            exhaustion_thresholds.append(self.min_time(limit.value, display=display))
 
        return exhaustion_thresholds[0] if len(exhaustion_thresholds) == 1 else exhaustion_thresholds


if __name__ == "__main__":
    # Case 1: Only Rate
    rate = Rate(value=100, unit="req", period="1h")
    br1 = BoundedRate(rate=rate)
    print("=== Only Rate ===")
    print(f"limits: {br1.limits}")
    print(f"capacity_at(1h): {br1.capacity_at('1h')}")
    print(f"min_time(500): {br1.min_time(500)}")
    print(f"quota_exhaustion_threshold: {br1.quota_exhaustion_threshold()}")

    # Case 2: Only Quota
    quota = Quota(value=1000, unit="req", period="1day")
    br2 = BoundedRate(quota=quota)
    print("\n=== Only Quota ===")
    print(f"limits: {br2.limits}")
    print(f"capacity_at(1day): {br2.capacity_at('1day')}")
    print(f"min_time(500): {br2.min_time(500)}")
    print(f"quota_exhaustion_threshold: {br2.quota_exhaustion_threshold()}")

    # Case 3: Rate + Quota
    br3 = BoundedRate(rate=rate, quota=quota)
    print("\n=== Rate + Quota ===")
    print(f"limits: {br3.limits}")
    print(f"capacity_at(1h): {br3.capacity_at('1h')}")
    print(f"capacity_at(1day): {br3.capacity_at('1day')}")
    print(f"min_time(500): {br3.min_time(500)}")
    print(f"min_time(1000): {br3.min_time(1000)}")
    print(f"quota_exhaustion_threshold: {br3.quota_exhaustion_threshold()}")
