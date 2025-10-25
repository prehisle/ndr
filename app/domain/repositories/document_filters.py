from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Sequence

from sqlalchemy import Float, Text, and_, cast, func, or_
from sqlalchemy.sql import Select

from app.infra.db.models import Document


@dataclass(frozen=True)
class MetadataFilterClause:
    field: str
    operator: str
    values: tuple[str, ...]


MetadataFilters = Sequence[MetadataFilterClause]

SCALAR_OPERATORS = {"eq", "in", "neq", "like"}
RANGE_OPERATORS = {"gt", "gte", "lt", "lte"}
ARRAY_OPERATORS = {"any", "all"}
SUPPORTED_METADATA_OPERATORS = frozenset(
    SCALAR_OPERATORS | RANGE_OPERATORS | ARRAY_OPERATORS
)
LIST_VALUE_OPERATORS = {"in", "any", "all"}


def apply_document_filters(
    stmt: Select,
    *,
    metadata_filters: MetadataFilters | None = None,
    search_query: str | None = None,
) -> Select:
    """Attach metadata filters (equality, range, containment) and fuzzy search."""

    conditions = []
    if metadata_filters:
        for clause in metadata_filters:
            condition = _build_metadata_condition(clause)
            if condition is not None:
                conditions.append(condition)

    if search_query:
        pattern = f"%{search_query}%"
        conditions.append(
            or_(
                Document.title.ilike(pattern),
                cast(Document.content, Text).ilike(pattern),
            )
        )

    if conditions:
        stmt = stmt.where(and_(*conditions))
    return stmt


def _build_metadata_condition(clause: MetadataFilterClause):
    if not clause.values:
        return None

    operator = clause.operator or "eq"
    operator = operator.lower()
    if clause.field == "tags" and operator in {"eq", "in"}:
        return _build_array_condition(clause, match_all=False)
    if operator == "any":
        return _build_array_condition(clause, match_all=False)
    if operator == "all":
        return _build_array_condition(clause, match_all=True)
    if operator == "like":
        return _build_like_condition(clause)
    if operator == "neq":
        return _build_not_equals_condition(clause)
    if operator in RANGE_OPERATORS:
        return _build_numeric_condition(clause)
    # Default to equality/IN matching for scalar text columns
    return _build_equals_condition(clause)


def _build_array_condition(clause: MetadataFilterClause, *, match_all: bool):
    field_expr = Document.metadata_.op("->")(clause.field)
    checks = [func.jsonb_exists(field_expr, value) for value in clause.values]
    if not checks:
        return None
    if len(checks) == 1:
        return checks[0]
    combiner = and_ if match_all else or_
    return combiner(*checks)


def _build_like_condition(clause: MetadataFilterClause):
    value_expr = cast(Document.metadata_.op("->>")(clause.field), Text)
    checks = []
    for value in clause.values:
        pattern = value if any(ch in value for ch in ("%", "_")) else f"%{value}%"
        checks.append(value_expr.ilike(pattern))
    if not checks:
        return None
    if len(checks) == 1:
        return checks[0]
    return or_(*checks)


def _build_not_equals_condition(clause: MetadataFilterClause):
    value_expr = cast(Document.metadata_.op("->>")(clause.field), Text)
    checks = [value_expr != value for value in clause.values]
    if not checks:
        return None
    if len(checks) == 1:
        return checks[0]
    return and_(*checks)


def _build_numeric_condition(clause: MetadataFilterClause):
    if len(clause.values) != 1:
        raise ValueError("Range operator expects a single comparison value")
    numeric_value = _parse_numeric_value(clause.values[0])
    numeric_expr = cast(Document.metadata_.op("->>")(clause.field), Float)
    match clause.operator:
        case "gt":
            return numeric_expr > numeric_value
        case "gte":
            return numeric_expr >= numeric_value
        case "lt":
            return numeric_expr < numeric_value
        case "lte":
            return numeric_expr <= numeric_value
    raise ValueError(f"Unsupported numeric operator: {clause.operator}")


def _build_equals_condition(clause: MetadataFilterClause):
    if clause.operator == "in":
        value_expr = cast(Document.metadata_.op("->>")(clause.field), Text)
        return value_expr.in_(clause.values)

    value_expr = cast(Document.metadata_.op("->>")(clause.field), Text)
    checks = [value_expr == value for value in clause.values]
    if not checks:
        return None
    if len(checks) == 1:
        return checks[0]
    return or_(*checks)


def _parse_numeric_value(value: str) -> float:
    try:
        return float(Decimal(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("Numeric comparison requires a valid number") from exc
