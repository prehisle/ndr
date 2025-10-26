#!/usr/bin/env python3
"""Clean up expired idempotency records.

Usage:
  .venv/bin/python scripts/cleanup_idempotency.py --dry-run
  .venv/bin/python scripts/cleanup_idempotency.py --hours 24

By default deletes all rows with expires_at <= now(). Use --dry-run to preview.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.infra.db.models import IdempotencyRecord
from app.infra.db.session import get_engine


def cleanup_idempotency(
    *, older_than: timedelta | None = None, dry_run: bool = False
) -> int:
    engine = get_engine()
    now = datetime.now(timezone.utc)
    threshold = now - older_than if older_than else now
    with Session(engine, autoflush=False, autocommit=False) as session:
        cond = IdempotencyRecord.expires_at <= threshold
        total_stmt = select(func.count()).select_from(IdempotencyRecord).where(cond)
        total = session.execute(total_stmt).scalar_one()
        if dry_run or total == 0:
            return int(total)
        session.execute(delete(IdempotencyRecord).where(cond))
        session.commit()
        return int(total)


def main() -> None:
    parser = argparse.ArgumentParser(description="Cleanup expired idempotency records")
    parser.add_argument(
        "--hours",
        type=int,
        default=None,
        help="Delete records expired more than N hours ago (default: now)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only print would-be deleted rows count without deleting",
    )
    args = parser.parse_args()
    older_than = timedelta(hours=args.hours) if args.hours is not None else None
    count = cleanup_idempotency(older_than=older_than, dry_run=args.dry_run)
    if args.dry_run:
        print(f"[DRY-RUN] {count} rows would be deleted")
    else:
        print(f"Deleted {count} rows")


if __name__ == "__main__":
    main()
