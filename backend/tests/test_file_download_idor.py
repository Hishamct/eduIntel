"""
backend/tests/test_file_download_idor.py

Comprehensive test suite verifying SEC-06 remediation:
- Insecure Direct Object Reference (IDOR) protections on file download endpoints:
    1. GET /teacher/homework/{submission_id}/file
    2. GET /student/study-materials/{material_id}/file
- Authentication and role guards (401 for anonymous, 403 for unauthorized roles).
- Student section resolution and Timetable verification:
    - Teachers must be assigned to student's class section or be designated grader.
    - Students must be enrolled in class section scheduled for that subject on Timetable.
- Administrative universal oversight access.
- Physical file verification on disk (404 when file absent from filesystem).

TEST EXECUTION ENVIRONMENT NOTE:
These automated unit and route-contract tests utilize FastAPI ASGITransport with
dependency injection overrides and AsyncMock session fixtures. They verify authorization
guards, relationship queries, and file responses without mutating active database records.
Live PostgreSQL integration testing with a disposable test database is formally
scheduled for Phase 4.
"""
import os
import tempfile
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.auth.security import create_access_token, hash_password
from app.core.database import get_db
from app.main import app
from app.student.models import HomeworkSubmission
from app.teacher.models import StudyMaterial
from app.users.dependencies import get_current_user
from app.users.models import AdminProfile, StudentProfile, TeacherProfile, User


def create_mock_user(role: str, user_id: uuid.UUID | None = None) -> User:
    uid = user_id or uuid.uuid4()
    user = User(
        id=uid,
        email=f"user_{role}_{uid.hex[:6]}@example.com",
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
            parent_email="parent@example.com",
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


class TestTeacherHomeworkDownloadIDOR:
    @pytest.mark.asyncio
    async def test_homework_download_anonymous_rejected_with_401(self):
        """Verifies unauthenticated requests to download homework return 401."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(f"/teacher/homework/{uuid.uuid4()}/file")
            assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_homework_download_student_rejected_with_403(self):
        """Verifies students attempting to call teacher homework download return 403."""
        student_user = create_mock_user("student")
        app.dependency_overrides[get_current_user] = lambda: student_user

        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                headers = make_auth_header(student_user)
                resp = await client.get(f"/teacher/homework/{uuid.uuid4()}/file", headers=headers)
                assert resp.status_code == 403
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_homework_download_nonexistent_submission_404(self):
        """Verifies 404 Not Found when submission UUID does not exist."""
        teacher_user = create_mock_user("teacher")
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.first.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        app.dependency_overrides[get_current_user] = lambda: teacher_user
        app.dependency_overrides[get_db] = lambda: mock_db

        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                headers = make_auth_header(teacher_user)
                resp = await client.get(f"/teacher/homework/{uuid.uuid4()}/file", headers=headers)
                assert resp.status_code == 404
                assert "Submission not found" in resp.json()["detail"]
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_homework_download_unauthorized_teacher_rejected_with_403(self):
        """
        CRITICAL IDOR TEST:
        Teacher B attempts to download homework of a student in class 10-A.
        Teacher B does NOT teach class 10-A on the timetable and is NOT the grader.
        Expected: HTTP 403 Forbidden.
        """
        teacher_b = create_mock_user("teacher")
        student_user = create_mock_user("student")
        profile = student_user.student_profile  # 10-A

        with tempfile.NamedTemporaryFile(delete=False) as tf:
            tf.write(b"Private student homework answers")
            temp_path = tf.name

        try:
            submission = HomeworkSubmission(
                id=uuid.uuid4(),
                student_id=student_user.id,
                subject="Physics",
                title="Homework 1",
                file_path=temp_path,
                original_filename="hw1.pdf",
                status="submitted",
                graded_by=None,  # Not graded by Teacher B
            )

            mock_db = AsyncMock()

            async def mock_execute(query):
                q = str(query).lower()
                res = MagicMock()
                if "homework_submissions" in q and "student_profiles" in q:
                    res.first.return_value = (submission, profile)
                elif "timetable_entries" in q:
                    # Teacher B is NOT on the timetable for 10-A
                    res.scalar_one_or_none.return_value = None
                return res

            mock_db.execute = AsyncMock(side_effect=mock_execute)

            app.dependency_overrides[get_current_user] = lambda: teacher_b
            app.dependency_overrides[get_db] = lambda: mock_db

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                headers = make_auth_header(teacher_b)
                resp = await client.get(f"/teacher/homework/{submission.id}/file", headers=headers)
                assert resp.status_code == 403
                assert "not assigned to teach this student" in resp.json()["detail"]
        finally:
            app.dependency_overrides.clear()
            if os.path.exists(temp_path):
                os.remove(temp_path)

    @pytest.mark.asyncio
    async def test_homework_download_assigned_teacher_on_timetable_success(self):
        """
        Teacher A teaches class 10-A on the Timetable.
        Teacher A is authorized to download homework submitted by students in 10-A.
        Expected: HTTP 200 OK FileResponse.
        """
        teacher_a = create_mock_user("teacher")
        student_user = create_mock_user("student")
        profile = student_user.student_profile  # 10-A

        with tempfile.NamedTemporaryFile(delete=False) as tf:
            tf.write(b"Student assignment content")
            temp_path = tf.name

        try:
            submission = HomeworkSubmission(
                id=uuid.uuid4(),
                student_id=student_user.id,
                subject="Physics",
                title="Homework 1",
                file_path=temp_path,
                original_filename="hw1.pdf",
                status="submitted",
                graded_by=None,
            )

            mock_db = AsyncMock()

            async def mock_execute(query):
                q = str(query).lower()
                res = MagicMock()
                if "homework_submissions" in q and "student_profiles" in q:
                    res.first.return_value = (submission, profile)
                elif "timetable_entries" in q:
                    # Teacher A is assigned to 10-A
                    res.scalar_one_or_none.return_value = uuid.uuid4()
                return res

            mock_db.execute = AsyncMock(side_effect=mock_execute)

            app.dependency_overrides[get_current_user] = lambda: teacher_a
            app.dependency_overrides[get_db] = lambda: mock_db

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                headers = make_auth_header(teacher_a)
                resp = await client.get(f"/teacher/homework/{submission.id}/file", headers=headers)
                assert resp.status_code == 200
                assert resp.content == b"Student assignment content"
        finally:
            app.dependency_overrides.clear()
            if os.path.exists(temp_path):
                os.remove(temp_path)

    @pytest.mark.asyncio
    async def test_homework_download_grader_teacher_success(self):
        """
        Teacher is the designated grader (submission.graded_by == current_user.id).
        Even if not currently scheduled in timetable slot, grader access is authorized.
        Expected: HTTP 200 OK FileResponse.
        """
        teacher_grader = create_mock_user("teacher")
        student_user = create_mock_user("student")
        profile = student_user.student_profile

        with tempfile.NamedTemporaryFile(delete=False) as tf:
            tf.write(b"Graded homework paper")
            temp_path = tf.name

        try:
            submission = HomeworkSubmission(
                id=uuid.uuid4(),
                student_id=student_user.id,
                subject="Physics",
                title="Homework 1",
                file_path=temp_path,
                original_filename="hw1.pdf",
                status="graded",
                graded_by=teacher_grader.id,  # Teacher is grader
            )

            mock_db = AsyncMock()

            async def mock_execute(query):
                q = str(query).lower()
                res = MagicMock()
                if "homework_submissions" in q and "student_profiles" in q:
                    res.first.return_value = (submission, profile)
                elif "timetable_entries" in q:
                    res.scalar_one_or_none.return_value = None
                return res

            mock_db.execute = AsyncMock(side_effect=mock_execute)

            app.dependency_overrides[get_current_user] = lambda: teacher_grader
            app.dependency_overrides[get_db] = lambda: mock_db

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                headers = make_auth_header(teacher_grader)
                resp = await client.get(f"/teacher/homework/{submission.id}/file", headers=headers)
                assert resp.status_code == 200
                assert resp.content == b"Graded homework paper"
        finally:
            app.dependency_overrides.clear()
            if os.path.exists(temp_path):
                os.remove(temp_path)

    @pytest.mark.asyncio
    async def test_homework_download_unassigned_teacher_rejected_when_graded_by_another_teacher(self):
        """
        Teacher B (unassigned) attempts to download homework graded by Teacher C.
        Because Teacher B is NOT the grader and NOT on the student's timetable,
        Teacher B must be rejected with HTTP 403 Forbidden.
        """
        teacher_b = create_mock_user("teacher")
        teacher_c_id = uuid.uuid4()
        student_user = create_mock_user("student")
        profile = student_user.student_profile

        with tempfile.NamedTemporaryFile(delete=False) as tf:
            tf.write(b"Homework paper graded by Teacher C")
            temp_path = tf.name

        try:
            submission = HomeworkSubmission(
                id=uuid.uuid4(),
                student_id=student_user.id,
                subject="Physics",
                title="Homework 1",
                file_path=temp_path,
                original_filename="hw1.pdf",
                status="graded",
                graded_by=teacher_c_id,  # Graded by Teacher C, NOT Teacher B
            )

            mock_db = AsyncMock()

            async def mock_execute(query):
                q = str(query).lower()
                res = MagicMock()
                if "homework_submissions" in q and "student_profiles" in q:
                    res.first.return_value = (submission, profile)
                elif "timetable_entries" in q:
                    res.scalar_one_or_none.return_value = None
                return res

            mock_db.execute = AsyncMock(side_effect=mock_execute)

            app.dependency_overrides[get_current_user] = lambda: teacher_b
            app.dependency_overrides[get_db] = lambda: mock_db

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                headers = make_auth_header(teacher_b)
                resp = await client.get(f"/teacher/homework/{submission.id}/file", headers=headers)
                assert resp.status_code == 403
                assert "not assigned to teach this student" in resp.json()["detail"]
        finally:
            app.dependency_overrides.clear()
            if os.path.exists(temp_path):
                os.remove(temp_path)

    @pytest.mark.asyncio
    async def test_homework_download_admin_success(self):
        """
        Institutional administrator is authorized to download any homework file.
        Expected: HTTP 200 OK FileResponse.
        """
        admin_user = create_mock_user("admin")
        student_user = create_mock_user("student")
        profile = student_user.student_profile

        with tempfile.NamedTemporaryFile(delete=False) as tf:
            tf.write(b"Administrator audit file")
            temp_path = tf.name

        try:
            submission = HomeworkSubmission(
                id=uuid.uuid4(),
                student_id=student_user.id,
                subject="Math",
                title="Calculus HW",
                file_path=temp_path,
                original_filename="calc.pdf",
                status="submitted",
            )

            mock_db = AsyncMock()
            mock_res = MagicMock()
            mock_res.first.return_value = (submission, profile)
            mock_db.execute = AsyncMock(return_value=mock_res)

            app.dependency_overrides[get_current_user] = lambda: admin_user
            app.dependency_overrides[get_db] = lambda: mock_db

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                headers = make_auth_header(admin_user)
                resp = await client.get(f"/teacher/homework/{submission.id}/file", headers=headers)
                assert resp.status_code == 200
                assert resp.content == b"Administrator audit file"
        finally:
            app.dependency_overrides.clear()
            if os.path.exists(temp_path):
                os.remove(temp_path)

    @pytest.mark.asyncio
    async def test_homework_download_file_missing_on_disk_returns_404(self):
        """
        Authorized teacher attempts to download a submission whose physical
        file was deleted or moved from disk.
        Expected: HTTP 404 Not Found (not 500 server crash).
        """
        teacher_a = create_mock_user("teacher")
        student_user = create_mock_user("student")
        profile = student_user.student_profile

        submission = HomeworkSubmission(
            id=uuid.uuid4(),
            student_id=student_user.id,
            subject="Physics",
            title="Homework 1",
            file_path="/tmp/nonexistent_homework_file_xyz123.pdf",
            original_filename="hw1.pdf",
            status="submitted",
        )

        mock_db = AsyncMock()

        async def mock_execute(query):
            q = str(query).lower()
            res = MagicMock()
            if "homework_submissions" in q and "student_profiles" in q:
                res.first.return_value = (submission, profile)
            elif "timetable_entries" in q:
                res.scalar_one_or_none.return_value = uuid.uuid4()
            return res

        mock_db.execute = AsyncMock(side_effect=mock_execute)

        app.dependency_overrides[get_current_user] = lambda: teacher_a
        app.dependency_overrides[get_db] = lambda: mock_db

        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                headers = make_auth_header(teacher_a)
                resp = await client.get(f"/teacher/homework/{submission.id}/file", headers=headers)
                assert resp.status_code == 404
                assert "not found on disk" in resp.json()["detail"]
        finally:
            app.dependency_overrides.clear()


class TestStudentStudyMaterialDownloadIDOR:
    @pytest.mark.asyncio
    async def test_study_material_download_anonymous_rejected_with_401(self):
        """Verifies unauthenticated callers receive 401 Unauthorized."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(f"/student/study-materials/{uuid.uuid4()}/file")
            assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_study_material_download_nonexistent_material_404(self):
        """Verifies 404 Not Found when study material UUID does not exist."""
        student_user = create_mock_user("student")
        mock_db = AsyncMock()
        mock_res = MagicMock()
        mock_res.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_res)

        app.dependency_overrides[get_current_user] = lambda: student_user
        app.dependency_overrides[get_db] = lambda: mock_db

        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                headers = make_auth_header(student_user)
                resp = await client.get(f"/student/study-materials/{uuid.uuid4()}/file", headers=headers)
                assert resp.status_code == 404
                assert "Study material not found" in resp.json()["detail"]
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_study_material_download_unenrolled_student_rejected_with_403(self):
        """
        CRITICAL IDOR TEST:
        Student is in class 8-B. Study material is for 12-A Physics.
        Student has NO timetable entry for this subject.
        Expected: HTTP 403 Forbidden.
        """
        student_user = create_mock_user("student")
        student_user.student_profile.grade = "8"
        student_user.student_profile.section = "B"

        with tempfile.NamedTemporaryFile(delete=False) as tf:
            tf.write(b"Advanced 12-A Quantum Physics Notes")
            temp_path = tf.name

        try:
            material = StudyMaterial(
                id=uuid.uuid4(),
                teacher_id=uuid.uuid4(),
                subject="Physics",
                title="Advanced Quantum Mechanics",
                file_path=temp_path,
                original_filename="quantum.pdf",
            )

            mock_db = AsyncMock()

            async def mock_execute(query):
                q = str(query).lower()
                res = MagicMock()
                if "study_materials" in q:
                    res.scalar_one_or_none.return_value = material
                elif "student_profiles" in q:
                    res.scalar_one_or_none.return_value = student_user.student_profile
                elif "timetable_entries" in q:
                    # No timetable entry for 8-B Physics
                    res.scalar_one_or_none.return_value = None
                return res

            mock_db.execute = AsyncMock(side_effect=mock_execute)

            app.dependency_overrides[get_current_user] = lambda: student_user
            app.dependency_overrides[get_db] = lambda: mock_db

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                headers = make_auth_header(student_user)
                resp = await client.get(f"/student/study-materials/{material.id}/file", headers=headers)
                assert resp.status_code == 403
                assert "not enrolled in any class section for this subject" in resp.json()["detail"]
        finally:
            app.dependency_overrides.clear()
            if os.path.exists(temp_path):
                os.remove(temp_path)

    @pytest.mark.asyncio
    async def test_study_material_download_enrolled_student_success(self):
        """
        Student in 10-A is scheduled for Physics on Timetable.
        Authorized to download 10-A Physics study material.
        Expected: HTTP 200 OK FileResponse.
        """
        student_user = create_mock_user("student")
        student_user.student_profile.grade = "10"
        student_user.student_profile.section = "A"

        with tempfile.NamedTemporaryFile(delete=False) as tf:
            tf.write(b"Class 10 Physics Mechanics Notes")
            temp_path = tf.name

        try:
            material = StudyMaterial(
                id=uuid.uuid4(),
                teacher_id=uuid.uuid4(),
                subject="Physics",
                title="Mechanics Notes",
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
                    res.scalar_one_or_none.return_value = student_user.student_profile
                elif "timetable_entries" in q:
                    # 10-A has Physics on Timetable
                    res.scalar_one_or_none.return_value = uuid.uuid4()
                return res

            mock_db.execute = AsyncMock(side_effect=mock_execute)

            app.dependency_overrides[get_current_user] = lambda: student_user
            app.dependency_overrides[get_db] = lambda: mock_db

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                headers = make_auth_header(student_user)
                resp = await client.get(f"/student/study-materials/{material.id}/file", headers=headers)
                assert resp.status_code == 200
                assert resp.content == b"Class 10 Physics Mechanics Notes"
        finally:
            app.dependency_overrides.clear()
            if os.path.exists(temp_path):
                os.remove(temp_path)

    @pytest.mark.asyncio
    async def test_study_material_download_uploader_teacher_success(self):
        """
        Teacher who uploaded the study material is authorized to download it.
        Expected: HTTP 200 OK FileResponse.
        """
        teacher_owner = create_mock_user("teacher")

        with tempfile.NamedTemporaryFile(delete=False) as tf:
            tf.write(b"Teacher proprietary lesson plan")
            temp_path = tf.name

        try:
            material = StudyMaterial(
                id=uuid.uuid4(),
                teacher_id=teacher_owner.id,  # Owner
                subject="Biology",
                title="Cell Biology Handout",
                file_path=temp_path,
                original_filename="cell.pdf",
            )

            mock_db = AsyncMock()
            mock_res = MagicMock()
            mock_res.scalar_one_or_none.return_value = material
            mock_db.execute = AsyncMock(return_value=mock_res)

            app.dependency_overrides[get_current_user] = lambda: teacher_owner
            app.dependency_overrides[get_db] = lambda: mock_db

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                headers = make_auth_header(teacher_owner)
                resp = await client.get(f"/student/study-materials/{material.id}/file", headers=headers)
                assert resp.status_code == 200
                assert resp.content == b"Teacher proprietary lesson plan"
        finally:
            app.dependency_overrides.clear()
            if os.path.exists(temp_path):
                os.remove(temp_path)

    @pytest.mark.asyncio
    async def test_study_material_download_unrelated_teacher_rejected_with_403(self):
        """
        Teacher B attempts to download Teacher A's material for a subject Teacher B does not teach.
        Expected: HTTP 403 Forbidden.
        """
        teacher_b = create_mock_user("teacher")
        teacher_a_id = uuid.uuid4()

        with tempfile.NamedTemporaryFile(delete=False) as tf:
            tf.write(b"Teacher A Chemistry Notes")
            temp_path = tf.name

        try:
            material = StudyMaterial(
                id=uuid.uuid4(),
                teacher_id=teacher_a_id,
                subject="Chemistry",
                title="Organic Chemistry",
                file_path=temp_path,
                original_filename="organic.pdf",
            )

            mock_db = AsyncMock()

            async def mock_execute(query):
                q = str(query).lower()
                res = MagicMock()
                if "study_materials" in q:
                    res.scalar_one_or_none.return_value = material
                elif "timetable_entries" in q:
                    # Teacher B does not teach Chemistry
                    res.scalar_one_or_none.return_value = None
                return res

            mock_db.execute = AsyncMock(side_effect=mock_execute)

            app.dependency_overrides[get_current_user] = lambda: teacher_b
            app.dependency_overrides[get_db] = lambda: mock_db

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                headers = make_auth_header(teacher_b)
                resp = await client.get(f"/student/study-materials/{material.id}/file", headers=headers)
                assert resp.status_code == 403
                assert "You do not teach this subject" in resp.json()["detail"]
        finally:
            app.dependency_overrides.clear()
            if os.path.exists(temp_path):
                os.remove(temp_path)

    @pytest.mark.asyncio
    async def test_study_material_download_admin_success(self):
        """
        Institutional administrator is authorized to download any study material.
        Expected: HTTP 200 OK FileResponse.
        """
        admin_user = create_mock_user("admin")

        with tempfile.NamedTemporaryFile(delete=False) as tf:
            tf.write(b"Administrative curriculum overview")
            temp_path = tf.name

        try:
            material = StudyMaterial(
                id=uuid.uuid4(),
                teacher_id=uuid.uuid4(),
                subject="History",
                title="World History Chapter 1",
                file_path=temp_path,
                original_filename="history.pdf",
            )

            mock_db = AsyncMock()
            mock_res = MagicMock()
            mock_res.scalar_one_or_none.return_value = material
            mock_db.execute = AsyncMock(return_value=mock_res)

            app.dependency_overrides[get_current_user] = lambda: admin_user
            app.dependency_overrides[get_db] = lambda: mock_db

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                headers = make_auth_header(admin_user)
                resp = await client.get(f"/student/study-materials/{material.id}/file", headers=headers)
                assert resp.status_code == 200
                assert resp.content == b"Administrative curriculum overview"
        finally:
            app.dependency_overrides.clear()
            if os.path.exists(temp_path):
                os.remove(temp_path)

    @pytest.mark.asyncio
    async def test_study_material_download_file_missing_on_disk_returns_404(self):
        """
        Authorized student attempts to download a study material record whose
        physical file was deleted from disk.
        Expected: HTTP 404 Not Found (not 500 server crash).
        """
        student_user = create_mock_user("student")
        student_user.student_profile.grade = "10"
        student_user.student_profile.section = "A"

        material = StudyMaterial(
            id=uuid.uuid4(),
            teacher_id=uuid.uuid4(),
            subject="Physics",
            title="Lost Physics Notes",
            file_path="/tmp/nonexistent_study_material_file_abc999.pdf",
            original_filename="lost.pdf",
        )

        mock_db = AsyncMock()

        async def mock_execute(query):
            q = str(query).lower()
            res = MagicMock()
            if "study_materials" in q:
                res.scalar_one_or_none.return_value = material
            elif "student_profiles" in q:
                res.scalar_one_or_none.return_value = student_user.student_profile
            elif "timetable_entries" in q:
                res.scalar_one_or_none.return_value = uuid.uuid4()
            return res

        mock_db.execute = AsyncMock(side_effect=mock_execute)

        app.dependency_overrides[get_current_user] = lambda: student_user
        app.dependency_overrides[get_db] = lambda: mock_db

        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                headers = make_auth_header(student_user)
                resp = await client.get(f"/student/study-materials/{material.id}/file", headers=headers)
                assert resp.status_code == 404
                assert "not found on disk" in resp.json()["detail"]
        finally:
            app.dependency_overrides.clear()
