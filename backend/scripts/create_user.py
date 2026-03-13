from __future__ import annotations

import argparse
import os
import sys
from getpass import getpass

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.core.security import get_password_hash
from app.models import User


def _read_password_from_tty() -> str:
    p1 = getpass("Password: ")
    if not p1:
        raise SystemExit("Password cannot be empty.")
    p2 = getpass("Password (again): ")
    if p1 != p2:
        raise SystemExit("Passwords do not match.")
    return p1


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Create or update an invoice_system user.")
    parser.add_argument("--username", required=True, help="Username (unique)")
    parser.add_argument("--password", default=None, help="Password (omit to be prompted securely)")
    parser.add_argument("--inactive", action="store_true", help="Create user as inactive")
    parser.add_argument(
        "--update-if-exists",
        action="store_true",
        help="If username exists, update its password and active flag",
    )
    args = parser.parse_args(argv)

    username = args.username.strip()
    if not username:
        raise SystemExit("Username cannot be empty.")

    password = args.password if args.password is not None else _read_password_from_tty()
    password_hash = get_password_hash(password)

    database_url = os.environ.get("DATABASE_URL") or settings.database_url
    engine = create_engine(database_url, pool_pre_ping=True)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    db = SessionLocal()
    try:
        existing = db.scalar(select(User).where(User.username == username))
        if existing:
            if not args.update_if_exists:
                print(f"User already exists: {username}", file=sys.stderr)
                return 2
            existing.password_hash = password_hash
            existing.is_active = not args.inactive
            db.add(existing)
            db.commit()
            print(f"Updated user: {username} (active={existing.is_active})")
            return 0

        user = User(username=username, password_hash=password_hash, is_active=not args.inactive)
        db.add(user)
        db.commit()
        print(f"Created user: {username} (active={user.is_active})")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

