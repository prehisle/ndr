"""Add parent_id column to nodes for explicit parent linkage."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op  # type: ignore[attr-defined]

# revision identifiers, used by Alembic.
revision = "202410210003"
down_revision = "202410200002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "nodes",
        sa.Column("parent_id", sa.BigInteger(), nullable=True),
    )
    op.create_foreign_key(
        "fk_nodes_parent_id", "nodes", "nodes", ["parent_id"], ["id"], ondelete="SET NULL"
    )
    op.create_index("ix_nodes_parent_id", "nodes", ["parent_id"])

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(
            sa.text(
                "UPDATE nodes AS child "
                "SET parent_id = parent.id "
                "FROM nodes AS parent "
                "WHERE child.parent_path = parent.path::text"
            )
        )
    else:
        op.execute(
            sa.text(
                "UPDATE nodes SET parent_id = ("
                "SELECT parent.id FROM nodes AS parent "
                "WHERE parent.path = nodes.parent_path "
                "LIMIT 1)"
            )
        )


def downgrade() -> None:
    op.drop_index("ix_nodes_parent_id", table_name="nodes")
    op.drop_constraint("fk_nodes_parent_id", "nodes", type_="foreignkey")
    op.drop_column("nodes", "parent_id")
