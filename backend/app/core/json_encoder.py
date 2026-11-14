"""
backend/app/core/json_encoder.py

Safe, deterministic JSON serialization utility for AI prompts, telemetry, and logging.
Enforces sorted keys, ISO-8601 timestamps, ROUND_HALF_UP Decimal string formatting,
chronological pruning with omission metadata, and strict payload bounds.
"""

import decimal
import json
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any


class InvalidAcademicDataError(ValueError):
    """Raised when academic numerical telemetry contains NaN, infinity, negative values, or invalid ranges."""


class ParentReportPayloadTooLargeError(Exception):
    """Raised when telemetry payload exceeds allowable size bounds even after pruning."""


class SafeJSONEncoder(json.JSONEncoder):
    """
    JSON encoder that deterministically handles non-standard Python types:
    - UUID -> str
    - datetime / date -> ISO-8601 string
    - Decimal -> exact fixed-point string rounded via ROUND_HALF_UP (2 decimal places)
      (Strictly validates: rejects NaN, +/- Infinity, and negative values before rounding)
    - set / frozenset -> sorted list
    - bytes -> UTF-8 decoded string (with replacement)
    - Pydantic / dataclass objects -> dict conversion
    """

    def default(self, obj: Any) -> Any:
        if isinstance(obj, uuid.UUID):
            return str(obj)
        if isinstance(obj, (datetime, date)):
            return obj.isoformat()
        if isinstance(obj, Decimal):
            d = obj
            if d.is_nan():
                raise InvalidAcademicDataError("Invalid academic decimal value: NaN is not allowed.")
            if d.is_infinite():
                raise InvalidAcademicDataError(f"Invalid academic decimal value: Infinity ({d}) is not allowed.")
            if d < Decimal("0.00"):
                raise InvalidAcademicDataError(f"Invalid academic decimal value: Negative values ({d}) are not allowed.")
            return f"{d.quantize(Decimal('0.01'), rounding=decimal.ROUND_HALF_UP):.2f}"
        if isinstance(obj, (set, frozenset)):
            return sorted(list(obj))
        if isinstance(obj, bytes):
            return obj.decode("utf-8", errors="replace")
        if hasattr(obj, "model_dump"):
            return obj.model_dump()
        if hasattr(obj, "dict"):
            return obj.dict()
        if hasattr(obj, "__dict__"):
            return {k: v for k, v in obj.__dict__.items() if not k.startswith("_")}
        try:
            return super().default(obj)
        except TypeError:
            return str(obj)


def safe_json_dumps(
    obj: Any,
    sort_keys: bool = True,
    indent: int | None = None,
    max_bytes: int | None = 8192,
) -> str:
    """
    Serializes a Python object to a deterministic JSON string.
    - sort_keys=True: Guarantees reproducible prompt strings.
    - ensure_ascii=False: Preserves international and multilingual characters.
    - allow_nan=False: Rejects raw unconstrained float NaN/Infinity.
    - max_bytes: Enforces hard size boundary (default 8 KB).
      Prunes recent_exams chronologically (oldest first) and injects omission_metadata.
      If base object exceeds bound even with 0 exams, raises ParentReportPayloadTooLargeError.
    """
    serialized = json.dumps(
        obj,
        cls=SafeJSONEncoder,
        sort_keys=sort_keys,
        indent=indent,
        ensure_ascii=False,
        allow_nan=False,
    )

    encoded_bytes = serialized.encode("utf-8")
    if max_bytes is not None and len(encoded_bytes) > max_bytes:
        # Prune recent_exams chronologically (oldest first; list is ordered newest to oldest)
        if isinstance(obj, dict) and "recent_exams" in obj and isinstance(obj["recent_exams"], list):
            pruned_obj = dict(obj)
            exams = list(obj["recent_exams"])
            total_exams = len(exams)

            while exams:
                exams.pop()
                pruned_obj["recent_exams"] = exams
                pruned_obj["omission_metadata"] = {
                    "is_pruned": True,
                    "total_records_recorded": total_exams,
                    "records_retained": len(exams),
                    "records_omitted": total_exams - len(exams),
                    "omission_reason": "MAX_TELEMETRY_BYTES_EXCEEDED",
                    "omission_strategy": "CHRONOLOGICAL_OLDEST_FIRST",
                }
                candidate = json.dumps(
                    pruned_obj,
                    cls=SafeJSONEncoder,
                    sort_keys=sort_keys,
                    indent=indent,
                    ensure_ascii=False,
                    allow_nan=False,
                )
                if len(candidate.encode("utf-8")) <= max_bytes:
                    return candidate

        # Fail-closed boundary: Never emit broken or truncated reports to parents
        raise ParentReportPayloadTooLargeError(
            f"Student academic record payload ({len(encoded_bytes)} bytes) exceeds maximum allowable "
            f"limit ({max_bytes} bytes) and cannot be processed safely."
        )

    return serialized
