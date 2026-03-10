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


class CapacityAtResponse(BaseModel):
    time: str
    capacity: float


class CapacityDuringResponse(BaseModel):
    start_instant: str
    end_instant: str
    capacity: float


class QuotaExhaustionThresholdItem(BaseModel):
    quota: Quota
    exhaustion_threshold: str


class QuotaExhaustionThresholdResponse(BaseModel):
    thresholds: List[QuotaExhaustionThresholdItem]


class IdleTimePeriodItem(BaseModel):
    quota: Quota
    idle_time: str


class IdleTimePeriodResponse(BaseModel):
    idle_times: List[IdleTimePeriodItem]


class RatesResponse(BaseModel):
    rates: List[Rate]


class QuotasResponse(BaseModel):
    quotas: List[Quota]


class LimitsResponse(BaseModel):
    rates: List[Rate]
    quotas: List[Quota]