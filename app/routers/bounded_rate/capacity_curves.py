from fastapi import APIRouter, HTTPException, Query, Response

from app.schemas.capacity_curves import CapacityCurvePointsResponse, CapacityCurveRequest
from app.services.capacity_curve_service import CapacityCurveService

router = APIRouter()
service = CapacityCurveService()

_PROVIDER_MODE_QUERY = Query(False, description="Provider-centric semantics: capacity is counted at the end of each period window instead of the start. Default: False (client-centric).")


# ══════════════════════════════════════════════════════════════════════════════
# /data/*  — raw JSON points for external plotting
# ══════════════════════════════════════════════════════════════════════════════

@router.post(
    "/data/accumulated",
    response_model=CapacityCurvePointsResponse,
    summary="Accumulated capacity curve — raw data points",
    description=(
        "Returns the (t_ms, capacity) points of the accumulated available capacity curve. "
        "Accepts a single Rate, a single Quota, or any combination (BoundedRate). "
        "The client is responsible for rendering the data."
    ),
)
def get_accumulated_curve_data(request: CapacityCurveRequest, provider_mode: bool = _PROVIDER_MODE_QUERY):
    try:
        points = service.get_accumulated_capacity_curve(
            request.time_interval, request.rate, request.quota, provider_mode=provider_mode
        )
        return CapacityCurvePointsResponse(
            t_ms=points.t_ms,
            capacity=points.capacity,
            point_count=len(points.t_ms),
            time_interval=request.time_interval,
            curve_type="accumulated",
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post(
    "/data/inflection",
    response_model=CapacityCurvePointsResponse,
    summary="Inflection point capacity curve — raw sparse data points",
    description=(
        "BoundedRate only (requires at least one quota / upper limit). "
        "Returns only the inflection points (slope changes), far fewer points than the dense curve. "
        "Recommended rendering: step function (shape='hv')."
    ),
)
def get_inflection_curve_data(request: CapacityCurveRequest, provider_mode: bool = _PROVIDER_MODE_QUERY):
    try:
        points = service.get_inflection_point_capacity_curve(
            request.time_interval, request.rate, request.quota, provider_mode=provider_mode
        )
        return CapacityCurvePointsResponse(
            t_ms=points.t_ms,
            capacity=points.capacity,
            point_count=len(points.t_ms),
            time_interval=request.time_interval,
            curve_type="inflection",
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ══════════════════════════════════════════════════════════════════════════════
# /chart/*  — self-contained Plotly HTML (for chatbot / direct visualization)
# ══════════════════════════════════════════════════════════════════════════════

@router.post(
    "/chart/accumulated",
    responses={
        200: {
            "content": {"text/html": {}},
            "description": "Interactive Plotly chart as self-contained HTML.",
        }
    },
    summary="Accumulated capacity curve — interactive HTML chart",
    description=(
        "Returns a self-contained Plotly HTML page with the accumulated capacity curve. "
        "Accepts a single Rate, a single Quota, or any combination (BoundedRate). "
        "Designed to be embedded directly in a chatbot or browser."
    ),
)
def get_accumulated_curve_chart(request: CapacityCurveRequest, provider_mode: bool = _PROVIDER_MODE_QUERY):
    try:
        html = service.render_accumulated_curve_html(
            request.time_interval, request.rate, request.quota, provider_mode=provider_mode
        )
        return Response(content=html, media_type="text/html")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post(
    "/chart/inflection",
    responses={
        200: {
            "content": {"text/html": {}},
            "description": "Interactive Plotly chart (inflection points) as self-contained HTML.",
        }
    },
    summary="Inflection point capacity curve — interactive HTML chart",
    description=(
        "BoundedRate only. Returns a self-contained Plotly HTML page with the inflection point "
        "capacity curve, rendered with linear interpolation between key slope-change points. "
        "Designed to be embedded directly in a chatbot or browser."
    ),
)
def get_inflection_curve_chart(request: CapacityCurveRequest, provider_mode: bool = _PROVIDER_MODE_QUERY):
    try:
        html = service.render_inflection_point_curve_html(
            request.time_interval, request.rate, request.quota, provider_mode=provider_mode
        )
        return Response(content=html, media_type="text/html")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))