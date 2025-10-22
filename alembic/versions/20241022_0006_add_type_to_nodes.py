"""Add type column to nodes and create index for filtering."""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op  # type: ignore[attr-defined]

# revision identifiers, used by Alembic.
revision = "202410220006"
down_revision = "202410220005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "nodes",
        sa.Column("type", sa.String(length=32), nullable=True),
    )
    op.create_index("ix_nodes_type", "nodes", ["type"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_nodes_type", table_name="nodes")
    op.drop_column("nodes", "type")
