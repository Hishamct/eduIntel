"""
backend/tests/test_tenant_student_scoping.py

Focused test suite verifying Phase 2C Stage 3, Sub-Batch 2B:
Student Academic Operations Tenant Scoping.

Verifies:
1. Route scoping: All /student/* routes require authenticated TenantContext with
   institutional role 'student' (or 'student'/'teacher'/'admin' for study-material download)
   and use tenant-scoped database sessions (get_tenant_db).
2. Fast rejection: Unauthenticated requests return 401; non-student roles and
   untenanted students return 403.
3. Homework submission & listing:
   - Homework upload persists institution_id from TenantContext and student_id from current_user.
   - Listing homework filters strictly by institution_id and student_id.
   - Service uses db.flush() instead of db.commit().
   - Cross-tenant and cross-student homework access is completely isolated.
4. Doubt threads & replies:
   - Creating a doubt thread persists institution_id on both DoubtThread and initial DoubtMessage.
   - Replying to a doubt verifies DoubtThread.institution_id == tenant.institution_id and
     DoubtThread.student_id == sender_id, rejecting cross-tenant or cross-student access with 404.
   - Listing doubts filters strictly by institution_id and student_id.
   - Service uses db.flush() instead of db.commit().
5. Student assignments:
   - Student assignments endpoint resolves student's class section within tenant context.
   - Passes mandatory institution_id to list_assignments (verifying mandatory signature).
   - Cross-tenant assignments are isolated.
6. Student dashboard:
   - Dashboard summary aggregates pending homework and unresolved doubts strictly within
     caller's institution and for caller's student_id.
7. Study material download IDOR & tenant isolation:
   - Cross-tenant download requests return 404 Not Found (non-enumerating).
   - Intra-tenant timetable enrollment and teacher ownership rules are enforced.
   - Institutional administrator access is preserved within the tenant.
"""

import os
import tempfile
import uuid
from datetime import UTC, datetime
from io import BytesIO
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from starlette.datastructures import UploadFile

from app.auth.security import create_access_token, hash_password
from app.core.tenant import get_tenant_db
from app.main import app
from app.student.models import DoubtMessage, DoubtThread
from app.student.service import (
    add_doubt_message,
    create_doubt_thread,
    get_dashboard_summary,
    list_doubt_threads,
    list_study_materials_for_student,
    save_homework_submission,
)
from app.teacher.models import StudyMaterial
from app.teacher.service import list_assignments
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
) -> User:
    """Helper creating mock User instances with optional tenant binding."""
    uid = user_id or uuid.uuid4()
    user = User(
        id=uid,
        email=email or f"mock_{role}_{uid.hex[:6]}@example.com",
        name=f"Mock {role.capitalize()}",
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
        if hasattr(obj, "status") and getattr(obj, "status", None) is None:
            obj.status = "submitted"

    mock_db.refresh = AsyncMock(side_effect=_mock_refresh)
    return mock_db, added_objects


# =====================================================================
# 1. Route Scoping & Role/Tenant Authorization Guards
# =====================================================================


class TestStudentRouteScopingAndAuth:
    """Verifies that /student/* routes enforce authentication, student role, and active tenant context."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("method", "endpoint", "payload"),
        [
            ("GET", "/student/dashboard", None),
            ("GET", "/student/homework", None),
            ("GET", "/student/doubts", None),
            (
                "POST",
                "/student/doubts",
                {"subject": "Math", "title": "Calculus", "body": "Help with derivatives"},
            ),
            (
                "POST",
                f"/student/doubts/{uuid.uuid4()}/messages",
                {"body": "Follow up question"},
            ),
            ("GET", "/student/assignments", None),
            ("GET", "/student/study-materials", None),
            ("GET", f"/student/study-materials/{uuid.uuid4()}/file", None),
        ],
    )
    async def test_student_routes_reject_unauthenticated_with_401(
        self, method: str, endpoint: str, payload: dict | None
    ):
        """Unauthenticated requests to any /student/* endpoint must return 401 Unauthorized."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            if method == "GET":
                resp = await client.get(endpoint)
            elif method == "POST":
                resp = await client.post(endpoint, json=payload)
            assert resp.status_code == 401

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("method", "endpoint", "payload"),
        [
            ("GET", "/student/dashboard", None),
            ("GET", "/student/homework", None),
            ("GET", "/student/doubts", None),
            (
                "POST",
                "/student/doubts",
                {"subject": "Math", "title": "Calculus", "body": "Help with derivatives"},
            ),
            (
                "POST",
                f"/student/doubts/{uuid.uuid4()}/messages",
                {"body": "Follow up question"},
            ),
            ("GET", "/student/assignments", None),
            ("GET", "/student/study-materials", None),
        ],
    )
    async def test_student_routes_reject_teacher_role_with_403(self, method: str, endpoint: str, payload: dict | None):
        """Teacher calling student-only routes must be rejected with 403 Forbidden."""
        teacher = create_mock_user("teacher", institution_id=TENANT_ALPHA)
        app.dependency_overrides[get_current_user] = lambda: teacher

        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                headers = make_auth_header(teacher)
                if method == "GET":
                    resp = await client.get(endpoint, headers=headers)
                elif method == "POST":
                    resp = await client.post(endpoint, json=payload, headers=headers)
                assert resp.status_code == 403
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("method", "endpoint", "payload"),
        [
            ("GET", "/student/dashboard", None),
            ("GET", "/student/homework", None),
            ("GET", "/student/doubts", None),
            (
                "POST",
                "/student/doubts",
                {"subject": "Math", "title": "Calculus", "body": "Help with derivatives"},
            ),
            (
                "POST",
                f"/student/doubts/{uuid.uuid4()}/messages",
                {"body": "Follow up question"},
            ),
            ("GET", "/student/assignments", None),
            ("GET", "/student/study-materials", None),
        ],
    )
    async def test_student_routes_reject_admin_role_with_403(self, method: str, endpoint: str, payload: dict | None):
        """Administrator calling student-only routes must be rejected with 403 Forbidden."""
        admin = create_mock_user("admin", institution_id=TENANT_ALPHA)
        app.dependency_overrides[get_current_user] = lambda: admin

        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                headers = make_auth_header(admin)
                if method == "GET":
                    resp = await client.get(endpoint, headers=headers)
                elif method == "POST":
                    resp = await client.post(endpoint, json=payload, headers=headers)
                assert resp.status_code == 403
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_student_routes_reject_untenanted_student_with_403(self):
        """Student without active institution context must be rejected with 403 Forbidden."""
        student_untenanted = create_mock_user("student", institution_id=None)
        app.dependency_overrides[get_current_user] = lambda: student_untenanted

        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                headers = make_auth_header(student_untenanted)
                resp = await client.get("/student/dashboard", headers=headers)
                assert resp.status_code == 403
                assert "Tenant context required" in resp.json()["detail"]
        finally:
            app.dependency_overrides.clear()


# =====================================================================
# 2. Homework Submission Scoping & Listing Isolation
# =====================================================================


class TestStudentHomeworkScoping:
    """Verifies that homework submission and listing are strictly scoped to the tenant and student."""

    @pytest.mark.asyncio
    async def test_save_homework_submission_populates_institution_id_and_flushes(self):
        """save_homework_submission must populate institution_id and student_id, and call db.flush()."""
        mock_db, added = create_mock_session()
        student_id = uuid.uuid4()

        mock_file = MagicMock()
        mock_file.filename = "homework_solution.pdf"
        mock_file.content_type = "application/pdf"
        mock_file.read = AsyncMock(return_value=b"%PDF-1.4 sample homework content")

        with patch("aiofiles.open", return_value=AsyncMock()) as mock_aiofile:
            mock_aiofile.return_value.__aenter__.return_value = AsyncMock()

            submission = await save_homework_submission(
                db=mock_db,
                institution_id=TENANT_ALPHA,
                student_id=student_id,
                subject="Physics",
                title="Mechanics Problem Set 1",
                description="Completed questions 1-10",
                file=mock_file,
            )

            assert submission.institution_id == TENANT_ALPHA
            assert submission.student_id == student_id
            assert submission.subject == "Physics"
            assert submission.title == "Mechanics Problem Set 1"
            assert len(added) == 1
            assert added[0] == submission
            mock_db.flush.assert_awaited_once()
            mock_db.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_upload_homework_route_scoped_to_tenant_and_student(self):
        """POST /student/homework/upload must populate institution_id and student_id from context."""
        student = create_mock_user("student", institution_id=TENANT_ALPHA)
        mock_db, added = create_mock_session()

        app.dependency_overrides[get_current_user] = lambda: student
        app.dependency_overrides[get_tenant_db] = lambda: mock_db

        try:
            with patch("aiofiles.open", return_value=AsyncMock()) as mock_aiofile:
                mock_aiofile.return_value.__aenter__.return_value = AsyncMock()

                transport = ASGITransport(app=app)
                async with AsyncClient(transport=transport, base_url="http://test") as client:
                    headers = make_auth_header(student)
                    files = {"file": ("homework.pdf", b"%PDF-1.4 test", "application/pdf")}
                    data = {
                        "subject": "Chemistry",
                        "title": "Stoichiometry HW",
                        "description": "Lab equations",
                    }
                    resp = await client.post(
                        "/student/homework/upload",
                        data=data,
                        files=files,
                        headers=headers,
                    )
                    assert resp.status_code == 200
                    payload = resp.json()
                    assert payload["subject"] == "Chemistry"
                    assert payload["title"] == "Stoichiometry HW"
                    assert len(added) == 1
                    assert added[0].institution_id == TENANT_ALPHA
                    assert added[0].student_id == student.id
                    mock_db.flush.assert_awaited_once()
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("malicious_filename", "expected_sanitized"),
        [
            ("../../../../etc/passwd", "passwd"),
            ("/etc/shadow", "shadow"),
            ("..\\..\\windows\\system32\\cmd.exe", "cmd.exe"),
            ("   ", "upload"),
            ("///", "upload"),
            ("valid_homework.pdf", "valid_homework.pdf"),
        ],
    )
    async def test_upload_homework_filename_sanitization_sec_s3_02(
        self, malicious_filename: str, expected_sanitized: str
    ):
        """
        SEC-S3-02: Verifies that filenames containing path traversal, absolute paths,
        or empty strings are strictly sanitized with os.path.basename and cannot escape UPLOAD_DIR.
        """
        student = create_mock_user("student", institution_id=TENANT_ALPHA)
        mock_db, added = create_mock_session()

        app.dependency_overrides[get_current_user] = lambda: student
        app.dependency_overrides[get_tenant_db] = lambda: mock_db

        try:
            with patch("aiofiles.open", return_value=AsyncMock()) as mock_aiofile:
                mock_aiofile.return_value.__aenter__.return_value = AsyncMock()

                transport = ASGITransport(app=app)
                async with AsyncClient(transport=transport, base_url="http://test") as client:
                    headers = make_auth_header(student)
                    files = {"file": (malicious_filename, b"submission bytes", "application/pdf")}
                    data = {
                        "subject": "Physics",
                        "title": "Kinematics HW",
                    }
                    resp = await client.post(
                        "/student/homework/upload",
                        data=data,
                        files=files,
                        headers=headers,
                    )
                    assert resp.status_code == 200
                    assert len(added) == 1
                    submission = added[0]

                    # 1. Original filename must be sanitized without path separators
                    assert submission.original_filename == expected_sanitized
                    assert "/" not in submission.original_filename
                    assert "\\" not in submission.original_filename
                    assert ".." not in submission.original_filename

                    # 2. Storage file_path must reside strictly within uploads/homework
                    assert submission.file_path.startswith("uploads/homework/")
                    assert submission.file_path.endswith(f"_{expected_sanitized}")
                    assert ".." not in submission.file_path
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("empty_filename", ["", None, "   "])
    async def test_save_homework_submission_empty_filename_sanitization_sec_s3_02(self, empty_filename: str | None):
        """
        SEC-S3-02: Verifies that save_homework_submission safely handles empty or None filenames.
        """
        mock_db, added = create_mock_session()
        upload_file = UploadFile(file=BytesIO(b"data"), filename=empty_filename)

        with patch("aiofiles.open", return_value=AsyncMock()) as mock_aiofile:
            mock_aiofile.return_value.__aenter__.return_value = AsyncMock()
            sub = await save_homework_submission(
                db=mock_db,
                institution_id=TENANT_ALPHA,
                student_id=uuid.uuid4(),
                subject="Physics",
                title="Kinematics HW",
                description="test",
                file=upload_file,
            )
            assert sub.original_filename == "upload"
            assert sub.file_path.startswith("uploads/homework/")
            assert sub.file_path.endswith("_upload")

    @pytest.mark.asyncio
    async def test_list_homework_route_filters_by_institution_and_student(self):
        """GET /student/homework must query with institution_id and student_id filters."""
        student = create_mock_user("student", institution_id=TENANT_ALPHA)
        mock_db = AsyncMock()
        mock_res = MagicMock()
        mock_res.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_res)

        app.dependency_overrides[get_current_user] = lambda: student
        app.dependency_overrides[get_tenant_db] = lambda: mock_db

        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                headers = make_auth_header(student)
                resp = await client.get("/student/homework", headers=headers)
                assert resp.status_code == 200

                executed_query = str(mock_db.execute.call_args[0][0]).lower()
                assert "homework_submissions.institution_id =" in executed_query
                assert "homework_submissions.student_id =" in executed_query
        finally:
            app.dependency_overrides.clear()


# =====================================================================
# 3. Doubt Threads & Messages Scoping
# =====================================================================


class TestStudentDoubtScoping:
    """Verifies that doubt thread creation, listing, and messaging are tenant- and student-scoped."""

    @pytest.mark.asyncio
    async def test_create_doubt_thread_populates_institution_id_and_flushes(self):
        """create_doubt_thread must populate institution_id on both DoubtThread and DoubtMessage."""
        mock_db, added = create_mock_session()
        student_id = uuid.uuid4()

        # Mock the re-fetch execute call
        mock_thread = DoubtThread(
            id=uuid.uuid4(),
            institution_id=TENANT_ALPHA,
            student_id=student_id,
            subject="Mathematics",
            title="Integrals question",
            status="open",
            created_at=datetime.now(UTC),
        )
        mock_message = DoubtMessage(
            id=uuid.uuid4(),
            institution_id=TENANT_ALPHA,
            thread_id=mock_thread.id,
            sender_id=student_id,
            sender_role="student",
            body="How to integrate e^(2x)?",
            created_at=datetime.now(UTC),
        )
        mock_thread.messages = [mock_message]

        mock_res = MagicMock()
        mock_res.scalar_one.return_value = mock_thread
        mock_db.execute = AsyncMock(return_value=mock_res)

        thread = await create_doubt_thread(
            db=mock_db,
            institution_id=TENANT_ALPHA,
            student_id=student_id,
            subject="Mathematics",
            title="Integrals question",
            body="How to integrate e^(2x)?",
        )

        assert thread.institution_id == TENANT_ALPHA
        assert thread.student_id == student_id
        # Verify two objects added: thread and message
        assert len(added) == 2
        thread_obj, msg_obj = added[0], added[1]
        assert isinstance(thread_obj, DoubtThread)
        assert thread_obj.institution_id == TENANT_ALPHA
        assert isinstance(msg_obj, DoubtMessage)
        assert msg_obj.institution_id == TENANT_ALPHA
        assert msg_obj.sender_id == student_id
        assert msg_obj.sender_role == "student"

        # Verify db.flush was called (twice: once for thread, once for message)
        assert mock_db.flush.await_count == 2
        mock_db.commit.assert_not_called()

        # Verify re-fetch query filters
        executed_query = str(mock_db.execute.call_args[0][0]).lower()
        assert "doubt_threads.institution_id =" in executed_query
        assert "doubt_threads.student_id =" in executed_query

    @pytest.mark.asyncio
    async def test_add_doubt_message_cross_tenant_rejected_with_404(self):
        """add_doubt_message must reject thread from another tenant with 404 Not Found."""
        mock_db = AsyncMock()
        # Query returns None because thread belongs to TENANT_BETA, not TENANT_ALPHA
        mock_res = MagicMock()
        mock_res.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_res)

        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            await add_doubt_message(
                db=mock_db,
                institution_id=TENANT_ALPHA,
                thread_id=uuid.uuid4(),
                sender_id=uuid.uuid4(),
                sender_role="student",
                body="Cross tenant attempt",
            )
        assert exc_info.value.status_code == 404
        assert "Doubt thread not found" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_add_doubt_message_cross_student_rejected_with_404(self):
        """add_doubt_message must reject student attempting to reply to another student's thread."""
        mock_db = AsyncMock()
        # Query returns None because student_id filter does not match
        mock_res = MagicMock()
        mock_res.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_res)

        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            await add_doubt_message(
                db=mock_db,
                institution_id=TENANT_ALPHA,
                thread_id=uuid.uuid4(),
                sender_id=uuid.uuid4(),
                sender_role="student",
                body="Cross student attempt",
            )
        assert exc_info.value.status_code == 404
        assert "Doubt thread not found" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_add_doubt_message_success_sets_institution_id_and_flushes(self):
        """add_doubt_message within same tenant and student must populate institution_id and flush."""
        mock_db, added = create_mock_session()
        student_id = uuid.uuid4()
        thread_id = uuid.uuid4()

        mock_thread = DoubtThread(
            id=thread_id,
            institution_id=TENANT_ALPHA,
            student_id=student_id,
            subject="Physics",
            title="Quantum wavefunctions",
            status="open",
            created_at=datetime.now(UTC),
        )
        mock_thread.messages = []

        mock_res = MagicMock()
        mock_res.scalar_one_or_none.return_value = mock_thread
        mock_res.scalar_one.return_value = mock_thread
        mock_db.execute = AsyncMock(return_value=mock_res)

        result_thread = await add_doubt_message(
            db=mock_db,
            institution_id=TENANT_ALPHA,
            thread_id=thread_id,
            sender_id=student_id,
            sender_role="student",
            body="I understand now, thank you!",
        )

        assert result_thread.id == thread_id
        assert len(added) == 1
        msg = added[0]
        assert isinstance(msg, DoubtMessage)
        assert msg.institution_id == TENANT_ALPHA
        assert msg.thread_id == thread_id
        assert msg.sender_id == student_id
        mock_db.flush.assert_awaited_once()
        mock_db.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_list_doubt_threads_filters_by_institution_and_student(self):
        """list_doubt_threads must filter by both institution_id and student_id."""
        mock_db = AsyncMock()
        mock_res = MagicMock()
        mock_res.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_res)
        student_id = uuid.uuid4()

        await list_doubt_threads(
            db=mock_db,
            institution_id=TENANT_ALPHA,
            student_id=student_id,
        )

        executed_query = str(mock_db.execute.call_args[0][0]).lower()
        assert "doubt_threads.institution_id =" in executed_query
        assert "doubt_threads.student_id =" in executed_query


# =====================================================================
# 4. Student Assignments Scoping & Mandatory Parameter Verification
# =====================================================================


class TestStudentAssignmentScoping:
    """Verifies that student assignment listing is scoped to tenant and class section."""

    @pytest.mark.asyncio
    async def test_student_assignments_scoped_to_tenant_and_class_section(self):
        """GET /student/assignments resolves student section and passes institution_id to list_assignments."""
        student = create_mock_user("student", institution_id=TENANT_ALPHA)
        student.student_profile.grade = "10"
        student.student_profile.section = "A"

        mock_db = AsyncMock()
        # First query: StudentProfile
        mock_prof_res = MagicMock()
        mock_prof_res.scalar_one_or_none.return_value = student.student_profile

        # Second query: list_assignments
        mock_assign_res = MagicMock()
        mock_assign_res.scalars.return_value.all.return_value = []

        mock_db.execute = AsyncMock(side_effect=[mock_prof_res, mock_assign_res])

        app.dependency_overrides[get_current_user] = lambda: student
        app.dependency_overrides[get_tenant_db] = lambda: mock_db

        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                headers = make_auth_header(student)
                resp = await client.get("/student/assignments", headers=headers)
                assert resp.status_code == 200

                # Verify profile query scoped to tenant
                prof_query = str(mock_db.execute.call_args_list[0][0][0]).lower()
                assert "student_profiles.user_id =" in prof_query
                assert "student_profiles.institution_id =" in prof_query

                # Verify assignments query scoped to tenant and section 10-A
                assign_query = str(mock_db.execute.call_args_list[1][0][0]).lower()
                assert "assignments.institution_id =" in assign_query
                assert "assignments.class_section =" in assign_query
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_student_assignments_without_profile_passes_none_section(self):
        """Student without grade/section passes class_section=None to list_assignments."""
        student = create_mock_user("student", institution_id=TENANT_ALPHA)
        student.student_profile.grade = None
        student.student_profile.section = None

        mock_db = AsyncMock()
        mock_prof_res = MagicMock()
        mock_prof_res.scalar_one_or_none.return_value = student.student_profile
        mock_assign_res = MagicMock()
        mock_assign_res.scalars.return_value.all.return_value = []

        mock_db.execute = AsyncMock(side_effect=[mock_prof_res, mock_assign_res])

        app.dependency_overrides[get_current_user] = lambda: student
        app.dependency_overrides[get_tenant_db] = lambda: mock_db

        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                headers = make_auth_header(student)
                resp = await client.get("/student/assignments", headers=headers)
                assert resp.status_code == 200

                assign_query = str(mock_db.execute.call_args_list[1][0][0]).lower()
                assert "assignments.institution_id =" in assign_query
                # No class_section filter should be present
                assert "assignments.class_section =" not in assign_query
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_list_assignments_requires_mandatory_institution_id(self):
        """SEC-S3-01 resolution check: list_assignments cannot be called without institution_id."""
        mock_db = AsyncMock()

        # Calling without institution_id must fail at the Python signature level
        with pytest.raises(TypeError, match="missing 1 required positional argument: 'institution_id'"):
            await list_assignments(db=mock_db)  # type: ignore

        # Calling with institution_id applies WHERE clause
        mock_res = MagicMock()
        mock_res.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_res)

        await list_assignments(db=mock_db, institution_id=TENANT_ALPHA)
        executed_query = str(mock_db.execute.call_args[0][0]).lower()
        assert "assignments.institution_id =" in executed_query


# =====================================================================
# 5. Study Materials Scoping
# =====================================================================


class TestStudentStudyMaterialScoping:
    """Verifies that study material listings for students are tenant-scoped."""

    @pytest.mark.asyncio
    async def test_list_study_materials_for_student_filters_by_institution_id(self):
        """list_study_materials_for_student must filter by institution_id."""
        mock_db = AsyncMock()
        mock_res = MagicMock()
        mock_res.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_res)

        await list_study_materials_for_student(
            db=mock_db,
            institution_id=TENANT_ALPHA,
            subject="Biology",
        )

        executed_query = str(mock_db.execute.call_args[0][0]).lower()
        assert "study_materials.institution_id =" in executed_query
        assert "study_materials.subject =" in executed_query

    @pytest.mark.asyncio
    async def test_get_study_materials_route_passes_tenant_context(self):
        """GET /student/study-materials must pass tenant.institution_id."""
        student = create_mock_user("student", institution_id=TENANT_ALPHA)
        mock_db = AsyncMock()
        mock_res = MagicMock()
        mock_res.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_res)

        app.dependency_overrides[get_current_user] = lambda: student
        app.dependency_overrides[get_tenant_db] = lambda: mock_db

        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                headers = make_auth_header(student)
                resp = await client.get("/student/study-materials?subject=Chemistry", headers=headers)
                assert resp.status_code == 200

                executed_query = str(mock_db.execute.call_args[0][0]).lower()
                assert "study_materials.institution_id =" in executed_query
                assert "study_materials.subject =" in executed_query
        finally:
            app.dependency_overrides.clear()


# =====================================================================
# 6. Student Dashboard Scoping
# =====================================================================


class TestStudentDashboardScoping:
    """Verifies that student dashboard metrics and activity are strictly scoped to the tenant and student."""

    @pytest.mark.asyncio
    async def test_get_dashboard_summary_scoped_to_institution_and_student(self):
        """get_dashboard_summary queries must include institution_id and student_id filters."""
        mock_db = AsyncMock()
        student_id = uuid.uuid4()

        # Count 1: pending homework
        mock_hw_cnt = MagicMock()
        mock_hw_cnt.scalar_one.return_value = 2

        # Count 2: unresolved doubts
        mock_doubt_cnt = MagicMock()
        mock_doubt_cnt.scalar_one.return_value = 1

        # Query 3: recent homework
        mock_hw_recent = MagicMock()
        mock_hw_recent.scalars.return_value.all.return_value = []

        # Query 4: recent doubts
        mock_doubt_recent = MagicMock()
        mock_doubt_recent.scalars.return_value.all.return_value = []

        mock_db.execute = AsyncMock(side_effect=[mock_hw_cnt, mock_doubt_cnt, mock_hw_recent, mock_doubt_recent])

        summary = await get_dashboard_summary(
            db=mock_db,
            institution_id=TENANT_ALPHA,
            student_id=student_id,
        )

        assert summary["pending_homework"] == 2
        assert summary["unresolved_doubts"] == 1
        assert summary["recent_activity"] == []

        for call in mock_db.execute.call_args_list:
            q = str(call[0][0]).lower()
            assert "institution_id =" in q
            assert "student_id =" in q

    @pytest.mark.asyncio
    async def test_student_dashboard_route_passes_tenant_context(self):
        """GET /student/dashboard must execute tenant-scoped queries."""
        student = create_mock_user("student", institution_id=TENANT_ALPHA)
        mock_db = AsyncMock()

        mock_hw_cnt = MagicMock()
        mock_hw_cnt.scalar_one.return_value = 0
        mock_doubt_cnt = MagicMock()
        mock_doubt_cnt.scalar_one.return_value = 0
        mock_hw_recent = MagicMock()
        mock_hw_recent.scalars.return_value.all.return_value = []
        mock_doubt_recent = MagicMock()
        mock_doubt_recent.scalars.return_value.all.return_value = []

        mock_db.execute = AsyncMock(side_effect=[mock_hw_cnt, mock_doubt_cnt, mock_hw_recent, mock_doubt_recent])

        app.dependency_overrides[get_current_user] = lambda: student
        app.dependency_overrides[get_tenant_db] = lambda: mock_db

        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                headers = make_auth_header(student)
                resp = await client.get("/student/dashboard", headers=headers)
                assert resp.status_code == 200
                data = resp.json()
                assert data["homework_count"] == 0
                assert data["unresolved_doubts"] == 0
                assert data["role"] == "student"
        finally:
            app.dependency_overrides.clear()


# =====================================================================
# 7. Study Material File Download IDOR & Tenant Isolation
# =====================================================================


class TestStudentStudyMaterialDownloadScoping:
    """Verifies that study material file download enforces strict tenant and IDOR isolation."""

    @pytest.mark.asyncio
    async def test_study_material_download_cross_tenant_returns_404(self):
        """Download request for material belonging to Tenant Beta by Tenant Alpha user returns 404."""
        student_alpha = create_mock_user("student", institution_id=TENANT_ALPHA)
        material_beta_id = uuid.uuid4()

        mock_db = AsyncMock()
        # Query for StudyMaterial in TENANT_ALPHA returns None
        mock_res = MagicMock()
        mock_res.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_res)

        app.dependency_overrides[get_current_user] = lambda: student_alpha
        app.dependency_overrides[get_tenant_db] = lambda: mock_db

        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                headers = make_auth_header(student_alpha)
                resp = await client.get(
                    f"/student/study-materials/{material_beta_id}/file",
                    headers=headers,
                )
                assert resp.status_code == 404
                assert "Study material not found" in resp.json()["detail"]

                # Confirm the query looked for material in TENANT_ALPHA
                executed_query = str(mock_db.execute.call_args[0][0]).lower()
                assert "study_materials.institution_id =" in executed_query
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_study_material_download_enrolled_student_same_tenant_success(self):
        """Enrolled student within Tenant Alpha successfully downloads material."""
        student_alpha = create_mock_user("student", institution_id=TENANT_ALPHA)
        student_alpha.student_profile.grade = "10"
        student_alpha.student_profile.section = "A"

        with tempfile.NamedTemporaryFile(delete=False) as tf:
            tf.write(b"Tenant Alpha Physics Lecture Notes")
            temp_path = tf.name

        try:
            material = StudyMaterial(
                id=uuid.uuid4(),
                institution_id=TENANT_ALPHA,
                teacher_id=uuid.uuid4(),
                subject="Physics",
                title="Mechanics",
                file_path=temp_path,
                original_filename="mechanics.pdf",
            )

            mock_db = AsyncMock()

            async def mock_execute(query):
                q = str(query).lower()
                res = MagicMock()
                if "study_materials" in q:
                    res.scalar_one_or_none.return_value = material
                elif "student_profiles" in q:
                    res.scalar_one_or_none.return_value = student_alpha.student_profile
                elif "timetable_entries" in q:
                    # Student's section 10-A is scheduled for Physics
                    assert "timetable_entries.institution_id =" in q
                    res.scalar_one_or_none.return_value = uuid.uuid4()
                return res

            mock_db.execute = AsyncMock(side_effect=mock_execute)

            app.dependency_overrides[get_current_user] = lambda: student_alpha
            app.dependency_overrides[get_tenant_db] = lambda: mock_db

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                headers = make_auth_header(student_alpha)
                resp = await client.get(
                    f"/student/study-materials/{material.id}/file",
                    headers=headers,
                )
                assert resp.status_code == 200
                assert resp.content == b"Tenant Alpha Physics Lecture Notes"
        finally:
            app.dependency_overrides.clear()
            if os.path.exists(temp_path):
                os.remove(temp_path)

    @pytest.mark.asyncio
    async def test_study_material_download_unenrolled_student_same_tenant_returns_403(self):
        """Student in Tenant Alpha not scheduled for subject on Timetable is rejected with 403."""
        student_alpha = create_mock_user("student", institution_id=TENANT_ALPHA)
        student_alpha.student_profile.grade = "8"
        student_alpha.student_profile.section = "B"

        with tempfile.NamedTemporaryFile(delete=False) as tf:
            tf.write(b"Tenant Alpha Advanced Biology Notes")
            temp_path = tf.name

        try:
            material = StudyMaterial(
                id=uuid.uuid4(),
                institution_id=TENANT_ALPHA,
                teacher_id=uuid.uuid4(),
                subject="Biology",
                title="Advanced Biology",
                file_path=temp_path,
                original_filename="bio.pdf",
            )

            mock_db = AsyncMock()

            async def mock_execute(query):
                q = str(query).lower()
                res = MagicMock()
                if "study_materials" in q:
                    res.scalar_one_or_none.return_value = material
                elif "student_profiles" in q:
                    res.scalar_one_or_none.return_value = student_alpha.student_profile
                elif "timetable_entries" in q:
                    # 8-B does not have Biology
                    res.scalar_one_or_none.return_value = None
                return res

            mock_db.execute = AsyncMock(side_effect=mock_execute)

            app.dependency_overrides[get_current_user] = lambda: student_alpha
            app.dependency_overrides[get_tenant_db] = lambda: mock_db

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                headers = make_auth_header(student_alpha)
                resp = await client.get(
                    f"/student/study-materials/{material.id}/file",
                    headers=headers,
                )
                assert resp.status_code == 403
                assert "not enrolled in any class section for this subject" in resp.json()["detail"]
        finally:
            app.dependency_overrides.clear()
            if os.path.exists(temp_path):
                os.remove(temp_path)

    @pytest.mark.asyncio
    async def test_study_material_download_enforces_tenant_role_not_global_role_sec_s3_03(self):
        """
        SEC-S3-03: Verifies that download authorization uses tenant.role rather than current_user.role.
        A user with global role 'admin' whose active membership role in Tenant Alpha is 'student'
        must be subjected to the student timetable enrollment check and rejected with 403 when not enrolled.
        """
        user = create_mock_user("admin", institution_id=TENANT_ALPHA)
        user.tenant_role = "student"
        user.student_profile = StudentProfile(
            user_id=user.id,
            institution_id=TENANT_ALPHA,
            grade="10",
            section="B",
        )

        with tempfile.NamedTemporaryFile(delete=False) as tf:
            tf.write(b"Advanced Biology Handout")
            temp_path = tf.name

        try:
            material = StudyMaterial(
                id=uuid.uuid4(),
                institution_id=TENANT_ALPHA,
                teacher_id=uuid.uuid4(),
                subject="Biology",
                title="Cell Division",
                file_path=temp_path,
                original_filename="biology.pdf",
            )

            mock_db = AsyncMock()

            async def mock_execute(query):
                q = str(query).lower()
                res = MagicMock()
                if "study_materials" in q:
                    res.scalar_one_or_none.return_value = material
                elif "student_profiles" in q:
                    res.scalar_one_or_none.return_value = user.student_profile
                elif "timetable_entries" in q:
                    res.scalar_one_or_none.return_value = None
                return res

            mock_db.execute = AsyncMock(side_effect=mock_execute)

            app.dependency_overrides[get_current_user] = lambda: user
            app.dependency_overrides[get_tenant_db] = lambda: mock_db

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                headers = make_auth_header(user)
                resp = await client.get(
                    f"/student/study-materials/{material.id}/file",
                    headers=headers,
                )
                assert resp.status_code == 403
                assert "You are not enrolled in any class section for this subject" in resp.json()["detail"]
        finally:
            app.dependency_overrides.clear()
            if os.path.exists(temp_path):
                os.remove(temp_path)

    @pytest.mark.asyncio
    async def test_study_material_download_teacher_tenant_role_with_student_global_role_sec_s3_03(self):
        """
        SEC-S3-03: Verifies that a user with global role 'student' whose active membership role
        in Tenant Alpha is 'teacher' is authorized as a teacher and can download material they uploaded.
        """
        user = create_mock_user("student", institution_id=TENANT_ALPHA)
        user.tenant_role = "teacher"

        with tempfile.NamedTemporaryFile(delete=False) as tf:
            tf.write(b"Teacher-Created Chemistry Lab")
            temp_path = tf.name

        try:
            material = StudyMaterial(
                id=uuid.uuid4(),
                institution_id=TENANT_ALPHA,
                teacher_id=user.id,
                subject="Chemistry",
                title="Lab Notes",
                file_path=temp_path,
                original_filename="chem_lab.pdf",
            )

            mock_db = AsyncMock()
            mock_res = MagicMock()
            mock_res.scalar_one_or_none.return_value = material
            mock_db.execute = AsyncMock(return_value=mock_res)

            app.dependency_overrides[get_current_user] = lambda: user
            app.dependency_overrides[get_tenant_db] = lambda: mock_db

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                headers = make_auth_header(user)
                resp = await client.get(
                    f"/student/study-materials/{material.id}/file",
                    headers=headers,
                )
                assert resp.status_code == 200
                assert resp.content == b"Teacher-Created Chemistry Lab"
        finally:
            app.dependency_overrides.clear()
            if os.path.exists(temp_path):
                os.remove(temp_path)
