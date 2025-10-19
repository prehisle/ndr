from __future__ import annotations

from contextlib import contextmanager
from typing import Generator, Iterable

from sqlalchemy.orm import Session


class ServiceError(Exception):
    """Base class for application service level exceptions."""


class MissingUserError(ServiceError):
    """Raised when a write operation lacks a valid user identifier."""


class TransactionBoundaryError(ServiceError):
    """Raised when transaction control is misused within a service."""


class BaseService:
    """Provides guard rails and helpers shared by application services."""

    def __init__(self, session: Session):
        self._session = session

    @property
    def session(self) -> Session:
        return self._session

    def _ensure_user(self, user_id: str | None) -> str:
        if not user_id:
            raise MissingUserError("user_id is required for this operation")
        return user_id

    def _commit(self) -> None:
        try:
            self._session.commit()
        except Exception:
            self._session.rollback()
            raise

    def _refresh_many(self, instances: Iterable[object]) -> None:
        for instance in instances:
            self._session.refresh(instance)

    @contextmanager
    def transaction(self) -> Generator[Session, None, None]:
        """Provide an explicit transaction boundary for composed use cases."""
        with self._session.begin():
            yield self._session

