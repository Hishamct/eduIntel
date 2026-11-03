"""
backend/tests/test_tenant_announcements_scoping.py

Focused test suite verifying Phase 2C Stage 3, Sub-Batch 2C:
Announcements Domain Tenant Scoping.

Verifies:
1. Route scoping: All /announcements/* routes use tenant-scoped database sessions (get_tenant_db)
   and enforce TenantContext role requirements.
2. Fast rejection: Unauthenticated requests return 401; untenanted callers return 403;
   non-admin roles attempting POST /announcements/ return 403.
3. Announcement creation: Admin POST /announcements/ creates announcement with
   institution_id set from TenantContext and status 201 Created.
4. Tenant isolation: GET /announcements/ filters strictly by institution_id,
   ensuring Tenant Alpha cannot view Tenant Beta announcements.
5. Service behavior: Services use db.flush() rather than committing, and seed script
   populates institution_id.
"""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.announcements.models import Announcement
from app.announcements.seed import SAMPLE_ANNOUNCEMENTS, seed_announcements
from app.announcements.service import create_announcement, get_all_announcements
from app.auth.security import create_access_token, hash_password
from app.core.tenant import PILOT_INSTITUTION_UUID, get_tenant_db
from app.main import app
from app.users.dependencies import get_current_user
from app.users.models import AdminProfile, StudentProfile, TeacherProfile, User

# Fixed Tenant UUIDs for testing cross-tenant boundaries
TENANT_ALPHA = uuid.UUID("11111111-1111-1111-1111-111111111111")
TENANT_BETA = uuid.UUID("22222222-2222-2222-2222-222222222222")


def create_mock_user(
    role: str,
    user_id: uuid.UUID | None = None,
    institution_id: uuid.UUID | None = TENANT_ALPHA,
    email: str | None = None,
    name: str | None = None,
) -> User:
    """Helper creating mock User instances with optional tenant binding."""
    uid = user_id or uuid.uuid4()
    user = User(
        id=uid,
        email=email or f"mock_{role}_{uid.hex[:6]}@example.com",
        name=name or f"Mock {role.capitalize()}",
        hashed_password=hash_password("MockPass123!"),
        role=role,
        is_active=True,
    )
    user.institution_id = institution_id

    if role == "student":
        user.student_profile = StudentProfile(
            user_id=uid,
            institution_id=institution_id,
            grade="10",
            section="A",
        )
    elif role == "teacher":
        user.teacher_profile = TeacherProfile(
            user_id=uid,
            institution_id=institution_id,
            department="Science",
            subjects="Physics",
        )
    elif role == "admin":
        user.admin_profile = AdminProfile(
            user_id=uid,
            institution_id=institution_id,
            designation="Administrator",
        )
    return user


def make_auth_header(user: User) -> dict:
    """Helper generating bearer token authorization headers."""
    token = create_access_token({"sub": str(user.id), "role": user.role})
    return {"Authorization": f"Bearer {token}"}


def create_mock_session():
    """Helper creating a properly wired mock AsyncSession for unit tests."""
    mock_db = AsyncMock()
    added_objects = []

    mock_db.add = MagicMock(side_effect=lambda obj: added_objects.append(obj))
    mock_db.flush = AsyncMock()

    async def _mock_refresh(obj):
        if hasattr(obj, "id") and getattr(obj, "id", None) is None:
            obj.id = uuid.uuid4()
        if hasattr(obj, "created_at") and getattr(obj, "created_at", None) is None:
            obj.created_at = datetime.now(UTC)

    mock_db.refresh = AsyncMock(side_effect=_mock_refresh)
    return mock_db, added_objects


# =====================================================================
# 1. Route Scoping & Role/Tenant Authorization Guards
# =====================================================================


class TestAnnouncementRouteScopingAndAuth:
    """Tests route-level authorization, authentication, and tenant enforcement."""

    @pytest.mark.asyncio
    async def test_unauthenticated_requests_rejected(self):
        """Unauthenticated requests to /announcements/ endpoints must return 401."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            res_get = await client.get("/announcements/")
            assert res_get.status_code == 401

            res_post = await client.post(
                "/announcements/",
                json={"title": "Test Title", "body": "Test Body"},
            )
            assert res_post.status_code == 401

    @pytest.mark.asyncio
    async def test_untenanted_users_rejected_with_403(self):
        """Users without an active tenant context must receive 403 on all endpoints."""
        untenanted_admin = create_mock_user("admin", institution_id=None)
        untenanted_student = create_mock_user("student", institution_id=None)

        mock_db, _ = create_mock_session()
        app.dependency_overrides[get_tenant_db] = lambda: mock_db

        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                # Untenanted student cannot list announcements
                app.dependency_overrides[get_current_user] = lambda: untenanted_student
                headers = make_auth_header(untenanted_student)
                res = await client.get("/announcements/", headers=headers)
                assert res.status_code == 403
                assert "Tenant context required" in res.json().get("detail", "")

                # Untenanted admin cannot post announcements
                app.dependency_overrides[get_current_user] = lambda: untenanted_admin
                headers_admin = make_auth_header(untenanted_admin)
                res_post = await client.post(
                    "/announcements/",
                    headers=headers_admin,
                    json={"title": "Test Title", "body": "Test Body"},
                )
                assert res_post.status_code == 403
                assert "Tenant context required" in res_post.json().get("detail", "")
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_non_admin_cannot_post_announcement(self):
        """Students and teachers must be rejected with 403 when attempting POST /announcements/."""
        student_user = create_mock_user("student", institution_id=TENANT_ALPHA)
        teacher_user = create_mock_user("teacher", institution_id=TENANT_ALPHA)

        mock_db, _ = create_mock_session()
        app.dependency_overrides[get_tenant_db] = lambda: mock_db

        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                # Student cannot post
                app.dependency_overrides[get_current_user] = lambda: student_user
                res_student = await client.post(
                    "/announcements/",
                    headers=make_auth_header(student_user),
                    json={"title": "Hack", "body": "Body"},
                )
                assert res_student.status_code == 403

                # Teacher cannot post
                app.dependency_overrides[get_current_user] = lambda: teacher_user
                res_teacher = await client.post(
                    "/announcements/",
                    headers=make_auth_header(teacher_user),
                    json={"title": "Hack", "body": "Body"},
                )
                assert res_teacher.status_code == 403
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_all_tenanted_roles_can_list_announcements(self):
        """Student, teacher, and admin within an institution can all GET /announcements/."""
        mock_db, _ = create_mock_session()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_result)
        app.dependency_overrides[get_tenant_db] = lambda: mock_db

        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                for role in ["student", "teacher", "admin"]:
                    user = create_mock_user(role, institution_id=TENANT_ALPHA)
                    app.dependency_overrides[get_current_user] = lambda u=user: u
                    res = await client.get("/announcements/", headers=make_auth_header(user))
                    assert res.status_code == 200, f"Role {role} failed to list announcements"
                    assert res.json() == []
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_admin_can_post_announcement_status_201(self):
        """Admin can successfully POST /announcements/ and receives 201 Created with persisted data."""
        admin_user = create_mock_user(
            "admin",
            institution_id=TENANT_ALPHA,
            name="Principal Skinner",
        )
        mock_db, added = create_mock_session()
        app.dependency_overrides[get_tenant_db] = lambda: mock_db
        app.dependency_overrides[get_current_user] = lambda: admin_user

        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                res = await client.post(
                    "/announcements/",
                    headers=make_auth_header(admin_user),
                    json={
                        "title": "School Reopening",
                        "body": "Campus reopens next Monday at 8 AM.",
                    },
                )
                assert res.status_code == 201
                data = res.json()
                assert data["title"] == "School Reopening"
                assert data["body"] == "Campus reopens next Monday at 8 AM."
                assert data["posted_by"] == "Principal Skinner"
                assert "id" in data
                assert "created_at" in data

                # Verify persistence attributes
                assert len(added) == 1
                created_announcement = added[0]
                assert isinstance(created_announcement, Announcement)
                assert created_announcement.institution_id == TENANT_ALPHA
                assert created_announcement.posted_by == "Principal Skinner"
                mock_db.flush.assert_awaited_once()
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_announcement_title_validation_255_chars_accepted(self):
        """SEC-S3-05: Exactly 255-character title is accepted and returns 201 Created."""
        admin_user = create_mock_user("admin", institution_id=TENANT_ALPHA)
        mock_db, added = create_mock_session()
        app.dependency_overrides[get_tenant_db] = lambda: mock_db
        app.dependency_overrides[get_current_user] = lambda: admin_user

        valid_title_255 = "A" * 255
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                res = await client.post(
                    "/announcements/",
                    headers=make_auth_header(admin_user),
                    json={"title": valid_title_255, "body": "Valid body content."},
                )
                assert res.status_code == 201
                data = res.json()
                assert len(data["title"]) == 255
                assert data["title"] == valid_title_255
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_announcement_title_validation_over_255_chars_rejected(self):
        """SEC-S3-05: Title exceeding 255 characters is rejected with 422 Unprocessable Entity."""
        admin_user = create_mock_user("admin", institution_id=TENANT_ALPHA)
        mock_db, _ = create_mock_session()
        app.dependency_overrides[get_tenant_db] = lambda: mock_db
        app.dependency_overrides[get_current_user] = lambda: admin_user

        invalid_title_256 = "B" * 256
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                res = await client.post(
                    "/announcements/",
                    headers=make_auth_header(admin_user),
                    json={"title": invalid_title_256, "body": "Body text."},
                )
                assert res.status_code == 422
                errors = res.json().get("detail", [])
                assert any("title" in str(err.get("loc", [])) for err in errors)
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_announcement_title_validation_empty_rejected(self):
        """SEC-S3-05: Empty title string is rejected with 422 Unprocessable Entity."""
        admin_user = create_mock_user("admin", institution_id=TENANT_ALPHA)
        mock_db, _ = create_mock_session()
        app.dependency_overrides[get_tenant_db] = lambda: mock_db
        app.dependency_overrides[get_current_user] = lambda: admin_user

        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                res = await client.post(
                    "/announcements/",
                    headers=make_auth_header(admin_user),
                    json={"title": "", "body": "Body with empty title."},
                )
                assert res.status_code == 422
                errors = res.json().get("detail", [])
                assert any("title" in str(err.get("loc", [])) for err in errors)
        finally:
            app.dependency_overrides.clear()


# =====================================================================
# 2. Service Scoping & Cross-Tenant Isolation
# =====================================================================


class TestAnnouncementServiceScopingAndIsolation:
    """Verifies service functions enforce institution_id boundaries and isolate tenants."""

    @pytest.mark.asyncio
    async def test_get_all_announcements_filters_by_institution_id(self):
        """get_all_announcements must filter query strictly by Announcement.institution_id."""
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_result)

        await get_all_announcements(mock_db, institution_id=TENANT_ALPHA)

        mock_db.execute.assert_awaited_once()
        stmt = mock_db.execute.call_args[0][0]
        compiled = str(stmt.compile(compile_kwargs={"literal_binds": False}))
        assert "announcements.institution_id =" in compiled

    @pytest.mark.asyncio
    async def test_create_announcement_sets_institution_id_and_flushes(self):
        """create_announcement sets institution_id, calls db.flush(), and does NOT commit."""
        mock_db, added = create_mock_session()

        announcement = await create_announcement(
            db=mock_db,
            institution_id=TENANT_ALPHA,
            title="Science Fair",
            body="Annual science fair entries due Friday.",
            posted_by="Admin Office",
        )

        assert len(added) == 1
        assert added[0].institution_id == TENANT_ALPHA
        assert added[0].title == "Science Fair"
        assert added[0].body == "Annual science fair entries due Friday."
        assert added[0].posted_by == "Admin Office"

        mock_db.flush.assert_awaited_once()
        mock_db.refresh.assert_awaited_once_with(announcement)
        # Verify db.commit() was NOT called
        assert not hasattr(mock_db, "commit") or not mock_db.commit.called

    @pytest.mark.asyncio
    async def test_cross_tenant_announcements_isolation(self):
        """Announcements belonging to Tenant Beta must not be returned to Tenant Alpha."""
        announcement_alpha = Announcement(
            id=uuid.uuid4(),
            institution_id=TENANT_ALPHA,
            title="Tenant Alpha Only",
            body="Secret Alpha news",
            posted_by="Admin Alpha",
            created_at=datetime.now(UTC),
        )
        announcement_beta = Announcement(
            id=uuid.uuid4(),
            institution_id=TENANT_BETA,
            title="Tenant Beta Only",
            body="Secret Beta news",
            posted_by="Admin Beta",
            created_at=datetime.now(UTC),
        )

        # Mock execute to simulate SQL filtering on institution_id
        async def mock_execute(stmt):
            params = stmt.compile().params
            mock_res = MagicMock()
            if any(val == TENANT_ALPHA for val in params.values()):
                mock_res.scalars.return_value.all.return_value = [announcement_alpha]
            elif any(val == TENANT_BETA for val in params.values()):
                mock_res.scalars.return_value.all.return_value = [announcement_beta]
            else:
                mock_res.scalars.return_value.all.return_value = []
            return mock_res

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(side_effect=mock_execute)

        # Fetch for Alpha
        alpha_results = await get_all_announcements(mock_db, institution_id=TENANT_ALPHA)
        assert len(alpha_results) == 1
        assert alpha_results[0].title == "Tenant Alpha Only"
        assert alpha_results[0].institution_id == TENANT_ALPHA

        # Fetch for Beta
        beta_results = await get_all_announcements(mock_db, institution_id=TENANT_BETA)
        assert len(beta_results) == 1
        assert beta_results[0].title == "Tenant Beta Only"
        assert beta_results[0].institution_id == TENANT_BETA

    @pytest.mark.asyncio
    async def test_seed_announcements_populates_institution_id(self):
        """seed_announcements accepts institution_id and sets it on all created announcements."""
        mock_db = AsyncMock()
        added_items = []
        mock_db.add = MagicMock(side_effect=lambda item: added_items.append(item))
        mock_db.commit = AsyncMock()

        # Mock AsyncSessionLocal context manager
        mock_session_ctx = MagicMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=None)

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                "app.announcements.seed.AsyncSessionLocal",
                lambda: mock_session_ctx,
            )
            custom_inst_id = uuid.uuid4()
            await seed_announcements(institution_id=custom_inst_id)

            assert len(added_items) == len(SAMPLE_ANNOUNCEMENTS)
            for item in added_items:
                assert item.institution_id == custom_inst_id
            mock_db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_seed_announcements_defaults_to_pilot_institution(self):
        """seed_announcements defaults institution_id to PILOT_INSTITUTION_UUID."""
        mock_db = AsyncMock()
        added_items = []
        mock_db.add = MagicMock(side_effect=lambda item: added_items.append(item))
        mock_db.commit = AsyncMock()

        mock_session_ctx = MagicMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=None)

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                "app.announcements.seed.AsyncSessionLocal",
                lambda: mock_session_ctx,
            )
            await seed_announcements()

            assert len(added_items) == len(SAMPLE_ANNOUNCEMENTS)
            for item in added_items:
                assert item.institution_id == PILOT_INSTITUTION_UUID
            mock_db.commit.assert_awaited_once()
