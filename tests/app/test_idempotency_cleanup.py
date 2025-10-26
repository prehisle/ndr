from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.infra.db.models import IdempotencyRecord
from app.infra.db.session import get_session_factory
from scripts.cleanup_idempotency import cleanup_idempotency


def _session() -> Session:
    session_factory = get_session_factory()
    return session_factory()


def test_cleanup_idempotency_deletes_only_expired():
    with _session() as s:
        now = datetime.now(timezone.utc)
        s.add_all(
            [
                IdempotencyRecord(
                    key="k1",
                    request_hash="h1",
                    status_code=200,
                    response_body={"ok": True},
                    expires_at=now - timedelta(hours=1),
                ),
                IdempotencyRecord(
                    key="k2",
                    request_hash="h2",
                    status_code=201,
                    response_body={"ok": True},
                    expires_at=now + timedelta(hours=1),
                ),
            ]
        )
        s.commit()

    # dry-run 统计
    would_delete = cleanup_idempotency(dry_run=True)
    assert would_delete == 1

    # 实际删除过期 1 条
    deleted = cleanup_idempotency()
    assert deleted == 1

    # 再次运行应为 0
    again = cleanup_idempotency(dry_run=True)
    assert again == 0

