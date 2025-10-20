"""Add position column to nodes for explicit ordering."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op  # type: ignore[attr-defined]

# revision identifiers, used by Alembic.
revision = "202410210004"
down_revision = "202410210003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "nodes",
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index(
        "ix_nodes_parent_position",
        "nodes",
        ["parent_id", "position"],
    )

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(
            sa.text(
                "WITH ranked AS ("
                "  SELECT id, ROW_NUMBER() OVER (PARTITION BY parent_id ORDER BY created_at, id) - 1 AS rn "
                "  FROM nodes"
                ") "
                "UPDATE nodes AS n "
                "SET position = ranked.rn "
                "FROM ranked "
                "WHERE n.id = ranked.id"
            )
        )
    else:
        op.execute(
            sa.text(
                "UPDATE nodes SET position = ("
                "  SELECT COUNT(*) FROM nodes AS sibling "
                "  WHERE ("
                "        (nodes.parent_id IS NULL AND sibling.parent_id IS NULL) "
                "     OR (nodes.parent_id IS NOT NULL AND sibling.parent_id = nodes.parent_id)"
                "      ) "
                "    AND (sibling.created_at < nodes.created_at "
                "         OR (sibling.created_at = nodes.created_at AND sibling.id <= nodes.id))"
                ") - 1"
            )
        )

    op.alter_column("nodes", "position", server_default=None)


def downgrade() -> None:
    op.drop_index("ix_nodes_parent_position", table_name="nodes")
    op.drop_column("nodes", "position")
