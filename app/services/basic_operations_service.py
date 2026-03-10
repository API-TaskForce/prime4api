from app.engine.evaluators import BoundedRate
from app.models import Rate, Quota
from typing import Optional, Union, List


class BasicOperationsService:

    def calculate_min_time(self, capacity_goal: int, rate: Optional[Union[Rate, List[Rate]]] = None, quota: Optional[Union[Quota, List[Quota]]] = None) -> str:
        try:
            evaluator = BoundedRate(rate, quota)
        except ValueError as e:
            raise ValueError(f"Error creating BoundedRate: {str(e)}")

        try:
            return evaluator.min_time(capacity_goal, display=True)
        except ValueError as e:
            raise ValueError(f"Error calculating min_time: {str(e)}")

    def calculate_capacity_at(self, time: str, rate: Optional[Union[Rate, List[Rate]]] = None, quota: Optional[Union[Quota, List[Quota]]] = None) -> float:
        try:
            evaluator = BoundedRate(rate, quota)
        except ValueError as e:
            raise ValueError(f"Error creating BoundedRate: {str(e)}")

        try:
            return float(evaluator.capacity_at(time))
        except ValueError as e:
            raise ValueError(f"Error calculating capacity_at: {str(e)}")

    def calculate_capacity_during(self, end_instant: str, rate: Optional[Union[Rate, List[Rate]]] = None, quota: Optional[Union[Quota, List[Quota]]] = None, start_instant: str = "0ms") -> float:
        try:
            evaluator = BoundedRate(rate, quota)
        except ValueError as e:
            raise ValueError(f"Error creating BoundedRate: {str(e)}")

        try:
            return float(evaluator.capacity_during(end_instant, start_instant))
        except ValueError as e:
            raise ValueError(f"Error calculating capacity_during: {str(e)}")

    def calculate_quota_exhaustion_threshold(self, rate: Optional[Union[Rate, List[Rate]]] = None, quota: Optional[Union[Quota, List[Quota]]] = None) -> list:
        try:
            evaluator = BoundedRate(rate, quota)
        except ValueError as e:
            raise ValueError(f"Error creating BoundedRate: {str(e)}")

        try:
            results = evaluator.quota_exhaustion_threshold(display=True)
            return [{"quota": limit, "exhaustion_threshold": value} for limit, value in results]
        except ValueError as e:
            raise ValueError(f"Error calculating quota_exhaustion_threshold: {str(e)}")

    def get_rates(self, rate: Optional[Union[Rate, List[Rate]]] = None, quota: Optional[Union[Quota, List[Quota]]] = None) -> List[Rate]:
        try:
            evaluator = BoundedRate(rate, quota)
        except ValueError as e:
            raise ValueError(f"Error creating BoundedRate: {str(e)}")
        return evaluator.rates

    def get_quotas(self, rate: Optional[Union[Rate, List[Rate]]] = None, quota: Optional[Union[Quota, List[Quota]]] = None) -> List[Quota]:
        try:
            evaluator = BoundedRate(rate, quota)
        except ValueError as e:
            raise ValueError(f"Error creating BoundedRate: {str(e)}")
        return evaluator.quotas

    def get_limits(self, rate: Optional[Union[Rate, List[Rate]]] = None, quota: Optional[Union[Quota, List[Quota]]] = None) -> list:
        try:
            evaluator = BoundedRate(rate, quota)
        except ValueError as e:
            raise ValueError(f"Error creating BoundedRate: {str(e)}")
        return evaluator.limits

    def calculate_idle_time_period(self, rate: Optional[Union[Rate, List[Rate]]] = None, quota: Optional[Union[Quota, List[Quota]]] = None) -> list:
        try:
            evaluator = BoundedRate(rate, quota)
        except ValueError as e:
            raise ValueError(f"Error creating BoundedRate: {str(e)}")

        try:
            results = evaluator.idle_time_period(display=True)
            return [{"quota": limit, "idle_time": value} for limit, value in results]
        except ValueError as e:
            raise ValueError(f"Error calculating idle_time_period: {str(e)}")
