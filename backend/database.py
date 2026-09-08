from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from backend.models import StudyStatus
from backend.parser import CANONICAL_COLUMNS, ParsedWorkbook
from backend.schema import (
    BOARD_ACTIVE_COLUMN,
    BOARD_COLUMNS,
    BOARD_FILTERS,
    BOARD_TO_SHEET,
    MULTI_VALUE_COLUMNS,
)


TABLE_BY_SHEET = {
    "CRFDraft": "crf_draft",
    "Forms": "forms",
    "Fields": "fields",
    "Folders": "folders",
    "DataDictionaryEntries": "dictionary_entries",
    "Checks": "checks",
}


def _quoted(identifier: str) -> str:
    return f'"{identifier.replace(chr(34), chr(34) * 2)}"'


class DashboardDatabase:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
        finally:
            connection.close()

    def initialize(self) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS study_metadata (
                    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                    filename TEXT NOT NULL,
                    project TEXT NOT NULL DEFAULT '',
                    draft TEXT NOT NULL DEFAULT '',
                    uploaded_at TEXT NOT NULL,
                    counts_json TEXT NOT NULL,
                    warnings_json TEXT NOT NULL
                )
                """
            )
            metadata_columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(study_metadata)").fetchall()
            }
            if "project" not in metadata_columns:
                connection.execute("ALTER TABLE study_metadata ADD COLUMN project TEXT NOT NULL DEFAULT ''")
            if "draft" not in metadata_columns:
                connection.execute("ALTER TABLE study_metadata ADD COLUMN draft TEXT NOT NULL DEFAULT ''")
            for sheet, table in TABLE_BY_SHEET.items():
                columns = ", ".join(f"{_quoted(column)} TEXT NOT NULL DEFAULT ''" for column in CANONICAL_COLUMNS[sheet])
                connection.execute(
                    f"CREATE TABLE IF NOT EXISTS {_quoted(table)} (row_id INTEGER PRIMARY KEY AUTOINCREMENT, row_order INTEGER NOT NULL, {columns})"
                )
            connection.execute(
                "CREATE TABLE IF NOT EXISTS crf_forms (row_id INTEGER PRIMARY KEY AUTOINCREMENT, form_oid TEXT NOT NULL, row_order INTEGER NOT NULL)"
            )
            connection.execute(
                "CREATE TABLE IF NOT EXISTS crf_folders (row_id INTEGER PRIMARY KEY AUTOINCREMENT, folder_oid TEXT NOT NULL, column_order INTEGER NOT NULL)"
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS crf_cells (
                    row_order INTEGER NOT NULL,
                    column_order INTEGER NOT NULL,
                    collected TEXT NOT NULL DEFAULT ''
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS check_yaml_conversions (
                    check_row_id INTEGER PRIMARY KEY,
                    infix_hash TEXT NOT NULL,
                    converter_version TEXT NOT NULL,
                    status TEXT NOT NULL,
                    ast_json TEXT,
                    yaml_text TEXT,
                    diagnostics_json TEXT NOT NULL DEFAULT '[]',
                    converted_at TEXT NOT NULL
                )
                """
            )
            connection.commit()

    def replace_study(self, parsed: ParsedWorkbook) -> StudyStatus:
        uploaded_at = datetime.now(timezone.utc).isoformat()
        draft_record = next(iter(parsed.entities.get("CRFDraft", [])), {})
        project = draft_record.get("ProjectName", "")
        draft = draft_record.get("DraftName", "")
        with self.connect() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute("DELETE FROM check_yaml_conversions")
                for table in TABLE_BY_SHEET.values():
                    connection.execute(f"DELETE FROM {_quoted(table)}")
                connection.execute("DELETE FROM crf_forms")
                connection.execute("DELETE FROM crf_folders")
                connection.execute("DELETE FROM crf_cells")

                for sheet, records in parsed.entities.items():
                    table = TABLE_BY_SHEET[sheet]
                    columns = CANONICAL_COLUMNS[sheet]
                    quoted_columns = ", ".join(_quoted(column) for column in columns)
                    placeholders = ", ".join("?" for _ in range(len(columns) + 1))
                    sql = f"INSERT INTO {_quoted(table)} (row_order, {quoted_columns}) VALUES ({placeholders})"
                    values = [
                        (row_order, *(record.get(column, "") for column in columns))
                        for row_order, record in enumerate(records)
                    ]
                    connection.executemany(sql, values)

                connection.executemany(
                    "INSERT INTO crf_forms (form_oid, row_order) VALUES (?, ?)",
                    [(value, index) for index, value in enumerate(parsed.matrix_forms)],
                )
                connection.executemany(
                    "INSERT INTO crf_folders (folder_oid, column_order) VALUES (?, ?)",
                    [(value, index) for index, value in enumerate(parsed.matrix_folders)],
                )
                cell_values: list[tuple[int, int, str]] = []
                width = len(parsed.matrix_folders)
                for index, (_, _, collected) in enumerate(parsed.matrix_cells):
                    cell_values.append((index // width, index % width, collected))
                connection.executemany(
                    "INSERT INTO crf_cells (row_order, column_order, collected) VALUES (?, ?, ?)",
                    cell_values,
                )
                connection.execute("DELETE FROM study_metadata")
                connection.execute(
                    "INSERT INTO study_metadata (singleton, filename, project, draft, uploaded_at, counts_json, warnings_json) VALUES (1, ?, ?, ?, ?, ?, ?)",
                    (
                        parsed.filename,
                        project,
                        draft,
                        uploaded_at,
                        json.dumps(parsed.counts),
                        json.dumps(parsed.warnings),
                    ),
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        return StudyStatus(
            ready=True,
            filename=parsed.filename,
            project=project or None,
            draft=draft or None,
            uploaded_at=uploaded_at,
            counts=parsed.counts,
            warnings=parsed.warnings,
        )

    def status(self) -> StudyStatus:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM study_metadata WHERE singleton = 1").fetchone()
        if row is None:
            return StudyStatus(ready=False)
        return StudyStatus(
            ready=True,
            filename=row["filename"],
            project=row["project"] or None,
            draft=row["draft"] or None,
            uploaded_at=row["uploaded_at"],
            counts=json.loads(row["counts_json"]),
            warnings=json.loads(row["warnings_json"]),
        )

    def query_board(
        self,
        board: str,
        filters: dict[str, str],
        active: str,
        page: int,
        page_size: int,
        sort: str,
        direction: str,
        columns: list[str] | None = None,
        all_rows: bool = False,
        exact: bool = False,
    ) -> tuple[list[str], list[dict[str, str]], int]:
        if board not in BOARD_TO_SHEET:
            raise ValueError("Unknown board.")
        allowed_columns = BOARD_COLUMNS[board]
        selected = columns or allowed_columns
        if not selected or any(column not in allowed_columns for column in selected):
            raise ValueError("One or more requested columns are not allowed.")
        if sort not in allowed_columns:
            raise ValueError("Sort column is not allowed.")
        direction = direction.lower()
        if direction not in {"asc", "desc"}:
            raise ValueError("Sort direction must be asc or desc.")

        clauses: list[str] = []
        parameters: list[str | int] = []
        for column, raw_value in filters.items():
            if column not in BOARD_FILTERS[board] or not raw_value.strip():
                continue
            values = [raw_value.strip()]
            if column in MULTI_VALUE_COLUMNS[board]:
                values = [value.strip() for value in raw_value.split(",") if value.strip()]
            if not values:
                continue
            operator = "=" if exact else "LIKE"
            value_clauses = [
                f"LOWER(TRIM({_quoted(column)})) {operator} LOWER(?)" for _ in values
            ]
            clauses.append(f"({' OR '.join(value_clauses)})")
            parameters.extend(values if exact else (f"%{value}%" for value in values))

        active_column = BOARD_ACTIVE_COLUMN.get(board)
        if active_column and active.strip():
            clauses.append(f"UPPER(TRIM({_quoted(active_column)})) = UPPER(?)")
            parameters.append(active.strip())

        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        table = TABLE_BY_SHEET[BOARD_TO_SHEET[board]]
        with self.connect() as connection:
            total = int(connection.execute(f"SELECT COUNT(*) FROM {_quoted(table)}{where}", parameters).fetchone()[0])
            select_sql = ", ".join(_quoted(column) for column in selected)
            hidden_select = 'row_id AS "_check_row_id", ' if board == "checks" else ""
            sql = (
                f"SELECT {hidden_select}{select_sql} FROM {_quoted(table)}{where} "
                f"ORDER BY LOWER({_quoted(sort)}) {direction.upper()}, row_order ASC"
            )
            query_parameters = list(parameters)
            if not all_rows:
                sql += " LIMIT ? OFFSET ?"
                query_parameters.extend([page_size, (page - 1) * page_size])
            rows = [dict(row) for row in connection.execute(sql, query_parameters).fetchall()]
        return selected, rows, total

    @staticmethod
    def _matches(value: str, query: str, exact: bool = False) -> bool:
        terms = [term.strip().casefold() for term in query.split(",") if term.strip()]
        normalized = value.strip().casefold()
        return not terms or any(
            normalized == term if exact else term in normalized for term in terms
        )

    def query_crf_book(
        self,
        form_query: str,
        folder_query: str,
        page: int,
        page_size: int,
        all_rows: bool = False,
        exact: bool = False,
    ) -> tuple[list[str], list[dict[str, str]], int]:
        with self.connect() as connection:
            forms = [dict(row) for row in connection.execute("SELECT form_oid, row_order FROM crf_forms ORDER BY row_order").fetchall()]
            folders = [dict(row) for row in connection.execute("SELECT folder_oid, column_order FROM crf_folders ORDER BY column_order").fetchall()]

            matched_forms = [
                row for row in forms if self._matches(row["form_oid"], form_query, exact)
            ]
            matched_folders = [
                row for row in folders if self._matches(row["folder_oid"], folder_query, exact)
            ]
            if folder_query.strip():
                visible_column_orders = [row["column_order"] for row in matched_folders]
                collected_row_orders: set[int] = set()
                if visible_column_orders:
                    placeholders = ", ".join("?" for _ in visible_column_orders)
                    collected_row_orders = {
                        int(row["row_order"])
                        for row in connection.execute(
                            f"SELECT DISTINCT row_order FROM crf_cells "
                            f"WHERE collected = 'X' AND column_order IN ({placeholders})",
                            visible_column_orders,
                        ).fetchall()
                    }
                matched_forms = [
                    row for row in matched_forms if row["row_order"] in collected_row_orders
                ]
            total = len(matched_forms)
            visible_forms = matched_forms if all_rows else matched_forms[(page - 1) * page_size : page * page_size]
            rows: list[dict[str, str]] = []
            for form in visible_forms:
                result = {"FormOID": form["form_oid"]}
                cells = connection.execute(
                    "SELECT column_order, collected FROM crf_cells WHERE row_order = ?",
                    (form["row_order"],),
                ).fetchall()
                by_column = {cell["column_order"]: cell["collected"] for cell in cells}
                for folder in matched_folders:
                    result[folder["folder_oid"]] = by_column.get(folder["column_order"], "")
                rows.append(result)
        return ["FormOID", *(row["folder_oid"] for row in matched_folders)], rows, total

    def get_check(self, check_row_id: int) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                'SELECT row_id, "CheckName", "Infix" FROM checks WHERE row_id = ?',
                (check_row_id,),
            ).fetchone()
        return dict(row) if row is not None else None

    def get_conversion_metadata(
        self,
    ) -> tuple[list[dict[str, str]], list[dict[str, str]], list[dict[str, str]]]:
        with self.connect() as connection:
            forms = [
                dict(row)
                for row in connection.execute(
                    'SELECT "OID", "DraftFormName" FROM forms ORDER BY row_order'
                ).fetchall()
            ]
            fields = [
                dict(row)
                for row in connection.execute(
                    'SELECT "FormOID", "FieldOID" FROM fields ORDER BY row_order'
                ).fetchall()
            ]
            folders = [
                dict(row)
                for row in connection.execute(
                    'SELECT "OID", "FolderName" FROM folders ORDER BY row_order'
                ).fetchall()
            ]
        return forms, fields, folders

    def get_cached_conversion(
        self,
        check_row_id: int,
        infix_hash: str,
        converter_version: str,
    ) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT *
                FROM check_yaml_conversions
                WHERE check_row_id = ? AND infix_hash = ? AND converter_version = ?
                """,
                (check_row_id, infix_hash, converter_version),
            ).fetchone()
        return dict(row) if row is not None else None

    def save_conversion(
        self,
        *,
        check_row_id: int,
        infix_hash: str,
        converter_version: str,
        status: str,
        ast: dict[str, Any] | None,
        yaml_text: str | None,
        diagnostics: list[dict[str, Any]],
        converted_at: str,
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO check_yaml_conversions (
                    check_row_id,
                    infix_hash,
                    converter_version,
                    status,
                    ast_json,
                    yaml_text,
                    diagnostics_json,
                    converted_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(check_row_id) DO UPDATE SET
                    infix_hash = excluded.infix_hash,
                    converter_version = excluded.converter_version,
                    status = excluded.status,
                    ast_json = excluded.ast_json,
                    yaml_text = excluded.yaml_text,
                    diagnostics_json = excluded.diagnostics_json,
                    converted_at = excluded.converted_at
                """,
                (
                    check_row_id,
                    infix_hash,
                    converter_version,
                    status,
                    json.dumps(ast, ensure_ascii=False) if ast is not None else None,
                    yaml_text,
                    json.dumps(diagnostics, ensure_ascii=False),
                    converted_at,
                ),
            )
            connection.commit()

