from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from fastapi import HTTPException, Request, status
from fastapi.encoders import jsonable_encoder
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.infra.db.models import IdempotencyRecord

DEFAULT_EXPIRATION_HOURS = 24


@dataclass
class IdempotencyResult:
    replay: bool
    status_code: int
    response: Any


class IdempotencyService:
    def __init__(self, db: Session):
        self.db = db

    def _hash_payload(self, request: Request, payload: dict[str, Any]) -> str:
        payload_json = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        raw = f"{request.method}:{request.url.path}:{payload_json}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def handle(
        self,
        request: Request,
        payload: dict[str, Any],
        status_code: int,
        executor: Callable[[], Any],
    ) -> IdempotencyResult | None:
        key = request.headers.get("Idempotency-Key")
        if not key:
            response = executor()
            return IdempotencyResult(
                replay=False, status_code=status_code, response=response
            )

        payload_hash = self._hash_payload(request, payload)
        existing = self.db.execute(
            select(IdempotencyRecord).where(IdempotencyRecord.key == key)
        ).scalar_one_or_none()
        if existing:
            if existing.request_hash != payload_hash:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Idempotency key conflict for different request payload",
                )
            return IdempotencyResult(
                replay=True,
                status_code=existing.status_code,
                response=existing.response_body,
            )

        response = executor()
        encoded = jsonable_encoder(response)
        record = IdempotencyRecord(
            key=key,
            request_hash=payload_hash,
            status_code=status_code,
            response_body=encoded,
            expires_at=datetime.now(tz=timezone.utc)
            + timedelta(hours=DEFAULT_EXPIRATION_HOURS),
        )
        self.db.add(record)
        self.db.commit()
        return IdempotencyResult(
            replay=False, status_code=status_code, response=response
        )
