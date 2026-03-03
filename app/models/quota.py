from typing import Annotated, Any
from pydantic import BaseModel, BeforeValidator, PlainSerializer, WithJsonSchema
from app.engine.time_models import TimeDuration
from app.utils.time_utils import parse_time_string_to_duration, format_time_with_unit

def parse_time(v: Any) -> TimeDuration:
    if isinstance(v, str):
        return parse_time_string_to_duration(v.strip())
    if isinstance(v, TimeDuration):
        return v
    raise ValueError("Period must be a string or TimeDuration")

def serialize_time(v: TimeDuration) -> str:
    return format_time_with_unit(v)

PydanticTimeDuration = Annotated[
    Any,
    BeforeValidator(parse_time),
    PlainSerializer(serialize_time, return_type=str),
    WithJsonSchema({'type': 'string', 'example': '1 month'})
]

class Quota(BaseModel):
    value: int
    unit: str
    period: PydanticTimeDuration




