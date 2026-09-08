from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class StudyStatus(BaseModel):
    ready: bool
    filename: str | None = None
    project: str | None = None
    draft: str | None = None
    uploaded_at: str | None = None
    counts: dict[str, int] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


class UploadResult(StudyStatus):
    message: str


class PageResult(BaseModel):
    board: str
    columns: list[str]
    rows: list[dict[str, Any]]
    total: int
    page: int
    page_size: int
    sort: str
    direction: str


class CrfBookResult(BaseModel):
    columns: list[str]
    rows: list[dict[str, str]]
    total: int
    page: int
    page_size: int


class ConversionDiagnostic(BaseModel):
    code: str
    severity: str
    message: str
    source_start: int
    source_end: int
    source_text: str


class CheckConversionResult(BaseModel):
    check_row_id: int
    check_name: str
    original_infix: str
    status: str
    yaml: str | None = None
    ast: dict[str, Any] | None = None
    diagnostics: list[ConversionDiagnostic] = Field(default_factory=list)
    cached: bool
    converter_version: str

