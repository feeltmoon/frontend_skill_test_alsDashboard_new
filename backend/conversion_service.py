from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from backend.database import DashboardDatabase
from backend.infix_converter import CONVERTER_VERSION, convert_infix
from backend.models import CheckConversionResult, ConversionDiagnostic


class CheckNotFoundError(LookupError):
    pass


def _response_from_cached(
    check: dict[str, object],
    cached: dict[str, object],
) -> CheckConversionResult | None:
    try:
        ast = json.loads(str(cached["ast_json"])) if cached["ast_json"] is not None else None
        diagnostics = json.loads(str(cached["diagnostics_json"]))
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(diagnostics, list):
        return None
    return CheckConversionResult(
        check_row_id=int(check["row_id"]),
        check_name=str(check["CheckName"]),
        original_infix=str(check["Infix"]),
        status=str(cached["status"]),
        yaml=str(cached["yaml_text"]) if cached["yaml_text"] is not None else None,
        ast=ast,
        diagnostics=[ConversionDiagnostic(**item) for item in diagnostics],
        cached=True,
        converter_version=CONVERTER_VERSION,
    )


def get_check_conversion(
    database: DashboardDatabase,
    check_row_id: int,
) -> CheckConversionResult:
    check = database.get_check(check_row_id)
    if check is None:
        raise CheckNotFoundError(f"Check row {check_row_id} is not part of the current study.")

    infix = str(check["Infix"])
    infix_hash = hashlib.sha256(infix.encode("utf-8")).hexdigest()
    cached = database.get_cached_conversion(
        check_row_id,
        infix_hash,
        CONVERTER_VERSION,
    )
    if cached is not None:
        cached_response = _response_from_cached(check, cached)
        if cached_response is not None:
            return cached_response

    forms, fields, folders = database.get_conversion_metadata()
    converted = convert_infix(
        str(check["CheckName"]),
        infix,
        forms,
        fields,
        folders,
    )
    diagnostics = [item.as_dict() for item in converted.diagnostics]
    database.save_conversion(
        check_row_id=check_row_id,
        infix_hash=infix_hash,
        converter_version=CONVERTER_VERSION,
        status=converted.status,
        ast=converted.ast,
        yaml_text=converted.yaml_text,
        diagnostics=diagnostics,
        converted_at=datetime.now(timezone.utc).isoformat(),
    )
    return CheckConversionResult(
        check_row_id=check_row_id,
        check_name=str(check["CheckName"]),
        original_infix=infix,
        status=converted.status,
        yaml=converted.yaml_text,
        ast=converted.ast,
        diagnostics=[ConversionDiagnostic(**item) for item in diagnostics],
        cached=False,
        converter_version=CONVERTER_VERSION,
    )
