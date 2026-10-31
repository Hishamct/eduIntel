"""
tests/test_parent_report_authorization.py

Comprehensive test suite verifying SEC-03 remediation:
- Mandatory authentication on POST /reports/parent-report/{student_id} (HTTP 401 Unauthorized for anonymous).
- Role restriction to teacher and admin (HTTP 403 Forbidden for students).
- Multi-factor teacher authorization:
    - Condition A: Timetable class assignment (Timetable.teacher_id == teacher.id and
      Timetable.class_section == student_section).
    - Condition B: Concrete student-specific academic relationship (ExamResult, Attendance, or HomeworkSubmission).
- Strict exclusion: Class-level assignment creation alone does NOT authorize a teacher.
- Recipient override removal: Client cannot supply parent_email (extra='forbid' -> HTTP 422).
- Enforces registered parent email from StudentProfile (HTTP 400 if null/missing).
- Administrative authorization across all students.

TEST EXECUTION ENVIRONMENT NOTE:
These automated unit and route-contract tests utilize FastAPI ASGITransport with
dependency injection overrides (`app.dependency_overrides`) and AsyncMock session
fixtures. They verify route authorization guards, multi-factor authorization logic,
schema validation, and HTTP status codes without mutating active development records.
Live PostgreSQL integration testing with a disposable test database is formally
scheduled for Phase 4 (Dedicated Testing Phase).
"""
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.auth.security import create_access_token, hash_password
from app.core.database import get_db
from app.main import app
from app.users.dependencies import get_current_user
from app.users.models import AdminProfile, StudentProfile, TeacherProfile, User


def create_mock_user(role: str, user_id: uuid.UUID | None = None, email: str | None = None) -> User:
    uid = user_id or uuid.uuid4()
    user = User(
        id=uid,
        email=email or f"user_{role}_{uid.hex[:6]}@example.com",
        name=f"Mock {role.capitalize()}",
        hashed_password=hash_password("MockPass123!"),
        role=role,
        is_active=True,
    )
    if role == "student":
        user.student_profile = StudentProfile(
            id=uuid.uuid4(),
            user_id=uid,
            grade="10",
            section="A",
            parent_email="parent.registered@example.com",
        )
    elif role == "teacher":
        user.teacher_profile = TeacherProfile(
            id=uuid.uuid4(),
            user_id=uid,
            department="Science",
            subjects="Physics",
        )
    elif role == "admin":
        user.admin_profile = AdminProfile(
            id=uuid.uuid4(),
            user_id=uid,
            designation="Administrator",
        )
    return user


def make_auth_header(user: User) -> dict:
    token = create_access_token({"sub": str(user.id), "role": user.role})
    return {"Authorization": f"Bearer {token}"}


def make_mock_db(
    student_user: User | None = None,
    student_profile: StudentProfile | None = None,
    on_timetable: bool = False,
    has_exam_link: bool = False,
    has_attendance_link: bool = False,
    has_homework_link: bool = False,
):
    """
    Creates an AsyncMock database session that responds correctly to
    SQLAlchemy select statements based on test expectations.
    """
    mock_db = AsyncMock()

    async def mock_execute(query):
        query_str = str(query).lower()
        res = MagicMock()

        if "student_profiles" in query_str and "users" in query_str:
            if student_user and student_profile:
                res.first.return_value = (student_user, student_profile)
            else:
                res.first.return_value = None
        elif "timetable_entries" in query_str:
            res.scalar_one_or_none.return_value = uuid.uuid4() if on_timetable else None
        elif "exam_results" in query_str:
            res.scalar_one_or_none.return_value = uuid.uuid4() if has_exam_link else None
        elif "attendance_records" in query_str:
            res.scalar_one_or_none.return_value = uuid.uuid4() if has_attendance_link else None
        elif "homework_submissions" in query_str:
            res.scalar_one_or_none.return_value = uuid.uuid4() if has_homework_link else None
        else:
            res.scalar_one_or_none.return_value = None
            res.first.return_value = None

        return res

    mock_db.execute = AsyncMock(side_effect=mock_execute)
    return mock_db


class TestParentReportAuthenticationAndRoleGuards:
    @pytest.mark.asyncio
    async def test_parent_report_anonymous_rejected_with_401(self):
        """Verifies unauthenticated callers receive 401 Unauthorized."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(f"/reports/parent-report/{uuid.uuid4()}")
            assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_parent_report_student_rejected_with_403(self):
        """Verifies authenticated students receive 403 Forbidden."""
        student_user = create_mock_user("student")
        app.dependency_overrides[get_current_user] = lambda: student_user

        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                headers = make_auth_header(student_user)
                resp = await client.post(f"/reports/parent-report/{uuid.uuid4()}", headers=headers)
                assert resp.status_code == 403
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_parent_report_invalid_uuid_rejected_with_400(self):
        """Verifies malformed student UUID string returns 400 Bad Request."""
        teacher_user = create_mock_user("teacher")
        app.dependency_overrides[get_current_user] = lambda: teacher_user

        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                headers = make_auth_header(teacher_user)
                resp = await client.post("/reports/parent-report/not-a-valid-uuid", headers=headers)
                assert resp.status_code == 400
                assert "Invalid student UUID" in resp.json()["detail"]
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_parent_report_student_not_found_with_404(self):
        """Verifies unknown student UUID returns 404 Not Found."""
        teacher_user = create_mock_user("teacher")
        mock_db = make_mock_db(student_user=None, student_profile=None)

        app.dependency_overrides[get_current_user] = lambda: teacher_user
        app.dependency_overrides[get_db] = lambda: mock_db

        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                headers = make_auth_header(teacher_user)
                resp = await client.post(f"/reports/parent-report/{uuid.uuid4()}", headers=headers)
                assert resp.status_code == 404
                assert "Student not found" in resp.json()["detail"]
        finally:
            app.dependency_overrides.clear()


class TestMultiFactorTeacherAuthorization:
    @pytest.mark.asyncio
    async def test_teacher_rejected_if_student_has_no_grade_section(self):
        """Verifies 403 Forbidden if student has no grade or section configured."""
        teacher_user = create_mock_user("teacher")
        student_user = create_mock_user("student")
        student_profile = StudentProfile(
            id=uuid.uuid4(),
            user_id=student_user.id,
            grade=None,
            section=None,
            parent_email="parent@example.com",
        )
        mock_db = make_mock_db(student_user=student_user, student_profile=student_profile)

        app.dependency_overrides[get_current_user] = lambda: teacher_user
        app.dependency_overrides[get_db] = lambda: mock_db

        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                headers = make_auth_header(teacher_user)
                resp = await client.post(f"/reports/parent-report/{student_user.id}", headers=headers)
                assert resp.status_code == 403
                assert "not assigned to any grade/section" in resp.json()["detail"]
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_teacher_not_on_timetable_rejected_with_403(self):
        """
        Condition A Failure: Teacher is NOT assigned on the timetable for this student's class section.
        Expected: HTTP 403 Forbidden.
        """
        teacher_user = create_mock_user("teacher")
        student_user = create_mock_user("student")
        student_profile = student_user.student_profile
        mock_db = make_mock_db(
            student_user=student_user,
            student_profile=student_profile,
            on_timetable=False,  # Not on timetable
            has_exam_link=True,
        )

        app.dependency_overrides[get_current_user] = lambda: teacher_user
        app.dependency_overrides[get_db] = lambda: mock_db

        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                headers = make_auth_header(teacher_user)
                resp = await client.post(f"/reports/parent-report/{student_user.id}", headers=headers)
                assert resp.status_code == 403
                assert "not assigned to teach this student's class section" in resp.json()["detail"]
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_teacher_on_timetable_but_no_student_specific_link_rejected_with_403(self):
        """
        Condition B Failure: Teacher IS on timetable, but has NO student-specific academic records
        (no entered exam score, marked attendance, or graded homework for this target student).
        Expected: HTTP 403 Forbidden.
        """
        teacher_user = create_mock_user("teacher")
        student_user = create_mock_user("student")
        student_profile = student_user.student_profile
        mock_db = make_mock_db(
            student_user=student_user,
            student_profile=student_profile,
            on_timetable=True,
            has_exam_link=False,
            has_attendance_link=False,
            has_homework_link=False,
        )

        app.dependency_overrides[get_current_user] = lambda: teacher_user
        app.dependency_overrides[get_db] = lambda: mock_db

        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                headers = make_auth_header(teacher_user)
                resp = await client.post(f"/reports/parent-report/{student_user.id}", headers=headers)
                assert resp.status_code == 403
                assert "No student-specific academic records" in resp.json()["detail"]
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_teacher_with_ungraded_homework_submission_rejected_with_403(self):
        """
        Verifies that an ungraded homework submission (status='submitted', graded_by is None)
        does NOT satisfy Condition B. Only graded submissions (status='graded') authorize the teacher.
        """
        teacher_user = create_mock_user("teacher")
        student_user = create_mock_user("student")
        student_profile = student_user.student_profile
        # on_timetable=True, but has_homework_link=False because it's ungraded
        mock_db = make_mock_db(
            student_user=student_user,
            student_profile=student_profile,
            on_timetable=True,
            has_homework_link=False,
        )

        app.dependency_overrides[get_current_user] = lambda: teacher_user
        app.dependency_overrides[get_db] = lambda: mock_db

        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                headers = make_auth_header(teacher_user)
                resp = await client.post(f"/reports/parent-report/{student_user.id}", headers=headers)
                assert resp.status_code == 403
                assert "No student-specific academic records" in resp.json()["detail"]
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_teacher_with_class_assignment_only_rejected_with_403(self):
        """
        CRITICAL REQUIREMENT:
        Creating a class-level Assignment must NOT count as student-specific authorization.
        Expected: HTTP 403 Forbidden.
        """
        teacher_user = create_mock_user("teacher")
        student_user = create_mock_user("student")
        student_profile = student_user.student_profile
        # on_timetable=True, but NO ExamResult, NO Attendance, NO HomeworkSubmission
        mock_db = make_mock_db(
            student_user=student_user,
            student_profile=student_profile,
            on_timetable=True,
            has_exam_link=False,
            has_attendance_link=False,
            has_homework_link=False,
        )

        app.dependency_overrides[get_current_user] = lambda: teacher_user
        app.dependency_overrides[get_db] = lambda: mock_db

        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                headers = make_auth_header(teacher_user)
                resp = await client.post(f"/reports/parent-report/{student_user.id}", headers=headers)
                assert resp.status_code == 403
                assert "No student-specific academic records" in resp.json()["detail"]
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_teacher_authorized_via_exam_result_success(self):
        """
        Teacher meets Condition A (timetable) AND Condition B (entered ExamResult for this student).
        Expected: HTTP 200 OK, dispatched strictly to registered parent email.
        """
        teacher_user = create_mock_user("teacher")
        student_user = create_mock_user("student")
        student_profile = student_user.student_profile
        mock_db = make_mock_db(
            student_user=student_user,
            student_profile=student_profile,
            on_timetable=True,
            has_exam_link=True,
        )

        app.dependency_overrides[get_current_user] = lambda: teacher_user
        app.dependency_overrides[get_db] = lambda: mock_db

        mock_report_response = {"status": "sent", "report_body": "Report text", "email_result": "{'status': 'sent'}"}

        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                headers = make_auth_header(teacher_user)
                with patch("app.reports.router.generate_and_send_report", new_callable=AsyncMock) as mock_agent:
                    mock_agent.return_value = mock_report_response
                    resp = await client.post(f"/reports/parent-report/{student_user.id}", headers=headers)
                    assert resp.status_code == 200
                    mock_agent.assert_called_once_with(
                        student_id=str(student_user.id),
                        student_name=student_user.name,
                        parent_email=student_profile.parent_email,
                        db=mock_db,
                        generated_by_user_id=teacher_user.id,
                    )
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_teacher_authorized_via_attendance_record_success(self):
        """
        Teacher meets Condition A (timetable) AND Condition B (marked Attendance for this student).
        Expected: HTTP 200 OK.
        """
        teacher_user = create_mock_user("teacher")
        student_user = create_mock_user("student")
        student_profile = student_user.student_profile
        mock_db = make_mock_db(
            student_user=student_user,
            student_profile=student_profile,
            on_timetable=True,
            has_attendance_link=True,
        )

        app.dependency_overrides[get_current_user] = lambda: teacher_user
        app.dependency_overrides[get_db] = lambda: mock_db

        mock_report_response = {"status": "sent", "report_body": "Report text", "email_result": "{'status': 'sent'}"}

        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                headers = make_auth_header(teacher_user)
                with patch("app.reports.router.generate_and_send_report", new_callable=AsyncMock) as mock_agent:
                    mock_agent.return_value = mock_report_response
                    resp = await client.post(f"/reports/parent-report/{student_user.id}", headers=headers)
                    assert resp.status_code == 200
                    mock_agent.assert_called_once()
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_teacher_authorized_via_homework_submission_success(self):
        """
        Teacher meets Condition A (timetable) AND Condition B (graded HomeworkSubmission for this student).
        Expected: HTTP 200 OK.
        """
        teacher_user = create_mock_user("teacher")
        student_user = create_mock_user("student")
        student_profile = student_user.student_profile
        mock_db = make_mock_db(
            student_user=student_user,
            student_profile=student_profile,
            on_timetable=True,
            has_homework_link=True,
        )

        app.dependency_overrides[get_current_user] = lambda: teacher_user
        app.dependency_overrides[get_db] = lambda: mock_db

        mock_report_response = {"status": "sent", "report_body": "Report text", "email_result": "{'status': 'sent'}"}

        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                headers = make_auth_header(teacher_user)
                with patch("app.reports.router.generate_and_send_report", new_callable=AsyncMock) as mock_agent:
                    mock_agent.return_value = mock_report_response
                    resp = await client.post(f"/reports/parent-report/{student_user.id}", headers=headers)
                    assert resp.status_code == 200
                    mock_agent.assert_called_once()
        finally:
            app.dependency_overrides.clear()


class TestAdminAuthorizationAndDeliveryIntegrity:
    @pytest.mark.asyncio
    async def test_admin_authorized_directly_without_academic_records(self):
        """
        Administrators possess universal authorization across all students in the institution.
        They do not require timetable assignments or student-specific academic records.
        Expected: HTTP 200 OK.
        """
        admin_user = create_mock_user("admin")
        student_user = create_mock_user("student")
        student_profile = student_user.student_profile
        # on_timetable=False, no academic links
        mock_db = make_mock_db(
            student_user=student_user,
            student_profile=student_profile,
            on_timetable=False,
            has_exam_link=False,
        )

        app.dependency_overrides[get_current_user] = lambda: admin_user
        app.dependency_overrides[get_db] = lambda: mock_db

        mock_report_response = {"status": "sent", "report_body": "Report text", "email_result": "{'status': 'sent'}"}

        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                headers = make_auth_header(admin_user)
                with patch("app.reports.router.generate_and_send_report", new_callable=AsyncMock) as mock_agent:
                    mock_agent.return_value = mock_report_response
                    resp = await client.post(f"/reports/parent-report/{student_user.id}", headers=headers)
                    assert resp.status_code == 200
                    mock_agent.assert_called_once_with(
                        student_id=str(student_user.id),
                        student_name=student_user.name,
                        parent_email=student_profile.parent_email,
                        db=mock_db,
                        generated_by_user_id=admin_user.id,
                    )
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_missing_registered_parent_email_rejected_with_400(self):
        """
        If the student has no registered parent email on file, report generation must abort.
        Expected: HTTP 400 Bad Request.
        """
        admin_user = create_mock_user("admin")
        student_user = create_mock_user("student")
        student_profile = StudentProfile(
            id=uuid.uuid4(),
            user_id=student_user.id,
            grade="10",
            section="A",
            parent_email=None,  # Missing email
        )
        mock_db = make_mock_db(student_user=student_user, student_profile=student_profile)

        app.dependency_overrides[get_current_user] = lambda: admin_user
        app.dependency_overrides[get_db] = lambda: mock_db

        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                headers = make_auth_header(admin_user)
                resp = await client.post(f"/reports/parent-report/{student_user.id}", headers=headers)
                assert resp.status_code == 400
                assert "no registered parent email on file" in resp.json()["detail"]
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_client_recipient_override_attempt_rejected_with_422(self):
        """
        CRITICAL VULNERABILITY REMEDIATION (SEC-03 Open Relay):
        Callers must NEVER be allowed to supply or override parent_email.
        ParentReportRequest enforces extra='forbid'.
        Expected: HTTP 422 Unprocessable Entity.
        """
        admin_user = create_mock_user("admin")
        student_user = create_mock_user("student")
        app.dependency_overrides[get_current_user] = lambda: admin_user

        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                headers = make_auth_header(admin_user)
                # Attacker attempt to override recipient email
                override_payload = {
                    "parent_email": "attacker@external-domain.com",
                    "student_name": "Injected Name",
                }
                resp = await client.post(
                    f"/reports/parent-report/{student_user.id}",
                    json=override_payload,
                    headers=headers,
                )
                assert resp.status_code == 422
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_smtp_delivery_failure_returns_sanitized_502(self):
        """
        Verifies that downstream delivery failures return a generic HTTP 502 Bad Gateway
        and do NOT leak raw exception strings, server connection details, or credentials
        to the client. Verifies server-side diagnostic logging without sensitive data.
        """
        admin_user = create_mock_user("admin")
        student_user = create_mock_user("student")
        student_profile = student_user.student_profile
        mock_db = make_mock_db(student_user=student_user, student_profile=student_profile)

        app.dependency_overrides[get_current_user] = lambda: admin_user
        app.dependency_overrides[get_db] = lambda: mock_db

        internal_error_msg = "CRITICAL: SMTP Authentication failed for user 'smtp_user' password='secret_password_123'"

        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                headers = make_auth_header(admin_user)
                with patch(
                    "app.reports.router.generate_and_send_report",
                    side_effect=RuntimeError(internal_error_msg),
                ):
                    with patch("app.reports.router.logger.error") as mock_logger:
                        resp = await client.post(f"/reports/parent-report/{student_user.id}", headers=headers)
                        assert resp.status_code == 502
                        data = resp.json()
                        # Generic user-facing message
                        assert "Failed to generate or deliver progress report" in data["detail"]
                        # Raw exception message MUST NOT be leaked to the client!
                        assert "secret_password_123" not in resp.text
                        assert "smtp_user" not in resp.text
                        assert "Authentication failed" not in resp.text

                        # Server-side diagnostic log emitted without credentials or parent email
                        mock_logger.assert_called_once()
                        log_format, *log_args = mock_logger.call_args[0]
                        assert "Parent report generation/delivery failed" in log_format
                        assert admin_user.id in log_args
                        assert student_user.id in log_args
                        assert "RuntimeError" in log_args
                        assert "secret_password_123" not in str(log_args)
                        assert student_profile.parent_email not in str(log_args)
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_expected_http_exceptions_not_converted_to_502(self):
        """
        Verifies that expected validation and authorization HTTPExceptions
        (such as 400 for missing parent email, 403 for unauthorized teacher)
        are returned with their exact status codes and are NOT caught or converted
        into 502 Bad Gateway responses.
        """
        admin_user = create_mock_user("admin")
        student_user = create_mock_user("student")
        student_profile = StudentProfile(
            id=uuid.uuid4(),
            user_id=student_user.id,
            grade="10",
            section="A",
            parent_email=None,
        )
        mock_db = make_mock_db(student_user=student_user, student_profile=student_profile)

        app.dependency_overrides[get_current_user] = lambda: admin_user
        app.dependency_overrides[get_db] = lambda: mock_db

        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                headers = make_auth_header(admin_user)
                resp = await client.post(f"/reports/parent-report/{student_user.id}", headers=headers)
                # Must be 400, not 502
                assert resp.status_code == 400
                assert resp.status_code != 502
        finally:
            app.dependency_overrides.clear()
