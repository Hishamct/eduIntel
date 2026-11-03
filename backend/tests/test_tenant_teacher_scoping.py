"""
backend/tests/test_tenant_teacher_scoping.py

Focused test suite verifying Phase 2C Stage 3, Sub-Batch 2A:
Teacher Academic Operations Tenant Scoping.

Verifies:
1. Route scoping: All /teacher/* routes require authenticated TenantContext with
   institutional role 'teacher' (or 'teacher'/'admin' for file download) and
   use tenant-scoped database sessions (get_tenant_db).
2. Fast rejection: Unauthenticated requests return 401; non-teacher roles and
   untenanted teachers return 403.
3. Assignment creation and listing:
   - Creating assignments populates institution_id from TenantContext.
   - Listing assignments filters strictly by institution_id.
   - Cross-tenant assignment access is completely isolated.
4. Study materials & RAG ingestion:
   - Study material persistence sets institution_id from TenantContext.
   - RAG ingestion receives the canonical institution UUID string.
   - Listing study materials filters strictly by institution_id.
5. Grading isolation:
   - Grading a homework submission verifies submission.institution_id == tenant.institution_id.
   - Cross-tenant grading attempts return HTTP 404 Not Found.
   - Service uses db.flush() instead of db.commit().
6. Dashboard & Student directory:
   - Dashboard summary aggregates submissions strictly within caller's institution.
   - Student directory filters StudentProfile strictly by caller's institution.
7. Homework file download IDOR & tenant isolation:
   - Cross-tenant download requests return 404 Not Found.
   - Intra-tenant timetable assignment and grader authorization rules are enforced.
   - Institutional administrator access is preserved within the tenant.
"""

import os
import tempfile
import uuid
from datetime import UTC, date, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.auth.security import create_access_token, hash_password
from app.core.tenant import get_tenant_db
from app.main import app
from app.student.models import HomeworkSubmission
from app.teacher.models import Assignment
from app.teacher.service import (
    create_assignment,
    get_teacher_dashboard_summary,
    grade_homework_submission,
    list_assignments,
    list_students_for_teacher,
    list_study_materials,
    save_study_material,
)
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
        user.student_profile = StudentProfile(user_id=uid, institution_id=institution_id, grade="10", section="A")
    elif role == "teacher":
        user.teacher_profile = TeacherProfile(
            user_id=uid,
            institution_id=institution_id,
            department="Science",
            subjects="Physics",
        )
    elif role == "admin":
        user.admin_profile = AdminProfile(user_id=uid, institution_id=institution_id, designation="Administrator")
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


class TestTeacherRouteScopingAndAuth:
    """Verifies that all /teacher/* routes enforce authentication, teacher role, and active tenant context."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("method", "endpoint", "payload"),
        [
            ("GET", "/teacher/dashboard", None),
            ("GET", "/teacher/homework", None),
            ("GET", "/teacher/assignments", None),
            ("GET", "/teacher/study-materials", None),
            ("GET", "/teacher/students", None),
            (
                "POST",
                "/teacher/assignments",
                {
                    "title": "Quantum Mechanics HW",
                    "subject": "Physics",
                    "class_section": "10-A",
                    "max_score": 100,
                },
            ),
            (
                "PATCH",
                f"/teacher/homework/{uuid.uuid4()}/grade",
                {"score": 95, "max_score": 100, "feedback": "Great job"},
            ),
            (
                "GET",
                f"/teacher/homework/{uuid.uuid4()}/file",
                None,
            ),
        ],
    )
    async def test_teacher_routes_reject_unauthenticated_with_401(
        self, method: str, endpoint: str, payload: dict | None
    ):
        """Unauthenticated requests to any /teacher/* endpoint must return 401 Unauthorized."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            if method == "GET":
                resp = await client.get(endpoint)
            elif method == "POST":
                resp = await client.post(endpoint, json=payload)
            elif method == "PATCH":
                resp = await client.patch(endpoint, json=payload)
            assert resp.status_code == 401

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("method", "endpoint", "payload"),
        [
            ("GET", "/teacher/dashboard", None),
            ("GET", "/teacher/homework", None),
            ("GET", "/teacher/assignments", None),
            ("GET", "/teacher/study-materials", None),
            ("GET", "/teacher/students", None),
            (
                "POST",
                "/teacher/assignments",
                {
                    "title": "Quantum Mechanics HW",
                    "subject": "Physics",
                    "class_section": "10-A",
                    "max_score": 100,
                },
            ),
            (
                "PATCH",
                f"/teacher/homework/{uuid.uuid4()}/grade",
                {"score": 95, "max_score": 100, "feedback": "Great job"},
            ),
        ],
    )
    async def test_teacher_routes_reject_non_teacher_roles_with_403(
        self, method: str, endpoint: str, payload: dict | None
    ):
        """Student or admin roles calling teacher-only endpoints must return 403 Forbidden."""
        student_user = create_mock_user("student", institution_id=TENANT_ALPHA)
        mock_db, _ = create_mock_session()

        app.dependency_overrides[get_current_user] = lambda: student_user
        app.dependency_overrides[get_tenant_db] = lambda: mock_db

        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                headers = make_auth_header(student_user)
                if method == "GET":
                    resp = await client.get(endpoint, headers=headers)
                elif method == "POST":
                    resp = await client.post(endpoint, json=payload, headers=headers)
                elif method == "PATCH":
                    resp = await client.patch(endpoint, json=payload, headers=headers)
                assert resp.status_code == 403
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_teacher_route_rejects_untenanted_teacher_with_403(self):
        """A user with role='teacher' but without an active institution membership returns 403."""
        untenanted_teacher = create_mock_user("teacher", institution_id=None)
        mock_db, _ = create_mock_session()

        app.dependency_overrides[get_current_user] = lambda: untenanted_teacher
        app.dependency_overrides[get_tenant_db] = lambda: mock_db

        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                headers = make_auth_header(untenanted_teacher)
                resp = await client.get("/teacher/dashboard", headers=headers)
                assert resp.status_code == 403
                assert "Tenant context required" in resp.json()["detail"]
        finally:
            app.dependency_overrides.clear()


# =====================================================================
# 2. Assignment Provisioning & Listing Scoping
# =====================================================================


class TestTeacherAssignmentScoping:
    """Verifies that assignments are created with and filtered by the caller's institution_id."""

    @pytest.mark.asyncio
    async def test_create_assignment_service_sets_institution_id_and_flushes(self):
        """create_assignment must set institution_id from parameter and call flush(), not commit()."""
        mock_db, added = create_mock_session()
        teacher_id = uuid.uuid4()

        assignment = await create_assignment(
            db=mock_db,
            institution_id=TENANT_ALPHA,
            created_by=teacher_id,
            title="Electromagnetism Problem Set",
            subject="Physics",
            class_section="10-A",
            due_date=date(2026, 12, 1),
            max_score=50,
            instructions="Complete exercises 1-5",
        )

        assert len(added) == 1
        assert added[0] == assignment
        assert assignment.institution_id == TENANT_ALPHA
        assert assignment.created_by == teacher_id
        assert assignment.title == "Electromagnetism Problem Set"
        mock_db.flush.assert_awaited_once()
        assert not hasattr(mock_db, "commit") or mock_db.commit.await_count == 0

    @pytest.mark.asyncio
    async def test_post_assignment_endpoint_injects_tenant_institution_id(self):
        """POST /teacher/assignments must set institution_id from TenantContext."""
        teacher = create_mock_user("teacher", institution_id=TENANT_ALPHA)
        mock_db, added = create_mock_session()

        app.dependency_overrides[get_current_user] = lambda: teacher
        app.dependency_overrides[get_tenant_db] = lambda: mock_db

        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                headers = make_auth_header(teacher)
                payload = {
                    "title": "Thermodynamics Quiz",
                    "subject": "Physics",
                    "class_section": "11-B",
                    "max_score": 100,
                    "instructions": "Answer all questions.",
                }
                resp = await client.post("/teacher/assignments", json=payload, headers=headers)
                assert resp.status_code == 200
                data = resp.json()
                assert data["title"] == "Thermodynamics Quiz"
                assert len(added) == 1
                assert added[0].institution_id == TENANT_ALPHA
                assert added[0].created_by == teacher.id
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_list_assignments_service_filters_by_institution_id(self):
        """list_assignments must apply WHERE clause for institution_id."""
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_result)

        await list_assignments(
            db=mock_db,
            institution_id=TENANT_ALPHA,
            class_section="10-A",
        )

        executed_query = str(mock_db.execute.call_args[0][0]).lower()
        assert "assignments.institution_id =" in executed_query
        assert "assignments.class_section =" in executed_query

    @pytest.mark.asyncio
    async def test_get_assignments_endpoint_scoped_to_tenant(self):
        """GET /teacher/assignments must pass caller's institution_id to list_assignments."""
        teacher = create_mock_user("teacher", institution_id=TENANT_BETA)
        mock_db = AsyncMock()
        mock_res = MagicMock()

        assignment_beta = Assignment(
            id=uuid.uuid4(),
            institution_id=TENANT_BETA,
            created_by=teacher.id,
            title="Beta Assignment",
            subject="Math",
            class_section="9-A",
            max_score=100,
            created_at=datetime.now(UTC),
        )
        mock_res.scalars.return_value.all.return_value = [assignment_beta]
        mock_db.execute = AsyncMock(return_value=mock_res)

        app.dependency_overrides[get_current_user] = lambda: teacher
        app.dependency_overrides[get_tenant_db] = lambda: mock_db

        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                headers = make_auth_header(teacher)
                resp = await client.get("/teacher/assignments", headers=headers)
                assert resp.status_code == 200
                data = resp.json()
                assert len(data) == 1
                assert data[0]["title"] == "Beta Assignment"

                # Verify query contained tenant WHERE clause
                executed_query = str(mock_db.execute.call_args[0][0]).lower()
                assert "assignments.institution_id =" in executed_query
        finally:
            app.dependency_overrides.clear()


# =====================================================================
# 3. Study Materials & Canonical RAG Ingestion Scoping
# =====================================================================


class TestTeacherStudyMaterialScoping:
    """Verifies that study materials are persisted and ingested into RAG with canonical tenant UUID."""

    @pytest.mark.asyncio
    async def test_save_study_material_sets_institution_id_and_calls_rag_with_uuid_string(self):
        """save_study_material must persist institution_id and invoke ingest_study_material with canonical UUID."""
        mock_db, added = create_mock_session()
        teacher_id = uuid.uuid4()

        mock_file = MagicMock()
        mock_file.filename = "notes.pdf"
        mock_file.content_type = "application/pdf"
        mock_file.read = AsyncMock(return_value=b"%PDF-1.4 sample content")

        with (
            patch("app.teacher.service.ocr_service.extract_text_from_pdf") as mock_pdf_extract,
            patch("app.teacher.service.ingest_study_material") as mock_ingest,
            patch("aiofiles.open", return_value=AsyncMock()) as mock_aiofile,
        ):
            mock_pdf_extract.return_value = {
                "extracted_text": "Sample lecture notes on thermodynamics.",
                "confidence": 0.99,
            }
            # Mock async file context manager
            mock_aiofile.return_value.__aenter__.return_value = AsyncMock()

            material = await save_study_material(
                db=mock_db,
                institution_id=TENANT_ALPHA,
                teacher_id=teacher_id,
                subject="Physics",
                title="Thermo Notes",
                description="Chapter 3 notes",
                file=mock_file,
            )

            assert material.institution_id == TENANT_ALPHA
            assert material.teacher_id == teacher_id
            assert material.extracted_text == "Sample lecture notes on thermodynamics."
            mock_db.flush.assert_awaited_once()

            # Verify RAG ingestion was called with canonical UUID string
            mock_ingest.assert_called_once()
            _, kwargs = mock_ingest.call_args
            assert kwargs["institution_id"] == str(TENANT_ALPHA)
            assert kwargs["title"] == "Thermo Notes"

    @pytest.mark.asyncio
    async def test_list_study_materials_filters_by_institution_id(self):
        """list_study_materials must apply WHERE clause for institution_id."""
        mock_db = AsyncMock()
        mock_res = MagicMock()
        mock_res.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_res)

        await list_study_materials(
            db=mock_db,
            institution_id=TENANT_ALPHA,
            subject="Chemistry",
        )

        executed_query = str(mock_db.execute.call_args[0][0]).lower()
        assert "study_materials.institution_id =" in executed_query
        assert "study_materials.subject =" in executed_query


# =====================================================================
# 4. Homework Grading Scoping & Cross-Tenant Rejection
# =====================================================================


class TestTeacherGradingScoping:
    """Verifies that homework grading validates institution ownership and rejects cross-tenant submissions."""

    @pytest.mark.asyncio
    async def test_grade_homework_valid_intra_tenant_success(self):
        """Grading a submission within the caller's institution succeeds and flushes."""
        mock_db, _ = create_mock_session()
        submission_id = uuid.uuid4()
        grader_id = uuid.uuid4()

        submission = HomeworkSubmission(
            id=submission_id,
            institution_id=TENANT_ALPHA,
            student_id=uuid.uuid4(),
            subject="Physics",
            title="Lab Report",
            file_path="/tmp/fake_lab.pdf",
            original_filename="lab.pdf",
            status="submitted",
        )

        mock_res = MagicMock()
        mock_res.scalar_one_or_none.return_value = submission
        mock_db.execute = AsyncMock(return_value=mock_res)

        graded = await grade_homework_submission(
            db=mock_db,
            institution_id=TENANT_ALPHA,
            submission_id=submission_id,
            grader_id=grader_id,
            score=90,
            max_score=100,
            feedback="Well documented observations.",
        )

        assert graded.status == "graded"
        assert graded.score == 90
        assert graded.graded_by == grader_id
        mock_db.flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_grade_homework_cross_tenant_rejected_with_404(self):
        """
        Attempting to grade a submission belonging to another institution must return 404 Not Found.
        (Established not-found defense prevents cross-tenant existence enumeration).
        """
        mock_db, _ = create_mock_session()
        submission_id = uuid.uuid4()

        # Database query filtered by TENANT_BETA returns None because submission is in TENANT_ALPHA
        mock_res = MagicMock()
        mock_res.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_res)

        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            await grade_homework_submission(
                db=mock_db,
                institution_id=TENANT_BETA,  # Caller is in Tenant Beta
                submission_id=submission_id,
                grader_id=uuid.uuid4(),
                score=100,
                max_score=100,
                feedback="Tampered grade attempt",
            )

        assert exc_info.value.status_code == 404
        assert "Homework submission not found" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_patch_homework_grade_endpoint_cross_tenant_returns_404(self):
        """PATCH /teacher/homework/{id}/grade returns 404 when target submission is from another tenant."""
        teacher_beta = create_mock_user("teacher", institution_id=TENANT_BETA)
        mock_db = AsyncMock()
        mock_res = MagicMock()
        mock_res.scalar_one_or_none.return_value = None  # Not found in Tenant Beta
        mock_db.execute = AsyncMock(return_value=mock_res)

        app.dependency_overrides[get_current_user] = lambda: teacher_beta
        app.dependency_overrides[get_tenant_db] = lambda: mock_db

        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                headers = make_auth_header(teacher_beta)
                payload = {"score": 85, "max_score": 100, "feedback": "Good effort"}
                resp = await client.patch(
                    f"/teacher/homework/{uuid.uuid4()}/grade",
                    json=payload,
                    headers=headers,
                )
                assert resp.status_code == 404
                assert "Homework submission not found" in resp.json()["detail"]

                # Verify query checked institution_id
                executed_query = str(mock_db.execute.call_args[0][0]).lower()
                assert "homework_submissions.institution_id =" in executed_query
        finally:
            app.dependency_overrides.clear()


# =====================================================================
# 5. Dashboard & Student Directory Scoping
# =====================================================================


class TestTeacherDashboardAndDirectoryScoping:
    """Verifies that dashboard metrics and student listings are scoped to caller's institution."""

    @pytest.mark.asyncio
    async def test_get_teacher_dashboard_summary_scoped_to_institution(self):
        """get_teacher_dashboard_summary queries count strictly with institution_id filter."""
        mock_db = AsyncMock()
        mock_res1 = MagicMock()
        mock_res1.scalar_one.return_value = 5  # 5 pending grading
        mock_res2 = MagicMock()
        mock_res2.scalar_one.return_value = 24  # 24 assigned students
        mock_db.execute = AsyncMock(side_effect=[mock_res1, mock_res2])

        summary = await get_teacher_dashboard_summary(
            db=mock_db,
            institution_id=TENANT_ALPHA,
        )

        assert summary["pending_grading"] == 5
        assert summary["students_assigned"] == 24
        assert mock_db.execute.await_count == 2

        # Verify WHERE clauses in both count queries
        call1 = str(mock_db.execute.call_args_list[0][0][0]).lower()
        call2 = str(mock_db.execute.call_args_list[1][0][0]).lower()
        assert "homework_submissions.institution_id =" in call1
        assert "homework_submissions.institution_id =" in call2

    @pytest.mark.asyncio
    async def test_list_students_for_teacher_filters_by_institution_id(self):
        """list_students_for_teacher joins StudentProfile and filters by institution_id."""
        mock_db = AsyncMock()
        mock_res = MagicMock()

        student_user = create_mock_user("student", institution_id=TENANT_ALPHA)
        profile = student_user.student_profile
        mock_res.all.return_value = [(student_user, profile)]
        mock_db.execute = AsyncMock(return_value=mock_res)

        students = await list_students_for_teacher(
            db=mock_db,
            institution_id=TENANT_ALPHA,
            class_section="10-A",
        )

        assert len(students) == 1
        assert students[0]["id"] == student_user.id
        assert students[0]["grade"] == "10"
        assert students[0]["section"] == "A"

        query_str = str(mock_db.execute.call_args[0][0]).lower()
        assert "student_profiles.institution_id =" in query_str
        assert "student_profiles.grade =" in query_str


# =====================================================================
# 6. Homework File Download Tenant & IDOR Isolation
# =====================================================================


class TestTeacherHomeworkFileDownloadScoping:
    """Verifies that file downloads enforce tenant boundaries as well as timetable/grader rules."""

    @pytest.mark.asyncio
    async def test_homework_download_cross_tenant_rejected_with_404(self):
        """
        Teacher from Tenant Beta attempts to download a submission belonging to Tenant Alpha.
        Because the submission query requires HomeworkSubmission.institution_id == tenant.institution_id,
        it returns 404 Not Found (cross-tenant object isolation).
        """
        teacher_beta = create_mock_user("teacher", institution_id=TENANT_BETA)
        mock_db = AsyncMock()
        mock_res = MagicMock()
        mock_res.first.return_value = None  # Submission does not exist in Tenant Beta
        mock_db.execute = AsyncMock(return_value=mock_res)

        app.dependency_overrides[get_current_user] = lambda: teacher_beta
        app.dependency_overrides[get_tenant_db] = lambda: mock_db

        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                headers = make_auth_header(teacher_beta)
                resp = await client.get(f"/teacher/homework/{uuid.uuid4()}/file", headers=headers)
                assert resp.status_code == 404
                assert "Submission not found" in resp.json()["detail"]

                # Verify query checked HomeworkSubmission.institution_id and StudentProfile.institution_id
                query_str = str(mock_db.execute.call_args[0][0]).lower()
                assert "homework_submissions.institution_id =" in query_str
                assert "student_profiles.institution_id =" in query_str
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_homework_download_authorized_teacher_in_same_tenant_success(self):
        """Teacher from Tenant Alpha downloads submission in Tenant Alpha when assigned on Timetable."""
        teacher_alpha = create_mock_user("teacher", institution_id=TENANT_ALPHA)
        student_alpha = create_mock_user("student", institution_id=TENANT_ALPHA)
        profile = student_alpha.student_profile

        with tempfile.NamedTemporaryFile(delete=False) as tf:
            tf.write(b"Tenant Alpha Physics Homework")
            temp_path = tf.name

        try:
            submission = HomeworkSubmission(
                id=uuid.uuid4(),
                institution_id=TENANT_ALPHA,
                student_id=student_alpha.id,
                subject="Physics",
                title="Lab 1",
                file_path=temp_path,
                original_filename="lab1.pdf",
                status="submitted",
            )

            mock_db = AsyncMock()

            async def mock_execute(query):
                q = str(query).lower()
                res = MagicMock()
                if "homework_submissions" in q and "student_profiles" in q:
                    res.first.return_value = (submission, profile)
                elif "timetable_entries" in q:
                    # Teacher Alpha is assigned to 10-A in Tenant Alpha
                    assert "timetable_entries.institution_id =" in q
                    res.scalar_one_or_none.return_value = uuid.uuid4()
                return res

            mock_db.execute = AsyncMock(side_effect=mock_execute)

            app.dependency_overrides[get_current_user] = lambda: teacher_alpha
            app.dependency_overrides[get_tenant_db] = lambda: mock_db

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                headers = make_auth_header(teacher_alpha)
                resp = await client.get(f"/teacher/homework/{submission.id}/file", headers=headers)
                assert resp.status_code == 200
                assert resp.content == b"Tenant Alpha Physics Homework"
        finally:
            app.dependency_overrides.clear()
            if os.path.exists(temp_path):
                os.remove(temp_path)

    @pytest.mark.asyncio
    async def test_homework_download_tenant_admin_universal_access(self):
        """Administrator of Tenant Alpha has universal access to download homework within Tenant Alpha."""
        admin_alpha = create_mock_user("admin", institution_id=TENANT_ALPHA)
        student_alpha = create_mock_user("student", institution_id=TENANT_ALPHA)
        profile = student_alpha.student_profile

        with tempfile.NamedTemporaryFile(delete=False) as tf:
            tf.write(b"Tenant Alpha Admin Review File")
            temp_path = tf.name

        try:
            submission = HomeworkSubmission(
                id=uuid.uuid4(),
                institution_id=TENANT_ALPHA,
                student_id=student_alpha.id,
                subject="Calculus",
                title="Midterm Prep",
                file_path=temp_path,
                original_filename="prep.pdf",
                status="submitted",
            )

            mock_db = AsyncMock()
            mock_res = MagicMock()
            mock_res.first.return_value = (submission, profile)
            mock_db.execute = AsyncMock(return_value=mock_res)

            app.dependency_overrides[get_current_user] = lambda: admin_alpha
            app.dependency_overrides[get_tenant_db] = lambda: mock_db

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                headers = make_auth_header(admin_alpha)
                resp = await client.get(f"/teacher/homework/{submission.id}/file", headers=headers)
                assert resp.status_code == 200
                assert resp.content == b"Tenant Alpha Admin Review File"
        finally:
            app.dependency_overrides.clear()
            if os.path.exists(temp_path):
                os.remove(temp_path)
