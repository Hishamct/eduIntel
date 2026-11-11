"""
Loads the trained at-risk and weak-topic models and runs predictions against
LIVE student data. Rebuilds the same feature engineering used at training
time (see app/ml/train_at_risk_model.py and train_weak_topic_model.py), but
computed over each student's full available history up to now, rather than
the fixed synthetic feature/label window used during training.

NOTE: this is a genuine limitation worth documenting — the model was trained
on a fixed 8-month synthetic feature window; at inference time we don't have
a clean "held-out future period" to validate against, we're just applying
the learned pattern to each student's current standing. This is the normal/
expected way trained models are used in production, but worth being explicit
about for a reviewer.
"""

import asyncio
import hashlib
import logging
import math
import threading
import uuid
from functools import lru_cache
from pathlib import Path
from typing import Any

import joblib
import numpy as np
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.models import Attendance
from app.ml.manifest import (
    FeatureValidationError,
    IncompatibleModelError,
    MLServiceError,
    ModelIntegrityError,
    SignedModelManifest,
    load_public_key,
    load_verified_manifest_from_file,
    verify_manifest_signature,
    verify_reference_distribution,
)
from app.student.models import DoubtThread, HomeworkSubmission
from app.teacher.models import ExamResult

logger = logging.getLogger(__name__)

AT_RISK_MODEL_PATH = "app/ml/models/at_risk_model.joblib"
WEAK_TOPIC_MODEL_PATH = "app/ml/models/weak_topic_model.joblib"

EXPECTED_HW_PER_MONTH = 4 * 4  # 4 weeks * 4 subjects, matches training assumption


class ModelNotFoundError(MLServiceError):
    """Raised when a required model artifact file does not exist."""


class ModelFormatError(MLServiceError):
    """Raised when a model artifact bundle is malformed or incompatible."""


MODEL_MANIFEST: dict[str, dict[str, Any]] = {
    "at_risk": {
        "filename": "at_risk_model.joblib",
        "sha256": "7bb3f75f281242963602eff52b793a5aa570ebdcd9d5c61ff43c12778c14ee16",
        "expected_features": [
            "attendance_rate",
            "homework_submission_rate",
            "avg_score_overall",
            "score_trend",
            "doubt_thread_count",
        ],
        "feature_bounds": {
            "attendance_rate": (0.0, 1.0),
            "homework_submission_rate": (0.0, 1.0),
            "avg_score_overall": (0.0, 100.0),
            "score_trend": (-100.0, 100.0),
            "doubt_thread_count": (0.0, 10000.0),
        },
    },
    "weak_topic": {
        "filename": "weak_topic_model.joblib",
        "sha256": "e0f386a4ec283f8144c2efef101c797cc99ffe3418f81321d92dc48db46b80c1",
        "expected_features": [
            "attendance_rate",
            "homework_submission_rate",
            "topic_avg_score",
            "student_overall_avg",
            "relative_gap",
            "subject_CHEMISTRY",
            "subject_COMPUTER SCIENCE",
            "subject_MATHEMATICS",
            "subject_PHYSICS",
        ],
        "feature_bounds": {
            "attendance_rate": (0.0, 1.0),
            "homework_submission_rate": (0.0, 1.0),
            "topic_avg_score": (0.0, 100.0),
            "student_overall_avg": (0.0, 100.0),
            "relative_gap": (-100.0, 100.0),
            "subject_CHEMISTRY": (0.0, 1.0),
            "subject_COMPUTER SCIENCE": (0.0, 1.0),
            "subject_MATHEMATICS": (0.0, 1.0),
            "subject_PHYSICS": (0.0, 1.0),
        },
    },
}

_MODEL_CACHE: dict[str, dict[str, Any]] = {}
_MODEL_LOAD_LOCK = threading.Lock()


def resolve_model_path(path_or_filename: str | Path) -> Path:
    """
    Resolves a model filename or relative path across execution contexts
    (repo root, backend root, or packaged models directory).
    """
    candidate = Path(path_or_filename)
    if candidate.is_file():
        return candidate.resolve()

    models_dir = Path(__file__).resolve().parent / "models"
    by_filename = models_dir / candidate.name
    if by_filename.is_file():
        return by_filename.resolve()

    cwd_candidate = Path.cwd() / candidate
    if cwd_candidate.is_file():
        return cwd_candidate.resolve()

    backend_candidate = Path.cwd() / "backend" / candidate
    if backend_candidate.is_file():
        return backend_candidate.resolve()

    return by_filename


def verify_model_checksum(file_path: Path | str, expected_sha256: str) -> None:
    """Verifies the SHA-256 integrity hash of a model file."""
    path = Path(file_path)
    if not path.is_file():
        raise ModelNotFoundError(f"Model artifact not found at {path}")

    sha256_hash = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            sha256_hash.update(chunk)

    computed = sha256_hash.hexdigest().lower()
    if computed != expected_sha256.lower():
        raise ModelIntegrityError(
            f"Model artifact integrity check failed for {path.name}: "
            f"expected SHA-256 {expected_sha256}, got {computed}"
        )


def load_verified_model(model_name: str, public_key: Any | None = None) -> dict[str, Any]:
    """
    Thread-safely loads, verifies Ed25519 digital signature of manifest,
    verifies SHA-256 integrity, validates bundle structure, and caches the model artifact.
    """
    if model_name in _MODEL_CACHE:
        return _MODEL_CACHE[model_name]

    with _MODEL_LOAD_LOCK:
        if model_name in _MODEL_CACHE:
            return _MODEL_CACHE[model_name]

        manifest = MODEL_MANIFEST.get(model_name)
        if not manifest:
            raise ModelNotFoundError(f"Unknown model name '{model_name}' not in MODEL_MANIFEST")

        artifact_file = manifest.get("filename") or manifest.get("artifact_filename")
        if not artifact_file:
            raise ModelFormatError(f"Model manifest for '{model_name}' missing filename")

        resolved_path = resolve_model_path(artifact_file)

        # 1. Cryptographic Ed25519 Manifest Verification
        manifest_filename = f"{model_name}_manifest.json"
        manifest_path = resolve_model_path(manifest_filename)
        signed_manifest: SignedModelManifest | None = None

        # Check if manifest itself has an embedded signature
        if "signature" in manifest:
            pub_k = load_public_key(public_key, key_id=manifest.get("key_id"))
            signed_manifest = verify_manifest_signature(manifest, pub_k)
        elif manifest_path.is_file():
            pub_k = load_public_key(public_key) if public_key else None
            signed_manifest = load_verified_manifest_from_file(manifest_path, public_key=pub_k)

        # Expected checksum and features
        expected_sha = manifest["sha256"]
        if signed_manifest is not None:
            expected_sha = signed_manifest.sha256 if manifest.get("sha256") == signed_manifest.sha256 else manifest.get("sha256", signed_manifest.sha256)

        # 2. SHA-256 Checksum Verification before deserialization
        verify_model_checksum(resolved_path, expected_sha)

        # 3. Reference distribution integrity check if present
        if signed_manifest is not None and signed_manifest.reference_distribution:
            ref_fn = signed_manifest.reference_distribution.get("filename")
            if ref_fn:
                ref_path = resolve_model_path(ref_fn)
                if ref_path.is_file():
                    verify_reference_distribution(signed_manifest, ref_path)

        # 4. Deserialization strictly AFTER signature & digest validation
        try:
            bundle = joblib.load(resolved_path)
        except Exception as exc:
            raise ModelFormatError(f"Failed to deserialize model bundle '{model_name}': {exc}") from exc

        if not isinstance(bundle, dict):
            raise ModelFormatError(f"Model bundle for '{model_name}' must be a dictionary, got {type(bundle).__name__}")

        if "model" not in bundle or "feature_cols" not in bundle:
            raise ModelFormatError(
                f"Model bundle for '{model_name}' missing required keys ('model', 'feature_cols')"
            )

        actual_cols = bundle["feature_cols"]
        if signed_manifest is not None:
            expected_cols = signed_manifest.expected_features
            # Validate hardcoded MODEL_MANIFEST agreement if present
            if "expected_features" in manifest and manifest["expected_features"] != expected_cols:
                raise IncompatibleModelError(
                    f"Static MODEL_MANIFEST for '{model_name}' disagrees with signed manifest features: "
                    f"{manifest['expected_features']} vs {expected_cols}"
                )
            if "feature_bounds" in manifest and manifest["feature_bounds"] != signed_manifest.feature_bounds:
                raise IncompatibleModelError(
                    f"Static MODEL_MANIFEST for '{model_name}' disagrees with signed manifest bounds."
                )
        elif "expected_features" in manifest:
            expected_cols = manifest["expected_features"]
        elif "features" in manifest:
            expected_cols = [f["name"] if isinstance(f, dict) else f.name for f in manifest["features"]]
        else:
            expected_cols = []

        if actual_cols != expected_cols:
            raise ModelFormatError(
                f"Feature columns mismatch for '{model_name}': expected {expected_cols}, got {actual_cols}"
            )

        model = bundle["model"]
        if not hasattr(model, "predict_proba") or not callable(model.predict_proba):
            raise ModelFormatError(f"Model '{model_name}' does not implement callable predict_proba")

        bundle["manifest"] = signed_manifest
        _MODEL_CACHE[model_name] = bundle
        logger.info("[ML Service] Verified and cached model artifact '%s' from %s", model_name, resolved_path)
        return bundle


def load_verified_fallback_model(fallback_model_name: str, public_key: Any | None = None) -> dict[str, Any]:
    """
    Independently loads and verifies a fallback model artifact, asserting its own
    Ed25519 digital signature and SHA-256 digest before deserialization.
    """
    return load_verified_model(fallback_model_name, public_key=public_key)


def _clear_loaded_models_for_testing() -> None:
    """Clears loaded model caches for isolated testing."""
    with _MODEL_LOAD_LOCK:
        _MODEL_CACHE.clear()
        _load_at_risk_model.cache_clear()
        _load_weak_topic_model.cache_clear()


@lru_cache(maxsize=1)
def _load_at_risk_model():
    return load_verified_model("at_risk")


@lru_cache(maxsize=1)
def _load_weak_topic_model():
    return load_verified_model("weak_topic")


def validate_at_risk_features(
    features: dict[str, Any],
    expected_cols: list[str] | None = None,
    manifest: SignedModelManifest | None = None,
) -> list[float]:
    """Validates types, finiteness, presence, exact naming, and domain boundaries for at-risk model features."""
    if manifest is not None:
        return manifest.validate_features(features)

    cached_manifest = _MODEL_CACHE.get("at_risk", {}).get("manifest")
    if cached_manifest is not None:
        return cached_manifest.validate_features(features)

    cols = expected_cols or MODEL_MANIFEST["at_risk"]["expected_features"]
    if not isinstance(features, dict):
        raise FeatureValidationError("At-risk features must be provided as a dictionary")

    # Reject unexpected extra features
    extra_features = set(features.keys()) - set(cols)
    if extra_features:
        raise FeatureValidationError(f"Unexpected extra feature(s) provided: {sorted(extra_features)}")

    manifest_dict = MODEL_MANIFEST["at_risk"]
    bounds = manifest_dict["feature_bounds"]
    vector: list[float] = []

    for col in cols:
        if col not in features:
            raise FeatureValidationError(f"Missing required feature: '{col}'")
        val = features[col]
        if isinstance(val, bool) or not isinstance(val, (int, float)):
            raise FeatureValidationError(f"Feature '{col}' must be numeric, got {type(val).__name__}")
        f_val = float(val)
        if not math.isfinite(f_val):
            raise FeatureValidationError(f"Feature '{col}' is not finite (got {val})")
        if col in bounds:
            min_val, max_val = bounds[col]
            if f_val < min_val or f_val > max_val:
                raise FeatureValidationError(
                    f"Feature '{col}' value {f_val} out of domain bounds [{min_val}, {max_val}]"
                )
        vector.append(f_val)

    return vector


def validate_weak_topic_features(
    row: dict[str, Any],
    expected_cols: list[str] | None = None,
    manifest: SignedModelManifest | None = None,
) -> list[float]:
    """Validates types, finiteness, presence, exact naming, and domain boundaries for weak-topic model features."""
    if manifest is not None:
        return manifest.validate_features(row)

    cached_manifest = _MODEL_CACHE.get("weak_topic", {}).get("manifest")
    if cached_manifest is not None:
        return cached_manifest.validate_features(row)

    cols = expected_cols or MODEL_MANIFEST["weak_topic"]["expected_features"]
    if not isinstance(row, dict):
        raise FeatureValidationError("Weak topic features must be provided as a dictionary")

    # Reject unexpected extra features
    extra_features = set(row.keys()) - set(cols)
    if extra_features:
        raise FeatureValidationError(f"Unexpected extra feature(s) provided: {sorted(extra_features)}")

    manifest_dict = MODEL_MANIFEST["weak_topic"]
    bounds = manifest_dict["feature_bounds"]
    vector: list[float] = []

    for col in cols:
        if col not in row:
            raise FeatureValidationError(f"Missing required feature: '{col}'")
        val = row[col]
        if isinstance(val, bool) or not isinstance(val, (int, float)):
            raise FeatureValidationError(f"Feature '{col}' must be numeric, got {type(val).__name__}")
        f_val = float(val)
        if not math.isfinite(f_val):
            raise FeatureValidationError(f"Feature '{col}' is not finite (got {val})")
        if col.startswith("subject_"):
            if f_val not in (0.0, 1.0):
                raise FeatureValidationError(f"One-hot feature '{col}' must be 0 or 1, got {f_val}")
        elif col in bounds:
            min_val, max_val = bounds[col]
            if f_val < min_val or f_val > max_val:
                raise FeatureValidationError(
                    f"Feature '{col}' value {f_val} out of domain bounds [{min_val}, {max_val}]"
                )
        vector.append(f_val)

    return vector


async def _get_student_history(db: AsyncSession, student_id: uuid.UUID):
    attendance_result = await db.execute(
        select(Attendance).where(Attendance.student_id == student_id)
    )
    attendance = attendance_result.scalars().all()

    homework_result = await db.execute(
        select(HomeworkSubmission).where(HomeworkSubmission.student_id == student_id)
    )
    homework = homework_result.scalars().all()

    exam_result = await db.execute(
        select(ExamResult).where(ExamResult.student_id == student_id)
    )
    exams = exam_result.scalars().all()

    doubt_result = await db.execute(
        select(DoubtThread).where(DoubtThread.student_id == student_id)
    )
    doubts = doubt_result.scalars().all()

    return attendance, homework, exams, doubts


def _months_of_history(attendance) -> float:
    if not attendance:
        return 0.0
    dates = [a.date for a in attendance]
    span_days = (max(dates) - min(dates)).days
    return max(span_days / 30, 0.1)  # avoid divide-by-zero for brand-new students


def _compute_at_risk_features(attendance, homework, exams, doubts) -> dict:
    """Shared feature-computation used by both get_at_risk_prediction (below)
    and app/ml/explain.py's SHAP explanation, so predictions and their
    explanations can never silently drift out of sync."""
    attendance_rate = sum(
        1 for a in attendance if a.status in ("present", "late")
    ) / len(attendance)

    months = _months_of_history(attendance)
    expected_hw = months * EXPECTED_HW_PER_MONTH
    homework_rate = min(len(homework) / expected_hw, 1.0) if expected_hw > 0 else 0

    exams_sorted = sorted(exams, key=lambda e: e.exam_date)
    if len(exams_sorted) >= 2:
        avg_score_early = np.mean(
            [float(e.score) for e in exams_sorted[: len(exams_sorted) // 2]]
        )
        avg_score_late = np.mean(
            [float(e.score) for e in exams_sorted[len(exams_sorted) // 2 :]]
        )
    else:
        avg_score_early = avg_score_late = float(exams_sorted[0].score)
    score_trend = avg_score_late - avg_score_early

    avg_score_overall = np.mean([float(e.score) for e in exams])
    doubt_count = len(doubts)

    return {
        "attendance_rate": round(attendance_rate, 3),
        "homework_submission_rate": round(homework_rate, 3),
        "avg_score_overall": round(float(avg_score_overall), 2),
        "score_trend": round(float(score_trend), 2),
        "doubt_thread_count": doubt_count,
    }


async def get_at_risk_prediction(db: AsyncSession, student_id: uuid.UUID) -> dict:
    attendance, homework, exams, doubts = await _get_student_history(db, student_id)

    if not attendance or not exams:
        return {
            "student_id": student_id,
            "is_at_risk": False,
            "risk_probability": None,
            "features_used": {},
            "note": "Insufficient history to generate a prediction (needs attendance and exam records).",
        }

    features = _compute_at_risk_features(attendance, homework, exams, doubts)

    bundle = await asyncio.to_thread(_load_at_risk_model)
    model = bundle["model"]
    feature_cols = bundle["feature_cols"]
    signed_manifest = bundle.get("manifest")

    vector = validate_at_risk_features(features, feature_cols, manifest=signed_manifest)
    X = [vector]

    # Offload CPU-bound inference to worker thread to prevent event-loop latency spikes
    probabilities = await asyncio.to_thread(model.predict_proba, X)
    probability = float(probabilities[0][1])

    return {
        "student_id": student_id,
        "is_at_risk": probability >= 0.5,
        "risk_probability": round(probability, 3),
        "features_used": features,
    }


async def get_weak_topic_predictions(
    db: AsyncSession, student_id: uuid.UUID
) -> list[dict]:
    attendance, homework, exams, _ = await _get_student_history(db, student_id)

    if not attendance or not exams:
        return []

    attendance_rate = sum(
        1 for a in attendance if a.status in ("present", "late")
    ) / len(attendance)
    months = _months_of_history(attendance)
    expected_hw = months * EXPECTED_HW_PER_MONTH
    homework_rate = min(len(homework) / expected_hw, 1.0) if expected_hw > 0 else 0

    # group exams by (subject, topic)
    by_topic: dict = {}
    for e in exams:
        by_topic.setdefault((e.subject, e.topic), []).append(e)

    if not by_topic:
        return []

    bundle = await asyncio.to_thread(_load_weak_topic_model)
    model = bundle["model"]
    feature_cols = bundle["feature_cols"]
    signed_manifest = bundle.get("manifest")
    subject_cols = [c for c in feature_cols if c.startswith("subject_")]

    rows_to_predict: list[list[float]] = []
    meta: list[tuple[str, str]] = []

    for (subject, topic), topic_exams in by_topic.items():
        topic_avg_score = np.mean([float(e.score) for e in topic_exams])

        other_scores = [
            float(e.score)
            for (s, t), exs in by_topic.items()
            if (s, t) != (subject, topic)
            for e in exs
        ]
        student_overall_avg = np.mean(other_scores) if other_scores else topic_avg_score
        relative_gap = topic_avg_score - student_overall_avg

        row = {
            "attendance_rate": round(attendance_rate, 3),
            "homework_submission_rate": round(homework_rate, 3),
            "topic_avg_score": round(float(topic_avg_score), 2),
            "student_overall_avg": round(float(student_overall_avg), 2),
            "relative_gap": round(float(relative_gap), 2),
        }
        # one-hot subject columns — set the matching one to 1, rest 0
        subject_col_name = f"subject_{subject}"
        for col in subject_cols:
            row[col] = 1 if col == subject_col_name else 0

        vector = validate_weak_topic_features(row, feature_cols, manifest=signed_manifest)
        rows_to_predict.append(vector)
        meta.append((subject, topic))

    if not rows_to_predict:
        return []

    # Batch offload CPU-bound inference to worker thread
    all_probabilities = await asyncio.to_thread(model.predict_proba, rows_to_predict)

    predictions = []
    for (subject, topic), probs in zip(meta, all_probabilities, strict=False):
        probability = float(probs[1])
        predictions.append(
            {
                "subject": subject,
                "topic": topic,
                "is_weak": probability >= 0.5,
                "weak_probability": round(probability, 3),
            }
        )

    # most concerning first
    predictions.sort(key=lambda p: -p["weak_probability"])
    return predictions
