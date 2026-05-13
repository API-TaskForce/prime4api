from pydantic import BaseModel, Field
from typing import Optional, Dict, List, Any


class DemandRateInput(BaseModel):
    value: float = Field(..., description="Rate value (e.g. 5)")
    unit: str = Field(..., description="'requests', 'emails', 'MBs', etc.")
    period: str = Field(..., description="Window period (e.g. '1s', '1min')")


class DemandQuotaInput(BaseModel):
    value: float = Field(..., description="Quota limit (e.g. 20000)")
    unit: str = Field(..., description="'requests', 'emails', 'MBs', etc.")
    period: str = Field(..., description="Reset period (e.g. '1month', '1day')")


class DemandInput(BaseModel):
    rate: Optional[DemandRateInput] = Field(None, description="Instantaneous rate of the demand.")
    quota: Optional[List[DemandQuotaInput]] = Field(
        None,
        description="Volume quota(s) for the demand. May mix units (e.g. emails + MBs)."
    )
    duration: Optional[str] = Field(
        None,
        description="Duration of the demand (e.g. '1h'). Creates an implicit quota: rate.value × duration."
    )
    demand_crf: Optional[Dict[str, float]] = Field(
        None,
        description=(
            "Per-unit workload factor for this demand: how many workload units each request consumes. "
            "E.g. {'emails': 2, 'MBs': 0.5}. If omitted, inherits capacity_request_factor from the request. "
            "Required when rate/quota is in 'requests' and the plan dimension is a workload unit."
        )
    )
    label: str = Field("Demand", description="Label for the chart legend and analytics keys.")


class DatasheetDemandRequest(BaseModel):
    datasheet_source: str = Field(..., description="Raw YAML text OR a valid URI to the datasheet.")
    plan_names: Optional[List[str]] = Field(None, description="Filter to one or more billing plans (e.g., ['pro', 'ultra']). If omitted, evaluates ALL plans.")
    endpoint_path: Optional[str] = Field(None, description="Filter by endpoint. If omitted, evaluates ALL endpoints.")
    alias: Optional[str] = Field(None, description="Filter by alias. If omitted, evaluates ALL aliases.")
    demands: List[DemandInput] = Field(..., description="One or more demands to compare against the plan.")


# ── Analytics response ──────────────────────────────────────────────────────

class DemandVerdict(BaseModel):
    verdict: str = Field(..., description="'YES', 'NO', or 'DEPENDS'")
    reason: Optional[str] = Field(
        None,
        description="'rate_exceeded', 'quota_exceeded', 'crf_required', 'unit_mismatch', 'invalid_demand'"
    )
    detail: Optional[Dict[str, Any]] = None


class DemandEndpointResult(BaseModel):
    plan: str
    endpoint: str
    alias: Optional[str] = None
    dimension: str
    verdicts: Dict[str, DemandVerdict]


class DatasheetDemandAnalyticsResponse(BaseModel):
    time_interval: str
    results: List[DemandEndpointResult]
