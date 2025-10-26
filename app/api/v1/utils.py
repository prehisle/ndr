from collections import defaultdict
from decimal import Decimal, InvalidOperation
from typing import DefaultDict

from fastapi import HTTPException, status
from starlette.requests import Request

from app.domain.repositories.document_filters import (
    LIST_VALUE_OPERATORS,
    RANGE_OPERATORS,
    SUPPORTED_METADATA_OPERATORS,
    MetadataFilterClause,
)


def extract_metadata_filters(request: Request) -> list[MetadataFilterClause]:
    """Parse `metadata.*` query params into structured filter clauses."""

    grouped: DefaultDict[tuple[str, str], list[str]] = defaultdict(list)

    for raw_key, raw_value in request.query_params.multi_items():
        if not raw_key.startswith("metadata."):
            continue
        field_expr = raw_key[len("metadata.") :].strip()
        if not field_expr or raw_value in (None, ""):
            continue

        field, operator = _split_field_and_operator(field_expr)
        if not field:
            continue

        if operator not in SUPPORTED_METADATA_OPERATORS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unsupported metadata filter operator '{operator}'",
            )

        grouped[(field, operator)].extend(_normalize_values(raw_value, operator))

    filters: list[MetadataFilterClause] = []
    for (field, operator), values in grouped.items():
        if not values:
            continue
        if operator in RANGE_OPERATORS and len(values) != 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Operator '{operator}' expects exactly one value",
            )
        if operator in RANGE_OPERATORS:
            _validate_numeric(values[0], field)
        filters.append(
            MetadataFilterClause(field=field, operator=operator, values=tuple(values))
        )
    return filters


def _split_field_and_operator(field_expr: str) -> tuple[str, str]:
    if "[" in field_expr and field_expr.endswith("]"):
        field, operator = field_expr[:-1].split("[", 1)
        field = field.strip()
        operator = (operator or "eq").strip().lower() or "eq"
        return field, operator
    return field_expr.strip(), "eq"


def _normalize_values(value: str, operator: str) -> list[str]:
    if operator in LIST_VALUE_OPERATORS and "," in value:
        return [item.strip() for item in value.split(",") if item.strip()]
    return [value]


def _validate_numeric(value: str, field: str) -> None:
    try:
        Decimal(value)
    except (InvalidOperation, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Metadata field '{field}' expects a numeric value for range filters",
        ) from exc
