from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List
from app.models import Rate, Quota


# ──────────────────────────────────────────────────────────────────────────────
# Dimension result (one entry per unit-dimension × workload scenario)
# ──────────────────────────────────────────────────────────────────────────────

class DimensionResult(BaseModel):
    dimension: str
    workload_factor: Optional[float] = None  # actual emails/req used; None when no workload
    value: Any

class CaseResult(BaseModel):
    capacity_request_factor: Optional[float] = None
    value: Any


# ──────────────────────────────────────────────────────────────────────────────
# Base / evaluate (agente MCP)
# ──────────────────────────────────────────────────────────────────────────────

class EvaluateDatasheetRequest(BaseModel):
    datasheet_source: str = Field(..., description="The raw YAML text OR a valid URI to download the file.")
    plan_names: Optional[List[str]] = Field(None, description="Filter to one or more billing plans (e.g., ['pro', 'ultra']). If omitted, evaluates ALL plans.")
    endpoint_path: Optional[str] = Field(None, description="The specific endpoint. If omitted, will evaluate ALL endpoints.")
    alias: Optional[str] = Field(None, description="Filter by alias. If omitted, evaluates ALL existing aliases.")
    operation: str = Field(..., description="The calculation to perform: 'min_time', 'capacity_at', 'idle_time', etc.")
    operation_params: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Dynamic parameters for the operation (e.g., {'capacity_goal': 28}).")


class EvaluateDatasheetResultItem(BaseModel):
    endpoint: str
    alias: Optional[str] = None
    result: Any


class EvaluateDatasheetResponse(BaseModel):
    operation: str
    operation_params: Dict[str, Any]
    results: Dict[str, List[EvaluateDatasheetResultItem]]


# ──────────────────────────────────────────────────────────────────────────────
# Base request para endpoints user-friendly
# ──────────────────────────────────────────────────────────────────────────────

class DatasheetBaseRequest(BaseModel):
    datasheet_source: str = Field(..., description="Raw YAML text OR a valid URI to download the datasheet.")
    plan_names: Optional[List[str]] = Field(None, description="Filter to one or more billing plans (e.g., ['pro', 'ultra']). If omitted, evaluates ALL plans.")
    endpoint_path: Optional[str] = Field(None, description="Filter by endpoint. If omitted, evaluates ALL endpoints.")
    alias: Optional[str] = Field(None, description="Filter by alias. If omitted, evaluates ALL aliases.")


# ──────────────────────────────────────────────────────────────────────────────
# Result items for calculation operations (return dimensions)
# ──────────────────────────────────────────────────────────────────────────────

class DatasheetMinTimeResultItem(BaseModel):
    endpoint: str
    alias: Optional[str] = None
    dimensions: Dict[str, List[CaseResult]]

class DatasheetCapacityAtResultItem(BaseModel):
    endpoint: str
    alias: Optional[str] = None
    dimensions: Dict[str, List[CaseResult]]

class DatasheetCapacityDuringResultItem(BaseModel):
    endpoint: str
    alias: Optional[str] = None
    dimensions: Dict[str, List[CaseResult]]

class DatasheetQuotaExhaustionResultItem(BaseModel):
    endpoint: str
    alias: Optional[str] = None
    dimensions: Dict[str, List[CaseResult]]

class DatasheetIdleTimePeriodResultItem(BaseModel):
    endpoint: str
    alias: Optional[str] = None
    dimensions: Dict[str, List[CaseResult]]

class DatasheetRatesResultItem(BaseModel):
    endpoint: str
    alias: Optional[str] = None
    rates: List[Rate]

class DatasheetQuotasResultItem(BaseModel):
    endpoint: str
    alias: Optional[str] = None
    quotas: List[Quota]

class DatasheetLimitsResultItem(BaseModel):
    endpoint: str
    alias: Optional[str] = None
    rates: List[Rate]
    quotas: List[Quota]


# ──────────────────────────────────────────────────────────────────────────────
# Responses por operación
# ──────────────────────────────────────────────────────────────────────────────

class DatasheetMinTimeResponse(BaseModel):
    capacity_goal: int
    results: Dict[str, List[DatasheetMinTimeResultItem]]

class DatasheetCapacityAtResponse(BaseModel):
    time: str
    results: Dict[str, List[DatasheetCapacityAtResultItem]]

class DatasheetCapacityDuringResponse(BaseModel):
    start_instant: str
    end_instant: str
    results: Dict[str, List[DatasheetCapacityDuringResultItem]]

class DatasheetQuotaExhaustionResponse(BaseModel):
    results: Dict[str, List[DatasheetQuotaExhaustionResultItem]]

class DatasheetIdleTimePeriodResponse(BaseModel):
    results: Dict[str, List[DatasheetIdleTimePeriodResultItem]]

class DatasheetRatesResponse(BaseModel):
    results: Dict[str, List[DatasheetRatesResultItem]]

class DatasheetQuotasResponse(BaseModel):
    results: Dict[str, List[DatasheetQuotasResultItem]]

class DatasheetLimitsResponse(BaseModel):
    results: Dict[str, List[DatasheetLimitsResultItem]]


# ──────────────────────────────────────────────────────────────────────────────
# Capacity curves
# ──────────────────────────────────────────────────────────────────────────────

class DatasheetCurveSeries(BaseModel):
    plan: str
    endpoint: str
    alias: Optional[str] = None
    dimension: str
    workload_unit: Optional[str] = None
    capacity_request_factor: Optional[float] = None
    rates: List[Rate] = Field(default_factory=list)
    quotas: List[Quota] = Field(default_factory=list)
    t_ms: List[float]
    capacity: List[float]

class DatasheetCurveDataResponse(BaseModel):
    time_interval: str
    curve_type: str   # "accumulated" | "inflection"
    series: List[DatasheetCurveSeries]


# ──────────────────────────────────────────────────────────────────────────────
# Navigation — requests
# ──────────────────────────────────────────────────────────────────────────────

class NavRequest(BaseModel):
    datasheet_source: str = Field(..., description="Raw YAML text OR URI to the datasheet.")
    plan_names: Optional[List[str]] = Field(None, description="Filter by one or more billing plans (e.g., ['pro', 'ultra']). If omitted, all plans are considered.")
    endpoint_path: Optional[str] = Field(None, description="Filter by endpoint path (e.g. '/mail/send'). If omitted, all endpoints are considered.")


# ──────────────────────────────────────────────────────────────────────────────
# Navigation — responses
# ──────────────────────────────────────────────────────────────────────────────

class NavPlansResponse(BaseModel):
    plans: List[str]

class NavEndpointsResponse(BaseModel):
    plans: Optional[List[str]] = None
    endpoints: List[str]

class NavCapacityUnitsResponse(BaseModel):
    plans: Optional[List[str]] = None
    endpoint: Optional[str] = None
    units: List[str]

class NavAliasesResponse(BaseModel):
    plans: Optional[List[str]] = None
    endpoint: Optional[str] = None
    aliases: Optional[List[str]] = None

class CRFRange(BaseModel):
    unit: str
    min: float
    max: float
    description: Optional[str] = None

class NavCRFRangesResponse(BaseModel):
    plans: Optional[List[str]] = None
    endpoint: Optional[str] = None
    crf_ranges: List[CRFRange]
