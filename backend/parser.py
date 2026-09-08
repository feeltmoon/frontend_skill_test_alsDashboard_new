from __future__ import annotations

from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from typing import BinaryIO

import pandas as pd


class WorkbookValidationError(ValueError):
    """Raised when an uploaded workbook does not meet the ALS contract."""


REQUIRED_SHEETS = (
    "CRFDraft",
    "Forms",
    "Fields",
    "Folders",
    "DataDictionaryEntries",
    "Checks",
)

ENTITY_KEYS = {
    "CRFDraft": ("DraftName",),
    "Forms": ("OID",),
    "Fields": ("FormOID", "FieldOID"),
    "Folders": ("OID",),
    "DataDictionaryEntries": ("DataDictionaryName", "CodedData"),
    "Checks": ("CheckName",),
}

CANONICAL_COLUMNS = {
    "CRFDraft": [
        "DraftName",
        "ProjectName",
        "ProjectType",
        "PrimaryFormOID",
        "DefaultMatrixOID",
    ],
    "Forms": [
        "OID",
        "Ordinal",
        "DraftFormName",
        "DraftFormActive",
        "IsTemplate",
        "IsSignatureRequired",
        "IsEproForm",
        "ViewRestrictions",
        "LogDirection",
        "DDEOption",
    ],
    "Fields": [
        "FormOID",
        "FieldOID",
        "VariableOID",
        "Ordinal",
        "IsLog",
        "IsVisible",
        "PreText",
        "DraftFieldActive",
        "DataFormat",
        "DataDictionaryName",
        "CodingDictionary",
        "ControlType",
        "IndentLevel",
        "FixedUnit",
        "HeaderText",
        "HelpText",
        "DefaultValue",
        "DoesNotBreakSignature",
        "SourceDocument",
        "ReviewGroups",
        "IsRequired",
        "QueryNonConformance",
        "QueryFutureDate",
        "CanSetRecordDate",
        "CanSetDataPageDate",
        "CanSetInstanceDate",
        "CanSetSubjectDate",
        "ViewRestrictions",
        "EntryRestrictions",
    ],
    "Folders": [
        "OID",
        "Ordinal",
        "FolderName",
        "ParentFolderOID",
        "IsReusable",
        "StartWinDays",
        "TargetDays",
        "EndWinDays",
        "OverDueDays",
        "CloseDays",
    ],
    "DataDictionaryEntries": [
        "DataDictionaryName",
        "CodedData",
        "Ordinal",
        "UserDataString",
        "Specify",
    ],
    "Checks": [
        "CheckName",
        "CheckActive",
        "BypassDuringMigration",
        "Infix",
        "CopySource",
        "NeedsRetesting",
        "RetestingReason",
        "OID",
    ],
}

BOOLEAN_COLUMNS = {
    "Forms": {
        "DraftFormActive",
        "IsTemplate",
        "IsSignatureRequired",
        "IsEproForm",
    },
    "Fields": {
        "IsLog",
        "IsVisible",
        "DraftFieldActive",
        "DoesNotBreakSignature",
        "IsRequired",
        "QueryNonConformance",
        "QueryFutureDate",
        "CanSetRecordDate",
        "CanSetDataPageDate",
        "CanSetInstanceDate",
        "CanSetSubjectDate",
    },
    "Folders": {"IsReusable"},
    "DataDictionaryEntries": {"Specify"},
    "Checks": {"CheckActive", "BypassDuringMigration"},
}

COLUMN_ALIASES = {
    "Folders": {
        "TargetDays": ("TargetDays", "Targetdays"),
    }
}

REQUIRED_COLUMNS = {
    "CRFDraft": {"DraftName"},
    "Forms": {"OID", "DraftFormName", "DraftFormActive"},
    "Fields": {
        "FormOID",
        "FieldOID",
        "VariableOID",
        "Ordinal",
        "DraftFieldActive",
        "PreText",
        "DataDictionaryName",
        "CodingDictionary",
        "ControlType",
    },
    "Folders": {"OID", "FolderName", "ParentFolderOID"},
    "DataDictionaryEntries": {"DataDictionaryName", "CodedData", "UserDataString"},
    "Checks": {"CheckName", "CheckActive", "Infix"},
}


@dataclass(slots=True)
class ParsedWorkbook:
    filename: str
    entities: dict[str, list[dict[str, str]]]
    matrix_forms: list[str]
    matrix_folders: list[str]
    matrix_cells: list[tuple[str, str, str]]
    counts: dict[str, int]
    warnings: list[str] = field(default_factory=list)


def _clean(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    return str(value).strip()


def _clean_boolean(value: object) -> str:
    cleaned = _clean(value)
    normalized = cleaned.upper()
    if normalized in {"TRUE", "1", "YES"}:
        return "TRUE"
    if normalized in {"FALSE", "0", "NO"}:
        return "FALSE"
    return cleaned


def _read_source(source: bytes | bytearray | BinaryIO | str | Path) -> bytes | str | Path:
    if isinstance(source, (str, Path)):
        return source
    if isinstance(source, (bytes, bytearray)):
        return bytes(source)
    return source.read()


def parse_als_workbook(
    source: bytes | bytearray | BinaryIO | str | Path,
    filename: str | None = None,
) -> ParsedWorkbook:
    raw_source = _read_source(source)
    inferred_name = filename or (Path(raw_source).name if isinstance(raw_source, (str, Path)) else "upload.xlsx")
    if Path(inferred_name).suffix.lower() != ".xlsx":
        raise WorkbookValidationError("Only .xlsx workbooks are supported; .xls and other file types are not accepted.")
    if isinstance(raw_source, bytes) and not raw_source:
        raise WorkbookValidationError("The uploaded workbook is empty.")

    excel_source = BytesIO(raw_source) if isinstance(raw_source, bytes) else raw_source
    try:
        book = pd.ExcelFile(excel_source, engine="openpyxl")
    except Exception as exc:  # pandas/openpyxl expose several format-specific errors
        raise WorkbookValidationError("The file could not be opened as a valid .xlsx workbook.") from exc

    sheet_names = list(book.sheet_names)
    missing_sheets = [name for name in REQUIRED_SHEETS if name not in sheet_names]
    if missing_sheets:
        raise WorkbookValidationError(f"Missing required sheet(s): {', '.join(missing_sheets)}.")

    master_sheets = [name for name in sheet_names if "MASTERDASH" in name.upper()]
    if not master_sheets:
        raise WorkbookValidationError("No MASTERDASH worksheet was found for CRF Book.")

    entities: dict[str, list[dict[str, str]]] = {}
    counts: dict[str, int] = {}
    warnings: list[str] = []
    if len(master_sheets) > 1:
        warnings.append(
            f"Multiple MASTERDASH worksheets were found; {master_sheets[0]} was used."
        )

    for sheet in REQUIRED_SHEETS:
        frame = pd.read_excel(book, sheet_name=sheet, dtype=str, keep_default_na=False)
        available = {str(column).strip() for column in frame.columns}
        missing_columns = sorted(REQUIRED_COLUMNS[sheet] - available)
        if missing_columns:
            raise WorkbookValidationError(
                f"Sheet {sheet} is missing required column(s): {', '.join(missing_columns)}."
            )

        canonical = pd.DataFrame()
        for column in CANONICAL_COLUMNS[sheet]:
            cleaner = _clean_boolean if column in BOOLEAN_COLUMNS.get(sheet, set()) else _clean
            aliases = COLUMN_ALIASES.get(sheet, {}).get(column, (column,))
            source_column = next((alias for alias in aliases if alias in frame.columns), None)
            canonical[column] = frame[source_column].map(cleaner) if source_column else ""
        keys = ENTITY_KEYS[sheet]
        required_keys = keys if sheet == "Fields" else keys[:1]
        valid_rows = canonical[list(required_keys)].ne("").all(axis=1)
        skipped_count = int((~valid_rows).sum())
        canonical = canonical[valid_rows].copy()
        if skipped_count:
            key_label = " + ".join(required_keys)
            warnings.append(f"{sheet}: skipped {skipped_count} row(s) with an empty {key_label}.")
        records = canonical.to_dict(orient="records")
        entities[sheet] = records
        counts[sheet] = len(records)

        duplicate_count = int(canonical.duplicated(subset=list(keys), keep=False).sum())
        if duplicate_count:
            key_label = " + ".join(keys)
            warnings.append(f"{sheet}: {duplicate_count} rows share a {key_label} value; all rows were preserved.")

    matrix = pd.read_excel(book, sheet_name=master_sheets[0], dtype=str, keep_default_na=False)
    if len(matrix.columns) < 3:
        raise WorkbookValidationError("The MASTERDASH worksheet must include FormOID, Subject, and at least one FolderOID column.")

    form_column = matrix.columns[0]
    folder_columns = [str(column).strip() for column in matrix.columns[2:]]
    if any(not folder for folder in folder_columns):
        raise WorkbookValidationError("The MASTERDASH worksheet contains an empty FolderOID header.")
    if len(folder_columns) != len(set(folder_columns)):
        raise WorkbookValidationError("The MASTERDASH worksheet contains duplicate FolderOID headers.")

    matrix_forms: list[str] = []
    matrix_cells: list[tuple[str, str, str]] = []
    for _, row in matrix.iterrows():
        form_oid = _clean(row[form_column])
        if not form_oid:
            continue
        matrix_forms.append(form_oid)
        for raw_column, folder_oid in zip(matrix.columns[2:], folder_columns, strict=True):
            collected = "X" if _clean(row[raw_column]).upper() == "X" else ""
            matrix_cells.append((form_oid, folder_oid, collected))

    counts["CRF_Book"] = len(matrix_forms)
    counts["CRF_BookFolders"] = len(folder_columns)
    counts["CRF_BookCollected"] = sum(1 for _, _, value in matrix_cells if value == "X")

    return ParsedWorkbook(
        filename=inferred_name,
        entities=entities,
        matrix_forms=matrix_forms,
        matrix_folders=folder_columns,
        matrix_cells=matrix_cells,
        counts=counts,
        warnings=warnings,
    )

