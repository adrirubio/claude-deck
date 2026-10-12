"""UTC serialization for API values; Python values stay unchanged."""
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, FieldSerializationInfo, SerializerFunctionWrapHandler, field_serializer


def utc_datetime(value: datetime) -> datetime:
    """Interpret naive server values as UTC and preserve the instant."""
    if value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def format_utc_time(value: datetime) -> str:
    """Format a response timestamp with an explicit UTC offset."""
    return utc_datetime(value).isoformat()


def naive_utc_confirmation(value: datetime) -> datetime:
    """Decode a confirmation instant into the existing UTC storage form."""
    return value if value.utcoffset() is None else utc_datetime(value).replace(tzinfo=None)


def _timestamp_string(value: str) -> str:
    """Serialize declared legacy timestamp strings without changing validation."""
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return value
    return format_utc_time(stamp)


_LEGACY_TIMESTAMP_FIELDS = frozenset({"created_at", "last_accessed", "last_tested_at", "modified_at"})


def utc_response_values(value: Any) -> Any:
    """Copy response values into UTC without changing the original values."""
    if isinstance(value, datetime):
        return utc_datetime(value)
    if isinstance(value, dict):
        return {key: utc_response_values(item) for key, item in value.items()}
    if isinstance(value, list):
        return [utc_response_values(item) for item in value]
    if isinstance(value, tuple):
        return tuple(utc_response_values(item) for item in value)
    if isinstance(value, ApiModel):
        return value
    if isinstance(value, BaseModel):
        return value.model_copy(update={
            name: _timestamp_string(item) if name in _LEGACY_TIMESTAMP_FIELDS and isinstance(item, str)
            else utc_response_values(item)
            for name, item in value
        })
    return value


class ApiModel(BaseModel):
    """One JSON serializer for typed and nested API datetime values."""

    @field_serializer("*", mode="wrap", when_used="json")
    def serialize_utc_values(
        self, value: Any, handler: SerializerFunctionWrapHandler, info: FieldSerializationInfo
    ) -> Any:
        if info.field_name in _LEGACY_TIMESTAMP_FIELDS and isinstance(value, str):
            value = _timestamp_string(value)
        return handler(utc_response_values(value))
