"""
CLI bootstrap command to provision the initial institutional administrator out-of-band.

Usage:
    python -m app.core.bootstrap_admin --email admin@eduintel.ai --name "System Administrator"
    (You will be prompted securely for password and confirmation)
"""
import argparse
import asyncio
import getpass
import sys
import uuid

from sqlalchemy import select

from app.auth.security import hash_password
from app.core.database import AsyncSessionLocal
from app.users.models import AdminProfile, User


async def bootstrap(email: str, name: str, password: str) -> bool:
    if len(password) < 8:
        print("Error: Password must be at least 8 characters long.", file=sys.stderr)
        return False

    async with AsyncSessionLocal() as db:
        existing = (
            await db.execute(select(User).where(User.email == email.lower()))
        ).scalar_one_or_none()
        if existing:
            print(f"Error: User with email '{email}' already exists.", file=sys.stderr)
            return False

        admin_user = User(
            id=uuid.uuid4(),
            email=email.lower(),
            name=name,
            hashed_password=hash_password(password),
            role="admin",
            is_active=True,
        )
        db.add(admin_user)
        await db.flush()

        admin_profile = AdminProfile(
            id=uuid.uuid4(),
            user_id=admin_user.id,
            designation="System Administrator",
        )
        db.add(admin_profile)
        await db.commit()
        print(f"Successfully bootstrapped Administrator: {email} (ID: {admin_user.id})")
        return True


def main():
    parser = argparse.ArgumentParser(
        description="EduIntel Initial Administrator Bootstrap CLI"
    )
    parser.add_argument("--email", required=True, help="Administrator email address")
    parser.add_argument("--name", required=True, help="Administrator full name")
    args = parser.parse_args()

    password = getpass.getpass("Enter administrator password: ")
    password_confirm = getpass.getpass("Confirm administrator password: ")
    if password != password_confirm:
        print("Error: Passwords do not match.", file=sys.stderr)
        sys.exit(1)

    success = asyncio.run(bootstrap(args.email, args.name, password))
    if not success:
        sys.exit(1)


if __name__ == "__main__":
    main()
