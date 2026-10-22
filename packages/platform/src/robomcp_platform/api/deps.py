"""Request dependencies: a DB session per request and the authenticated principal.

Endpoints commit explicitly; anything uncommitted is rolled back when the session closes.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from robomcp_platform.models import ApiKey, Membership
from robomcp_platform.security import hash_api_key, looks_like_api_key


def get_session(request: Request) -> Iterator[Session]:
    with request.app.state.sessionmaker() as session:
        yield session


SessionDep = Annotated[Session, Depends(get_session)]


@dataclass(frozen=True)
class Principal:
    org_id: uuid.UUID
    user_id: uuid.UUID
    role: str
    api_key_id: uuid.UUID
    api_key_prefix: str


_bearer = HTTPBearer(auto_error=False)


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(status.HTTP_401_UNAUTHORIZED, detail, headers={"WWW-Authenticate": "Bearer"})


def get_principal(
    session: SessionDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> Principal:
    if credentials is None:
        raise _unauthorized("missing bearer API key")
    if not looks_like_api_key(credentials.credentials):
        raise _unauthorized("invalid API key")
    row = session.execute(
        select(ApiKey.id, ApiKey.prefix, ApiKey.org_id, ApiKey.user_id, Membership.role)
        .join(Membership, (Membership.org_id == ApiKey.org_id) & (Membership.user_id == ApiKey.user_id))
        .where(ApiKey.key_hash == hash_api_key(credentials.credentials), ApiKey.revoked_at.is_(None))
    ).one_or_none()
    if row is None:
        raise _unauthorized("invalid API key")
    session.execute(update(ApiKey).where(ApiKey.id == row.id).values(last_used_at=func.now()))
    session.commit()
    return Principal(org_id=row.org_id, user_id=row.user_id, role=row.role, api_key_id=row.id,
                     api_key_prefix=row.prefix)


PrincipalDep = Annotated[Principal, Depends(get_principal)]
