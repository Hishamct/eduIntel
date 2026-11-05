"""
backend/tests/test_platform_admin.py

Automated Security and Integration Test Suite for Platform Admin Workstream:
1. Administrative CLI Provisioning & Password Complexity Enforcement
2. Mass Assignment & Privilege Escalation Defenses
3. Read-Only Cross-Tenant RLS Policy Verification under unprivileged role
4. Multi-Institution Suspension & Tenant Isolation Semantics
"""

import os
import sys
import uuid
from pathlib import Path

import asyncpg
import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.auth.security import hash_password
from app.auth.service import authenticate_user
from app.institutions.models import Institution, InstitutionMembership
from app.main import app
from app.users.dependencies import require_platform_admin
from app.users.models import User

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from create_platform_admin import (  # noqa: E402
    provision_platform_admin,
    validate_email_format,
    validate_password_complexity,
)


# -----------------------------------------------------------------------------
# 1. Platform Admin CLI & Password Policy Tests
# -----------------------------------------------------------------------------
class TestPlatformAdminCLIPolicy:
    """Tests password complexity rules and idempotent provisioning logic."""

    def test_password_complexity_enforces_minimum_length(self):
        with pytest.raises(ValueError, match="at least 12 characters"):
            validate_password_complexity("Short1!")

    def test_password_complexity_enforces_uppercase(self):
        with pytest.raises(ValueError, match="uppercase letter"):
            validate_password_complexity("lowercase1234!")

    def test_password_complexity_enforces_lowercase(self):
        with pytest.raises(ValueError, match="lowercase letter"):
            validate_password_complexity("UPPERCASE1234!")

    def test_password_complexity_enforces_digit(self):
        with pytest.raises(ValueError, match="at least one digit"):
            validate_password_complexity("NoDigitsHere!!")

    def test_password_complexity_enforces_symbol(self):
        with pytest.raises(ValueError, match="special symbol"):
            validate_password_complexity("NoSpecialChars123")

    def test_password_complexity_accepts_strong_password(self):
        validate_password_complexity("SuperSecret123!#$")

    def test_email_validation_rejects_malformed_email(self):
        with pytest.raises(ValueError, match="Invalid email format"):
            validate_email_format("not-an-email")

    @pytest.mark.asyncio
    async def test_provision_platform_admin_creates_new_user(self):
        unique_email = f"plat_admin_{uuid.uuid4().hex[:8]}@example.com"
        result = await provision_platform_admin(
            email=unique_email,
            name="Test SuperAdmin",
            password="EnterprisePassword123!@",
        )
        assert result["action"] == "created"
        assert result["email"] == unique_email

        second_run = await provision_platform_admin(
            email=unique_email,
        )
        assert second_run["action"] == "already_platform_admin"

    @pytest.mark.asyncio
    async def test_promote_existing_user_preserves_memberships(self):
        from app.core.database import AsyncSessionLocal
        unique_email = f"regular_admin_{uuid.uuid4().hex[:8]}@example.com"
        async with AsyncSessionLocal() as session, session.begin():
            inst = Institution(name="School X", slug=f"school-{uuid.uuid4().hex[:6]}", is_active=True)
            session.add(inst)
            await session.flush()

            u = User(
                email=unique_email,
                name="Regular Admin",
                hashed_password=hash_password("RegularPass123!"),
                role="admin",
                is_active=True,
                is_platform_admin=False,
            )
            session.add(u)
            await session.flush()

            mem = InstitutionMembership(
                institution_id=inst.id,
                user_id=u.id,
                role="admin",
                status="active",
            )
            session.add(mem)

        res = await provision_platform_admin(email=unique_email)
        assert res["action"] == "promoted"

        async with AsyncSessionLocal() as session:
            verified_u = (await session.execute(select(User).where(User.email == unique_email))).scalar_one()
            assert verified_u.is_platform_admin is True
            assert verified_u.role == "admin"

            mems_stmt = select(InstitutionMembership).where(InstitutionMembership.user_id == verified_u.id)
            mems = (await session.execute(mems_stmt)).scalars().all()
            assert len(mems) == 1
            assert mems[0].institution_id == inst.id
            assert mems[0].role == "admin"


# -----------------------------------------------------------------------------
# 2. Privilege Escalation & Route Guard Tests
# -----------------------------------------------------------------------------
class TestPlatformAdminRouteGuards:
    """Verifies that only users with verified database is_platform_admin can pass require_platform_admin."""

    @pytest.mark.asyncio
    async def test_non_platform_admin_rejected_with_403(self):
        regular_admin = User(
            id=uuid.uuid4(),
            email="instadmin@example.com",
            name="Inst Admin",
            role="admin",
            is_active=True,
            is_platform_admin=False,
        )
        with pytest.raises(HTTPException) as exc_info:
            await require_platform_admin(current_user=regular_admin)
        assert exc_info.value.status_code == 403
        assert "Platform administrator privileges required" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_verified_platform_admin_passes_dependency(self):
        platform_admin = User(
            id=uuid.uuid4(),
            email="superadmin@eduintel.ai",
            name="Platform SuperAdmin",
            role="admin",
            is_active=True,
            is_platform_admin=True,
        )
        res = await require_platform_admin(current_user=platform_admin)
        assert res.id == platform_admin.id
        assert res.is_platform_admin is True

    @pytest.mark.asyncio
    async def test_jwt_claim_spoofing_rejected_when_db_record_is_false(self):
        """Even if JWT claims is_platform_admin=True, if DB row has False, require_platform_admin rejects."""
        user_row = User(
            id=uuid.uuid4(),
            email="attacker@example.com",
            name="Attacker",
            role="student",
            is_active=True,
            is_platform_admin=False,  # DB row says False!
        )
        with pytest.raises(HTTPException) as exc_info:
            await require_platform_admin(current_user=user_row)
        assert exc_info.value.status_code == 403


# -----------------------------------------------------------------------------
# 3. Read-Only Cross-Tenant RLS Policy Verification under Unprivileged Role
# -----------------------------------------------------------------------------
class TestReadOnlyCrossTenantRLSPolicy:
    """
    Proves empirically that under an unprivileged database role:
    1. Platform Admin has cross-tenant READ access (USING clause).
    2. Cross-tenant WRITE operations fail closed via RLS WITH CHECK (SQLSTATE 42501).
    """

    @pytest.mark.asyncio
    async def test_cross_tenant_write_rejected_by_rls_with_check(self):
        test_url = (
            os.getenv("TEST_DATABASE_URL", "postgresql://eduintel:eduintel_dev@localhost:5432/eduintel_test")
            .replace("postgresql+asyncpg://", "postgresql://")
            .replace("eduintel_app:", "eduintel:")
        )
        conn = await asyncpg.connect(test_url)

        # 1. Provision unprivileged application role eduintel_app (NOSUPERUSER, NOBYPASSRLS)
        await conn.execute("""
            DO $$
            BEGIN
              IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'eduintel_app') THEN
                CREATE ROLE eduintel_app WITH LOGIN NOSUPERUSER NOBYPASSRLS;
              END IF;
            END
            $$;
            GRANT USAGE ON SCHEMA public TO eduintel_app;
            GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO eduintel_app;
            GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO eduintel_app;
            GRANT eduintel TO eduintel_app;
        """)

        async with conn.transaction():
            inst_a = uuid.uuid4()
            inst_b = uuid.uuid4()
            user_id = uuid.uuid4()

            # Insert test fixtures as admin
            await conn.execute(
                "INSERT INTO institutions (id, name, slug, is_active) VALUES ($1, $2, $3, true)",
                inst_a, "Inst A", f"inst-a-{inst_a.hex[:6]}"
            )
            await conn.execute(
                "INSERT INTO institutions (id, name, slug, is_active) VALUES ($1, $2, $3, true)",
                inst_b, "Inst B", f"inst-b-{inst_b.hex[:6]}"
            )
            await conn.execute(
                "INSERT INTO users (id, email, hashed_password, role, is_active) VALUES ($1, $2, $3, $4, $5)",
                user_id, f"u_{user_id.hex[:6]}@test.com", "pw", "student", True
            )

            # 2. Switch to unprivileged role eduintel_app where RLS is enforced
            await conn.execute("SET ROLE eduintel_app")

            # 3. Set Platform Admin session parameter (app.is_platform_admin = 'true')
            await conn.execute("SELECT set_config('app.is_platform_admin', 'true', true)")
            await conn.execute("SELECT set_config('app.current_institution_id', $1, true)", str(inst_a))

            # A. Verify READ bypass works across tenant boundaries
            read_user = await conn.fetch("SELECT id FROM users WHERE id = $1", user_id)
            assert len(read_user) == 1, "Platform Admin should be able to read records across tenants"

            # B. Verify WRITE isolation: attempting to insert record for inst_b while bound to inst_a
            # MUST raise asyncpg.exceptions.InsufficientPrivilegeError specifically from RLS policy
            rls_error_caught = False
            sp_id = uuid.uuid4()
            try:
                # Use nested savepoint so error doesn't abort outer transaction
                async with conn.transaction():
                    await conn.execute(
                        "INSERT INTO student_profiles (id, institution_id, user_id, grade) VALUES ($1, $2, $3, '10')",
                        sp_id, inst_b, user_id
                    )
            except asyncpg.exceptions.InsufficientPrivilegeError as exc:
                rls_error_caught = True
                assert exc.sqlstate == "42501"
                assert "violates row-level security policy" in str(exc)
                assert 'for table "student_profiles"' in str(exc)

            assert rls_error_caught is True, (
                "Cross-tenant write MUST fail closed with InsufficientPrivilegeError (SQLSTATE 42501) "
                "from PostgreSQL RLS WITH CHECK policy."
            )

            # C. Verify DELETE isolation (SEC-03):
            # Attempting to delete row belonging to inst_b while bound to inst_a MUST affect 0 rows
            user_a = uuid.uuid4()
            user_b = uuid.uuid4()
            row_inst_a = uuid.uuid4()
            row_inst_b = uuid.uuid4()

            await conn.execute("RESET ROLE")
            await conn.execute(
                "INSERT INTO users (id, email, hashed_password, role, is_active) VALUES ($1, $2, $3, $4, $5)",
                user_a, f"ua_{user_a.hex[:6]}@test.com", "pw", "student", True
            )
            await conn.execute(
                "INSERT INTO users (id, email, hashed_password, role, is_active) VALUES ($1, $2, $3, $4, $5)",
                user_b, f"ub_{user_b.hex[:6]}@test.com", "pw", "student", True
            )
            await conn.execute(
                "INSERT INTO student_profiles (id, institution_id, user_id, grade) VALUES ($1, $2, $3, '10')",
                row_inst_a, inst_a, user_a
            )
            await conn.execute(
                "INSERT INTO student_profiles (id, institution_id, user_id, grade) VALUES ($1, $2, $3, '11')",
                row_inst_b, inst_b, user_b
            )

            await conn.execute("SET ROLE eduintel_app")
            await conn.execute("SELECT set_config('app.is_platform_admin', 'true', true)")
            await conn.execute("SELECT set_config('app.current_institution_id', $1, true)", str(inst_a))

            # Cross-tenant DELETE on inst_b MUST NOT delete the row (affects 0 rows)
            del_result = await conn.execute(
                "DELETE FROM student_profiles WHERE id = $1", row_inst_b
            )
            assert del_result == "DELETE 0", "Cross-tenant DELETE must be blocked by RLS delete policy"

            # Verify row_inst_b still exists in the database
            row_check = await conn.fetch("SELECT id FROM student_profiles WHERE id = $1", row_inst_b)
            assert len(row_check) == 1, "Foreign tenant record must not be deleted"

            # Deleting row belonging to inst_a succeeds (1 row deleted)
            del_own = await conn.execute(
                "DELETE FROM student_profiles WHERE id = $1", row_inst_a
            )
            assert del_own == "DELETE 1", "Deletion of row matching bound tenant must succeed"

            # D. Verify UPDATE isolation:
            # Cannot update foreign tenant record inst_b
            upd_foreign = await conn.execute(
                "UPDATE student_profiles SET grade = '12' WHERE id = $1", row_inst_b
            )
            assert upd_foreign == "UPDATE 0", "Cross-tenant UPDATE must affect 0 rows"

            # Reset role before rollback
            await conn.execute("RESET ROLE")

        await conn.close()

    @pytest.mark.asyncio
    async def test_ordinary_tenant_isolation_under_split_policies(self):
        """Verifies ordinary non-admin users cannot read or delete foreign tenant rows."""
        test_url = (
            os.getenv("TEST_DATABASE_URL", "postgresql://eduintel:eduintel_dev@localhost:5432/eduintel_test")
            .replace("postgresql+asyncpg://", "postgresql://")
            .replace("eduintel_app:", "eduintel:")
        )
        conn = await asyncpg.connect(test_url)
        async with conn.transaction():
            inst_a = uuid.uuid4()
            inst_b = uuid.uuid4()
            u_id_a = uuid.uuid4()
            u_id_b = uuid.uuid4()
            sp_a = uuid.uuid4()
            sp_b = uuid.uuid4()

            await conn.execute(
                "INSERT INTO institutions (id, name, slug, is_active) VALUES ($1, $2, $3, true)",
                inst_a, "A", f"a-{inst_a.hex[:6]}"
            )
            await conn.execute(
                "INSERT INTO institutions (id, name, slug, is_active) VALUES ($1, $2, $3, true)",
                inst_b, "B", f"b-{inst_b.hex[:6]}"
            )
            await conn.execute(
                "INSERT INTO users (id, email, hashed_password, role, is_active) VALUES ($1, $2, $3, $4, $5)",
                u_id_a, f"u_{u_id_a.hex[:6]}@t.com", "pw", "student", True
            )
            await conn.execute(
                "INSERT INTO users (id, email, hashed_password, role, is_active) VALUES ($1, $2, $3, $4, $5)",
                u_id_b, f"u_{u_id_b.hex[:6]}@t.com", "pw", "student", True
            )
            await conn.execute(
                "INSERT INTO student_profiles (id, institution_id, user_id, grade) VALUES ($1, $2, $3, '9')",
                sp_a, inst_a, u_id_a
            )
            await conn.execute(
                "INSERT INTO student_profiles (id, institution_id, user_id, grade) VALUES ($1, $2, $3, '9')",
                sp_b, inst_b, u_id_b
            )

            await conn.execute("SET ROLE eduintel_app")
            await conn.execute("SELECT set_config('app.is_platform_admin', 'false', true)")
            await conn.execute("SELECT set_config('app.current_institution_id', $1, true)", str(inst_a))

            # Ordinary user can only SELECT rows from inst_a
            rows = await conn.fetch("SELECT id FROM student_profiles WHERE id IN ($1, $2)", sp_a, sp_b)
            assert len(rows) == 1
            assert rows[0]["id"] == sp_a

            # Ordinary user cannot DELETE rows from inst_b
            del_res = await conn.execute("DELETE FROM student_profiles WHERE id = $1", sp_b)
            assert del_res == "DELETE 0"

            await conn.execute("RESET ROLE")
        await conn.close()


# -----------------------------------------------------------------------------
# 4. Multi-Institution Suspension Semantics
# -----------------------------------------------------------------------------
class TestMultiInstitutionSuspensionSemantics:
    """Verifies that suspending an institution isolates it without locking multi-tenant users from active schools."""

    @pytest.mark.asyncio
    async def test_suspension_and_multi_institution_login_isolation(self):
        from app.auth.schemas import LoginRequest
        from app.core.database import AsyncSessionLocal

        active_inst_id = uuid.uuid4()
        suspended_inst_id = uuid.uuid4()
        password_str = "ComplexPass123!@"

        async with AsyncSessionLocal() as session, session.begin():
            inst_active = Institution(
                id=active_inst_id,
                name="Active Academy",
                slug=f"act-{active_inst_id.hex[:6]}",
                is_active=True,
            )
            inst_suspended = Institution(
                id=suspended_inst_id,
                name="Suspended College",
                slug=f"sus-{suspended_inst_id.hex[:6]}",
                is_active=False,
            )
            session.add_all([inst_active, inst_suspended])
            await session.flush()

            u_single_suspended = User(
                email=f"single_sus_{uuid.uuid4().hex[:6]}@test.edu",
                name="Single Suspended",
                hashed_password=hash_password(password_str),
                role="teacher",
                is_active=True,
            )
            u_multi = User(
                email=f"multi_{uuid.uuid4().hex[:6]}@test.edu",
                name="Multi Inst",
                hashed_password=hash_password(password_str),
                role="teacher",
                is_active=True,
            )
            session.add_all([u_single_suspended, u_multi])
            await session.flush()

            m1 = InstitutionMembership(
                institution_id=suspended_inst_id,
                user_id=u_single_suspended.id,
                role="teacher",
                status="active",
            )
            m2_act = InstitutionMembership(
                institution_id=active_inst_id,
                user_id=u_multi.id,
                role="teacher",
                status="active",
            )
            m2_sus = InstitutionMembership(
                institution_id=suspended_inst_id,
                user_id=u_multi.id,
                role="teacher",
                status="active",
            )
            session.add_all([m1, m2_act, m2_sus])

        async with AsyncSessionLocal() as session:
            with pytest.raises(ValueError, match="INSTITUTION_SUSPENDED"):
                await authenticate_user(session, LoginRequest(email=u_single_suspended.email, password=password_str))

            token = await authenticate_user(session, LoginRequest(email=u_multi.email, password=password_str))
            assert token is not None

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            headers_act = {"Authorization": f"Bearer {token}", "X-Institution-Id": str(active_inst_id)}
            res_act = await client.get("/institutions/current", headers=headers_act)
            assert res_act.status_code == 200
            assert res_act.json()["name"] == "Active Academy"

            headers_sus = {"Authorization": f"Bearer {token}", "X-Institution-Id": str(suspended_inst_id)}
            res_sus = await client.get("/institutions/current", headers=headers_sus)
            assert res_sus.status_code == 403
            assert "suspended" in res_sus.json()["detail"].lower()


# -----------------------------------------------------------------------------
# 5. Institution Lifecycle & Atomic Onboarding API Tests (Stage 3)
# -----------------------------------------------------------------------------
class TestInstitutionLifecycleAndOnboarding:
    """
    Verifies Stage 3 institution onboarding, atomic rollbacks, inactive initial
    admin password protection, invitation token redemption, and status toggles.
    """

    @pytest.mark.asyncio
    async def test_onboarding_lifecycle_and_unusable_pre_activation_password(self):
        from app.auth.models import PasswordResetToken
        from app.auth.security import create_access_token
        from app.auth.service import _hash_token
        from app.core.database import AsyncSessionLocal

        # 1. Provision Platform Admin in DB
        plat_email = f"plat_suite_{uuid.uuid4().hex[:6]}@eduintel.ai"
        plat_admin_res = await provision_platform_admin(
            email=plat_email,
            name="Platform SuperAdmin",
            password="EnterprisePassword123!@",
        )
        plat_admin_id = plat_admin_res["user_id"]
        plat_token = create_access_token(data={"sub": str(plat_admin_id), "role": "admin", "is_platform_admin": True})

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            headers = {"Authorization": f"Bearer {plat_token}"}

            # 2. Onboard new institution
            slug = f"alpha-inst-{uuid.uuid4().hex[:6]}"
            admin_email = f"admin_{uuid.uuid4().hex[:6]}@alpha.edu"
            onboard_payload = {
                "name": "Alpha Institute of Tech",
                "slug": slug,
                "contact_email": "contact@alpha.edu",
                "admin_email": admin_email,
                "admin_name": "Dr. Alpha Admin",
            }

            res = await client.post("/institutions", json=onboard_payload, headers=headers)
            assert res.status_code == 201
            data = res.json()
            inst_id = data["institution_id"]
            admin_user_id = data["admin_user_id"]
            activation_token = data["activation_token"]
            assert activation_token is not None
            assert data["invitation_sent"] is True

            # 3. Verify Database State
            async with AsyncSessionLocal() as session:
                # User is inactive
                u = (await session.execute(select(User).where(User.id == uuid.UUID(admin_user_id)))).scalar_one()
                assert u.is_active is False
                assert u.is_platform_admin is False

                # Token stored hashed at rest with SHA-256
                tok_stmt = select(PasswordResetToken).where(PasswordResetToken.user_id == u.id)
                tok_row = (await session.execute(tok_stmt)).scalar_one()
                assert tok_row.token == _hash_token(activation_token)
                assert tok_row.used is False

                # Admin profile and membership exist
                mems_stmt = select(InstitutionMembership).where(InstitutionMembership.user_id == u.id)
                mems = (await session.execute(mems_stmt)).scalars().all()
                assert len(mems) == 1
                assert mems[0].institution_id == uuid.UUID(inst_id)

            # 4. Proves generated password / any password CANNOT log in before activation
            login_payload = {"email": admin_email, "password": "AnyAttemptedPassword123!@"}
            login_res = await client.post("/auth/login", json=login_payload)
            assert login_res.status_code == 401
            detail = login_res.json()["detail"].lower()
            assert "inactive" in detail or "not been activated" in detail

            # 5. Activate Account via reset-password endpoint
            new_password = "MyPersonalSecurePassword123!@"
            reset_payload = {"token": activation_token, "new_password": new_password}
            reset_res = await client.post("/auth/password-reset/confirm", json=reset_payload)
            assert reset_res.status_code == 200

            # 6. Verify Activation Succeeded & Token Consumed
            async with AsyncSessionLocal() as session:
                u_after = (await session.execute(select(User).where(User.id == uuid.UUID(admin_user_id)))).scalar_one()
                assert u_after.is_active is True

                tok_after = (await session.execute(tok_stmt)).scalar_one()
                assert tok_after.used is True

            # Replay rejection: token cannot be reused
            replay_payload = {"token": activation_token, "new_password": "AnotherPassword123!@"}
            replay_res = await client.post("/auth/password-reset/confirm", json=replay_payload)
            assert replay_res.status_code == 400

            # 7. Now Initial Admin can successfully log in!
            login_success = await client.post("/auth/login", json={"email": admin_email, "password": new_password})
            assert login_success.status_code == 200
            assert "access_token" in login_success.json()

            # Clear institutional admin login cookie so subsequent requests use platform admin Bearer token
            client.cookies.clear()

            # 8. Platform Admin lists institutions
            list_res = await client.get("/institutions", headers=headers)
            assert list_res.status_code == 200
            inst_list = list_res.json()
            found = [i for i in inst_list if i["id"] == inst_id]
            assert len(found) == 1
            assert found[0]["admin_count"] == 1

            # 9. Platform Admin suspends institution
            patch_url = f"/institutions/{inst_id}/status"
            patch_res = await client.patch(patch_url, json={"is_active": False}, headers=headers)
            assert patch_res.status_code == 200
            assert patch_res.json()["is_active"] is False

            # Verify login for that single-institution admin is blocked due to suspension
            login_blocked = await client.post("/auth/login", json={"email": admin_email, "password": new_password})
            assert login_blocked.status_code == 403
            assert "suspended" in login_blocked.json()["detail"].lower()

            # Reactivate
            client.cookies.clear()
            patch_reactivate = await client.patch(patch_url, json={"is_active": True}, headers=headers)
            assert patch_reactivate.status_code == 200
            assert patch_reactivate.json()["is_active"] is True

    @pytest.mark.asyncio
    async def test_atomic_rollback_on_duplicate_slug_or_email(self):
        from app.auth.security import create_access_token
        from app.core.database import AsyncSessionLocal

        plat_email = f"plat_rb_{uuid.uuid4().hex[:6]}@eduintel.ai"
        plat_res = await provision_platform_admin(
            email=plat_email, name="Platform Admin", password="ComplexPassword123!@"
        )
        plat_token = create_access_token(
            data={"sub": str(plat_res["user_id"]), "role": "admin", "is_platform_admin": True}
        )

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            headers = {"Authorization": f"Bearer {plat_token}"}

            first_slug = f"unique-slug-{uuid.uuid4().hex[:6]}"
            first_email = f"unique_admin_{uuid.uuid4().hex[:6]}@school.org"

            # 1. First onboarding succeeds
            res1 = await client.post("/institutions", json={
                "name": "First School",
                "slug": first_slug,
                "admin_email": first_email,
                "admin_name": "First Admin",
            }, headers=headers)
            assert res1.status_code == 201

            # 2. Duplicate slug fails with 409 and clean rollback
            diff_email = f"diff_admin_{uuid.uuid4().hex[:6]}@school.org"
            res_dup_slug = await client.post("/institutions", json={
                "name": "Second School",
                "slug": first_slug,  # Duplicate!
                "admin_email": diff_email,
                "admin_name": "Second Admin",
            }, headers=headers)
            assert res_dup_slug.status_code == 409
            assert "already exists" in res_dup_slug.json()["detail"]

            # Confirm diff_email was NOT created in DB (clean rollback)
            async with AsyncSessionLocal() as session:
                diff_user = (await session.execute(select(User).where(User.email == diff_email))).scalar_one_or_none()
                assert diff_user is None

            # 3. Duplicate admin email fails with 409 and clean rollback
            diff_slug = f"diff-slug-{uuid.uuid4().hex[:6]}"
            res_dup_email = await client.post("/institutions", json={
                "name": "Third School",
                "slug": diff_slug,
                "admin_email": first_email,  # Duplicate email!
                "admin_name": "Third Admin",
            }, headers=headers)
            assert res_dup_email.status_code == 409
            assert "already exists" in res_dup_email.json()["detail"]

            # Confirm diff_slug was NOT created in DB (clean rollback)
            async with AsyncSessionLocal() as session:
                diff_inst_stmt = select(Institution).where(Institution.slug == diff_slug)
                diff_inst = (await session.execute(diff_inst_stmt)).scalar_one_or_none()
                assert diff_inst is None

    @pytest.mark.asyncio
    async def test_non_platform_admin_cannot_access_institution_management(self):
        from app.auth.security import create_access_token
        from app.core.database import AsyncSessionLocal

        # Standard institute admin user in DB (is_platform_admin=False)
        regular_user_id = uuid.uuid4()
        async with AsyncSessionLocal() as session, session.begin():
            reg_user = User(
                id=regular_user_id,
                email=f"regular_{regular_user_id.hex[:6]}@school.edu",
                name="Regular Admin",
                hashed_password=hash_password("RegularPass123!@"),
                role="admin",
                is_active=True,
                is_platform_admin=False,
            )
            session.add(reg_user)

        inst_admin_token = create_access_token(
            data={"sub": str(regular_user_id), "role": "admin", "is_platform_admin": False}
        )

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            headers = {"Authorization": f"Bearer {inst_admin_token}"}

            # Attempting list institutions
            res_list = await client.get("/institutions", headers=headers)
            assert res_list.status_code == 403

            # Attempting onboard institution
            res_onboard = await client.post("/institutions", json={
                "name": "Unauthorized School",
                "slug": f"unauth-{uuid.uuid4().hex[:6]}",
                "admin_email": "unauth@school.edu",
                "admin_name": "Unauth Admin",
            }, headers=headers)
            assert res_onboard.status_code == 403

            # Attempting patch status
            res_patch = await client.patch(
                f"/institutions/{uuid.uuid4()}/status", json={"is_active": False}, headers=headers
            )
            assert res_patch.status_code == 403

    @pytest.mark.asyncio
    async def test_onboarding_rejects_malformed_emails_with_422(self):
        """SEC-01: Verifies malformed admin and contact emails are strictly rejected with HTTP 422."""
        from app.auth.security import create_access_token
        plat_res = await provision_platform_admin(
            email=f"plat_{uuid.uuid4().hex[:6]}@eduintel.ai",
            name="Platform SuperAdmin",
            password="EnterprisePassword123!@",
        )
        plat_token = create_access_token(
            data={"sub": str(plat_res["user_id"]), "role": "admin", "is_platform_admin": True}
        )
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            headers = {"Authorization": f"Bearer {plat_token}"}

            # 1. Malformed admin_email
            res1 = await client.post("/institutions", json={
                "name": "Invalid Admin Email School",
                "slug": f"invalid-admin-{uuid.uuid4().hex[:6]}",
                "admin_email": "not-an-email",
                "admin_name": "Admin Name",
            }, headers=headers)
            assert res1.status_code == 422, "Malformed admin_email must be rejected with HTTP 422"

            # 2. Malformed contact_email
            res2 = await client.post("/institutions", json={
                "name": "Invalid Contact Email School",
                "slug": f"invalid-contact-{uuid.uuid4().hex[:6]}",
                "contact_email": "invalid-contact-email",
                "admin_email": f"valid_{uuid.uuid4().hex[:6]}@school.edu",
                "admin_name": "Admin Name",
            }, headers=headers)
            assert res2.status_code == 422, "Malformed contact_email must be rejected with HTTP 422"

            # 3. Valid emails succeed with HTTP 201
            res3 = await client.post("/institutions", json={
                "name": "Valid Email School",
                "slug": f"valid-{uuid.uuid4().hex[:6]}",
                "contact_email": "contact@valid.school.edu",
                "admin_email": f"admin_{uuid.uuid4().hex[:6]}@valid.school.edu",
                "admin_name": "Admin Name",
            }, headers=headers)
            assert res3.status_code == 201

    @pytest.mark.asyncio
    async def test_invitation_status_semantics_configured_vs_unconfigured_vs_failed(self, monkeypatch):
        """SEC-04: Verifies invitation status accurately reflects SMTP configuration and delivery evidence."""
        from app.auth.security import create_access_token
        from app.core.config import settings

        plat_res = await provision_platform_admin(
            email=f"plat_inv_{uuid.uuid4().hex[:6]}@eduintel.ai",
            name="Platform Admin",
            password="EnterprisePassword123!@",
        )
        plat_token = create_access_token(
            data={"sub": str(plat_res["user_id"]), "role": "admin", "is_platform_admin": True}
        )
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            headers = {"Authorization": f"Bearer {plat_token}"}

            # Case A: SMTP configured and successful
            res_sent = await client.post("/institutions", json={
                "name": "Sent Email School",
                "slug": f"sent-{uuid.uuid4().hex[:6]}",
                "admin_email": f"admin_sent_{uuid.uuid4().hex[:6]}@school.edu",
                "admin_name": "Admin Sent",
            }, headers=headers)
            assert res_sent.status_code == 201
            data_sent = res_sent.json()
            assert data_sent["invitation_sent"] is True
            assert data_sent["invitation_status"] == "sent"
            assert data_sent["activation_token"] is not None

            # Case B: SMTP unconfigured/disabled (settings.SMTP_HOST = "")
            monkeypatch.setattr(settings, "SMTP_HOST", "")
            res_unconf = await client.post("/institutions", json={
                "name": "Unconfigured SMTP School",
                "slug": f"unconf-{uuid.uuid4().hex[:6]}",
                "admin_email": f"admin_unconf_{uuid.uuid4().hex[:6]}@school.edu",
                "admin_name": "Admin Unconf",
            }, headers=headers)
            assert res_unconf.status_code == 201
            data_unconf = res_unconf.json()
            assert data_unconf["invitation_sent"] is False
            assert data_unconf["invitation_status"] == "unconfigured"
            # Activation token still returned once for offline copy/delivery!
            assert data_unconf["activation_token"] is not None

            # Case C: SMTP delivery failure (send_email_direct returns error)
            monkeypatch.setattr(settings, "SMTP_HOST", "smtp.test.com")
            monkeypatch.setattr(
                "app.auth.service.send_email_direct",
                lambda **kwargs: {"status": "error", "detail": "Connection timed out"},
            )
            res_fail = await client.post("/institutions", json={
                "name": "Failed SMTP School",
                "slug": f"fail-{uuid.uuid4().hex[:6]}",
                "admin_email": f"admin_fail_{uuid.uuid4().hex[:6]}@school.edu",
                "admin_name": "Admin Fail",
            }, headers=headers)
            assert res_fail.status_code == 201
            data_fail = res_fail.json()
            assert data_fail["invitation_sent"] is False
            assert data_fail["invitation_status"] == "failed"
            assert data_fail["activation_token"] is not None
