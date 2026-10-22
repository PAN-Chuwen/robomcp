"""`robomcp-platform` admin commands (run with direct database access)."""

from __future__ import annotations

import argparse

from sqlalchemy import select

from robomcp_platform.config import get_settings
from robomcp_platform.db import make_engine, make_sessionmaker
from robomcp_platform.models import Membership, Organization, User
from robomcp_platform.tenancy import create_org_with_owner, issue_api_key


def _print_key(plaintext: str, prefix: str) -> None:
    print(f"API key (shown once, store it now): {plaintext}")
    print(f"display prefix: {prefix}")


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="robomcp-platform")
    sub = p.add_subparsers(dest="command", required=True)

    b = sub.add_parser("bootstrap", help="create an organisation, its owner and an API key")
    b.add_argument("--org-name", required=True)
    b.add_argument("--org-slug", required=True)
    b.add_argument("--email", required=True, help="owner's email (an existing user is reused)")
    b.add_argument("--name", help="owner's display name")

    k = sub.add_parser("create-api-key", help="issue another API key for an existing member")
    k.add_argument("--org-slug", required=True)
    k.add_argument("--email", required=True)
    k.add_argument("--key-name", default="cli")

    args = p.parse_args(argv)
    engine = make_engine(get_settings().database_url)
    try:
        with make_sessionmaker(engine).begin() as s:
            if args.command == "bootstrap":
                if s.scalar(select(Organization.id).where(Organization.slug == args.org_slug)):
                    p.error(f"organisation {args.org_slug!r} already exists")
                made = create_org_with_owner(s, org_name=args.org_name, org_slug=args.org_slug,
                                             email=args.email, display_name=args.name)
                print(f"org {made.org.slug} ({made.org.id}); owner {made.user.email} ({made.user.id})")
                _print_key(made.api_key.plaintext, made.api_key.prefix)
            elif args.command == "create-api-key":
                member = s.execute(
                    select(Membership.org_id, Membership.user_id)
                    .join(Organization, Organization.id == Membership.org_id)
                    .join(User, User.id == Membership.user_id)
                    .where(Organization.slug == args.org_slug, User.email == args.email)
                ).one_or_none()
                if member is None:
                    p.error(f"{args.email} is not a member of {args.org_slug!r}")
                key = issue_api_key(s, org_id=member.org_id, user_id=member.user_id, name=args.key_name)
                _print_key(key.plaintext, key.prefix)
    finally:
        engine.dispose()
