from __future__ import annotations

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app.infra.db.models import Node
from app.infra.db.session import get_session_factory
from app.infra.db.types import as_ltree, make_lquery


@pytest.fixture()
def session():
    session_factory = get_session_factory()
    with session_factory() as session:
        yield session
        session.rollback()


def _node(name: str, slug: str, path: str, parent_path: str | None = None) -> Node:
    return Node(
        name=name,
        slug=slug,
        path=path,
        parent_path=parent_path,
        created_by="tester",
        updated_by="tester",
    )


def test_ltree_subtree_query_returns_only_descendants(session):
    root = _node("Root", "root", "root", None)
    child = _node("Child", "child", "root.child", "root")
    grandchild = _node("Grand", "grand", "root.child.grand", "root.child")
    sibling_root = _node("Other", "other", "other", None)
    session.add_all([root, child, grandchild, sibling_root])
    session.commit()

    stmt = text(
        """
        SELECT path::text
        FROM nodes
        WHERE path <@ CAST(:pattern AS lquery)
        ORDER BY path
        """
    )
    paths = [row[0] for row in session.execute(stmt, {"pattern": "root.*{1,}"})]
    assert paths == ["root.child", "root.child.grand"]


def test_ltree_path_uniqueness_enforced(session):
    root = _node("Root", "root", "root", None)
    session.add(root)
    session.commit()

    duplicate = _node("DupRoot", "dup-root", "root", None)
    session.add(duplicate)
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()
