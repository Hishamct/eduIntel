#!/usr/bin/env python3
"""
scripts/create_platform_admin.py

Controlled Administrative CLI tool to idempotently provision or promote
Platform Administrator accounts in EduIntel AI.

Security Invariants:
1. No public HTTP endpoint exists to grant platform admin privileges.
2. Enforces strict password complexity (min 12 chars, mixed case, numbers, symbols).
3. Passwords and credentials are NEVER logged or printed to stdout.
4. Promoting an existing user updates strictly `is_platform_admin = True`
   without altering their institutional memberships or roles.
"""

import argparse
import asyncio
import getpass
import os
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

# Add backend directory to sys.path and set working directory to locate backend/.env
SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = SCRIPT_DIR.parent / "backend"
sys.path.insert(0, str(BACKEND_DIR))
os.chdir(BACKEND_DIR)

from app.auth.security import hash_password
from app.core.database import AsyncSessionLocal
from app.users.models import User
from sqlalchemy import select


def validate_password_complexity(password: str) -> None:
    """Enforces enterprise password strength requirements."""
    if len(password) < 12:
        raise ValueError("Password must be at least 12 characters long.")
    if not re.search(r"[A-Z]", password):
        raise ValueError("Password must contain at least one uppercase letter.")
    if not re.search(r"[a-z]", password):
        raise ValueError("Password must contain at least one lowercase letter.")
    if not re.search(r"[0-9]", password):
        raise ValueError("Password must contain at least one digit.")
    if not re.search(r"[!@#$%^&*(),.?\":{}|<>]", password):
        raise ValueError("Password must contain at least one special symbol.")


def validate_email_format(email: str) -> None:
    pattern = r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$"
    if not re.match(pattern, email):
        raise ValueError(f"Invalid email format: '{email}'")


async def provision_platform_admin(
    email: str,
    name: str | None = None,
    password: str | None = None,
) -> dict:
    """
    Provisions a new Platform Admin or promotes an existing user.
    Never prints or stores passwords in plain text.
    """
    clean_email = email.strip().lower()
    validate_email_format(clean_email)

    async with AsyncSessionLocal() as session, session.begin():
        stmt = select(User).where(User.email == clean_email)
        existing_user = (await session.execute(stmt)).scalar_one_or_none()

        if existing_user:
            if existing_user.is_platform_admin:
                return {
                    "action": "already_platform_admin",
                    "user_id": str(existing_user.id),
                    "email": existing_user.email,
                }

            # Explicitly promote existing user without altering memberships/roles
            existing_user.is_platform_admin = True
            if name:
                existing_user.name = name
            await session.flush()
            return {
                "action": "promoted",
                "user_id": str(existing_user.id),
                "email": existing_user.email,
            }
        else:
            if not password:
                raise ValueError("Password is required when creating a new platform admin user.")
            validate_password_complexity(password)

            new_user = User(
                email=clean_email,
                name=name or "Platform Administrator",
                hashed_password=hash_password(password),
                role="admin",
                is_active=True,
                is_platform_admin=True,
            )
            session.add(new_user)
            await session.flush()
            return {
                "action": "created",
                "user_id": str(new_user.id),
                "email": new_user.email,
            }


async def main_async(args):
    clean_email = args.email.strip().lower()
    validate_email_format(clean_email)

    password = args.password
    if not password:
        async with AsyncSessionLocal() as session:
            stmt = select(User.id).where(User.email == clean_email)
            res = await session.execute(stmt)
            exists = res.scalar_one_or_none() is not None

        if not exists:
            if sys.stdin.isatty():
                password = getpass.getpass("Enter secure password for new Platform Admin: ")
                confirm = getpass.getpass("Confirm password: ")
                if password != confirm:
                    print("ERROR: Passwords do not match.", file=sys.stderr)
                    sys.exit(1)
            else:
                print("ERROR: --password is required when creating a new user non-interactively.", file=sys.stderr)
                sys.exit(1)

    result = await provision_platform_admin(
        email=args.email,
        name=args.name,
        password=password,
    )
    timestamp = datetime.now(UTC).isoformat()
    action = result["action"]
    print(f"[{timestamp}] SUCCESS: Platform Admin {action}")
    print(f"User ID: {result['user_id']}")
    print(f"Email:   {result['email']}")


def main():
    parser = argparse.ArgumentParser(
        description="EduIntel AI — Provision or promote a Platform Administrator"
    )
    parser.add_argument("--email", required=True, help="Administrator email address")
    parser.add_argument("--name", help="Display name for the administrator")
    parser.add_argument("--password", help="Administrator password (prompted if omitted for new users)")

    args = parser.parse_args()

    try:
        asyncio.run(main_async(args))
    except ValueError as val_err:
        print(f"VALIDATION ERROR: {val_err}", file=sys.stderr)
        sys.exit(1)
    except Exception as exc:  # noqa: BLE001
        print(f"EXECUTION ERROR: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
