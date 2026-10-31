"""
backend/tests/test_ml_diagnostics_idor.py

Comprehensive test suite verifying SEC-07 remediation:
- Insecure Direct Object Reference (IDOR) protections on ML diagnostic endpoints:
    1. GET /ml/predict/at-risk/{student_id}
    2. GET /ml/predict/at-risk-admin/{student_id}
    3. GET /ml/explain/at-risk/{student_id}
    4. GET /ml/predict/weak-topics/{student_id}
    5. GET /ml/diagnose/{student_id}
    6. GET /ml/diagnose-with-recommendations/{student_id}
- Authentication and role guards (401 for anonymous, 403 for unauthorized roles).
- Student existence and StudentProfile verification (404 for missing target, non-student, or missing profile).
- Section assignment and Timetable authorization for teachers:
    - 403 if student has no grade/section.
    - 403 if teacher is not assigned to the student's class section on the institutional Timetable.
    - 200 when teacher is assigned to the student's class section.
- Administrator universal platform oversight on admin diagnostic endpoint.
- Sanitized 502 error responses on unexpected inference exceptions with zero trace leakage.

TEST EXECUTION ENVIRONMENT NOTE:
These automated unit and route-contract tests utilize FastAPI ASGITransport with
dependency injection overrides and AsyncMock database sessions. Live PostgreSQL
integration testing with a disposable test database is scheduled for Phase 4.
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


def create_mock_user(
    role: str,
    user_id: uuid.UUID | None = None,
    grade: str | None = "10",
    section: str | None = "A",
    has_profile: bool = True,
) -> User:
    uid = user_id or uuid.uuid4()
    user = User(
        id=uid,
        email=f"user_{role}_{uid.hex[:6]}@example.com",
        name=f"Mock {role.capitalize()}",
        hashed_password=hash_password("MockPass123!"),
        role=role,
        is_active=True,
    )
    if role == "student" and has_profile:
        user.student_profile = StudentProfile(
            id=uuid.uuid4(),
            user_id=uid,
            grade=grade,
            section=section,
            parent_email="parent@example.com",
        )
    elif role == "teacher" and has_profile:
        user.teacher_profile = TeacherProfile(
            id=uuid.uuid4(),
            user_id=uid,
            department="Science",
            subjects="Mathematics",
        )
    elif role == "admin" and has_profile:
        user.admin_profile = AdminProfile(
            id=uuid.uuid4(),
            user_id=uid,
            designation="Administrator",
        )
    return user


def make_auth_header(user: User) -> dict:
    token = create_access_token({"sub": str(user.id), "role": user.role})
    return {"Authorization": f"Bearer {token}"}


TEACHER_ENDPOINTS = [
    "/ml/predict/at-risk/{student_id}",
    "/ml/explain/at-risk/{student_id}",
    "/ml/predict/weak-topics/{student_id}",
    "/ml/diagnose/{student_id}",
    "/ml/diagnose-with-recommendations/{student_id}",
]


class TestMLDiagnosticsAuthenticationAndRoles:
    """Tests 401 for anonymous and 403 for unauthorized roles."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("endpoint_template", TEACHER_ENDPOINTS)
    async def test_teacher_endpoints_anonymous_rejected_401(self, endpoint_template: str):
        random_id = uuid.uuid4()
        url = endpoint_template.format(student_id=random_id)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get(url)
            assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_admin_endpoint_anonymous_rejected_401(self):
        random_id = uuid.uuid4()
        url = f"/ml/predict/at-risk-admin/{random_id}"
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get(url)
            assert resp.status_code == 401

    @pytest.mark.asyncio
    @pytest.mark.parametrize("endpoint_template", TEACHER_ENDPOINTS)
    async def test_student_calling_teacher_endpoints_rejected_403(
        self, endpoint_template: str
    ):
        student = create_mock_user("student")
        target_student_id = uuid.uuid4()
        url = endpoint_template.format(student_id=target_student_id)

        app.dependency_overrides[get_current_user] = lambda: student
        try:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.get(url, headers=make_auth_header(student))
                assert resp.status_code == 403
        finally:
            app.dependency_overrides.pop(get_current_user, None)

    @pytest.mark.asyncio
    async def test_student_calling_admin_endpoint_rejected_403(self):
        student = create_mock_user("student")
        target_student_id = uuid.uuid4()
        url = f"/ml/predict/at-risk-admin/{target_student_id}"

        app.dependency_overrides[get_current_user] = lambda: student
        try:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.get(url, headers=make_auth_header(student))
                assert resp.status_code == 403
        finally:
            app.dependency_overrides.pop(get_current_user, None)

    @pytest.mark.asyncio
    async def test_teacher_calling_admin_endpoint_rejected_403(self):
        teacher = create_mock_user("teacher")
        target_student_id = uuid.uuid4()
        url = f"/ml/predict/at-risk-admin/{target_student_id}"

        app.dependency_overrides[get_current_user] = lambda: teacher
        try:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.get(url, headers=make_auth_header(teacher))
                assert resp.status_code == 403
        finally:
            app.dependency_overrides.pop(get_current_user, None)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("endpoint_template", TEACHER_ENDPOINTS)
    async def test_admin_calling_teacher_endpoints_rejected_403(
        self, endpoint_template: str
    ):
        """Preserves existing admin permissions before explicit authorization."""
        admin = create_mock_user("admin")
        target_student_id = uuid.uuid4()
        url = endpoint_template.format(student_id=target_student_id)

        app.dependency_overrides[get_current_user] = lambda: admin
        try:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.get(url, headers=make_auth_header(admin))
                assert resp.status_code == 403
        finally:
            app.dependency_overrides.pop(get_current_user, None)


class TestMLDiagnosticsTargetValidation:
    """Tests 404 for missing target, non-student target, or missing StudentProfile."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("endpoint_template", TEACHER_ENDPOINTS)
    async def test_nonexistent_student_returns_404_for_teacher(
        self, endpoint_template: str
    ):
        teacher = create_mock_user("teacher")
        missing_id = uuid.uuid4()
        url = endpoint_template.format(student_id=missing_id)

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.first.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        app.dependency_overrides[get_current_user] = lambda: teacher
        app.dependency_overrides[get_db] = lambda: mock_db
        try:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.get(url, headers=make_auth_header(teacher))
                assert resp.status_code == 404
                assert resp.json()["detail"] == "Student not found"
        finally:
            app.dependency_overrides.pop(get_current_user, None)
            app.dependency_overrides.pop(get_db, None)

    @pytest.mark.asyncio
    async def test_nonexistent_student_returns_404_for_admin(self):
        admin = create_mock_user("admin")
        missing_id = uuid.uuid4()
        url = f"/ml/predict/at-risk-admin/{missing_id}"

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.first.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        app.dependency_overrides[get_current_user] = lambda: admin
        app.dependency_overrides[get_db] = lambda: mock_db
        try:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.get(url, headers=make_auth_header(admin))
                assert resp.status_code == 404
                assert resp.json()["detail"] == "Student not found"
        finally:
            app.dependency_overrides.pop(get_current_user, None)
            app.dependency_overrides.pop(get_db, None)

    @pytest.mark.asyncio
    async def test_target_user_is_not_student_returns_404(self):
        """When student_id points to another teacher or admin, must return 404."""
        teacher = create_mock_user("teacher")
        peer_teacher_id = uuid.uuid4()
        url = f"/ml/predict/at-risk/{peer_teacher_id}"

        mock_db = AsyncMock()
        # Query filter requires User.role == "student" and join StudentProfile,
        # so non-student returns no rows
        mock_result = MagicMock()
        mock_result.first.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        app.dependency_overrides[get_current_user] = lambda: teacher
        app.dependency_overrides[get_db] = lambda: mock_db
        try:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.get(url, headers=make_auth_header(teacher))
                assert resp.status_code == 404
                assert resp.json()["detail"] == "Student not found"
        finally:
            app.dependency_overrides.pop(get_current_user, None)
            app.dependency_overrides.pop(get_db, None)


class TestMLDiagnosticsTeacherSectionAuthorization:
    """Tests 403 when student has unassigned section or teacher is not assigned to timetable."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "grade,section",
        [(None, "A"), ("10", None), (None, None), ("", "A"), ("10", "")],
    )
    async def test_student_unassigned_grade_or_section_returns_403(
        self, grade: str | None, section: str | None
    ):
        teacher = create_mock_user("teacher")
        student = create_mock_user("student", grade=grade, section=section)
        url = f"/ml/predict/at-risk/{student.id}"

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.first.return_value = (student, student.student_profile)
        mock_db.execute = AsyncMock(return_value=mock_result)

        app.dependency_overrides[get_current_user] = lambda: teacher
        app.dependency_overrides[get_db] = lambda: mock_db
        try:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.get(url, headers=make_auth_header(teacher))
                assert resp.status_code == 403
                assert "Student is not assigned to any grade/section" in resp.json()["detail"]
        finally:
            app.dependency_overrides.pop(get_current_user, None)
            app.dependency_overrides.pop(get_db, None)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("endpoint_template", TEACHER_ENDPOINTS)
    async def test_teacher_not_assigned_to_timetable_returns_403(
        self, endpoint_template: str
    ):
        teacher = create_mock_user("teacher")
        student = create_mock_user("student", grade="10", section="B")
        url = endpoint_template.format(student_id=student.id)

        mock_db = AsyncMock()

        async def fake_execute(statement, *args, **kwargs):
            query_str = str(statement)
            res = MagicMock()
            if "student_profiles" in query_str or "users" in query_str:
                res.first.return_value = (student, student.student_profile)
            elif "timetable_entries" in query_str:
                # Teacher is NOT assigned to 10-B
                res.scalar_one_or_none.return_value = None
            return res

        mock_db.execute = AsyncMock(side_effect=fake_execute)

        app.dependency_overrides[get_current_user] = lambda: teacher
        app.dependency_overrides[get_db] = lambda: mock_db
        try:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.get(url, headers=make_auth_header(teacher))
                assert resp.status_code == 403
                assert (
                    "Authorization denied: You are not assigned to teach this student's class section."
                    in resp.json()["detail"]
                )
        finally:
            app.dependency_overrides.pop(get_current_user, None)
            app.dependency_overrides.pop(get_db, None)


class TestMLDiagnosticsAuthorizedAccess:
    """Tests 200 OK for assigned teachers and administrators."""

    @pytest.fixture
    def authorized_setup(self):
        teacher = create_mock_user("teacher")
        student = create_mock_user("student", grade="10", section="A")

        mock_db = AsyncMock()

        async def fake_execute(statement, *args, **kwargs):
            query_str = str(statement)
            res = MagicMock()
            if "student_profiles" in query_str or "users" in query_str:
                res.first.return_value = (student, student.student_profile)
            elif "timetable_entries" in query_str:
                res.scalar_one_or_none.return_value = uuid.uuid4()
            return res

        mock_db.execute = AsyncMock(side_effect=fake_execute)
        return teacher, student, mock_db

    @pytest.mark.asyncio
    async def test_teacher_predict_at_risk_authorized_200(self, authorized_setup):
        teacher, student, mock_db = authorized_setup
        url = f"/ml/predict/at-risk/{student.id}"

        expected_response = {
            "student_id": str(student.id),
            "is_at_risk": True,
            "risk_probability": 0.78,
            "features_used": {"attendance_rate": 0.65},
            "note": None,
        }

        app.dependency_overrides[get_current_user] = lambda: teacher
        app.dependency_overrides[get_db] = lambda: mock_db
        with patch("app.ml.router.get_at_risk_prediction", new_callable=AsyncMock) as mock_pred:
            mock_pred.return_value = expected_response
            try:
                async with AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as client:
                    resp = await client.get(url, headers=make_auth_header(teacher))
                    assert resp.status_code == 200
                    data = resp.json()
                    assert data["student_id"] == str(student.id)
                    assert data["is_at_risk"] is True
                    assert data["risk_probability"] == 0.78
            finally:
                app.dependency_overrides.pop(get_current_user, None)
                app.dependency_overrides.pop(get_db, None)

    @pytest.mark.asyncio
    async def test_admin_predict_at_risk_admin_authorized_200(self):
        admin = create_mock_user("admin")
        student = create_mock_user("student", grade="10", section="A")
        url = f"/ml/predict/at-risk-admin/{student.id}"

        mock_db = AsyncMock()

        async def fake_execute(statement, *args, **kwargs):
            query_str = str(statement)
            res = MagicMock()
            if "student_profiles" in query_str or "users" in query_str:
                res.first.return_value = (student, student.student_profile)
            return res

        mock_db.execute = AsyncMock(side_effect=fake_execute)

        expected_response = {
            "student_id": str(student.id),
            "is_at_risk": False,
            "risk_probability": 0.12,
            "features_used": {"attendance_rate": 0.95},
            "note": None,
        }

        app.dependency_overrides[get_current_user] = lambda: admin
        app.dependency_overrides[get_db] = lambda: mock_db
        with patch("app.ml.router.get_at_risk_prediction", new_callable=AsyncMock) as mock_pred:
            mock_pred.return_value = expected_response
            try:
                async with AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as client:
                    resp = await client.get(url, headers=make_auth_header(admin))
                    assert resp.status_code == 200
                    data = resp.json()
                    assert data["student_id"] == str(student.id)
                    assert data["is_at_risk"] is False
            finally:
                app.dependency_overrides.pop(get_current_user, None)
                app.dependency_overrides.pop(get_db, None)

    @pytest.mark.asyncio
    async def test_teacher_explain_at_risk_authorized_200(self, authorized_setup):
        teacher, student, mock_db = authorized_setup
        url = f"/ml/explain/at-risk/{student.id}"

        expected_response = {
            "student_id": str(student.id),
            "risk_probability": 0.75,
            "top_factors": [
                {
                    "feature": "attendance_rate",
                    "label": "Attendance rate",
                    "value": 0.65,
                    "contribution": 0.45,
                    "direction": "increases_risk",
                }
            ],
            "summary": "Attendance rate (0.65) is the strongest factor increasing risk.",
        }

        app.dependency_overrides[get_current_user] = lambda: teacher
        app.dependency_overrides[get_db] = lambda: mock_db
        with patch("app.ml.router.get_at_risk_explanation", new_callable=AsyncMock) as mock_exp:
            mock_exp.return_value = expected_response
            try:
                async with AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as client:
                    resp = await client.get(url, headers=make_auth_header(teacher))
                    assert resp.status_code == 200
                    data = resp.json()
                    assert data["student_id"] == str(student.id)
                    assert len(data["top_factors"]) == 1
            finally:
                app.dependency_overrides.pop(get_current_user, None)
                app.dependency_overrides.pop(get_db, None)

    @pytest.mark.asyncio
    async def test_teacher_predict_weak_topics_authorized_200(self, authorized_setup):
        teacher, student, mock_db = authorized_setup
        url = f"/ml/predict/weak-topics/{student.id}"

        predictions = [
            {
                "subject": "Mathematics",
                "topic": "Quadratic Equations",
                "is_weak": True,
                "weak_probability": 0.88,
            }
        ]

        app.dependency_overrides[get_current_user] = lambda: teacher
        app.dependency_overrides[get_db] = lambda: mock_db
        with patch("app.ml.router.get_weak_topic_predictions", new_callable=AsyncMock) as mock_pred:
            mock_pred.return_value = predictions
            try:
                async with AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as client:
                    resp = await client.get(url, headers=make_auth_header(teacher))
                    assert resp.status_code == 200
                    data = resp.json()
                    assert data["student_id"] == str(student.id)
                    assert len(data["predictions"]) == 1
                    assert data["predictions"][0]["is_weak"] is True
            finally:
                app.dependency_overrides.pop(get_current_user, None)
                app.dependency_overrides.pop(get_db, None)

    @pytest.mark.asyncio
    async def test_teacher_diagnose_authorized_200(self, authorized_setup):
        teacher, student, mock_db = authorized_setup
        url = f"/ml/diagnose/{student.id}"

        app.dependency_overrides[get_current_user] = lambda: teacher
        app.dependency_overrides[get_db] = lambda: mock_db
        with patch("app.ml.router.get_at_risk_prediction", new_callable=AsyncMock) as mock_at_risk, \
             patch("app.ml.router.get_weak_topic_predictions", new_callable=AsyncMock) as mock_weak, \
             patch("app.ml.router.diagnose_student") as mock_diag:
            mock_at_risk.return_value = {"is_at_risk": True, "risk_probability": 0.82}
            mock_weak.return_value = [{"topic": "Trigonometry", "is_weak": True}]
            mock_diag.return_value = {
                "overall_status": "at_risk",
                "top_weak_topics": [{"topic": "Trigonometry"}],
            }
            try:
                async with AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as client:
                    resp = await client.get(url, headers=make_auth_header(teacher))
                    assert resp.status_code == 200
                    data = resp.json()
                    assert data["student_id"] == str(student.id)
                    assert data["overall_status"] == "at_risk"
            finally:
                app.dependency_overrides.pop(get_current_user, None)
                app.dependency_overrides.pop(get_db, None)

    @pytest.mark.asyncio
    async def test_teacher_diagnose_with_recommendations_authorized_200(self, authorized_setup):
        teacher, student, mock_db = authorized_setup
        url = f"/ml/diagnose-with-recommendations/{student.id}"

        app.dependency_overrides[get_current_user] = lambda: teacher
        app.dependency_overrides[get_db] = lambda: mock_db
        with patch("app.ml.router.get_at_risk_prediction", new_callable=AsyncMock) as mock_at_risk, \
             patch("app.ml.router.get_weak_topic_predictions", new_callable=AsyncMock) as mock_weak, \
             patch("app.ml.router.diagnose_student") as mock_diag, \
             patch("app.ml.router.get_recommendations_for_weak_topics") as mock_recs:
            mock_at_risk.return_value = {"is_at_risk": True, "risk_probability": 0.82}
            mock_weak.return_value = [{"topic": "Trigonometry", "is_weak": True}]
            mock_diag.return_value = {
                "overall_status": "at_risk",
                "top_weak_topics": [{"topic": "Trigonometry"}],
            }
            mock_recs.return_value = [{"topic": "Trigonometry", "recommendation": "Practice problem set"}]
            try:
                async with AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as client:
                    resp = await client.get(url, headers=make_auth_header(teacher))
                    assert resp.status_code == 200
                    data = resp.json()
                    assert data["student_id"] == str(student.id)
                    assert len(data["recommendations"]) == 1
            finally:
                app.dependency_overrides.pop(get_current_user, None)
                app.dependency_overrides.pop(get_db, None)


class TestMLDiagnosticsErrorSanitization:
    """Verifies that unexpected inference exceptions return sanitized 502 with no details leaked."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("endpoint_template", TEACHER_ENDPOINTS)
    async def test_unexpected_inference_error_returns_sanitized_502(
        self, endpoint_template: str
    ):
        teacher = create_mock_user("teacher")
        student = create_mock_user("student", grade="10", section="A")
        url = endpoint_template.format(student_id=student.id)

        mock_db = AsyncMock()

        async def fake_execute(statement, *args, **kwargs):
            query_str = str(statement)
            res = MagicMock()
            if "student_profiles" in query_str or "users" in query_str:
                res.first.return_value = (student, student.student_profile)
            elif "timetable_entries" in query_str:
                res.scalar_one_or_none.return_value = uuid.uuid4()
            return res

        mock_db.execute = AsyncMock(side_effect=fake_execute)

        app.dependency_overrides[get_current_user] = lambda: teacher
        app.dependency_overrides[get_db] = lambda: mock_db
        with patch(
            "app.ml.router.get_at_risk_prediction",
            new_callable=AsyncMock,
            side_effect=RuntimeError("Secret internal database connection string: postgresql://admin:secret@10.0.0.1"),
        ), patch(
            "app.ml.router.get_at_risk_explanation",
            new_callable=AsyncMock,
            side_effect=RuntimeError("Secret internal database connection string: postgresql://admin:secret@10.0.0.1"),
        ), patch(
            "app.ml.router.get_weak_topic_predictions",
            new_callable=AsyncMock,
            side_effect=RuntimeError("Secret internal database connection string: postgresql://admin:secret@10.0.0.1"),
        ):
            try:
                async with AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as client:
                    resp = await client.get(url, headers=make_auth_header(teacher))
                    assert resp.status_code == 502
                    detail = resp.json()["detail"]
                    assert detail == "ML service temporarily unavailable. Please try again later."
                    # Critical security assertion: ensure the secret exception details are never leaked
                    assert "Secret internal database connection string" not in resp.text
                    assert "postgres" not in resp.text
            finally:
                app.dependency_overrides.pop(get_current_user, None)
                app.dependency_overrides.pop(get_db, None)

    @pytest.mark.asyncio
    async def test_admin_unexpected_inference_error_returns_sanitized_502(self):
        admin = create_mock_user("admin")
        student = create_mock_user("student", grade="10", section="A")
        url = f"/ml/predict/at-risk-admin/{student.id}"

        mock_db = AsyncMock()

        async def fake_execute(statement, *args, **kwargs):
            query_str = str(statement)
            res = MagicMock()
            if "student_profiles" in query_str or "users" in query_str:
                res.first.return_value = (student, student.student_profile)
            return res

        mock_db.execute = AsyncMock(side_effect=fake_execute)

        app.dependency_overrides[get_current_user] = lambda: admin
        app.dependency_overrides[get_db] = lambda: mock_db
        with patch(
            "app.ml.router.get_at_risk_prediction",
            new_callable=AsyncMock,
            side_effect=ValueError("Sensitive internal matrix shape error at /internal/lib/model.bin"),
        ):
            try:
                async with AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as client:
                    resp = await client.get(url, headers=make_auth_header(admin))
                    assert resp.status_code == 502
                    detail = resp.json()["detail"]
                    assert detail == "ML service temporarily unavailable. Please try again later."
                    assert "Sensitive internal matrix shape error" not in resp.text
            finally:
                app.dependency_overrides.pop(get_current_user, None)
                app.dependency_overrides.pop(get_db, None)
