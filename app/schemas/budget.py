from pydantic import BaseModel, Field
from typing import Optional, List


class BudgetRecommendationRequest(BaseModel):
    datasheet_source: str = Field(..., description="Raw YAML text OR a valid URI to the datasheet.")
    plan_names: Optional[List[str]] = Field(None, description="Filter to one or more billing plans (e.g., ['pro', 'ultra']). If omitted, evaluates ALL plans.")
    endpoint_path: Optional[str] = Field(None, description="Filter by endpoint. If omitted, evaluates ALL endpoints.")
    alias: Optional[str] = Field(None, description="Filter by alias. If omitted, evaluates ALL aliases.")


class PlanRecommendation(BaseModel):
    plan: str
    endpoint: str
    alias: Optional[str] = None
    dimension: str

    base_cost: float = Field(..., description="Fixed plan subscription price.")
    overage_cost: float = Field(..., description="Total overage cost to reach desired_capacity.")
    total_cost: float = Field(..., description="base_cost + overage_cost.")
    currency: str

    affordable: bool = Field(..., description="total_cost <= max_budget (always True when no max_budget).")
    budget_surplus: Optional[float] = Field(None, description="max_budget - total_cost when max_budget is provided and plan is affordable.")
    unreachable: bool = Field(..., description="True when desired_capacity cannot be reached within the billing period.")
    unreachable_reason: Optional[str] = Field(
        None,
        description=(
            "'rate_limit': the rate is too slow regardless of budget; "
            "'budget_limit': expanding the quota further would fix it."
        ),
    )

    time_to_capacity_ms: Optional[float] = Field(None, description="ms to first reach desired_capacity (with expanded quotas).")
    time_to_capacity: Optional[str] = Field(None, description="Human-readable time to first reach desired_capacity.")


class BudgetRecommendationResponse(BaseModel):
    desired_capacity: float
    capacity_unit: str
    max_budget: Optional[float] = None
    exclude_plan_price: bool
    currency: str
    results: List[PlanRecommendation]
