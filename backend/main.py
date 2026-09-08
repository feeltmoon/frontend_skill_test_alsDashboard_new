from __future__ import annotations

import csv
import json
import os
from io import StringIO
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from backend.conversion_service import CheckNotFoundError, get_check_conversion
from backend.database import DashboardDatabase
from backend.models import (
    CheckConversionResult,
    CrfBookResult,
    PageResult,
    StudyStatus,
    UploadResult,
)
from backend.parser import WorkbookValidationError, parse_als_workbook
from backend.schema import (
    BOARD_ACTIVE_COLUMN,
    BOARD_COLUMNS,
    BOARD_FILTERS,
    FIELD_FIXED_COLUMNS,
    FIELD_OPTIONAL_GROUPS,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = Path(os.environ.get("ALS_DASHBOARD_DB", PROJECT_ROOT / "data" / "als_dashboard.sqlite3"))
MAX_UPLOAD_BYTES = 100 * 1024 * 1024

database = DashboardDatabase(DB_PATH)
app = FastAPI(title="ALS Dashboard", version="1.0.0")


def _require_study() -> None:
    if not database.status().ready:
        raise HTTPException(status_code=409, detail="Upload a valid ALS .xlsx workbook first.")


def _parse_filters(raw: str, board: str) -> dict[str, str]:
    try:
        value = json.loads(raw or "{}")
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=422, detail="Filters must be a valid JSON object.") from exc
    if not isinstance(value, dict):
        raise HTTPException(status_code=422, detail="Filters must be a JSON object.")
    unknown = set(value) - set(BOARD_FILTERS[board])
    if unknown:
        raise HTTPException(status_code=422, detail=f"Unsupported filter(s): {', '.join(sorted(unknown))}.")
    return {str(key): str(item) for key, item in value.items()}


def _parse_columns(raw: str, board: str) -> list[str] | None:
    if not raw.strip():
        return None
    columns = [column.strip() for column in raw.split(",") if column.strip()]
    unknown = [column for column in columns if column not in BOARD_COLUMNS[board]]
    if unknown:
        raise HTTPException(status_code=422, detail=f"Unsupported column(s): {', '.join(unknown)}.")
    return columns


def _csv_response(columns: list[str], rows: list[dict[str, str]], filename: str) -> Response:
    buffer = StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    content = "\ufeff" + buffer.getvalue()
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/status", response_model=StudyStatus)
def get_status() -> StudyStatus:
    return database.status()


@app.get("/api/schema")
def get_schema() -> dict[str, object]:
    return {
        "boards": {
            board: {
                "columns": columns,
                "filters": BOARD_FILTERS[board],
                "activeColumn": BOARD_ACTIVE_COLUMN.get(board),
            }
            for board, columns in BOARD_COLUMNS.items()
        },
        "fieldFixedColumns": FIELD_FIXED_COLUMNS,
        "fieldOptionalGroups": FIELD_OPTIONAL_GROUPS,
    }


@app.post("/api/upload", response_model=UploadResult)
async def upload_workbook(file: Annotated[UploadFile, File(...)]) -> UploadResult:
    filename = file.filename or "upload.xlsx"
    if Path(filename).suffix.lower() != ".xlsx":
        raise HTTPException(status_code=415, detail="Only .xlsx workbooks are supported; .xls is not accepted.")
    content = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="The workbook exceeds the 100 MB upload limit.")
    try:
        parsed = parse_als_workbook(content, filename)
    except WorkbookValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    status = database.replace_study(parsed)
    return UploadResult(**status.model_dump(), message="Workbook parsed and activated successfully.")


@app.get("/api/data/{board}", response_model=PageResult)
def get_board_data(
    board: str,
    filters: str = "{}",
    active: str = "",
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=10, le=200)] = 50,
    sort: str = "",
    direction: str = "asc",
    columns: str = "",
    exact: bool = False,
) -> PageResult:
    if board not in BOARD_COLUMNS:
        raise HTTPException(status_code=404, detail="Unknown board.")
    _require_study()
    parsed_filters = _parse_filters(filters, board)
    selected_columns = _parse_columns(columns, board)
    sort_column = sort or BOARD_COLUMNS[board][0]
    try:
        returned_columns, rows, total = database.query_board(
            board,
            parsed_filters,
            active,
            page,
            page_size,
            sort_column,
            direction,
            selected_columns,
            exact=exact,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return PageResult(
        board=board,
        columns=returned_columns,
        rows=rows,
        total=total,
        page=page,
        page_size=page_size,
        sort=sort_column,
        direction=direction,
    )


@app.get("/api/data/{board}/csv")
def export_board_csv(
    board: str,
    filters: str = "{}",
    active: str = "",
    sort: str = "",
    direction: str = "asc",
    columns: str = "",
    exact: bool = False,
) -> Response:
    if board not in BOARD_COLUMNS:
        raise HTTPException(status_code=404, detail="Unknown board.")
    _require_study()
    parsed_filters = _parse_filters(filters, board)
    selected_columns = _parse_columns(columns, board)
    sort_column = sort or BOARD_COLUMNS[board][0]
    try:
        returned_columns, rows, _ = database.query_board(
            board,
            parsed_filters,
            active,
            1,
            50,
            sort_column,
            direction,
            selected_columns,
            all_rows=True,
            exact=exact,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _csv_response(returned_columns, rows, f"als-{board}.csv")


@app.get("/api/crf-book", response_model=CrfBookResult)
def get_crf_book(
    form_oid: str = "",
    folder_oid: str = "",
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=10, le=200)] = 25,
    exact: bool = False,
) -> CrfBookResult:
    _require_study()
    columns, rows, total = database.query_crf_book(
        form_oid, folder_oid, page, page_size, exact=exact
    )
    return CrfBookResult(columns=columns, rows=rows, total=total, page=page, page_size=page_size)


@app.get("/api/crf-book/csv")
def export_crf_book_csv(
    form_oid: str = "", folder_oid: str = "", exact: bool = False
) -> Response:
    _require_study()
    columns, rows, _ = database.query_crf_book(
        form_oid, folder_oid, 1, 25, all_rows=True, exact=exact
    )
    return _csv_response(columns, rows, "als-crf-book.csv")


@app.get(
    "/api/checks/{check_row_id}/conversion",
    response_model=CheckConversionResult,
)
def convert_check_infix(check_row_id: int) -> CheckConversionResult | JSONResponse:
    _require_study()
    try:
        result = get_check_conversion(database, check_row_id)
    except CheckNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if result.status == "error":
        return JSONResponse(status_code=422, content=result.model_dump(mode="json"))
    return result


app.mount("/", StaticFiles(directory=PROJECT_ROOT / "frontend", html=True), name="frontend")

