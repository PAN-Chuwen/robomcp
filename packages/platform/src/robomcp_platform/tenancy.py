"""Organisations, owners and API keys (bootstrap path; GitHub OAuth sign-in arrives in M2)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from robomcp_platform.models import ApiKey, Membership, Organization, User
from robomcp_platform.security import NewApiKey, generate_api_key


@dataclass(frozen=True)
class Bootstrapped:
    org: Organization
    user: User
    api_key: NewApiKey  # plaintext is only available here


def issue_api_key(session: Session, *, org_id: uuid.UUID, user_id: uuid.UUID, name: str) -> NewApiKey:
    key = generate_api_key()
    session.add(ApiKey(org_id=org_id, user_id=user_id, name=name, prefix=key.prefix, key_hash=key.key_hash))
    return key


def create_org_with_owner(
    session: Session,
    *,
    org_name: str,
    org_slug: str,
    email: str,
    display_name: str | None = None,
    key_name: str = "bootstrap",
) -> Bootstrapped:
    """Create an organisation, make `email` its owner (creating the user if needed) and issue a key."""
    user = session.scalar(select(User).where(User.email == email))
    if user is None:
        user = User(email=email, display_name=display_name)
        session.add(user)
    org = Organization(name=org_name, slug=org_slug)
    session.add(org)
    session.flush()
    session.add(Membership(org_id=org.id, user_id=user.id, role="owner"))
    session.flush()
    key = issue_api_key(session, org_id=org.id, user_id=user.id, name=key_name)
    session.flush()
    return Bootstrapped(org=org, user=user, api_key=key)
