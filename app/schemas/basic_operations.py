from pydantic import BaseModel
from typing import Optional, Union, List
from app.models import Rate, Quota


# REQUESTS

class BoundedRateRequest(BaseModel):
    rate: Optional[Union[Rate, List[Rate]]] = None
    quota: Optional[Union[Quota, List[Quota]]] = None


# RESPONSES

class MinTimeResponse(BaseModel):
    capacity_goal: int
    min_time: str