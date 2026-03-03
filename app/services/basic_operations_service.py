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
