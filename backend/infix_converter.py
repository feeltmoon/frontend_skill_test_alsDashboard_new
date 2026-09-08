from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import yaml


CONVERTER_VERSION = "8"

CANONICAL_OPERATOR_NAMES = (
    "GreaterThanOrEqualTo",
    "LessThanOrEqualTo",
    "IsNotEqualTo",
    "GreaterThan",
    "LessThan",
    "IsNotEmpty",
    "IsEqualTo",
    "IsEmpty",
    "DoesNotStartWith",
    "StartsWith",
    "DoesNotContain",
    "Contains",
    "NotIn",
    "In",
)
SOURCE_OPERATOR_MAP = {
    **{value.casefold(): value for value in CANONICAL_OPERATOR_NAMES},
    "isgreaterthan": "GreaterThan",
    "isgreaterthanorequalto": "GreaterThanOrEqualTo",
    "islessthan": "LessThan",
    "islessthanorequalto": "LessThanOrEqualTo",
    "ispresent": "IsPresent",
}
SOURCE_OPERATORS = tuple(
    sorted(SOURCE_OPERATOR_MAP, key=len, reverse=True)
)
UNARY_OPERATORS = {"IsEmpty", "IsNotEmpty", "IsPresent"}
NEGATED_OPERATORS = {
    "Contains": "DoesNotContain",
    "DoesNotContain": "Contains",
    "StartsWith": "DoesNotStartWith",
    "DoesNotStartWith": "StartsWith",
    "IsEqualTo": "IsNotEqualTo",
    "IsNotEqualTo": "IsEqualTo",
    "IsEmpty": "IsNotEmpty",
    "IsNotEmpty": "IsEmpty",
    "In": "NotIn",
    "NotIn": "In",
    "GreaterThan": "LessThanOrEqualTo",
    "GreaterThanOrEqualTo": "LessThan",
    "LessThan": "GreaterThanOrEqualTo",
    "LessThanOrEqualTo": "GreaterThan",
}
OPERATOR_PATTERN = re.compile(
    rf"\b({'|'.join(re.escape(value) for value in SOURCE_OPERATORS)})\b",
    re.IGNORECASE,
)
OPERATOR_LIKE_PATTERN = re.compile(
    r"\b(Is[A-Z][A-Za-z0-9]*|[A-Z][A-Za-z0-9]*(?:With|Than|To|Contains?))\b"
)
POSITION_PATTERN = re.compile(
    r"\s+(?:with|and)\s+"
    r"(record position|form repeat number|folder repeat number)\s+"
    r"(-?\d+|\.\.\.)",
    re.IGNORECASE,
)
MISSING_POSITION_SEPARATOR_PATTERN = re.compile(
    r"(?P<position>-?\d+|\.\.\.)(?P<connector>and\s+"
    r"(?:form|folder)\s+repeat\s+number\b)",
    re.IGNORECASE,
)
ARITHMETIC_FUNCTIONS = (
    "AddMonth",
    "AddYear",
    "AddHour",
    "AddDay",
    "AddSec",
    "AddMin",
)
ARITHMETIC_FUNCTION_MAP = {
    value.casefold(): value for value in ARITHMETIC_FUNCTIONS
}
ARITHMETIC_FUNCTION_PATTERN = re.compile(
    rf"\s+({'|'.join(ARITHMETIC_FUNCTIONS)})\s+"
    r"(-?\d+(?:\.\d+)?)\s*$",
    re.IGNORECASE,
)
ARITHMETIC_OPERAND_PARENTHESES_PATTERN = re.compile(
    rf"\(([^()]*(?:{'|'.join(ARITHMETIC_FUNCTIONS)})\s+"
    r"-?\d+(?:\.\d+)?\s*)\)",
    re.IGNORECASE,
)


class _FlowSequence(list[Any]):
    pass


class _QuotedString(str):
    pass


class _ReadableYamlDumper(yaml.SafeDumper):
    def increase_indent(
        self,
        flow: bool = False,
        indentless: bool = False,
    ) -> None:
        return super().increase_indent(flow, indentless=False)


def _represent_flow_sequence(
    dumper: _ReadableYamlDumper,
    value: _FlowSequence,
) -> yaml.SequenceNode:
    return dumper.represent_sequence(
        "tag:yaml.org,2002:seq",
        value,
        flow_style=True,
    )


def _represent_quoted_string(
    dumper: _ReadableYamlDumper,
    value: _QuotedString,
) -> yaml.ScalarNode:
    return dumper.represent_scalar(
        "tag:yaml.org,2002:str",
        str(value),
        style='"',
    )


_ReadableYamlDumper.add_representer(_FlowSequence, _represent_flow_sequence)
_ReadableYamlDumper.add_representer(_QuotedString, _represent_quoted_string)


@dataclass(slots=True)
class Diagnostic:
    code: str
    severity: str
    message: str
    source_start: int
    source_end: int
    source_text: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "severity": self.severity,
            "message": self.message,
            "source_start": self.source_start,
            "source_end": self.source_end,
            "source_text": self.source_text,
        }


@dataclass(slots=True)
class ConversionResult:
    status: str
    ast: dict[str, Any] | None
    yaml_text: str | None
    diagnostics: list[Diagnostic] = field(default_factory=list)


@dataclass(slots=True)
class MetadataIndex:
    form_name_to_oids: dict[str, list[str]]
    folder_name_to_oids: dict[str, list[str]]
    field_to_forms: dict[str, list[str]]

    @classmethod
    def from_records(
        cls,
        forms: list[dict[str, str]],
        fields: list[dict[str, str]],
        folders: list[dict[str, str]],
    ) -> MetadataIndex:
        form_name_to_oids: dict[str, list[str]] = {}
        folder_name_to_oids: dict[str, list[str]] = {}
        field_to_forms: dict[str, list[str]] = {}

        for row in forms:
            label = row.get("DraftFormName", "").strip().casefold()
            oid = row.get("OID", "").strip()
            if label and oid and oid not in form_name_to_oids.setdefault(label, []):
                form_name_to_oids[label].append(oid)

        for row in folders:
            label = row.get("FolderName", "").strip().casefold()
            oid = row.get("OID", "").strip()
            if label and oid and oid not in folder_name_to_oids.setdefault(label, []):
                folder_name_to_oids[label].append(oid)

        for row in fields:
            field_oid = row.get("FieldOID", "").strip()
            form_oid = row.get("FormOID", "").strip()
            if field_oid and form_oid and form_oid not in field_to_forms.setdefault(field_oid, []):
                field_to_forms[field_oid].append(form_oid)

        return cls(
            form_name_to_oids=form_name_to_oids,
            folder_name_to_oids=folder_name_to_oids,
            field_to_forms=field_to_forms,
        )


@dataclass(slots=True)
class BooleanToken:
    kind: str
    value: str
    start: int
    end: int


def _diagnostic(
    diagnostics: list[Diagnostic],
    code: str,
    message: str,
    source_text: str,
    start: int = 0,
    end: int | None = None,
    severity: str = "error",
) -> None:
    diagnostics.append(
        Diagnostic(
            code=code,
            severity=severity,
            message=message,
            source_start=start,
            source_end=len(source_text) if end is None else end,
            source_text=source_text[start:end],
        )
    )


def _normalize_arithmetic_operand_parentheses(
    expression: str,
    diagnostics: list[Diagnostic],
) -> str:
    def replace(match: re.Match[str]) -> str:
        content = match.group(1)
        contains_comparison = any(
            operator.group(1).casefold() != "in"
            for operator in OPERATOR_PATTERN.finditer(content)
        )
        contains_boolean = bool(
            re.search(r"\b(?:And|Or|Not)\b", content, re.IGNORECASE)
        )
        if contains_comparison or contains_boolean:
            return match.group(0)

        following = expression[match.end() :]
        glued_operator = re.match(
            r"(Is(?:GreaterThanOrEqualTo|LessThanOrEqualTo|NotEqualTo|"
            r"GreaterThan|LessThan|EqualTo))\b",
            following,
            re.IGNORECASE,
        )
        if glued_operator is not None:
            _diagnostic(
                diagnostics,
                "normalized_operator_separator",
                "Inserted a missing space after an arithmetic operand.",
                f"){glued_operator.group(1)}",
                severity="warning",
            )
        return f" {content.strip()} "

    previous = expression
    while True:
        normalized = ARITHMETIC_OPERAND_PARENTHESES_PATTERN.sub(replace, previous)
        if normalized == previous:
            return normalized
        previous = normalized


def _tokenize_boolean(expression: str, diagnostics: list[Diagnostic]) -> list[BooleanToken]:
    tokens: list[BooleanToken] = []
    buffer_start = 0
    quote_open = False
    index = 0

    def flush(end: int) -> None:
        nonlocal buffer_start
        value = expression[buffer_start:end].strip()
        if value:
            leading = len(expression[buffer_start:end]) - len(expression[buffer_start:end].lstrip())
            start = buffer_start + leading
            tokens.append(BooleanToken("TEXT", value, start, end))
        buffer_start = end

    while index < len(expression):
        character = expression[index]
        if character == '"':
            quote_open = not quote_open
            index += 1
            continue

        if not quote_open and character in "()":
            flush(index)
            tokens.append(
                BooleanToken("LPAREN" if character == "(" else "RPAREN", character, index, index + 1)
            )
            index += 1
            buffer_start = index
            continue

        if not quote_open:
            connector = None
            for candidate in ("And", "Or", "Not", "AND", "OR", "NOT"):
                end = index + len(candidate)
                if expression[index:end] != candidate:
                    continue
                before_ok = index == 0 or not expression[index - 1].isalnum()
                after_ok = end == len(expression) or not expression[end].isalnum()
                prefix = expression[buffer_start:index]
                if candidate.upper() == "NOT":
                    unary_position = not prefix.strip() and (
                        not tokens
                        or tokens[-1].kind in {"LPAREN", "AND", "OR"}
                    )
                    if before_ok and after_ok and unary_position:
                        connector = "NOT"
                        break
                    continue
                previous_group = bool(tokens and tokens[-1].kind == "RPAREN" and not prefix.strip())
                operator_matches = list(OPERATOR_PATTERN.finditer(prefix))
                predicate_complete = any(
                    match.group(1).casefold() != "in" for match in operator_matches
                ) or len(operator_matches) >= 3
                if before_ok and after_ok and (previous_group or predicate_complete):
                    connector = candidate.upper()
                    break
            if connector:
                flush(index)
                end = index + len(connector)
                tokens.append(BooleanToken(connector, expression[index:end], index, end))
                index = end
                buffer_start = index
                continue

        index += 1

    flush(len(expression))
    if quote_open:
        _diagnostic(
            diagnostics,
            "unsupported_token",
            "The condition contains an unmatched quote.",
            expression,
        )
    return tokens


def _detect_ambiguous_boolean_groups(
    tokens: list[BooleanToken],
    diagnostics: list[Diagnostic],
) -> None:
    def inspect(start: int, stop: int) -> None:
        depth = 0
        connectors: set[str] = set()
        index = start
        while index < stop:
            token = tokens[index]
            if token.kind == "LPAREN":
                if depth == 0:
                    nested_start = index + 1
                    nested_depth = 1
                    nested_end = nested_start
                    while nested_end < stop and nested_depth:
                        if tokens[nested_end].kind == "LPAREN":
                            nested_depth += 1
                        elif tokens[nested_end].kind == "RPAREN":
                            nested_depth -= 1
                        nested_end += 1
                    inspect(nested_start, max(nested_start, nested_end - 1))
                    index = nested_end
                    continue
                depth += 1
            elif token.kind == "RPAREN":
                depth = max(0, depth - 1)
            elif depth == 0 and token.kind in {"AND", "OR"}:
                connectors.add(token.kind)
            index += 1

        if connectors == {"AND", "OR"}:
            source = " ".join(token.value for token in tokens[start:stop])
            _diagnostic(
                diagnostics,
                "ambiguous_boolean_precedence",
                "Mixed AND and OR operators require explicit grouping.",
                source,
            )

    inspect(0, len(tokens))


class ConditionParser:
    def __init__(
        self,
        tokens: list[BooleanToken],
        metadata: MetadataIndex,
        diagnostics: list[Diagnostic],
    ) -> None:
        self.tokens = tokens
        self.metadata = metadata
        self.diagnostics = diagnostics
        self.position = 0

    def parse(self) -> dict[str, Any] | None:
        if not self.tokens:
            _diagnostic(
                self.diagnostics,
                "unsupported_token",
                "The rule does not contain a condition.",
                "",
            )
            return None
        node = self._parse_or()
        if self.position < len(self.tokens):
            token = self.tokens[self.position]
            _diagnostic(
                self.diagnostics,
                "unsupported_token",
                "Unexpected content remains after the parsed condition.",
                token.value,
            )
        return node

    def _parse_or(self) -> dict[str, Any] | None:
        left = self._parse_and()
        while self._accept("OR"):
            right = self._parse_and()
            left = {"kind": "any", "children": [left, right]}
        return left

    def _parse_and(self) -> dict[str, Any] | None:
        left = self._parse_primary()
        while self._accept("AND"):
            right = self._parse_primary()
            left = {"kind": "all", "children": [left, right]}
        return left

    def _parse_primary(self) -> dict[str, Any] | None:
        if self._accept("NOT"):
            node = self._parse_primary()
            if node is None:
                return None
            if node.get("kind") != "predicate":
                _diagnostic(
                    self.diagnostics,
                    "unsupported_operator",
                    "Not can currently negate one predicate, not a Boolean group.",
                    "Not",
                )
                return None
            operator = node.get("operator")
            negated_operator = NEGATED_OPERATORS.get(operator)
            if negated_operator is None:
                _diagnostic(
                    self.diagnostics,
                    "unsupported_operator",
                    f'Operator "{operator}" does not have a supported negated form.',
                    f"Not {operator}",
                )
                return None
            return {**node, "operator": negated_operator}

        if self._accept("LPAREN"):
            node = self._parse_or()
            if not self._accept("RPAREN"):
                _diagnostic(
                    self.diagnostics,
                    "unbalanced_parentheses",
                    "A condition group is missing its closing parenthesis.",
                    self.tokens[self.position - 1].value if self.position else "",
                )
            return node

        token = self._current()
        if token is None or token.kind != "TEXT":
            source = token.value if token else ""
            _diagnostic(
                self.diagnostics,
                "unsupported_token",
                "Expected a condition predicate.",
                source,
            )
            if token is not None:
                self.position += 1
            return None

        self.position += 1
        return _parse_predicate(token.value, self.metadata, self.diagnostics)

    def _current(self) -> BooleanToken | None:
        return self.tokens[self.position] if self.position < len(self.tokens) else None

    def _accept(self, kind: str) -> bool:
        token = self._current()
        if token is None or token.kind != kind:
            return False
        self.position += 1
        return True


def _parse_scalar(value: str) -> Any:
    cleaned = value.strip()
    if len(cleaned) >= 2 and cleaned[0] == cleaned[-1] == '"':
        return cleaned[1:-1].replace(r"\"", '"')
    if re.fullmatch(r"-?\d+", cleaned):
        return int(cleaned)
    if re.fullmatch(r"-?\d+\.\d+", cleaned):
        return float(cleaned)
    if cleaned.casefold() == "true":
        return True
    if cleaned.casefold() == "false":
        return False
    if cleaned.startswith("[") and cleaned.endswith("]"):
        return [_parse_scalar(part) for part in cleaned[1:-1].split(",") if part.strip()]
    return cleaned


def _parse_positions(
    datapoint_text: str,
    diagnostics: list[Diagnostic],
) -> tuple[str, dict[str, str]]:
    malformed_separator = MISSING_POSITION_SEPARATOR_PATTERN.search(datapoint_text)
    normalized_text = datapoint_text
    if malformed_separator is not None:
        _diagnostic(
            diagnostics,
            "normalized_position_separator",
            'Inserted a missing space before the repeat-position "and" clause.',
            malformed_separator.group(0),
            severity="warning",
        )
        normalized_text = MISSING_POSITION_SEPARATOR_PATTERN.sub(
            r"\g<position> \g<connector>",
            datapoint_text,
        )

    positions = {
        "record position": "...",
        "form repeat number": "...",
        "folder repeat number": "...",
    }
    for match in POSITION_PATTERN.finditer(normalized_text):
        positions[match.group(1).casefold()] = match.group(2)
    cleaned = POSITION_PATTERN.sub("", normalized_text).strip()
    return cleaned, positions


def _resolve_datapoint(
    datapoint_text: str,
    metadata: MetadataIndex,
    diagnostics: list[Diagnostic],
) -> str | None:
    cleaned, positions = _parse_positions(datapoint_text, diagnostics)
    parts = [part.strip() for part in re.split(r"\s+in\s+", cleaned, maxsplit=2, flags=re.IGNORECASE)]
    if len(parts) < 2 or not parts[0] or not parts[1]:
        _diagnostic(
            diagnostics,
            "unsupported_token",
            "A datapoint must include a FieldOID and form label.",
            datapoint_text,
        )
        return None

    field_oid = parts[0]
    form_label = parts[1]
    folder_label = parts[2] if len(parts) == 3 else ""

    form_candidates = list(metadata.form_name_to_oids.get(form_label.casefold(), []))
    if not form_candidates:
        _diagnostic(
            diagnostics,
            "unresolved_form_label",
            f'Form label "{form_label}" could not be resolved.',
            form_label,
        )
        return None

    field_forms = metadata.field_to_forms.get(field_oid, [])
    valid_form_candidates = [oid for oid in form_candidates if oid in field_forms]
    if len(valid_form_candidates) == 1:
        form_oid = valid_form_candidates[0]
    elif len(form_candidates) == 1:
        form_oid = form_candidates[0]
        if form_oid not in field_forms:
            code = "field_not_found" if not field_forms else "field_form_mismatch"
            _diagnostic(
                diagnostics,
                code,
                f'FieldOID "{field_oid}" is not defined under FormOID "{form_oid}".',
                datapoint_text,
            )
            return None
    else:
        _diagnostic(
            diagnostics,
            "ambiguous_form_label",
            f'Form label "{form_label}" resolves to multiple FormOIDs.',
            form_label,
        )
        return None

    record = positions["record position"]
    form_repeat = positions["form repeat number"]
    folder_repeat = positions["folder repeat number"]
    position_suffix = f"({record}|{form_repeat}|{folder_repeat})"

    if not folder_label:
        return f"{form_oid}.{field_oid}{position_suffix}"

    folder_candidates = metadata.folder_name_to_oids.get(folder_label.casefold(), [])
    if not folder_candidates:
        _diagnostic(
            diagnostics,
            "unresolved_folder_label",
            f'Folder label "{folder_label}" could not be resolved.',
            folder_label,
        )
        return None
    if len(folder_candidates) > 1:
        _diagnostic(
            diagnostics,
            "ambiguous_folder_label",
            f'Folder label "{folder_label}" resolves to multiple FolderOIDs.',
            folder_label,
        )
        return None

    return f"{folder_candidates[0]}.{form_oid}.{field_oid}{position_suffix}"


def _parse_operand(
    operand_text: str,
    metadata: MetadataIndex,
    diagnostics: list[Diagnostic],
) -> dict[str, Any] | None:
    function_match = ARITHMETIC_FUNCTION_PATTERN.search(operand_text)
    datapoint_text = operand_text
    transform: dict[str, Any] | None = None
    if function_match is not None:
        datapoint_text = operand_text[: function_match.start()].strip()
        transform = {
            "function": ARITHMETIC_FUNCTION_MAP[
                function_match.group(1).casefold()
            ],
            "amount": _parse_scalar(function_match.group(2)),
        }

    datapoint = _resolve_datapoint(datapoint_text, metadata, diagnostics)
    if datapoint is None:
        return None

    operand: dict[str, Any] = {"field": datapoint}
    if transform is not None:
        operand["transform"] = transform
    return operand


def _parse_predicate(
    predicate_text: str,
    metadata: MetadataIndex,
    diagnostics: list[Diagnostic],
) -> dict[str, Any] | None:
    custom_function_match = re.fullmatch(
        r"(.+?)\s+(CF_[A-Za-z0-9_]+)",
        predicate_text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if custom_function_match is not None:
        operand = _parse_operand(
            custom_function_match.group(1).strip(),
            metadata,
            diagnostics,
        )
        if operand is None:
            return None
        return {
            "kind": "predicate",
            **operand,
            "operator": "CustomFunction",
            "function": custom_function_match.group(2),
        }

    unknown_operator = next(
        (
            match
            for match in OPERATOR_LIKE_PATTERN.finditer(predicate_text)
            if match.group(1).casefold() not in SOURCE_OPERATOR_MAP
        ),
        None,
    )
    if unknown_operator is not None:
        _diagnostic(
            diagnostics,
            "unsupported_operator",
            f'Operator "{unknown_operator.group(1)}" is not supported.',
            unknown_operator.group(1),
        )
        return None

    matches = list(OPERATOR_PATTERN.finditer(predicate_text))
    if not matches:
        possible = re.search(r"\b(Is[A-Za-z]+|GreaterThan\w*|LessThan\w*)\b", predicate_text)
        _diagnostic(
            diagnostics,
            "unsupported_operator",
            f'Operator "{possible.group(1) if possible else "unknown"}" is not supported.',
            predicate_text,
        )
        return None

    named_matches = [
        item for item in matches if item.group(1).casefold() != "in"
    ]
    match = named_matches[-1] if named_matches else matches[-1]
    operator = SOURCE_OPERATOR_MAP[match.group(1).casefold()]
    left_operand = _parse_operand(
        predicate_text[: match.start()].strip(),
        metadata,
        diagnostics,
    )
    if left_operand is None:
        return None

    value_text = predicate_text[match.end() :].strip()
    if operator not in UNARY_OPERATORS and not value_text:
        _diagnostic(
            diagnostics,
            "malformed_value",
            f'Operator "{operator}" requires a comparison value.',
            predicate_text,
        )
        return None

    result: dict[str, Any] = {"kind": "predicate", **left_operand, "operator": operator}
    if operator not in UNARY_OPERATORS:
        if re.search(r"\s+in\s+", value_text, re.IGNORECASE):
            right_operand = _parse_operand(value_text, metadata, diagnostics)
            if right_operand is None:
                return None
            result["value"] = (
                right_operand["field"]
                if len(right_operand) == 1
                else right_operand
            )
        else:
            result["value"] = _parse_scalar(value_text)
    return result


def _is_compressible_value(value: Any) -> bool:
    if isinstance(value, (dict, list)):
        return False
    if isinstance(value, str) and re.fullmatch(
        r"[^.\s]+\.[^.\s]+\.[^(]+\([^)]*\)",
        value,
    ):
        return False
    return True


def _fold_predicate_runs(
    kind: str,
    children: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    source_operator = "IsNotEqualTo" if kind == "all" else "IsEqualTo"
    folded_operator = "NotIn" if kind == "all" else "In"
    folded: list[dict[str, Any]] = []
    index = 0

    while index < len(children):
        child = children[index]
        if (
            child.get("kind") != "predicate"
            or child.get("operator") != source_operator
            or "value" not in child
            or not _is_compressible_value(child["value"])
        ):
            folded.append(child)
            index += 1
            continue

        field_name = child.get("field")
        run = [child]
        cursor = index + 1
        while cursor < len(children):
            candidate = children[cursor]
            if (
                candidate.get("kind") != "predicate"
                or candidate.get("field") != field_name
                or candidate.get("operator") != source_operator
                or "value" not in candidate
                or not _is_compressible_value(candidate["value"])
            ):
                break
            run.append(candidate)
            cursor += 1

        if len(run) == 1:
            folded.append(child)
        else:
            values: list[Any] = []
            for predicate in run:
                if predicate["value"] not in values:
                    values.append(predicate["value"])
            folded.append(
                {
                    "kind": "predicate",
                    "field": field_name,
                    "operator": folded_operator,
                    "value": values,
                }
            )
        index = cursor

    return folded


def _flatten_associative_groups(
    node: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if node is None or node["kind"] == "predicate":
        return node

    kind = node["kind"]
    normalized_children: list[dict[str, Any]] = []
    for child in node["children"]:
        normalized = _flatten_associative_groups(child)
        if normalized is None:
            continue
        if normalized["kind"] == kind:
            normalized_children.extend(normalized["children"])
        else:
            normalized_children.append(normalized)

    return {
        "kind": kind,
        "children": normalized_children,
    }


def _compress_predicate_groups(
    node: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if node is None or node["kind"] == "predicate":
        return node
    kind = node["kind"]
    children = [
        normalized
        for child in node["children"]
        if (normalized := _compress_predicate_groups(child)) is not None
    ]
    return {
        "kind": kind,
        "children": _fold_predicate_runs(kind, children),
    }


def _normalize_condition(node: dict[str, Any] | None) -> dict[str, Any] | None:
    return _compress_predicate_groups(_flatten_associative_groups(node))


def _condition_to_output(node: dict[str, Any] | None) -> dict[str, Any] | None:
    if node is None:
        return None
    kind = node["kind"]
    if kind == "predicate":
        return {key: value for key, value in node.items() if key != "kind"}
    output_kind = "all" if kind == "all" else "any"
    return {
        output_kind: [
            _condition_to_output(child)
            for child in node["children"]
            if child is not None
        ]
    }


def _yaml_render_model(value: Any, key: str | None = None) -> Any:
    if isinstance(value, dict):
        return {
            item_key: _yaml_render_model(item_value, item_key)
            for item_key, item_value in value.items()
        }
    if isinstance(value, list):
        rendered = [_yaml_render_model(item) for item in value]
        if key == "value":
            return _FlowSequence(
                _QuotedString(item) if isinstance(item, str) else item
                for item in rendered
            )
        return rendered
    return value


def _space_yaml_condition_blocks(yaml_text: str) -> str:
    output: list[str] = []
    previous_content = ""
    for line in yaml_text.splitlines():
        is_sequence_item = bool(re.match(r"^\s+-\s+", line))
        starts_first_group_item = previous_content.rstrip().endswith(("all:", "any:"))
        if is_sequence_item and previous_content and not starts_first_group_item:
            output.append("")
        output.append(line)
        if line.strip():
            previous_content = line
    return "\n".join(output) + "\n"


def _strip_outer_quotes(value: str) -> str:
    cleaned = value.strip()
    if len(cleaned) >= 2 and cleaned[0] == cleaned[-1] == '"':
        return cleaned[1:-1]
    return cleaned


def _split_action_clauses(action_text: str) -> list[str]:
    """Split Rave's comma-and action list without splitting quoted text/options."""
    clauses: list[str] = []
    start = 0
    depth = 0
    in_quote = False
    escaped = False
    index = 0

    while index < len(action_text):
        character = action_text[index]
        if in_quote:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_quote = False
            index += 1
            continue

        if character == '"':
            in_quote = True
        elif character == "(":
            depth += 1
        elif character == ")" and depth:
            depth -= 1
        elif depth == 0:
            separator = re.match(r",\s+and\s+", action_text[index:], re.IGNORECASE)
            if separator is not None:
                clauses.append(action_text[start:index].strip())
                index += separator.end()
                start = index
                continue
        index += 1

    clauses.append(action_text[start:].strip())
    return [clause for clause in clauses if clause]


def _resolve_form_label(
    form_label: str,
    metadata: MetadataIndex,
    diagnostics: list[Diagnostic],
) -> str | None:
    candidates = metadata.form_name_to_oids.get(form_label.casefold(), [])
    if not candidates:
        _diagnostic(
            diagnostics,
            "unresolved_form_label",
            f'Form label "{form_label}" could not be resolved.',
            form_label,
        )
        return None
    if len(candidates) > 1:
        _diagnostic(
            diagnostics,
            "ambiguous_form_label",
            f'Form label "{form_label}" resolves to multiple FormOIDs.',
            form_label,
        )
        return None
    return candidates[0]


def _parse_open_query_action(
    action_text: str,
    metadata: MetadataIndex,
    diagnostics: list[Diagnostic],
) -> dict[str, Any] | None:
    flags = {
        "requires_response": bool(
            re.search(r"\(\s*requires response\s*\)", action_text, re.IGNORECASE)
        ),
        "requires_manual_close": bool(
            re.search(r"\(\s*requires manual close\s*\)", action_text, re.IGNORECASE)
        ),
    }
    without_flags = re.sub(
        r"\(\s*requires (?:response|manual close)\s*\)",
        "",
        action_text,
        flags=re.IGNORECASE,
    ).strip()
    match = re.fullmatch(
        r"open a query to\s+(.+?)\s+from\s+(.+?)\s+on\s+(.+?)"
        r"\s*,\s*displaying\s+(.+)",
        without_flags,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if match is None:
        return None

    recipient, source, target_text, query_text = (part.strip() for part in match.groups())
    target = _resolve_datapoint(target_text, metadata, diagnostics)
    if target is None:
        return None

    action: dict[str, Any] = {
        "type": "OpenQuery",
        "target": target,
        "source": source,
        "recipient": recipient,
        "text": _strip_outer_quotes(query_text),
    }
    action.update(flags)
    return action


def _parse_action_clause(
    action_text: str,
    metadata: MetadataIndex,
    diagnostics: list[Diagnostic],
) -> dict[str, Any] | None:
    if re.match(r"open a query\b", action_text, re.IGNORECASE):
        diagnostic_start = len(diagnostics)
        action = _parse_open_query_action(action_text, metadata, diagnostics)
        if action is None and len(diagnostics) == diagnostic_start:
            _diagnostic(
                diagnostics,
                "unsupported_action",
                "The OpenQuery action is incomplete or malformed.",
                action_text,
            )
        return action

    visibility_match = re.fullmatch(
        r"set the datapoint used by\s+(.+?)\s+to\s+(Visible|Invisible)"
        r"(?:\s*\(([^)]*)\))?",
        action_text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if visibility_match is not None:
        target_text, visibility, option = (
            part.strip() if part is not None else None
            for part in visibility_match.groups()
        )
        target = _resolve_datapoint(target_text, metadata, diagnostics)
        if target is None:
            return None
        action: dict[str, Any] = {
            "type": "SetDatapointVisibility",
            "target": target,
            "visibility": visibility.capitalize(),
        }
        if option is not None:
            if option.casefold() != "don't enter empty when not visible".casefold():
                _diagnostic(
                    diagnostics,
                    "unsupported_action",
                    f'Visibility option "{option}" is not supported.',
                    option,
                )
                return None
            action["enter_empty_when_not_visible"] = False
        return action

    add_form_match = re.fullmatch(
        r"add the\s+(.+?)\s+form\s+on\s+(.+)",
        action_text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if add_form_match is not None:
        form_label = _strip_outer_quotes(add_form_match.group(1))
        form_oid = _resolve_form_label(form_label, metadata, diagnostics)
        trigger = _resolve_datapoint(add_form_match.group(2).strip(), metadata, diagnostics)
        if form_oid is None or trigger is None:
            return None
        return {
            "type": "AddForm",
            "form": form_oid,
            "trigger": trigger,
        }

    merge_matrix_match = re.fullmatch(
        r"merge the\s+(.+?)\s+matrix\s+on\s+(.+)",
        action_text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if merge_matrix_match is not None:
        matrix_oid = _strip_outer_quotes(merge_matrix_match.group(1))
        trigger = _resolve_datapoint(
            merge_matrix_match.group(2).strip(),
            metadata,
            diagnostics,
        )
        if not matrix_oid or trigger is None:
            return None
        return {
            "type": "MergeMatrix",
            "matrix": matrix_oid,
            "trigger": trigger,
        }

    predicate_diagnostic_start = len(diagnostics)
    predicate = _parse_predicate(action_text, metadata, diagnostics)
    if predicate is not None:
        return {
            "type": "Require",
            "condition": {key: value for key, value in predicate.items() if key != "kind"},
        }
    del diagnostics[predicate_diagnostic_start:]

    action_name = (
        "custom function"
        if re.search(r"custom function", action_text, re.IGNORECASE)
        else action_text[:80].strip()
    )
    _diagnostic(
        diagnostics,
        "unsupported_action",
        f'Action "{action_name}" is not supported by this converter version.',
        action_text,
    )
    return None


def _parse_action(
    action_text: str,
    metadata: MetadataIndex,
    diagnostics: list[Diagnostic],
) -> dict[str, Any] | None:
    clauses = _split_action_clauses(action_text)
    if not clauses:
        _diagnostic(
            diagnostics,
            "missing_action_property",
            "The rule action is empty.",
            action_text,
        )
        return None
    steps = [
        _parse_action_clause(clause, metadata, diagnostics)
        for clause in clauses
    ]
    if any(step is None for step in steps):
        return None
    parsed_steps = [step for step in steps if step is not None]
    if all(step["type"] == "Require" for step in parsed_steps):
        _diagnostic(
            diagnostics,
            "unsupported_action",
            "The action side contains predicates but no supported action.",
            action_text,
        )
        return None
    if len(parsed_steps) == 1:
        return parsed_steps[0]
    return {"type": "Sequence", "steps": parsed_steps}


def _split_rule(infix: str, diagnostics: list[Diagnostic]) -> tuple[str, str] | None:
    match = re.search(r"\s+then\.\.\.\s+", infix, re.IGNORECASE)
    if match is None:
        _diagnostic(
            diagnostics,
            "unsupported_action",
            'The rule does not contain the expected "then..." action delimiter.',
            infix,
        )
        return None
    condition = infix[: match.start()].strip()
    action = infix[match.end() :].strip()
    if re.match(r"^if\b", condition, re.IGNORECASE):
        condition = re.sub(r"^if\b", "", condition, count=1, flags=re.IGNORECASE).strip()
    return condition, action


def convert_infix(
    check_name: str,
    infix: str,
    forms: list[dict[str, str]],
    fields: list[dict[str, str]],
    folders: list[dict[str, str]],
) -> ConversionResult:
    diagnostics: list[Diagnostic] = []
    split = _split_rule(infix, diagnostics)
    if split is None:
        return ConversionResult("error", None, None, diagnostics)

    condition_text, action_text = split
    metadata = MetadataIndex.from_records(forms, fields, folders)
    condition_text = _normalize_arithmetic_operand_parentheses(
        condition_text,
        diagnostics,
    )
    tokens = _tokenize_boolean(condition_text, diagnostics)
    _detect_ambiguous_boolean_groups(tokens, diagnostics)
    condition_node = ConditionParser(tokens, metadata, diagnostics).parse()
    action = _parse_action(action_text, metadata, diagnostics)

    has_errors = any(item.severity == "error" for item in diagnostics)
    if has_errors or condition_node is None or action is None:
        return ConversionResult("error", None, None, diagnostics)

    condition = _condition_to_output(_normalize_condition(condition_node))
    ast = {
        "rule": {
            "name": check_name,
            "condition": condition,
            "action": action,
        }
    }
    yaml_text = yaml.dump(
        _yaml_render_model(ast),
        Dumper=_ReadableYamlDumper,
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
    )
    yaml_text = _space_yaml_condition_blocks(yaml_text)
    status = "warning" if diagnostics else "success"
    return ConversionResult(status, ast, yaml_text, diagnostics)
