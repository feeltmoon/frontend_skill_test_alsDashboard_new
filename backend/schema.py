from __future__ import annotations

from backend.parser import CANONICAL_COLUMNS


BOARD_TO_SHEET = {
    "forms": "Forms",
    "fields": "Fields",
    "folders": "Folders",
    "dictionary-entries": "DataDictionaryEntries",
    "checks": "Checks",
}

BOARD_COLUMNS = {board: CANONICAL_COLUMNS[sheet] for board, sheet in BOARD_TO_SHEET.items()}

BOARD_FILTERS = {
    "forms": ["OID", "DraftFormName"],
    "fields": ["FormOID", "FieldOID", "PreText", "DataDictionaryName", "CodingDictionary", "ControlType"],
    "folders": ["OID", "FolderName", "ParentFolderOID"],
    "dictionary-entries": ["DataDictionaryName", "CodedData", "UserDataString"],
    "checks": ["CheckName", "Infix"],
}

BOARD_ACTIVE_COLUMN = {
    "forms": "DraftFormActive",
    "fields": "DraftFieldActive",
    "checks": "CheckActive",
}

MULTI_VALUE_COLUMNS = {
    "forms": {"OID", "DraftFormName"},
    "fields": {"FormOID", "FieldOID", "PreText", "DataDictionaryName", "CodingDictionary", "ControlType"},
    "folders": {"OID", "FolderName", "ParentFolderOID"},
    "dictionary-entries": {"DataDictionaryName", "CodedData", "UserDataString"},
    "checks": {"CheckName"},
}

FIELD_FIXED_COLUMNS = CANONICAL_COLUMNS["Fields"][:18]

FIELD_OPTIONAL_GROUPS = {
    "Verification": ["SourceDocument", "ReviewGroups"],
    "System Check": ["IsRequired", "QueryNonConformance", "QueryFutureDate"],
    "Record Date": ["CanSetRecordDate", "CanSetDataPageDate", "CanSetInstanceDate", "CanSetSubjectDate"],
    "Restriction": ["ViewRestrictions", "EntryRestrictions"],
}

