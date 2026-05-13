from fastapi import APIRouter, HTTPException
from app.schemas.datasheet import (
    NavRequest,
    NavPlansResponse,
    NavEndpointsResponse,
    NavCapacityUnitsResponse,
    NavAliasesResponse,
    NavCRFRangesResponse,
    CRFRange,
)
from app.services.datasheet_evaluator_service import DatasheetEvaluatorService
from app.utils.yaml_utils import load_yaml_source

router = APIRouter()
evaluator_service = DatasheetEvaluatorService()

_EX = {"response_model_exclude_none": True}


@router.post("/plans", response_model=NavPlansResponse,
             summary="List all billing plans in the datasheet")
def get_plans(request: NavRequest):
    yaml_data = load_yaml_source(request.datasheet_source)
    try:
        return NavPlansResponse(plans=evaluator_service.get_plans(yaml_data))
    except (ValueError, KeyError) as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/endpoints", response_model=NavEndpointsResponse, **_EX,
             summary="List endpoints. Optionally filter by plan_names; omit for union across all plans.")
def get_endpoints(request: NavRequest):
    yaml_data = load_yaml_source(request.datasheet_source)
    try:
        return NavEndpointsResponse(
            plans=request.plan_names,
            endpoints=evaluator_service.get_endpoints(yaml_data, request.plan_names),
        )
    except KeyError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/capacity-units", response_model=NavCapacityUnitsResponse, **_EX,
             summary="List workload-based capacity units. All filters optional; omit for union across entire datasheet.")
def get_capacity_units(request: NavRequest):
    yaml_data = load_yaml_source(request.datasheet_source)
    try:
        units = evaluator_service.get_capacity_units(
            yaml_data, request.plan_names, request.endpoint_path
        )
        return NavCapacityUnitsResponse(
            plans=request.plan_names,
            endpoint=request.endpoint_path,
            units=units,
        )
    except KeyError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/aliases", response_model=NavAliasesResponse, **_EX,
             summary="List aliases. All filters optional; omit for union across all plans/endpoints. Field absent if no aliases exist.")
def get_aliases(request: NavRequest):
    yaml_data = load_yaml_source(request.datasheet_source)
    try:
        aliases = evaluator_service.get_aliases(
            yaml_data, request.plan_names, request.endpoint_path
        )
        return NavAliasesResponse(
            plans=request.plan_names,
            endpoint=request.endpoint_path,
            aliases=aliases,
        )
    except KeyError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/crf-ranges", response_model=NavCRFRangesResponse, **_EX,
             summary="Return CRF min/max per workload unit. All filters optional; omit for broadest ranges across all plans/endpoints.")
def get_crf_ranges(request: NavRequest):
    yaml_data = load_yaml_source(request.datasheet_source)
    try:
        raw = evaluator_service.get_crf_ranges(
            yaml_data, request.plan_names, request.endpoint_path
        )
        return NavCRFRangesResponse(
            plans=request.plan_names,
            endpoint=request.endpoint_path,
            crf_ranges=[CRFRange(**r) for r in raw],
        )
    except KeyError as e:
        raise HTTPException(status_code=400, detail=str(e))
