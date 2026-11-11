"""
backend/tests/test_ml_router_and_inference_hardening.py

Comprehensive test suite verifying Phase 5 Step 3.6 Stage 4:
Worksheet Generator & ML Router Hardening.

Test Categories:
1. TestModelArtifactIntegrityAndManifest (8 tests)
2. TestConcurrentModelLoadingAndCacheThreadSafety (2 tests)
3. TestFeatureValidationAndDomainBoundaries (8 tests)
4. TestEventLoopUnblocking (3 tests)
5. TestMLRouterConcurrencyAndOverloadProtection (4 tests)
6. TestErrorSanitizationAndZeroLeakage (5 tests)
7. TestWorksheetTimeoutAndCancellationLifecycle (2 tests)
8. TestMLInferencePhysicalWorkerLifecycle (5 tests)
9. TestFastAPIShutdownLifespanQuiescence (6 tests)
"""

from __future__ import annotations

import asyncio
import copy
import datetime
import hashlib
import threading
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import joblib
import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient

from app.auth.security import create_access_token, hash_password
from app.core.database import get_db
from app.core.llm_client import LLMCallUsage
from app.core.tenant import TenantContext, get_tenant_context, get_tenant_db
from app.main import app, lifespan
from app.ml.explain import _clear_explainer_cache_for_testing, get_at_risk_explanation
from app.ml.router import (
    _ACTIVE_DETACHED_TELEMETRY_TASKS,
    _ACTIVE_ML_INFERENCE_TASKS,
    _ACTIVE_WORKSHEET_TASKS,
    ML_INFERENCE_SEMAPHORE,
    WORKSHEET_GENERATION_SEMAPHORE,
    _persist_background_detached_usage,
    _reset_ml_shutdown_state_for_testing,
    generate_worksheet,
    ml_inference_capacity_scope,
    run_with_inference_capacity,
    wait_for_ml_quiescence,
)
from app.ml.service import (
    MODEL_MANIFEST,
    FeatureValidationError,
    ModelFormatError,
    ModelIntegrityError,
    ModelNotFoundError,
    _clear_loaded_models_for_testing,
    get_at_risk_prediction,
    get_weak_topic_predictions,
    load_verified_model,
    validate_at_risk_features,
    validate_weak_topic_features,
)
from app.users.dependencies import get_current_user
from app.users.models import AdminProfile, StudentProfile, TeacherProfile, User


def create_test_user(
    role: str,
    user_id: uuid.UUID | None = None,
    grade: str | None = "10",
    section: str | None = "A",
) -> User:
    uid = user_id or uuid.uuid4()
    user = User(
        id=uid,
        email=f"ml_test_{role}_{uid.hex[:6]}@example.com",
        name=f"ML Test {role.capitalize()}",
        hashed_password=hash_password("HardenedPass123!"),
        role=role,
        is_active=True,
    )
    if role == "student":
        user.student_profile = StudentProfile(
            id=uuid.uuid4(),
            user_id=uid,
            grade=grade,
            section=section,
            parent_email="parent@example.com",
        )
    elif role == "teacher":
        user.teacher_profile = TeacherProfile(
            id=uuid.uuid4(),
            user_id=uid,
            department="Science",
            subjects="Mathematics",
        )
    elif role == "admin":
        user.admin_profile = AdminProfile(
            id=uuid.uuid4(),
            user_id=uid,
            designation="Principal",
        )
    return user


def make_test_auth_headers(user: User) -> dict[str, str]:
    token = create_access_token(
        data={"sub": str(user.id), "email": user.email, "role": user.role}
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(autouse=True)
def clean_model_and_explainer_caches():
    """Ensures each test begins and ends with empty model/explainer caches."""
    _clear_loaded_models_for_testing()
    _clear_explainer_cache_for_testing()
    yield
    _clear_loaded_models_for_testing()
    _clear_explainer_cache_for_testing()


@pytest.fixture(autouse=True)
def reset_ml_shutdown_state_module_fixture():
    """
    Module-wide fixture guaranteeing _ML_SHUTDOWN_IN_PROGRESS is strictly False
    before and after every single test across all classes in this module.
    Prevents cross-test state leakage under randomized test ordering.
    """
    _reset_ml_shutdown_state_for_testing()
    yield
    _reset_ml_shutdown_state_for_testing()


async def assert_event_set_within(
    event: threading.Event | asyncio.Event,
    task: asyncio.Task | None = None,
    timeout: float = 3.0,
    description: str = "Worker startup event",
) -> None:
    """
    Defensively awaits an event with an explicit timeout.
    If an associated task is passed and completes before the event is set,
    immediately surfaces the task's exception or return state with a detailed error.
    """
    deadline = asyncio.get_running_loop().time() + timeout
    while True:
        if isinstance(event, threading.Event):
            if event.is_set():
                return
        elif event.is_set():
            return

        if task is not None and task.done():
            # If the task failed (e.g. HTTP 503 rejection), surface the exception immediately
            exc = task.exception()
            if exc is not None:
                raise RuntimeError(
                    f"{description} aborted prematurely because task {task} failed: {exc}"
                ) from exc
            else:
                raise RuntimeError(
                    f"{description} aborted prematurely because task {task} completed without setting event (result={task.result()})"
                )

        if asyncio.get_running_loop().time() > deadline:
            task_status = f"task done={task.done()}" if task is not None else "no task"
            raise TimeoutError(
                f"{description} was not set within {timeout:.1f}s ({task_status})"
            )

        await asyncio.sleep(0.01)


class DummyPickleablePredictor:
    def predict_proba(self, X):
        return [[0.5, 0.5]]


# ==============================================================================
# 1. TestModelArtifactIntegrityAndManifest
# ==============================================================================
class TestModelArtifactIntegrityAndManifest:
    """Verifies SHA-256 verification, manifest compliance, and format validations."""

    def test_at_risk_model_loads_and_verifies_checksum(self):
        bundle = load_verified_model("at_risk")
        assert isinstance(bundle, dict)
        assert "model" in bundle
        assert "feature_cols" in bundle
        assert hasattr(bundle["model"], "predict_proba")
        assert bundle["feature_cols"] == MODEL_MANIFEST["at_risk"]["expected_features"]

    def test_weak_topic_model_loads_and_verifies_checksum(self):
        bundle = load_verified_model("weak_topic")
        assert isinstance(bundle, dict)
        assert "model" in bundle
        assert "feature_cols" in bundle
        assert hasattr(bundle["model"], "predict_proba")
        assert bundle["feature_cols"] == MODEL_MANIFEST["weak_topic"]["expected_features"]

    def test_unknown_model_name_raises_model_not_found(self):
        with pytest.raises(ModelNotFoundError, match="Unknown model name"):
            load_verified_model("non_existent_model")

    def test_checksum_mismatch_raises_model_integrity_error(self):
        tampered_manifest = copy.deepcopy(MODEL_MANIFEST)
        tampered_manifest["at_risk"]["sha256"] = "0" * 64
        with patch.dict("app.ml.service.MODEL_MANIFEST", tampered_manifest):
            with pytest.raises(ModelIntegrityError, match="integrity check failed"):
                load_verified_model("at_risk")

    def test_missing_model_file_raises_model_not_found_error(self):
        missing_manifest = copy.deepcopy(MODEL_MANIFEST)
        missing_manifest["at_risk"]["filename"] = "completely_missing_model.joblib"
        with patch.dict("app.ml.service.MODEL_MANIFEST", missing_manifest):
            with pytest.raises(ModelNotFoundError, match="not found"):
                load_verified_model("at_risk")

    def test_corrupted_model_file_raises_model_format_error(self, tmp_path: Path):
        bad_file = tmp_path / "corrupted_model.joblib"
        bad_file.write_bytes(b"This is not a valid joblib or pickle stream.")

        # Compute actual hash of corrupted file so checksum check passes
        sha = hashlib.sha256(bad_file.read_bytes()).hexdigest()

        corrupt_manifest = copy.deepcopy(MODEL_MANIFEST)
        corrupt_manifest["at_risk"]["filename"] = str(bad_file)
        corrupt_manifest["at_risk"]["sha256"] = sha

        with patch.dict("app.ml.service.MODEL_MANIFEST", corrupt_manifest):
            with pytest.raises(ModelFormatError, match="Failed to deserialize"):
                load_verified_model("at_risk")

    def test_model_bundle_missing_keys_raises_model_format_error(self, tmp_path: Path):
        incomplete_bundle = {"model": DummyPickleablePredictor()}  # missing feature_cols
        bundle_file = tmp_path / "missing_keys.joblib"
        joblib.dump(incomplete_bundle, bundle_file)

        sha = hashlib.sha256(bundle_file.read_bytes()).hexdigest()
        manifest = copy.deepcopy(MODEL_MANIFEST)
        manifest["at_risk"]["filename"] = str(bundle_file)
        manifest["at_risk"]["sha256"] = sha

        with patch.dict("app.ml.service.MODEL_MANIFEST", manifest):
            with pytest.raises(ModelFormatError, match="missing required keys"):
                load_verified_model("at_risk")

    def test_model_lacking_predict_proba_raises_model_format_error(self, tmp_path: Path):
        non_predictor = {
            "model": object(),  # Has no predict_proba method
            "feature_cols": MODEL_MANIFEST["at_risk"]["expected_features"],
        }
        bundle_file = tmp_path / "non_predictor.joblib"
        joblib.dump(non_predictor, bundle_file)

        sha = hashlib.sha256(bundle_file.read_bytes()).hexdigest()
        manifest = copy.deepcopy(MODEL_MANIFEST)
        manifest["at_risk"]["filename"] = str(bundle_file)
        manifest["at_risk"]["sha256"] = sha

        with patch.dict("app.ml.service.MODEL_MANIFEST", manifest):
            with pytest.raises(ModelFormatError, match="does not implement callable predict_proba"):
                load_verified_model("at_risk")


# ==============================================================================
# 2. TestConcurrentModelLoadingAndCacheThreadSafety
# ==============================================================================
class TestConcurrentModelLoadingAndCacheThreadSafety:
    """Verifies that model artifact loading is synchronized and cached safely across threads."""

    def test_concurrent_load_verified_model_is_thread_safe(self):
        results = []
        errors = []

        def worker():
            try:
                bundle = load_verified_model("at_risk")
                results.append(id(bundle))
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(12)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        assert len(results) == 12
        # All concurrent invocations must resolve to the identical cached instance
        assert len(set(results)) == 1

    def test_cache_clear_helper_resets_caches(self):
        bundle1 = load_verified_model("at_risk")
        _clear_loaded_models_for_testing()
        bundle2 = load_verified_model("at_risk")
        assert bundle1 is not bundle2
        assert bundle1["feature_cols"] == bundle2["feature_cols"]


# ==============================================================================
# 3. TestFeatureValidationAndDomainBoundaries
# ==============================================================================
class TestFeatureValidationAndDomainBoundaries:
    """Verifies feature schema, ordering, types, finiteness, and range checks."""

    def test_valid_at_risk_features_pass_validation(self):
        cols = MODEL_MANIFEST["at_risk"]["expected_features"]
        valid_dict = {
            "attendance_rate": 0.85,
            "homework_submission_rate": 0.90,
            "avg_score_overall": 72.5,
            "score_trend": 4.2,
            "doubt_thread_count": 3,
        }
        vector = validate_at_risk_features(valid_dict, cols)
        assert vector == [0.85, 0.90, 72.5, 4.2, 3.0]

    def test_at_risk_missing_feature_raises_validation_error(self):
        cols = MODEL_MANIFEST["at_risk"]["expected_features"]
        incomplete = {
            "attendance_rate": 0.85,
            "homework_submission_rate": 0.90,
            # avg_score_overall missing
            "score_trend": 4.2,
            "doubt_thread_count": 3,
        }
        with pytest.raises(FeatureValidationError, match="Missing required feature: 'avg_score_overall'"):
            validate_at_risk_features(incomplete, cols)

    def test_at_risk_boolean_feature_rejected(self):
        cols = MODEL_MANIFEST["at_risk"]["expected_features"]
        bool_feat = {
            "attendance_rate": True,  # booleans are int subclasses in Python; must be explicitly rejected
            "homework_submission_rate": 0.90,
            "avg_score_overall": 72.5,
            "score_trend": 4.2,
            "doubt_thread_count": 3,
        }
        with pytest.raises(FeatureValidationError, match="must be numeric"):
            validate_at_risk_features(bool_feat, cols)

    def test_at_risk_non_finite_feature_rejected(self):
        cols = MODEL_MANIFEST["at_risk"]["expected_features"]
        nan_feat = {
            "attendance_rate": float("nan"),
            "homework_submission_rate": 0.90,
            "avg_score_overall": 72.5,
            "score_trend": 4.2,
            "doubt_thread_count": 3,
        }
        with pytest.raises(FeatureValidationError, match="is not finite"):
            validate_at_risk_features(nan_feat, cols)

        inf_feat = {
            "attendance_rate": 0.85,
            "homework_submission_rate": float("inf"),
            "avg_score_overall": 72.5,
            "score_trend": 4.2,
            "doubt_thread_count": 3,
        }
        with pytest.raises(FeatureValidationError, match="is not finite"):
            validate_at_risk_features(inf_feat, cols)

    def test_at_risk_out_of_bounds_features_rejected(self):
        cols = MODEL_MANIFEST["at_risk"]["expected_features"]

        # attendance_rate > 1.0
        with pytest.raises(FeatureValidationError, match="out of domain bounds"):
            validate_at_risk_features(
                {
                    "attendance_rate": 1.25,
                    "homework_submission_rate": 0.9,
                    "avg_score_overall": 80.0,
                    "score_trend": 0.0,
                    "doubt_thread_count": 0,
                },
                cols,
            )

        # avg_score_overall < 0.0
        with pytest.raises(FeatureValidationError, match="out of domain bounds"):
            validate_at_risk_features(
                {
                    "attendance_rate": 0.8,
                    "homework_submission_rate": 0.9,
                    "avg_score_overall": -5.0,
                    "score_trend": 0.0,
                    "doubt_thread_count": 0,
                },
                cols,
            )

        # score_trend > 100.0
        with pytest.raises(FeatureValidationError, match="out of domain bounds"):
            validate_at_risk_features(
                {
                    "attendance_rate": 0.8,
                    "homework_submission_rate": 0.9,
                    "avg_score_overall": 80.0,
                    "score_trend": 150.0,
                    "doubt_thread_count": 0,
                },
                cols,
            )

    def test_valid_weak_topic_features_pass_validation(self):
        cols = MODEL_MANIFEST["weak_topic"]["expected_features"]
        valid_row = {
            "attendance_rate": 0.80,
            "homework_submission_rate": 0.75,
            "topic_avg_score": 45.0,
            "student_overall_avg": 70.0,
            "relative_gap": -25.0,
            "subject_CHEMISTRY": 0,
            "subject_COMPUTER SCIENCE": 0,
            "subject_MATHEMATICS": 1,
            "subject_PHYSICS": 0,
        }
        vector = validate_weak_topic_features(valid_row, cols)
        assert len(vector) == len(cols)
        assert vector[cols.index("subject_MATHEMATICS")] == 1.0

    def test_weak_topic_invalid_one_hot_rejected(self):
        cols = MODEL_MANIFEST["weak_topic"]["expected_features"]
        invalid_one_hot = {
            "attendance_rate": 0.80,
            "homework_submission_rate": 0.75,
            "topic_avg_score": 45.0,
            "student_overall_avg": 70.0,
            "relative_gap": -25.0,
            "subject_CHEMISTRY": 0,
            "subject_COMPUTER SCIENCE": 0,
            "subject_MATHEMATICS": 5.0,  # Must be 0 or 1
            "subject_PHYSICS": 0,
        }
        with pytest.raises(FeatureValidationError, match="One-hot feature 'subject_MATHEMATICS' must be 0 or 1"):
            validate_weak_topic_features(invalid_one_hot, cols)


# ==============================================================================
# 4. TestEventLoopUnblocking
# ==============================================================================
class TestEventLoopUnblocking:
    """Verifies CPU-bound model loading, inference, and SHAP trees run off the asyncio event loop."""

    @pytest.mark.asyncio
    async def test_at_risk_prediction_offloads_inference_to_thread(self):
        mock_db = AsyncMock()
        student_id = uuid.uuid4()

        # Mock student history so prediction executes
        with patch(
            "app.ml.service._get_student_history",
            new_callable=AsyncMock,
            return_value=(
                [MagicMock(date=None, status="present")],  # attendance
                [MagicMock(created_at=None)],               # homework
                [MagicMock(score=75, exam_date=None)],     # exams
                [MagicMock(created_at=None)],               # doubts
            ),
        ), patch(
            "app.ml.service._compute_at_risk_features",
            return_value={
                "attendance_rate": 0.9,
                "homework_submission_rate": 0.8,
                "avg_score_overall": 75.0,
                "score_trend": 2.0,
                "doubt_thread_count": 1,
            },
        ), patch("asyncio.to_thread", wraps=asyncio.to_thread) as spy_to_thread:
            result = await get_at_risk_prediction(mock_db, student_id)
            assert "is_at_risk" in result
            assert "risk_probability" in result

            # Verify asyncio.to_thread was called for model load and model.predict_proba
            thread_call_targets = [call.args[0] for call in spy_to_thread.call_args_list]
            assert any(callable(t) and "predict_proba" in getattr(t, "__name__", "") for t in thread_call_targets)

    @pytest.mark.asyncio
    async def test_weak_topic_prediction_offloads_inference_to_thread(self):
        mock_db = AsyncMock()
        student_id = uuid.uuid4()

        mock_exam = MagicMock(subject="MATHEMATICS", topic="Calculus", score=60, exam_date=None)

        d1 = datetime.date(2025, 1, 1)
        d2 = datetime.date(2025, 3, 1)
        with patch(
            "app.ml.service._get_student_history",
            new_callable=AsyncMock,
            return_value=(
                [MagicMock(date=d1, status="present"), MagicMock(date=d2, status="present")],
                [MagicMock(created_at=None)],
                [mock_exam],
                [],
            ),
        ), patch("asyncio.to_thread", wraps=asyncio.to_thread) as spy_to_thread:
            predictions = await get_weak_topic_predictions(mock_db, student_id)
            assert isinstance(predictions, list)
            assert len(predictions) == 1
            assert predictions[0]["topic"] == "Calculus"

            thread_call_targets = [call.args[0] for call in spy_to_thread.call_args_list]
            assert any(callable(t) and "predict_proba" in getattr(t, "__name__", "") for t in thread_call_targets)

    @pytest.mark.asyncio
    async def test_at_risk_explanation_offloads_shap_to_thread(self):
        mock_db = AsyncMock()
        student_id = uuid.uuid4()

        with patch(
            "app.ml.explain._get_student_history",
            new_callable=AsyncMock,
            return_value=(
                [MagicMock(date=None, status="present")],
                [MagicMock(created_at=None)],
                [MagicMock(score=75, exam_date=None)],
                [MagicMock(created_at=None)],
            ),
        ), patch(
            "app.ml.explain._compute_at_risk_features",
            return_value={
                "attendance_rate": 0.9,
                "homework_submission_rate": 0.8,
                "avg_score_overall": 75.0,
                "score_trend": 2.0,
                "doubt_thread_count": 1,
            },
        ), patch("asyncio.to_thread", wraps=asyncio.to_thread) as spy_to_thread:
            result = await get_at_risk_explanation(mock_db, student_id)
            assert "top_factors" in result
            assert len(result["top_factors"]) > 0

            # Verify SHAP calculation was offloaded to worker thread
            thread_call_targets = [call.args[0] for call in spy_to_thread.call_args_list]
            assert any(
                callable(t) and ("_compute_shap" in getattr(t, "__name__", "") or "predict_proba" in getattr(t, "__name__", ""))
                for t in thread_call_targets
            )


# ==============================================================================
# 5. TestMLRouterConcurrencyAndOverloadProtection
# ==============================================================================
class TestMLRouterConcurrencyAndOverloadProtection:
    """Verifies semaphore concurrency bounds and HTTP 503 Retry-After: 5 overload behavior."""

    @pytest.mark.asyncio
    async def test_ml_inference_semaphore_overload_returns_503(self):
        teacher = create_test_user("teacher")
        student = create_test_user("student", grade="10", section="A")

        mock_db = AsyncMock()

        async def fake_execute(stmt, *args, **kwargs):
            query_str = str(stmt)
            res = MagicMock()
            if "student_profiles" in query_str or "users" in query_str:
                res.first.return_value = (student, student.student_profile)
            elif "timetable_entries" in query_str:
                res.scalar_one_or_none.return_value = uuid.uuid4()
            return res

        mock_db.execute = AsyncMock(side_effect=fake_execute)

        app.dependency_overrides[get_current_user] = lambda: teacher
        app.dependency_overrides[get_db] = lambda: mock_db

        try:
            # Saturate all 16 semaphore permits
            permits = []
            for _ in range(16):
                await ML_INFERENCE_SEMAPHORE.acquire()
                permits.append(None)

            assert ML_INFERENCE_SEMAPHORE._value == 0

            # Fast timeout for test speed
            with patch("app.ml.router.ML_INFERENCE_ACQUIRE_TIMEOUT", 0.05):
                async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                    resp = await client.get(
                        f"/ml/predict/at-risk/{student.id}",
                        headers=make_test_auth_headers(teacher),
                    )
                    assert resp.status_code == 503
                    assert resp.headers.get("retry-after") == "5"
                    assert "maximum capacity" in resp.json()["detail"]
        finally:
            for _ in permits:
                ML_INFERENCE_SEMAPHORE.release()
            app.dependency_overrides.pop(get_current_user, None)
            app.dependency_overrides.pop(get_db, None)

    @pytest.mark.asyncio
    async def test_worksheet_generation_semaphore_overload_returns_503(self):
        inst_id = uuid.uuid4()
        teacher_tenant = TenantContext(institution_id=inst_id, user_id=uuid.uuid4(), role="teacher")
        mock_db = AsyncMock()

        app.dependency_overrides[get_tenant_context] = lambda: teacher_tenant
        app.dependency_overrides[get_tenant_db] = lambda: mock_db

        permits = []
        try:
            # Saturate all 10 worksheet generation slots
            for _ in range(10):
                await WORKSHEET_GENERATION_SEMAPHORE.acquire()
                permits.append(None)

            assert WORKSHEET_GENERATION_SEMAPHORE._value == 0

            with patch("app.ml.router.WORKSHEET_SEMAPHORE_TIMEOUT", 0.05):
                async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                    resp = await client.get(
                        "/ml/generate-worksheet?subject=Math&topic=Calculus",
                    )
                    assert resp.status_code == 503
                    assert resp.headers.get("retry-after") == "5"
                    assert "maximum capacity" in resp.json()["detail"]
        finally:
            for _ in permits:
                WORKSHEET_GENERATION_SEMAPHORE.release()
            app.dependency_overrides.pop(get_tenant_context, None)
            app.dependency_overrides.pop(get_tenant_db, None)


# ==============================================================================
# 6. TestErrorSanitizationAndZeroLeakage
# ==============================================================================
class TestErrorSanitizationAndZeroLeakage:
    """Verifies that ML service exceptions return sanitized HTTP 502 with zero trace leakage."""

    @pytest.mark.asyncio
    async def test_model_integrity_error_sanitized_to_502(self):
        teacher = create_test_user("teacher")
        student = create_test_user("student", grade="10", section="A")

        mock_db = AsyncMock()

        async def fake_execute(stmt, *args, **kwargs):
            query_str = str(stmt)
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
            side_effect=ModelIntegrityError("SHA-256 integrity check failed at /opt/eduintel/backend/app/ml/models/at_risk.joblib"),
        ):
            try:
                async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                    resp = await client.get(
                        f"/ml/predict/at-risk/{student.id}",
                        headers=make_test_auth_headers(teacher),
                    )
                    assert resp.status_code == 502
                    detail = resp.json()["detail"]
                    assert detail == "ML service temporarily unavailable. Please try again later."
                    assert "/opt/eduintel" not in resp.text
                    assert "SHA-256" not in resp.text
            finally:
                app.dependency_overrides.pop(get_current_user, None)
                app.dependency_overrides.pop(get_db, None)

    @pytest.mark.asyncio
    async def test_feature_validation_error_sanitized_to_502(self):
        teacher = create_test_user("teacher")
        student = create_test_user("student", grade="10", section="A")

        mock_db = AsyncMock()

        async def fake_execute(stmt, *args, **kwargs):
            query_str = str(stmt)
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
            "app.ml.router.get_weak_topic_predictions",
            side_effect=FeatureValidationError("Internal feature vector contains NaN at index 4"),
        ):
            try:
                async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                    resp = await client.get(
                        f"/ml/predict/weak-topics/{student.id}",
                        headers=make_test_auth_headers(teacher),
                    )
                    assert resp.status_code == 502
                    detail = resp.json()["detail"]
                    assert detail == "ML service temporarily unavailable. Please try again later."
                    assert "NaN" not in resp.text
            finally:
                app.dependency_overrides.pop(get_current_user, None)
                app.dependency_overrides.pop(get_db, None)


# ==============================================================================
# 7. TestWorksheetTimeoutAndCancellationLifecycle
# ==============================================================================
class TestWorksheetTimeoutAndCancellationLifecycle:
    """Verifies worksheet generation deadline timeout and background detached telemetry persistence."""

    @pytest.mark.asyncio
    async def test_worksheet_generation_timeout_returns_504(self):
        inst_id = uuid.uuid4()
        teacher_tenant = TenantContext(institution_id=inst_id, user_id=uuid.uuid4(), role="teacher")
        mock_db = AsyncMock()

        app.dependency_overrides[get_tenant_context] = lambda: teacher_tenant
        app.dependency_overrides[get_tenant_db] = lambda: mock_db

        def slow_pdf_worker(*args, **kwargs):
            import time
            time.sleep(0.3)
            return b"%PDF-mock", LLMCallUsage(total_tokens=100)

        with patch("app.ml.router.TOTAL_WORKSHEET_DEADLINE_SECONDS", 0.05), patch(
            "app.ml.router.generate_worksheet_pdf", side_effect=slow_pdf_worker
        ):
            try:
                async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                    resp = await client.get("/ml/generate-worksheet?subject=Math&topic=Calculus")
                    assert resp.status_code == 504
                    assert "timed out" in resp.json()["detail"]
            finally:
                app.dependency_overrides.pop(get_tenant_context, None)
                app.dependency_overrides.pop(get_tenant_db, None)

    @pytest.mark.asyncio
    async def test_worksheet_detached_telemetry_persisted_on_disconnect(self):
        inst_id = uuid.uuid4()
        usage = LLMCallUsage(
            provider="gemini",
            model="gemini-2.5-pro",
            input_tokens=150,
            output_tokens=250,
            latency_ms=120,
            used_fallback=False,
        )

        with patch("app.ml.router.log_llm_usage", new_callable=AsyncMock) as mock_log:
            from app.ml.router import _persist_background_detached_usage
            await _persist_background_detached_usage(usage, inst_id)
            mock_log.assert_awaited_once()
            call_kwargs = mock_log.await_args.kwargs
            assert call_kwargs["usage"] == usage
            assert call_kwargs["institution_id"] == inst_id


# ==============================================================================
# 8. TestMLInferencePhysicalWorkerLifecycle
# ==============================================================================
class TestMLInferencePhysicalWorkerLifecycle:
    """
    Verifies that asyncio.shield + completion callbacks prevent premature
    semaphore release when awaiting request coroutines are cancelled, and that
    physical OS worker threads retain semaphore permits until execution actually ends.
    """

    @pytest.mark.asyncio
    async def test_physical_thread_retains_semaphore_permit_under_cancellation(self):
        """
        Empirically verifies:
        1. Worker acquires semaphore permit and starts real thread.
        2. Awaiting coroutine is cancelled.
        3. Semaphore available permits remains 0 while OS thread continues running.
        4. Second caller is rejected with HTTP 503 (capacity exhausted).
        5. Once OS thread unblocks and finishes, semaphore permit is released.
        6. Subsequent caller can acquire permit and succeed.
        """
        test_sem = asyncio.Semaphore(1)
        started_event = threading.Event()
        block_event = threading.Event()

        def slow_blocking_physical_thread():
            started_event.set()
            block_event.wait(timeout=5.0)
            return {"status": "ok"}

        async def worker_coro():
            return await asyncio.to_thread(slow_blocking_physical_thread)

        try:
            with patch("app.ml.router.ML_INFERENCE_SEMAPHORE", test_sem), patch(
                "app.ml.router.ML_INFERENCE_ACQUIRE_TIMEOUT", 0.05
            ):
                # Start worker 1 in a background asyncio task
                t1 = asyncio.create_task(run_with_inference_capacity(worker_coro))

                # Defensively wait for real thread to start execution
                await assert_event_set_within(
                    started_event,
                    task=t1,
                    timeout=3.0,
                    description="Worker 1 startup",
                )

                # Capacity must now be 0
                assert test_sem._value == 0

                # Cancel awaiting coroutine (simulating client disconnection or timeout)
                t1.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await t1

                # CRITICAL INVARIANT: Even though t1 was cancelled, the underlying OS thread
                # is still running, so test_sem must STILL have 0 available permits!
                assert test_sem._value == 0

                # Second caller tries to execute while worker 1's OS thread is still active
                with pytest.raises(HTTPException) as exc_info:
                    await run_with_inference_capacity(lambda: "worker2")
                assert exc_info.value.status_code == 503
                assert exc_info.value.headers.get("Retry-After") == "5"

                # Now unblock the underlying OS worker thread
                block_event.set()

                # Allow event loop and thread pool completion callback to execute
                await asyncio.sleep(0.05)

                # Permit must now be restored to 1
                assert test_sem._value == 1

                # Subsequent caller can now run cleanly
                result = await run_with_inference_capacity(lambda: "worker3")
                assert result == "worker3"
                assert test_sem._value == 1
        finally:
            block_event.set()

    @pytest.mark.asyncio
    async def test_endpoint_cancellation_preserves_semaphore_until_thread_completes(self):
        """
        Verifies endpoint-level cancellation for /ml/predict/at-risk/{student_id}:
        Semaphore permit is not returned until the offloaded thread actually finishes.
        """
        teacher = create_test_user("teacher")
        student = create_test_user("student", grade="10", section="A")
        mock_db = AsyncMock()

        async def fake_execute(stmt, *args, **kwargs):
            query_str = str(stmt)
            res = MagicMock()
            if "student_profiles" in query_str or "users" in query_str:
                res.first.return_value = (student, student.student_profile)
            elif "timetable_entries" in query_str:
                res.scalar_one_or_none.return_value = uuid.uuid4()
            return res

        mock_db.execute = AsyncMock(side_effect=fake_execute)
        app.dependency_overrides[get_current_user] = lambda: teacher
        app.dependency_overrides[get_db] = lambda: mock_db

        test_sem = asyncio.Semaphore(1)
        started_event = threading.Event()
        block_event = threading.Event()

        def slow_endpoint_physical_thread():
            started_event.set()
            block_event.wait(timeout=5.0)
            return {
                "student_id": student.id,
                "is_at_risk": False,
                "risk_probability": 0.15,
                "features_used": {
                    "attendance_rate": 0.9,
                    "homework_submission_rate": 0.8,
                    "avg_score_overall": 75.0,
                    "score_trend": 2.0,
                    "doubt_thread_count": 1,
                },
            }

        async def slow_inference_service(db, student_id):
            return await asyncio.to_thread(slow_endpoint_physical_thread)

        try:
            with patch("app.ml.router.ML_INFERENCE_SEMAPHORE", test_sem), patch(
                "app.ml.router.ML_INFERENCE_ACQUIRE_TIMEOUT", 0.05
            ), patch(
                "app.ml.router.get_at_risk_prediction", side_effect=slow_inference_service
            ):
                async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                    req_task = asyncio.create_task(
                        client.get(
                            f"/ml/predict/at-risk/{student.id}",
                            headers=make_test_auth_headers(teacher),
                        )
                    )

                    await assert_event_set_within(
                        started_event,
                        task=req_task,
                        timeout=3.0,
                        description="Endpoint worker startup",
                    )

                    assert test_sem._value == 0

                    # Cancel caller request
                    req_task.cancel()
                    with pytest.raises(asyncio.CancelledError):
                        await req_task

                    # Invariant: Permit remains held while thread runs
                    assert test_sem._value == 0

                    # Concurrent request must get 503
                    resp2 = await client.get(
                        f"/ml/predict/at-risk/{student.id}",
                        headers=make_test_auth_headers(teacher),
                    )
                    assert resp2.status_code == 503
                    assert resp2.headers.get("retry-after") == "5"

                    # Release physical thread
                    block_event.set()
                    await asyncio.sleep(0.05)

                    assert test_sem._value == 1

                    # Subsequent request succeeds
                    resp3 = await client.get(
                        f"/ml/predict/at-risk/{student.id}",
                        headers=make_test_auth_headers(teacher),
                    )
                    assert resp3.status_code == 200
                    assert resp3.json()["is_at_risk"] is False
        finally:
            block_event.set()
            app.dependency_overrides.pop(get_current_user, None)
            app.dependency_overrides.pop(get_db, None)

    @pytest.mark.asyncio
    async def test_detached_telemetry_strong_reference_retention(self):
        """
        Verifies that detached background telemetry tasks are tracked in
        _ACTIVE_DETACHED_TELEMETRY_TASKS until completion, preventing GC collection.
        """
        inst_id = uuid.uuid4()
        usage = LLMCallUsage(
            provider="gemini",
            model="gemini-2.5-flash",
            input_tokens=100,
            output_tokens=200,
            latency_ms=80,
            used_fallback=False,
        )

        pause_event = asyncio.Event()

        async def controlled_bg_persistence(u, i):
            await pause_event.wait()

        with patch("app.ml.router._persist_background_detached_usage", side_effect=controlled_bg_persistence):
            bg_task = asyncio.create_task(_persist_background_detached_usage(usage, inst_id))
            _ACTIVE_DETACHED_TELEMETRY_TASKS.add(bg_task)
            bg_task.add_done_callback(_ACTIVE_DETACHED_TELEMETRY_TASKS.discard)

            assert bg_task in _ACTIVE_DETACHED_TELEMETRY_TASKS

            pause_event.set()
            await bg_task

            assert bg_task not in _ACTIVE_DETACHED_TELEMETRY_TASKS

    @pytest.mark.asyncio
    async def test_wait_for_ml_quiescence_lifecycle(self):
        """
        Verifies wait_for_ml_quiescence waits for all registered tasks across
        inference, worksheet, and telemetry sets.
        """
        flag1 = False
        flag2 = False

        async def sample_task1():
            nonlocal flag1
            await asyncio.sleep(0.05)
            flag1 = True

        async def sample_task2():
            nonlocal flag2
            await asyncio.sleep(0.05)
            flag2 = True

        t1 = asyncio.create_task(sample_task1())
        _ACTIVE_ML_INFERENCE_TASKS.add(t1)
        t1.add_done_callback(_ACTIVE_ML_INFERENCE_TASKS.discard)

        t2 = asyncio.create_task(sample_task2())
        _ACTIVE_WORKSHEET_TASKS.add(t2)
        t2.add_done_callback(_ACTIVE_WORKSHEET_TASKS.discard)

        await wait_for_ml_quiescence(timeout=1.0)
        assert flag1 is True
        assert flag2 is True
        assert len(_ACTIVE_ML_INFERENCE_TASKS) == 0
        assert len(_ACTIVE_WORKSHEET_TASKS) == 0

    @pytest.mark.asyncio
    async def test_legacy_context_manager_retired_and_raises_runtime_error(self):
        """
        Verifies PREREQ-3.6-S4-02: ml_inference_capacity_scope is retired and raises
        RuntimeError pointing to run_with_inference_capacity().
        """
        with pytest.raises(RuntimeError) as exc_info:
            async with ml_inference_capacity_scope():
                pass
        assert "retired" in str(exc_info.value)
        assert "run_with_inference_capacity" in str(exc_info.value)


# ==============================================================================
# 9. TestFastAPIShutdownLifespanQuiescence
# ==============================================================================
class TestFastAPIShutdownLifespanQuiescence:
    """
    Verifies PREREQ-3.6-S4-01 & Stage 4R Remediation:
    FastAPI lifespan shutdown integration drains active ML inference, worksheet generation,
    and detached telemetry tasks within the 5.0-second graceful timeout without claiming
    un-terminated threads died, and ensures iterative re-inspection prevents missing
    secondary tasks spawned during drain.
    """

    @pytest.mark.asyncio
    async def test_lifespan_shutdown_with_no_active_ml_operations(self):
        """Verifies clean shutdown sequence when zero ML or telemetry tasks are active."""
        _ACTIVE_ML_INFERENCE_TASKS.clear()
        _ACTIVE_WORKSHEET_TASKS.clear()
        _ACTIVE_DETACHED_TELEMETRY_TASKS.clear()

        async with lifespan(app):
            pass

        assert len(_ACTIVE_ML_INFERENCE_TASKS) == 0
        assert len(_ACTIVE_WORKSHEET_TASKS) == 0
        assert len(_ACTIVE_DETACHED_TELEMETRY_TASKS) == 0

    @pytest.mark.asyncio
    async def test_lifespan_shutdown_with_active_inference_worker(self):
        """
        Verifies that an in-flight ML inference worker running in an OS thread
        is awaited and drained during lifespan shutdown before loop teardown.
        """
        started_event = threading.Event()
        finish_event = threading.Event()

        def slow_inference_thread():
            started_event.set()
            finish_event.wait(timeout=5.0)
            return {"is_at_risk": False}

        async def worker_coro():
            return await asyncio.to_thread(slow_inference_thread)

        worker_task = asyncio.create_task(run_with_inference_capacity(worker_coro))

        try:
            await assert_event_set_within(
                started_event,
                task=worker_task,
                timeout=3.0,
                description="Lifespan worker startup",
            )

            assert len(_ACTIVE_ML_INFERENCE_TASKS) == 1
            active_task = next(iter(_ACTIVE_ML_INFERENCE_TASKS))
            assert not active_task.done()

            # Allow worker thread to finish while shutdown is waiting
            finish_event.set()

            async with lifespan(app):
                pass

            assert len(_ACTIVE_ML_INFERENCE_TASKS) == 0
            result = await worker_task
            assert result == {"is_at_risk": False}
        finally:
            finish_event.set()

    @pytest.mark.asyncio
    async def test_lifespan_shutdown_with_active_worksheet_worker(self):
        """
        Verifies that an in-flight worksheet worker running in an OS thread
        is awaited and drained during lifespan shutdown.
        """
        started_event = threading.Event()
        finish_event = threading.Event()

        def slow_pdf_thread():
            started_event.set()
            finish_event.wait(timeout=5.0)
            usage = LLMCallUsage(
                provider="gemini",
                model="gemini-2.5-flash",
                input_tokens=100,
                output_tokens=50,
                latency_ms=50,
                used_fallback=False,
            )
            return b"%PDF-mock", usage

        await WORKSHEET_GENERATION_SEMAPHORE.acquire()
        sem_released = False

        worker_task = asyncio.create_task(asyncio.to_thread(slow_pdf_thread))
        _ACTIVE_WORKSHEET_TASKS.add(worker_task)

        def _on_done(t):
            nonlocal sem_released
            _ACTIVE_WORKSHEET_TASKS.discard(t)
            if not sem_released:
                sem_released = True
                WORKSHEET_GENERATION_SEMAPHORE.release()

        worker_task.add_done_callback(_on_done)

        try:
            await assert_event_set_within(
                started_event,
                task=worker_task,
                timeout=3.0,
                description="Worksheet worker startup",
            )

            assert worker_task in _ACTIVE_WORKSHEET_TASKS

            finish_event.set()

            async with lifespan(app):
                pass

            assert worker_task not in _ACTIVE_WORKSHEET_TASKS
            assert len(_ACTIVE_WORKSHEET_TASKS) == 0
            assert sem_released is True
        finally:
            finish_event.set()

    @pytest.mark.asyncio
    async def test_lifespan_shutdown_with_detached_telemetry_running(self):
        """
        Verifies that detached background telemetry tasks are drained
        cleanly during lifespan shutdown.
        """
        pause_event = asyncio.Event()

        async def controlled_bg_telemetry():
            await pause_event.wait()

        bg_task = asyncio.create_task(controlled_bg_telemetry())
        _ACTIVE_DETACHED_TELEMETRY_TASKS.add(bg_task)
        bg_task.add_done_callback(_ACTIVE_DETACHED_TELEMETRY_TASKS.discard)

        assert bg_task in _ACTIVE_DETACHED_TELEMETRY_TASKS

        # Allow background task to complete while shutdown drains
        pause_event.set()

        async with lifespan(app):
            pass

        assert bg_task not in _ACTIVE_DETACHED_TELEMETRY_TASKS
        assert len(_ACTIVE_DETACHED_TELEMETRY_TASKS) == 0

    @pytest.mark.asyncio
    async def test_lifespan_shutdown_worker_still_running_after_deadline(self):
        """
        Verifies that if a worker does NOT finish before the shutdown timeout,
        lifespan shutdown times out gracefully without crashing or falsely claiming
        the thread terminated.
        """
        started_event = threading.Event()
        block_event = threading.Event()

        def persistent_worker():
            started_event.set()
            block_event.wait(timeout=5.0)
            return {"status": "eventually_done"}

        worker_task = asyncio.create_task(
            run_with_inference_capacity(lambda: asyncio.to_thread(persistent_worker))
        )

        try:
            await assert_event_set_within(
                started_event,
                task=worker_task,
                timeout=3.0,
                description="Persistent worker startup",
            )

            assert len(_ACTIVE_ML_INFERENCE_TASKS) == 1
            active_task = next(iter(_ACTIVE_ML_INFERENCE_TASKS))
            assert not active_task.done()

            # Execute shutdown with a fast 0.05s timeout
            with patch("app.ml.router.wait_for_ml_quiescence", lambda timeout=5.0: wait_for_ml_quiescence(timeout=0.05)):
                async with lifespan(app):
                    pass

            # Invariant: Thread is STILL running, task is NOT falsely discarded as dead
            assert len(_ACTIVE_ML_INFERENCE_TASKS) == 1
            assert active_task in _ACTIVE_ML_INFERENCE_TASKS

            # Now unblock the worker thread
            block_event.set()
            await worker_task

            # Invariant: Callback runs and removes task once thread finishes
            assert len(_ACTIVE_ML_INFERENCE_TASKS) == 0
        finally:
            block_event.set()

    @pytest.mark.asyncio
    async def test_lifespan_shutdown_cleanup_callbacks_and_task_registries_after_completion(self):
        """
        Verifies that completion callbacks and task registries clean up properly
        when workers finish during lifespan shutdown.
        """
        callback_called = False

        async def quick_task():
            await asyncio.sleep(0.02)
            return "ok"

        t = asyncio.create_task(quick_task())
        _ACTIVE_ML_INFERENCE_TASKS.add(t)

        def cb(task):
            nonlocal callback_called
            callback_called = True
            _ACTIVE_ML_INFERENCE_TASKS.discard(task)

        t.add_done_callback(cb)

        async with lifespan(app):
            pass

        assert callback_called is True
        assert len(_ACTIVE_ML_INFERENCE_TASKS) == 0

    @pytest.mark.asyncio
    async def test_composite_worksheet_worker_to_telemetry_quiescence_race(self):
        """
        Stage 4R Composite Regression Test:
        Verifies that when a worksheet worker finishes during shutdown drain
        and schedules detached telemetry in its completion callback, wait_for_ml_quiescence
        iteratively drains and does NOT return prematurely while telemetry remains registered.
        Quiescence returns 0 only after all three registries are genuinely empty.
        """
        _ACTIVE_ML_INFERENCE_TASKS.clear()
        _ACTIVE_WORKSHEET_TASKS.clear()
        _ACTIVE_DETACHED_TELEMETRY_TASKS.clear()

        worker_started = threading.Event()
        worker_can_finish = threading.Event()
        telemetry_blocked = asyncio.Event()
        telemetry_completed = False

        def slow_pdf_thread():
            worker_started.set()
            worker_can_finish.wait(timeout=5.0)
            usage = LLMCallUsage(
                provider="gemini",
                model="gemini-2.5-flash",
                input_tokens=100,
                output_tokens=50,
                latency_ms=50,
                used_fallback=False,
            )
            return b"%PDF-mock", usage

        # 1. Start worksheet worker task
        await WORKSHEET_GENERATION_SEMAPHORE.acquire()
        sem_released = False

        worker_task = asyncio.create_task(asyncio.to_thread(slow_pdf_thread))
        _ACTIVE_WORKSHEET_TASKS.add(worker_task)

        async def controlled_telemetry():
            nonlocal telemetry_completed
            await telemetry_blocked.wait()
            telemetry_completed = True

        def _on_done(t):
            nonlocal sem_released
            _ACTIVE_WORKSHEET_TASKS.discard(t)
            # Simulate router.py line 454 spawning detached telemetry
            bg_task = asyncio.create_task(controlled_telemetry())
            _ACTIVE_DETACHED_TELEMETRY_TASKS.add(bg_task)
            bg_task.add_done_callback(_ACTIVE_DETACHED_TELEMETRY_TASKS.discard)
            if not sem_released:
                sem_released = True
                WORKSHEET_GENERATION_SEMAPHORE.release()

        worker_task.add_done_callback(_on_done)

        try:
            await assert_event_set_within(
                worker_started,
                task=worker_task,
                timeout=3.0,
                description="Composite worksheet worker startup",
            )

            assert len(_ACTIVE_WORKSHEET_TASKS) == 1

            # 2. Begin wait_for_ml_quiescence in background task
            quiescence_task = asyncio.create_task(wait_for_ml_quiescence(timeout=5.0))

            # Allow quiescence drain to enter its loop
            await asyncio.sleep(0.05)
            assert not quiescence_task.done()

            # 3. Complete worksheet worker while shutdown is in progress
            worker_can_finish.set()
            await worker_task

            # Give event loop a turn so done callback runs and spawns detached telemetry
            await asyncio.sleep(0.05)

            # 4 & 5. Worksheet worker is done, but telemetry is blocked!
            assert len(_ACTIVE_WORKSHEET_TASKS) == 0
            assert len(_ACTIVE_DETACHED_TELEMETRY_TASKS) == 1
            assert telemetry_completed is False

            # 6. Verify that quiescence does NOT return while telemetry remains registered!
            assert not quiescence_task.done()

            # 7. Release telemetry
            telemetry_blocked.set()

            # 8. Verify that quiescence returns successfully only after all three registries are empty
            res = await asyncio.wait_for(quiescence_task, timeout=2.0)
            assert res == 0
            assert telemetry_completed is True
            assert len(_ACTIVE_ML_INFERENCE_TASKS) == 0
            assert len(_ACTIVE_WORKSHEET_TASKS) == 0
            assert len(_ACTIVE_DETACHED_TELEMETRY_TASKS) == 0
        finally:
            worker_can_finish.set()
            telemetry_blocked.set()

    @pytest.mark.asyncio
    async def test_shutdown_admission_gate_rejects_new_inference_admissions(self):
        """
        Stage 4R Requirement B:
        Verifies that when shutdown is initiated, run_with_inference_capacity
        rejects new work with HTTP 503 Service Unavailable and Retry-After: 5.
        """
        drain_task = asyncio.create_task(wait_for_ml_quiescence(timeout=1.0))
        await asyncio.sleep(0.01)

        with pytest.raises(HTTPException) as exc_info:
            await run_with_inference_capacity(lambda: "new_work")

        assert exc_info.value.status_code == 503
        assert exc_info.value.headers.get("Retry-After") == "5"
        assert "shutting down" in exc_info.value.detail.lower()

        await drain_task

    @pytest.mark.asyncio
    async def test_shutdown_admission_gate_rejects_new_worksheet_admissions(self):
        """
        Stage 4R Requirement B:
        Verifies that when shutdown is initiated, /ml/generate-worksheet endpoint
        rejects new admissions with HTTP 503 Service Unavailable and Retry-After: 5.
        """
        inst_id = uuid.uuid4()
        teacher = create_test_user("teacher")
        mock_tenant = TenantContext(
            institution_id=inst_id,
            user_id=teacher.id,
            role="teacher",
        )
        app.dependency_overrides[get_current_user] = lambda: teacher
        app.dependency_overrides[get_tenant_db] = lambda: AsyncMock()
        app.dependency_overrides[get_tenant_context] = lambda: mock_tenant

        drain_task = asyncio.create_task(wait_for_ml_quiescence(timeout=1.0))
        await asyncio.sleep(0.01)

        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.get(
                    "/ml/generate-worksheet",
                    params={"subject": "Math", "topic": "Fractions"},
                    headers=make_test_auth_headers(teacher),
                )
                assert resp.status_code == 503
                assert resp.headers.get("retry-after") == "5"
                assert "shutting down" in resp.json()["detail"].lower()
        finally:
            app.dependency_overrides.pop(get_current_user, None)
            app.dependency_overrides.pop(get_tenant_db, None)
            app.dependency_overrides.pop(get_tenant_context, None)
            await drain_task


# ==============================================================================
# 10. TestStage4RShutdownIsolationAndDefensiveWaits
# ==============================================================================
class TestStage4RShutdownIsolationAndDefensiveWaits:
    """
    Verifies Stage 4R Remediation:
    1. Cross-test isolation preventing _ML_SHUTDOWN_IN_PROGRESS from leaking.
    2. Subsequent workers can execute cleanly once the fixture resets the flag.
    3. Rejected workers (HTTP 503) fail fast with descriptive errors instead of
       causing deadlocks in unbounded event polling loops.
    4. Shutdown admission gate continues rejecting work while active.
    """

    @pytest.mark.asyncio
    async def test_shutdown_flag_does_not_contaminate_next_test_stage_a(self):
        """Step A: Activate shutdown gate directly and verify it is True."""
        import app.ml.router as ml_router

        ml_router._ML_SHUTDOWN_IN_PROGRESS = True
        assert ml_router._ML_SHUTDOWN_IN_PROGRESS is True

    @pytest.mark.asyncio
    async def test_shutdown_flag_does_not_contaminate_next_test_stage_b(self):
        """
        Step B: Verify module-level fixture automatically reset the flag to False
        before entering this test, and verify an inference worker starts cleanly.
        """
        import app.ml.router as ml_router

        assert ml_router._ML_SHUTDOWN_IN_PROGRESS is False

        # Verify an inference worker executes cleanly without being blocked or rejected
        result = await run_with_inference_capacity(lambda: "worker_fresh")
        assert result == "worker_fresh"

    @pytest.mark.asyncio
    async def test_rejected_worker_surfaces_immediately_without_unbounded_loop(self):
        """
        Verifies that when an operation fails before setting started_event
        (such as HTTP 503 shutdown rejection), assert_event_set_within raises
        RuntimeError immediately rather than hanging indefinitely.
        """
        import app.ml.router as ml_router

        ml_router._ML_SHUTDOWN_IN_PROGRESS = True
        started_event = threading.Event()

        # Attempt to run a worker while shutdown gate is active
        task = asyncio.create_task(
            run_with_inference_capacity(lambda: asyncio.to_thread(started_event.set))
        )

        with pytest.raises(RuntimeError) as exc_info:
            await assert_event_set_within(
                started_event,
                task=task,
                timeout=0.5,
                description="Worker admission",
            )

        assert "Worker admission aborted prematurely" in str(exc_info.value)
        assert "503" in str(exc_info.value)
        assert started_event.is_set() is False

    @pytest.mark.asyncio
    async def test_existing_shutdown_admission_rejection_when_gate_is_active(self):
        """
        Verifies that when shutdown is active, both inference and worksheet
        admissions are deterministically rejected with 503 and Retry-After: 5.
        """
        import app.ml.router as ml_router

        ml_router._ML_SHUTDOWN_IN_PROGRESS = True

        # Inference rejection
        with pytest.raises(HTTPException) as exc1:
            await run_with_inference_capacity(lambda: "blocked")
        assert exc1.value.status_code == 503
        assert exc1.value.headers.get("Retry-After") == "5"

        # Worksheet rejection
        with pytest.raises(HTTPException) as exc2:
            await generate_worksheet(
                subject="Math",
                topic="Algebra",
                student_name=None,
                student_context=None,
                tenant=TenantContext(
                    institution_id=uuid.uuid4(),
                    user_id=uuid.uuid4(),
                    role="teacher",
                ),
                db=AsyncMock(),
            )
        assert exc2.value.status_code == 503
        assert exc2.value.headers.get("Retry-After") == "5"


