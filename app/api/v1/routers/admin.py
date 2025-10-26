from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.api.v1.deps import get_db, require_admin_key
from app.infra.db.models import IdempotencyRecord


router = APIRouter(dependencies=[Depends(require_admin_key)])


@router.post("/admin/idempotency/cleanup")
def cleanup_idempotency(
    db: Session = Depends(get_db), hours: int | None = Query(default=None, ge=0)
):
    now = datetime.now(timezone.utc)
    threshold = now if hours is None else now - timedelta(hours=hours)
    to_delete = (
        db.query(IdempotencyRecord).filter(IdempotencyRecord.expires_at <= threshold)
    )
    count = to_delete.count()
    if count:
        db.execute(delete(IdempotencyRecord).where(IdempotencyRecord.expires_at <= threshold))
        db.commit()
    return {"deleted": int(count), "threshold": threshold.isoformat()}

