"""Asset repository for data access operations.

This module provides the data access layer for Asset entities,
handling database queries and persistence operations.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.infra.db.models import Asset


class AssetRepository:
    """Repository for Asset entity database operations."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, asset_id: int) -> Asset | None:
        """Get an asset by ID.

        Args:
            asset_id: The asset's primary key.

        Returns:
            The Asset if found, None otherwise.
        """
        return self._session.get(Asset, asset_id)

    def paginate_assets(
        self,
        page: int,
        size: int,
        include_deleted: bool,
        *,
        deleted_only: bool = False,
        search_query: str | None = None,
        status: str | None = None,
    ) -> tuple[list[Asset], int]:
        """Paginate assets with optional filters.

        Args:
            page: Page number (1-based).
            size: Number of items per page.
            include_deleted: Include soft-deleted assets.
            deleted_only: Only return soft-deleted assets.
            search_query: Optional filename search pattern.
            status: Optional status filter.

        Returns:
            Tuple of (list of assets, total count).
        """
        base_stmt = select(Asset)
        count_stmt = select(func.count()).select_from(Asset)

        # Apply deletion filter
        if deleted_only:
            base_stmt = base_stmt.where(Asset.deleted_at.is_not(None))
            count_stmt = count_stmt.where(Asset.deleted_at.is_not(None))
        elif not include_deleted:
            base_stmt = base_stmt.where(Asset.deleted_at.is_(None))
            count_stmt = count_stmt.where(Asset.deleted_at.is_(None))

        # Apply status filter
        if status is not None:
            base_stmt = base_stmt.where(Asset.status == status)
            count_stmt = count_stmt.where(Asset.status == status)

        # Apply search filter
        if search_query:
            pattern = f"%{search_query}%"
            base_stmt = base_stmt.where(Asset.filename.ilike(pattern))
            count_stmt = count_stmt.where(Asset.filename.ilike(pattern))

        # Order and paginate
        base_stmt = base_stmt.order_by(Asset.created_at.desc(), Asset.id.desc())
        base_stmt = base_stmt.offset((page - 1) * size).limit(size)

        items = list(self._session.execute(base_stmt).scalars())
        total = self._session.execute(count_stmt).scalar_one()

        return items, total
