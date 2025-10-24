from __future__ import annotations

from typing import MutableMapping, TypedDict

MISSING_USER_ID = "<missing>"


class AuthContext(TypedDict):
    """Lightweight representation of request authentication metadata."""

    user_id: str
    request_id: str | None
    user_supplied: str | None


def _resolve_user(raw_user: str | None) -> tuple[str, str | None]:
    """Return the normalized user identifier and the original value.

    ``None`` indicates the header is completely absent, while an empty string is
    preserved to keep parity with the original behaviour. Both cases map to the
    ``"<missing>"`` sentinel to align with existing logging and auditing
    semantics.
    """

    if raw_user is None:
        return MISSING_USER_ID, None
    if raw_user == "":
        return MISSING_USER_ID, ""
    return raw_user, raw_user


def build_auth_context(
    *, x_user_id: str | None, x_request_id: str | None
) -> AuthContext:
    """Construct the request context shared by dependencies and logging."""

    user_id, user_supplied = _resolve_user(x_user_id)
    return {
        "user_id": user_id,
        "request_id": x_request_id,
        "user_supplied": user_supplied,
    }


def resolve_user_id(raw_user: str | None) -> str:
    """Derive the effective user identifier used for auditing/logging."""

    user_id, _ = _resolve_user(raw_user)
    return user_id


def ensure_request_id_header(
    headers: MutableMapping[str, str],
    request_id: str | None,
) -> None:
    """Propagate the request identifier when the upstream handler omitted it."""

    if request_id is None:
        return
    if "X-Request-Id" not in headers:
        headers["X-Request-Id"] = request_id
