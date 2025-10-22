from __future__ import annotations

from typing import Mapping, Sequence

from sqlalchemy import Text, and_, cast, func, or_
from sqlalchemy.sql import Select

from app.infra.db.models import Document

MetadataFilters = Mapping[str, Sequence[str]]


def apply_document_filters(
    stmt: Select,
    *,
    metadata_filters: MetadataFilters | None = None,
    search_query: str | None = None,
) -> Select:
    """Attach metadata and fuzzy-search filters to the given statement."""

    conditions = []
    if metadata_filters:
        for raw_key, values in metadata_filters.items():
            key = raw_key.strip()
            if not key or not values:
                continue
            if key == "tags":
                tags_expr = Document.metadata_.op("->")("tags")
                tag_checks = [func.jsonb_exists(tags_expr, value) for value in values]
                if tag_checks:
                    conditions.append(or_(*tag_checks))
                continue

            value_expr = cast(
                Document.metadata_.op("->>")(key),
                Text,
            )
            value_checks = [value_expr == value for value in values]
            if value_checks:
                conditions.append(or_(*value_checks))

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
