"""
backend/tests/test_ml_integrity_and_drift.py

Phase 5 Step 3.6 Stage 6 & 6R: ML Model Integrity & Feature Drift Monitoring Test Suite.

Comprehensive tests covering:
1. Signed Model Manifests & Ed25519 Cryptographic Verification
2. Trust Anchor Pinning, Fingerprint Allowlist & Key Rotation (S6-01, S6-05)
3. Reference Distribution Cryptographic Binding & Integrity (S6-02)
4. Verification-Before-Deserialization Invariant
5. Authoritative Feature Schema Validation from Signed Manifest (S6-04)
6. Population Stability Index (PSI) Math Engine & Valid Sample Size Gating (S6-03)
7. Multi-Feature Aggregate Drift Reporting & Advisory Alerts
8. Concurrency and Thread Safety
"""

from __future__ import annotations

import base64
import copy
import hashlib
import json
import math
import threading
from pathlib import Path
from typing import Any
from unittest.mock import patch

import joblib
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519

from app.core.config import settings
from app.ml.drift import (
    DriftStatus,
    FeatureReferenceDistribution,
    ModelDriftReport,
    calculate_single_feature_psi,
    check_model_feature_drift,
    evaluate_model_feature_drift,
    load_reference_distributions_from_file,
)
from app.ml.manifest import (
    GLOBAL_TRUSTED_KEY_REGISTRY,
    FeatureSpec,
    FeatureValidationError,
    IncompatibleModelError,
    ManifestKeyError,
    ManifestValidationError,
    ModelIntegrityError,
    ModelSignatureError,
    SignedModelManifest,
    TrustedKeyRegistry,
    _init_default_key_registry,
    canonical_json_bytes,
    compute_public_key_fingerprint,
    load_public_key,
    load_verified_manifest_from_file,
    parse_manifest_dict,
    sign_manifest_dict,
    verify_manifest_signature,
    verify_reference_distribution,
)
from app.ml.service import (
    MODEL_MANIFEST,
    _clear_loaded_models_for_testing,
    load_verified_fallback_model,
    load_verified_model,
    validate_at_risk_features,
    validate_weak_topic_features,
)


class DummyPickleablePredictor:
    """Pickleable predictor stub for joblib test fixtures."""
    def predict_proba(self, X):
        return [[0.8, 0.2]]


# ---------------------------------------------------------------------------
# Test Fixtures & Keypairs
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def clean_ml_caches():
    """Ensures a clean model cache before and after every test."""
    _clear_loaded_models_for_testing()
    yield
    _clear_loaded_models_for_testing()


@pytest.fixture(autouse=True)
def isolate_trusted_key_registry():
    """Snapshots and restores GLOBAL_TRUSTED_KEY_REGISTRY before and after every test."""
    saved_keys = dict(GLOBAL_TRUSTED_KEY_REGISTRY._keys)
    try:
        yield
    finally:
        GLOBAL_TRUSTED_KEY_REGISTRY._keys = dict(saved_keys)
        if not GLOBAL_TRUSTED_KEY_REGISTRY._keys:
            _init_default_key_registry()


@pytest.fixture
def ephemeral_keypair() -> tuple[ed25519.Ed25519PrivateKey, ed25519.Ed25519PublicKey]:
    """Generates an isolated, ephemeral Ed25519 keypair for cryptographic testing."""
    priv = ed25519.Ed25519PrivateKey.generate()
    pub = priv.public_key()
    return priv, pub


@pytest.fixture
def valid_at_risk_manifest_dict() -> dict[str, Any]:
    """Returns a valid raw dictionary for an at-risk model manifest."""
    return {
        "model_name": "at_risk",
        "model_version": "1.0.0",
        "artifact_filename": "at_risk_model.joblib",
        "sha256": "7bb3f75f281242963602eff52b793a5aa570ebdcd9d5c61ff43c12778c14ee16",
        "algorithm": "xgboost.XGBClassifier",
        "feature_schema_version": "1.0",
        "created_at": "2026-11-06T00:00:00Z",
        "key_id": "eduintel-ml-signer-2026-v1",
        "features": [
            {"name": "attendance_rate", "type": "float", "min": 0.0, "max": 1.0, "order": 0},
            {"name": "homework_submission_rate", "type": "float", "min": 0.0, "max": 1.0, "order": 1},
            {"name": "avg_score_overall", "type": "float", "min": 0.0, "max": 100.0, "order": 2},
            {"name": "score_trend", "type": "float", "min": -100.0, "max": 100.0, "order": 3},
            {"name": "doubt_thread_count", "type": "float", "min": 0.0, "max": 10000.0, "order": 4},
        ],
        "reference_distribution": {
            "filename": "at_risk_reference_distribution.json",
            "sha256": "d5b3edd4c8a677daeb567f97622d48480f51dd84af05c1da7befa672665ad0bf",
            "version": "1.0.0",
        },
        "compatibility": {"python": ">=3.11", "xgboost": ">=2.0.0"},
        "metadata": {"test": True},
    }


# ===========================================================================
# 1. Signed Model Manifest & Cryptographic Verification Tests
# ===========================================================================

class TestSignedModelManifestVerification:
    """Verifies Ed25519 signature enforcement, canonicalization, trust anchor pinning, and key rotation."""

    def test_canonical_json_bytes_is_deterministic(self, valid_at_risk_manifest_dict):
        """Canonical JSON serialization must produce identical bytes regardless of key insertion order."""
        dict1 = dict(valid_at_risk_manifest_dict)
        dict2 = {k: valid_at_risk_manifest_dict[k] for k in reversed(list(valid_at_risk_manifest_dict.keys()))}

        bytes1 = canonical_json_bytes(dict1)
        bytes2 = canonical_json_bytes(dict2)
        assert bytes1 == bytes2
        assert b" " not in bytes1.split(b":")[0]  # compact separators, no extra spaces

    def test_valid_signature_passes_verification(self, ephemeral_keypair, valid_at_risk_manifest_dict):
        """A properly signed manifest verifies successfully against its corresponding public key."""
        priv, pub = ephemeral_keypair
        signed = sign_manifest_dict(valid_at_risk_manifest_dict, priv)

        assert "signature" in signed
        manifest_obj = verify_manifest_signature(signed, pub)
        assert manifest_obj.model_name == "at_risk"
        assert manifest_obj.sha256 == valid_at_risk_manifest_dict["sha256"]

    def test_tampered_manifest_fails_signature_verification(self, ephemeral_keypair, valid_at_risk_manifest_dict):
        """Modifying any field in a signed manifest causes Ed25519 verification to reject."""
        priv, pub = ephemeral_keypair
        signed = sign_manifest_dict(valid_at_risk_manifest_dict, priv)

        tampered = copy.deepcopy(signed)
        tampered["model_version"] = "1.0.1"

        with pytest.raises(ModelSignatureError, match="Ed25519 signature verification failed"):
            verify_manifest_signature(tampered, pub)

    def test_tampered_signature_bytes_fails_verification(self, ephemeral_keypair, valid_at_risk_manifest_dict):
        """Corrupting the signature payload causes verification to fail."""
        priv, pub = ephemeral_keypair
        signed = sign_manifest_dict(valid_at_risk_manifest_dict, priv)

        sig_bytes = bytearray(base64.b64decode(signed["signature"]))
        sig_bytes[10] ^= 0xFF
        signed["signature"] = base64.b64encode(sig_bytes).decode("ascii")

        with pytest.raises(ModelSignatureError, match="signature verification failed"):
            verify_manifest_signature(signed, pub)

    def test_missing_signature_fails_verification(self, ephemeral_keypair, valid_at_risk_manifest_dict):
        """Unsigned manifest is rejected fail-closed."""
        _, pub = ephemeral_keypair
        with pytest.raises(ModelSignatureError, match="No Ed25519 digital signature provided"):
            verify_manifest_signature(valid_at_risk_manifest_dict, pub)

    def test_signature_verified_with_wrong_public_key_fails(self, valid_at_risk_manifest_dict):
        """Signing with Key A and verifying with Key B must fail."""
        priv_a = ed25519.Ed25519PrivateKey.generate()
        priv_b = ed25519.Ed25519PrivateKey.generate()
        pub_b = priv_b.public_key()

        signed_with_a = sign_manifest_dict(valid_at_risk_manifest_dict, priv_a)
        with pytest.raises(ModelSignatureError, match="signature verification failed"):
            verify_manifest_signature(signed_with_a, pub_b)

    def test_malformed_manifest_schema_raises_validation_error(self):
        """Manifest missing required fields raises ManifestValidationError."""
        incomplete = {"model_name": "at_risk"}
        with pytest.raises(ManifestValidationError, match="missing required fields"):
            parse_manifest_dict(incomplete)

    def test_malformed_sha256_format_rejected(self, valid_at_risk_manifest_dict):
        """Manifest containing invalid SHA-256 string (wrong length or characters) is rejected."""
        bad_sha = dict(valid_at_risk_manifest_dict)
        bad_sha["sha256"] = "not_a_valid_hex_digest"
        with pytest.raises(ManifestValidationError, match="malformed"):
            parse_manifest_dict(bad_sha)

    def test_load_public_key_from_invalid_source_raises_key_error(self):
        """Attempting to load public key from non-existent or invalid source raises ManifestKeyError."""
        with pytest.raises(ManifestKeyError):
            load_public_key("invalid_pem_non_existent_path_12345")

    def test_public_key_from_pem_and_raw_bytes(self, ephemeral_keypair):
        """Public key can be loaded from PEM bytes or raw 32 bytes."""
        _, pub = ephemeral_keypair
        pem_bytes = pub.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        loaded_from_pem = load_public_key(pem_bytes)
        assert isinstance(loaded_from_pem, ed25519.Ed25519PublicKey)

        raw_32 = pub.public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        loaded_from_raw = load_public_key(raw_32)
        assert isinstance(loaded_from_raw, ed25519.Ed25519PublicKey)

    # --- S6-01: Trust Anchor & Fingerprint Pinning Tests ---

    def test_unapproved_public_key_rejected_by_fingerprint_allowlist(self, ephemeral_keypair):
        """Public key with an unapproved fingerprint is rejected fail-closed under pinning."""
        _, unapproved_pub = ephemeral_keypair
        fp = compute_public_key_fingerprint(unapproved_pub)
        assert fp

        with patch.object(settings, "ML_MODEL_TRUSTED_KEY_FINGERPRINTS", ["0" * 64]):
            with pytest.raises(ManifestKeyError, match="not in approved trust-anchor allowlist"):
                load_public_key(unapproved_pub, enforce_pinning=True)

    def test_production_environment_override_rejected_if_unapproved(self, ephemeral_keypair):
        """In production, environment override with an unapproved public key fails closed."""
        _, unapproved_pub = ephemeral_keypair
        pem_str = unapproved_pub.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode("ascii")

        with patch.object(settings, "ENVIRONMENT", "production"):
            with patch.object(settings, "ML_MODEL_SIGNING_PUBLIC_KEY", pem_str):
                with patch.object(settings, "ML_MODEL_TRUSTED_KEY_FINGERPRINTS", ["0" * 64]):
                    with pytest.raises(ManifestKeyError, match="not in approved trust-anchor allowlist"):
                        load_public_key()

    def test_approved_key_fingerprint_verified_successfully(self, ephemeral_keypair):
        """A public key matching an approved fingerprint passes trust anchor validation."""
        _, pub = ephemeral_keypair
        fp = compute_public_key_fingerprint(pub)

        with patch.object(settings, "ML_MODEL_TRUSTED_KEY_FINGERPRINTS", [fp]):
            loaded = load_public_key(pub, enforce_pinning=True)
            assert loaded is pub

    # --- S6-02: Reference Distribution Cryptographic Binding Tests ---

    def test_tampered_reference_distribution_fails_digest_verification(self, valid_at_risk_manifest_dict):
        """Modifying reference distribution content causes SHA-256 digest check to fail closed."""
        manifest = parse_manifest_dict(valid_at_risk_manifest_dict)

        # Passing file with modified content fails digest verification
        with pytest.raises(ModelIntegrityError, match="digest mismatch|checksum mismatch"):
            with patch("pathlib.Path.is_file", return_value=True):
                with patch("pathlib.Path.read_bytes", return_value=b'{"tampered": true}'):
                    verify_reference_distribution(manifest, "fake_ref.json")

    def test_reference_distribution_model_version_mismatch_rejected(self, valid_at_risk_manifest_dict):
        """Reference distribution with incompatible model_version is rejected."""
        manifest = parse_manifest_dict(valid_at_risk_manifest_dict)
        mismatched_ref = {
            "model_name": "at_risk",
            "model_version": "2.0.0",  # Manifest expects 1.0.0
            "features": {f["name"]: {} for f in valid_at_risk_manifest_dict["features"]},
        }
        with pytest.raises(ManifestValidationError, match="model_version"):
            verify_reference_distribution(manifest, mismatched_ref)

    def test_reference_distribution_feature_mismatch_rejected(self, valid_at_risk_manifest_dict):
        """Reference distribution with missing or extra features is rejected."""
        manifest = parse_manifest_dict(valid_at_risk_manifest_dict)
        mismatched_features = {
            "model_name": "at_risk",
            "model_version": "1.0.0",
            "features": {"only_one_feature": {}},
        }
        with pytest.raises(ManifestValidationError, match="features do not match"):
            verify_reference_distribution(manifest, mismatched_features)

    # --- S6-05: Key ID Resolution & Rotation Tests ---

    def test_key_id_lookup_resolves_and_unknown_key_id_rejected(self, ephemeral_keypair):
        """Registry successfully resolves known key_id; unknown key_id raises ManifestKeyError."""
        _, pub = ephemeral_keypair
        registry = TrustedKeyRegistry()
        registry.register("key-v1", pub, status="active")

        assert registry.get_key("key-v1") is pub
        with pytest.raises(ManifestKeyError, match="Unknown signing key_id"):
            registry.get_key("unknown-key-id")

    def test_controlled_dual_key_rotation(self, valid_at_risk_manifest_dict):
        """Both deprecated and active keys verify manifests signed during key rotation period."""
        priv_old = ed25519.Ed25519PrivateKey.generate()
        priv_new = ed25519.Ed25519PrivateKey.generate()

        registry = TrustedKeyRegistry()
        registry.register("key-2025-v1", priv_old.public_key(), status="deprecated")
        registry.register("key-2026-v2", priv_new.public_key(), status="active")

        # Manifest signed with old key
        manifest_old = sign_manifest_dict(valid_at_risk_manifest_dict, priv_old, key_id="key-2025-v1")
        verified_old = verify_manifest_signature(manifest_old, registry=registry)
        assert verified_old.key_id == "key-2025-v1"

        # Manifest signed with new key
        manifest_new = sign_manifest_dict(valid_at_risk_manifest_dict, priv_new, key_id="key-2026-v2")
        verified_new = verify_manifest_signature(manifest_new, registry=registry)
        assert verified_new.key_id == "key-2026-v2"

    def test_revoked_key_rejected_fail_closed(self, ephemeral_keypair, valid_at_risk_manifest_dict):
        """Manifest signed by a revoked key is rejected fail-closed."""
        priv, pub = ephemeral_keypair
        registry = TrustedKeyRegistry()
        registry.register("compromised-key", pub, status="revoked")

        signed = sign_manifest_dict(valid_at_risk_manifest_dict, priv, key_id="compromised-key")
        with pytest.raises(ManifestKeyError, match="has been explicitly revoked|has been revoked"):
            verify_manifest_signature(signed, registry=registry)


# ===========================================================================
# 2. Verification-Before-Deserialization & Fallback Invariants
# ===========================================================================

class TestVerificationBeforeDeserialization:
    """Ensures model artifacts are NEVER deserialized if signature or digest verification fails."""

    def test_tampered_model_artifact_rejected_before_joblib_load(self, tmp_path: Path, ephemeral_keypair):
        """If model artifact digest does not match manifest SHA-256, joblib.load is never called."""
        priv, pub = ephemeral_keypair

        artifact_path = tmp_path / "tampered_model.joblib"
        artifact_path.write_bytes(b"Simulated corrupted or malicious model artifact payload")

        manifest_dict = {
            "model_name": "test_model",
            "model_version": "1.0.0",
            "artifact_filename": str(artifact_path),
            "sha256": "1" * 64,  # Mismatched SHA-256
            "algorithm": "xgboost.XGBClassifier",
            "feature_schema_version": "1.0",
            "created_at": "2026-11-06T00:00:00Z",
            "key_id": "test-key-1",
            "features": [{"name": "feat1", "type": "float", "min": 0.0, "max": 1.0, "order": 0}],
        }
        signed = sign_manifest_dict(manifest_dict, priv)

        manifest_file = tmp_path / "test_model_manifest.json"
        manifest_file.write_text(json.dumps(signed))

        with patch("joblib.load") as mock_joblib:
            with patch.dict("app.ml.service.MODEL_MANIFEST", {"test_model": signed}):
                with pytest.raises(ModelIntegrityError, match="integrity check failed"):
                    load_verified_model("test_model", public_key=pub)

            mock_joblib.assert_not_called()

    def test_invalid_signature_blocks_artifact_loading(self, tmp_path: Path, ephemeral_keypair):
        """If manifest signature verification fails, model file is not opened or deserialized."""
        _, pub = ephemeral_keypair

        artifact_path = tmp_path / "valid_file.joblib"
        artifact_path.write_bytes(b"Valid dummy bytes")

        untrusted_priv = ed25519.Ed25519PrivateKey.generate()
        manifest_dict = {
            "model_name": "untrusted_model",
            "model_version": "1.0.0",
            "artifact_filename": str(artifact_path),
            "sha256": hashlib.sha256(artifact_path.read_bytes()).hexdigest(),
            "algorithm": "xgboost.XGBClassifier",
            "feature_schema_version": "1.0",
            "created_at": "2026-11-06T00:00:00Z",
            "key_id": "test-key-1",
            "features": [{"name": "feat1", "type": "float", "min": 0.0, "max": 1.0, "order": 0}],
        }
        signed = sign_manifest_dict(manifest_dict, untrusted_priv)

        manifest_file = tmp_path / "untrusted_model_manifest.json"
        manifest_file.write_text(json.dumps(signed))

        with patch("joblib.load") as mock_joblib:
            with patch("app.ml.service.resolve_model_path", side_effect=lambda p: manifest_file if str(p).endswith(".json") else artifact_path):
                with patch.dict("app.ml.service.MODEL_MANIFEST", {"untrusted_model": signed}):
                    with pytest.raises(ModelSignatureError):
                        load_verified_model("untrusted_model", public_key=pub)

            mock_joblib.assert_not_called()

    def test_independent_fallback_model_verification(self, tmp_path: Path, ephemeral_keypair):
        """Fallback models independently verify their own digital signature and SHA-256 before use."""
        priv, pub = ephemeral_keypair

        fallback_bundle = {
            "model": DummyPickleablePredictor(),
            "feature_cols": ["attendance_rate", "homework_submission_rate", "avg_score_overall", "score_trend", "doubt_thread_count"],
        }
        fallback_file = tmp_path / "at_risk_fallback.joblib"
        joblib.dump(fallback_bundle, fallback_file)
        fallback_sha = hashlib.sha256(fallback_file.read_bytes()).hexdigest()

        fallback_manifest = {
            "model_name": "at_risk_fallback",
            "model_version": "0.9.0",
            "artifact_filename": str(fallback_file),
            "sha256": fallback_sha,
            "algorithm": "xgboost.XGBClassifier",
            "feature_schema_version": "1.0",
            "created_at": "2026-10-01T00:00:00Z",
            "key_id": "test-key-1",
            "features": [
                {"name": "attendance_rate", "type": "float", "min": 0.0, "max": 1.0, "order": 0},
                {"name": "homework_submission_rate", "type": "float", "min": 0.0, "max": 1.0, "order": 1},
                {"name": "avg_score_overall", "type": "float", "min": 0.0, "max": 100.0, "order": 2},
                {"name": "score_trend", "type": "float", "min": -100.0, "max": 100.0, "order": 3},
                {"name": "doubt_thread_count", "type": "float", "min": 0.0, "max": 10000.0, "order": 4},
            ],
        }
        signed_fallback = sign_manifest_dict(fallback_manifest, priv)

        manifest_file = tmp_path / "at_risk_fallback_manifest.json"
        manifest_file.write_text(json.dumps(signed_fallback))

        with patch("app.ml.service.resolve_model_path", side_effect=lambda p: manifest_file if str(p).endswith(".json") else fallback_file):
            with patch.dict("app.ml.service.MODEL_MANIFEST", {"at_risk_fallback": signed_fallback}):
                loaded = load_verified_fallback_model("at_risk_fallback", public_key=pub)
                assert loaded["feature_cols"] == fallback_bundle["feature_cols"]
                assert loaded["manifest"] is not None

    def test_unapproved_fingerprint_blocks_deserialization(self, tmp_path: Path, ephemeral_keypair):
        """If public key fingerprint is not in approved allowlist, deserialization never occurs."""
        priv, pub = ephemeral_keypair
        artifact_path = tmp_path / "model.joblib"
        artifact_path.write_bytes(b"dummy artifact bytes")

        manifest_dict = {
            "model_name": "at_risk",
            "model_version": "1.0.0",
            "artifact_filename": str(artifact_path),
            "sha256": hashlib.sha256(artifact_path.read_bytes()).hexdigest(),
            "algorithm": "xgboost.XGBClassifier",
            "feature_schema_version": "1.0",
            "created_at": "2026-11-06T00:00:00Z",
            "key_id": "test-key-unapproved",
            "features": [{"name": "attendance_rate", "type": "float", "min": 0.0, "max": 1.0, "order": 0}],
        }
        signed = sign_manifest_dict(manifest_dict, priv, key_id="test-key-unapproved")
        manifest_file = tmp_path / "at_risk_manifest.json"
        manifest_file.write_text(json.dumps(signed))

        with patch("joblib.load") as mock_joblib:
            with patch.object(settings, "ENVIRONMENT", "production"):
                with patch.object(settings, "ML_MODEL_TRUSTED_KEY_FINGERPRINTS", ["0" * 64]):
                    with patch("app.ml.service.resolve_model_path", side_effect=lambda p: manifest_file if str(p).endswith(".json") else artifact_path):
                        with pytest.raises(ManifestKeyError, match="not in approved trust-anchor allowlist"):
                            load_verified_model("at_risk", public_key=pub)

            mock_joblib.assert_not_called()

    def test_unknown_key_id_in_production_blocks_deserialization(self, tmp_path: Path, ephemeral_keypair):
        """If manifest key_id is not found in trusted registry in production, joblib.load is never called."""
        priv, _ = ephemeral_keypair
        artifact_path = tmp_path / "model.joblib"
        artifact_path.write_bytes(b"dummy artifact bytes")

        manifest_dict = {
            "model_name": "at_risk",
            "model_version": "1.0.0",
            "artifact_filename": str(artifact_path),
            "sha256": hashlib.sha256(artifact_path.read_bytes()).hexdigest(),
            "algorithm": "xgboost.XGBClassifier",
            "feature_schema_version": "1.0",
            "created_at": "2026-11-06T00:00:00Z",
            "key_id": "completely-unknown-key-id",
            "features": [{"name": "attendance_rate", "type": "float", "min": 0.0, "max": 1.0, "order": 0}],
        }
        signed = sign_manifest_dict(manifest_dict, priv, key_id="completely-unknown-key-id")
        manifest_file = tmp_path / "at_risk_manifest.json"
        manifest_file.write_text(json.dumps(signed))

        with patch("joblib.load") as mock_joblib:
            with patch.object(settings, "ENVIRONMENT", "production"):
                with patch("app.ml.service.resolve_model_path", side_effect=lambda p: manifest_file if str(p).endswith(".json") else artifact_path):
                    with pytest.raises(ManifestKeyError, match="Unknown signing key_id|is not registered"):
                        load_verified_model("at_risk")

            mock_joblib.assert_not_called()

    def test_tampered_manifest_blocks_deserialization(self, tmp_path: Path, ephemeral_keypair):
        """If manifest is tampered, signature check fails and joblib.load is never called."""
        priv, pub = ephemeral_keypair
        artifact_path = tmp_path / "model.joblib"
        artifact_path.write_bytes(b"dummy artifact bytes")

        manifest_dict = {
            "model_name": "at_risk",
            "model_version": "1.0.0",
            "artifact_filename": str(artifact_path),
            "sha256": hashlib.sha256(artifact_path.read_bytes()).hexdigest(),
            "algorithm": "xgboost.XGBClassifier",
            "feature_schema_version": "1.0",
            "created_at": "2026-11-06T00:00:00Z",
            "key_id": "test-key-1",
            "features": [{"name": "attendance_rate", "type": "float", "min": 0.0, "max": 1.0, "order": 0}],
        }
        signed = sign_manifest_dict(manifest_dict, priv, key_id="test-key-1")
        # Tamper payload without re-signing
        signed["algorithm"] = "sklearn.linear_model.LogisticRegression"
        manifest_file = tmp_path / "at_risk_manifest.json"
        manifest_file.write_text(json.dumps(signed))

        with patch("joblib.load") as mock_joblib:
            with patch("app.ml.service.resolve_model_path", side_effect=lambda p: manifest_file if str(p).endswith(".json") else artifact_path):
                with pytest.raises(ModelSignatureError):
                    load_verified_model("at_risk", public_key=pub)

            mock_joblib.assert_not_called()

    def test_model_manifest_incompatibility_raises_error(self, tmp_path: Path, ephemeral_keypair):
        """If loaded manifest features disagree with static MODEL_MANIFEST, IncompatibleModelError is raised."""
        priv, pub = ephemeral_keypair

        bundle = {
            "model": DummyPickleablePredictor(),
            "feature_cols": ["different_feature"],
        }
        model_file = tmp_path / "incompatible_model.joblib"
        joblib.dump(bundle, model_file)

        manifest = {
            "model_name": "incompatible_model",
            "model_version": "1.0.0",
            "artifact_filename": str(model_file),
            "sha256": hashlib.sha256(model_file.read_bytes()).hexdigest(),
            "algorithm": "xgboost.XGBClassifier",
            "feature_schema_version": "1.0",
            "created_at": "2026-11-06T00:00:00Z",
            "key_id": "test-key-1",
            "features": [{"name": "different_feature", "type": "float", "min": 0.0, "max": 1.0, "order": 0}],
        }
        signed = sign_manifest_dict(manifest, priv)

        # Static MODEL_MANIFEST expects different features
        static_manifest = {
            "filename": str(model_file),
            "sha256": manifest["sha256"],
            "expected_features": ["original_expected_feature"],
        }

        manifest_file = tmp_path / "incompatible_model_manifest.json"
        manifest_file.write_text(json.dumps(signed))

        with patch("app.ml.service.resolve_model_path", side_effect=lambda p: manifest_file if str(p).endswith(".json") else model_file):
            with patch.dict("app.ml.service.MODEL_MANIFEST", {"incompatible_model": static_manifest}):
                with pytest.raises(IncompatibleModelError, match="disagrees with signed manifest"):
                    load_verified_model("incompatible_model", public_key=pub)


# ===========================================================================
# 3. Strict Feature Schema Validation Tests
# ===========================================================================

class TestFeatureSchemaValidation:
    """Verifies strict feature names, ordering, rejection of unexpected keys, booleans, NaNs, and bounds."""

    def test_valid_features_produce_positional_vector(self):
        cols = MODEL_MANIFEST["at_risk"]["expected_features"]
        valid_input = {
            "attendance_rate": 0.85,
            "homework_submission_rate": 0.90,
            "avg_score_overall": 75.0,
            "score_trend": 2.5,
            "doubt_thread_count": 5.0,
        }
        vector = validate_at_risk_features(valid_input, cols)
        assert vector == [0.85, 0.90, 75.0, 2.5, 5.0]

    def test_unexpected_extra_feature_is_rejected(self):
        cols = MODEL_MANIFEST["at_risk"]["expected_features"]
        extra_input = {
            "attendance_rate": 0.85,
            "homework_submission_rate": 0.90,
            "avg_score_overall": 75.0,
            "score_trend": 2.5,
            "doubt_thread_count": 5.0,
            "unexpected_injected_column": 999.0,
        }
        with pytest.raises(FeatureValidationError, match="Unexpected extra feature"):
            validate_at_risk_features(extra_input, cols)

    def test_missing_feature_is_rejected(self):
        cols = MODEL_MANIFEST["at_risk"]["expected_features"]
        missing_input = {
            "attendance_rate": 0.85,
            "homework_submission_rate": 0.90,
            "score_trend": 2.5,
            "doubt_thread_count": 5.0,
        }
        with pytest.raises(FeatureValidationError, match="Missing required feature"):
            validate_at_risk_features(missing_input, cols)

    def test_boolean_supplied_as_numeric_is_rejected(self):
        cols = MODEL_MANIFEST["at_risk"]["expected_features"]
        bool_input = {
            "attendance_rate": True,
            "homework_submission_rate": 0.90,
            "avg_score_overall": 75.0,
            "score_trend": 2.5,
            "doubt_thread_count": 5.0,
        }
        with pytest.raises(FeatureValidationError, match="must be numeric"):
            validate_at_risk_features(bool_input, cols)

    def test_nan_and_inf_features_are_rejected(self):
        cols = MODEL_MANIFEST["at_risk"]["expected_features"]
        base = {
            "attendance_rate": 0.85,
            "homework_submission_rate": 0.90,
            "avg_score_overall": 75.0,
            "score_trend": 2.5,
            "doubt_thread_count": 5.0,
        }

        with pytest.raises(FeatureValidationError, match="is not finite|non-finite"):
            validate_at_risk_features(dict(base, attendance_rate=float("nan")), cols)

        with pytest.raises(FeatureValidationError, match="is not finite|non-finite"):
            validate_at_risk_features(dict(base, score_trend=float("inf")), cols)

        with pytest.raises(FeatureValidationError, match="is not finite|non-finite"):
            validate_at_risk_features(dict(base, score_trend=float("-inf")), cols)

    def test_out_of_bounds_features_are_rejected(self):
        cols = MODEL_MANIFEST["at_risk"]["expected_features"]
        base = {
            "attendance_rate": 0.85,
            "homework_submission_rate": 0.90,
            "avg_score_overall": 75.0,
            "score_trend": 2.5,
            "doubt_thread_count": 5.0,
        }

        with pytest.raises(FeatureValidationError, match="out of domain bounds"):
            validate_at_risk_features(dict(base, attendance_rate=1.05), cols)

        with pytest.raises(FeatureValidationError, match="out of domain bounds"):
            validate_at_risk_features(dict(base, avg_score_overall=-1.0), cols)

    def test_weak_topic_features_rejects_extra_keys(self):
        cols = MODEL_MANIFEST["weak_topic"]["expected_features"]
        row = {
            "attendance_rate": 0.80,
            "homework_submission_rate": 0.75,
            "topic_avg_score": 45.0,
            "student_overall_avg": 70.0,
            "relative_gap": -25.0,
            "subject_CHEMISTRY": 0.0,
            "subject_COMPUTER SCIENCE": 0.0,
            "subject_MATHEMATICS": 1.0,
            "subject_PHYSICS": 0.0,
            "malicious_extra_feature": 123.0,
        }
        with pytest.raises(FeatureValidationError, match="Unexpected extra feature"):
            validate_weak_topic_features(row, cols)

    def test_authoritative_manifest_bounds_enforced_at_runtime(self):
        """SignedModelManifest bounds strictly override static dictionary bounds during inference."""
        strict_manifest = SignedModelManifest(
            model_name="at_risk",
            model_version="1.0.0",
            artifact_filename="at_risk_model.joblib",
            sha256="7bb3f75f281242963602eff52b793a5aa570ebdcd9d5c61ff43c12778c14ee16",
            algorithm="xgboost.XGBClassifier",
            feature_schema_version="1.0",
            created_at="2026-11-06T00:00:00Z",
            features=[
                FeatureSpec(name="attendance_rate", type="float", min=0.30, max=0.70, order=0),
                FeatureSpec(name="homework_submission_rate", type="float", min=0.0, max=1.0, order=1),
                FeatureSpec(name="avg_score_overall", type="float", min=0.0, max=100.0, order=2),
                FeatureSpec(name="score_trend", type="float", min=-100.0, max=100.0, order=3),
                FeatureSpec(name="doubt_thread_count", type="float", min=0.0, max=10000.0, order=4),
            ],
        )

        # 0.85 attendance_rate is valid under default (0.0 - 1.0), but invalid under strict manifest (0.30 - 0.70)
        input_data = {
            "attendance_rate": 0.85,
            "homework_submission_rate": 0.90,
            "avg_score_overall": 75.0,
            "score_trend": 2.5,
            "doubt_thread_count": 5.0,
        }
        with pytest.raises(FeatureValidationError, match="out of domain bounds \\[0.3, 0.7\\]"):
            validate_at_risk_features(input_data, manifest=strict_manifest)

        # 0.50 attendance_rate is within strict manifest bounds
        valid_strict = dict(input_data, attendance_rate=0.50)
        vec = validate_at_risk_features(valid_strict, manifest=strict_manifest)
        assert vec[0] == 0.50


# ===========================================================================
# 4. Population Stability Index (PSI) Engine Tests
# ===========================================================================

class TestPopulationStabilityIndexEngine:
    """Verifies PSI calculation, Laplace smoothing, valid sample-size gating, and classifications."""

    @pytest.fixture
    def standard_reference(self) -> FeatureReferenceDistribution:
        """Standard 10-bin reference distribution for attendance_rate."""
        return FeatureReferenceDistribution(
            feature_name="attendance_rate",
            bin_edges=[0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0],
            expected_proportions=[0.05, 0.05, 0.05, 0.05, 0.10, 0.10, 0.15, 0.20, 0.15, 0.10],
            reference_version="1.0.0",
            model_version="1.0.0",
            sample_size=1000,
        )

    def test_identical_distributions_yield_zero_psi(self, standard_reference):
        """When actual distribution exactly matches expected, PSI must be ~0.0."""
        obs = []
        edges = standard_reference.bin_edges
        for b, prop in enumerate(standard_reference.expected_proportions):
            count = int(prop * 1000)
            midpoint = (edges[b] + edges[b + 1]) / 2.0
            obs.extend([midpoint] * count)

        result = calculate_single_feature_psi(obs, standard_reference)
        assert result.status == DriftStatus.NO_DRIFT
        assert result.psi is not None
        assert abs(result.psi - 0.0) < 1e-4

    def test_known_hand_calculated_psi_example(self):
        """Validates analytical accuracy against a known hand-calculated 2-bin case."""
        simple_ref = FeatureReferenceDistribution(
            feature_name="score",
            bin_edges=[0.0, 50.0, 100.0],
            expected_proportions=[0.50, 0.50],
            reference_version="1.0.0",
            model_version="1.0.0",
        )
        obs = [25.0] * 80 + [75.0] * 120
        result = calculate_single_feature_psi(obs, simple_ref, min_sample_size=200)

        assert result.psi is not None
        assert abs(result.psi - 0.04054) < 1e-4
        assert result.status == DriftStatus.NO_DRIFT

    def test_small_distribution_shift_is_classified_no_drift(self, standard_reference):
        """PSI < 0.10 returns NO_DRIFT."""
        edges = standard_reference.bin_edges
        shifted_proportions = [0.06, 0.04, 0.06, 0.04, 0.09, 0.11, 0.14, 0.21, 0.14, 0.11]
        obs = []
        for b, prop in enumerate(shifted_proportions):
            midpoint = (edges[b] + edges[b + 1]) / 2.0
            obs.extend([midpoint] * int(prop * 200))
        result = calculate_single_feature_psi(obs, standard_reference, min_sample_size=200)
        assert result.status == DriftStatus.NO_DRIFT
        assert result.psi is not None
        assert result.psi < 0.10
        assert result.sample_count == 200
        assert result.valid_sample_count == 200

    def test_large_distribution_shift_triggers_high_drift(self, standard_reference):
        """PSI >= 0.25 returns HIGH_DRIFT."""
        obs = [0.05] * 200
        result = calculate_single_feature_psi(obs, standard_reference, min_sample_size=200)
        assert result.status == DriftStatus.HIGH_DRIFT
        assert result.psi is not None
        assert result.psi >= 0.25

    def test_zero_frequency_bins_do_not_divide_by_zero_or_log_zero(self, standard_reference):
        """Bins with zero actual count use Laplace smoothing epsilon without raising math error."""
        obs = [0.75] * 200
        result = calculate_single_feature_psi(obs, standard_reference, min_sample_size=200)
        assert result.psi is not None
        assert math.isfinite(result.psi)

    def test_missing_and_non_finite_values_routed_to_dedicated_bin(self, standard_reference):
        """None, NaN, Inf, and booleans are captured in the dedicated (B+1) missing bin."""
        obs = [0.85] * 200 + [None] * 20 + [float("nan")] * 15 + [float("inf")] * 10 + [True] * 5
        assert len(obs) == 250
        result = calculate_single_feature_psi(obs, standard_reference, min_sample_size=200)
        assert result.missing_count == 50
        assert result.valid_sample_count == 200
        assert abs(result.actual_proportions[-1] - (50 / 250)) < 1e-4

    # --- S6-03: Valid Numeric Sample Size Gating Tests ---

    def test_sample_size_gate_190_missing_10_valid_returns_insufficient_sample_size(self, standard_reference):
        """190 missing + 10 valid numeric observations must return INSUFFICIENT_SAMPLE_SIZE."""
        obs = [None] * 190 + [0.85] * 10
        result = calculate_single_feature_psi(obs, standard_reference, min_sample_size=200)
        assert result.status == DriftStatus.INSUFFICIENT_SAMPLE_SIZE
        assert result.psi is None
        assert result.valid_sample_count == 10
        assert result.missing_count == 190
        assert "Valid numeric sample size 10 is below required minimum of 200" in result.message

    def test_sample_size_gate_199_valid_returns_insufficient_sample_size(self, standard_reference):
        """199 valid numeric observations must return INSUFFICIENT_SAMPLE_SIZE."""
        obs = [0.85] * 199
        result = calculate_single_feature_psi(obs, standard_reference, min_sample_size=200)
        assert result.status == DriftStatus.INSUFFICIENT_SAMPLE_SIZE
        assert result.psi is None
        assert result.valid_sample_count == 199

    def test_sample_size_gate_exactly_200_valid_evaluates_psi(self, standard_reference):
        """Exactly 200 valid observations satisfies the minimum sample gate."""
        obs = [0.85] * 200
        result = calculate_single_feature_psi(obs, standard_reference, min_sample_size=200)
        assert result.status != DriftStatus.INSUFFICIENT_SAMPLE_SIZE
        assert result.psi is not None
        assert result.valid_sample_count == 200

    def test_sample_size_gate_200_raw_with_fewer_than_200_valid_returns_insufficient_sample_size(self, standard_reference):
        """200 raw observations with 195 valid and 5 invalid must return INSUFFICIENT_SAMPLE_SIZE."""
        obs = [0.85] * 195 + [None] * 3 + [float("nan")] * 2
        assert len(obs) == 200
        result = calculate_single_feature_psi(obs, standard_reference, min_sample_size=200)
        assert result.status == DriftStatus.INSUFFICIENT_SAMPLE_SIZE
        assert result.psi is None
        assert result.valid_sample_count == 195
        assert result.missing_count == 5

    def test_sample_size_gate_more_than_200_valid_evaluates_psi(self, standard_reference):
        """250 valid observations evaluates PSI normally."""
        obs = [0.85] * 250
        result = calculate_single_feature_psi(obs, standard_reference, min_sample_size=200)
        assert result.status != DriftStatus.INSUFFICIENT_SAMPLE_SIZE
        assert result.psi is not None
        assert result.valid_sample_count == 250

    def test_invalid_threshold_order_raises_value_error(self, standard_reference):
        """Configuring warning_threshold >= high_threshold raises ValueError."""
        with pytest.raises(ValueError, match="Invalid drift thresholds"):
            calculate_single_feature_psi(
                [0.85] * 200,
                standard_reference,
                warning_threshold=0.30,
                high_threshold=0.20,
            )


# ===========================================================================
# 5. Multi-Feature Aggregate Drift Evaluation & Advisory Alerting
# ===========================================================================

class TestMultiFeatureDriftEvaluation:
    """Verifies aggregate drift summaries, non-masking of single drifted features, and advisory alerts."""

    @pytest.fixture
    def multi_feature_refs(self) -> dict[str, FeatureReferenceDistribution]:
        return {
            "attendance_rate": FeatureReferenceDistribution(
                feature_name="attendance_rate",
                bin_edges=[0.0, 0.5, 1.0],
                expected_proportions=[0.20, 0.80],
                reference_version="1.0.0",
                model_version="1.0.0",
            ),
            "avg_score_overall": FeatureReferenceDistribution(
                feature_name="avg_score_overall",
                bin_edges=[0.0, 50.0, 100.0],
                expected_proportions=[0.30, 0.70],
                reference_version="1.0.0",
                model_version="1.0.0",
            ),
        }

    def test_aggregate_summary_does_not_conceal_individual_feature_drift(self, multi_feature_refs):
        """If one feature drifts heavily and another is stable, overall report flags the drifted feature."""
        records = [
            {"attendance_rate": 0.80, "avg_score_overall": 10.0}
            for _ in range(200)
        ]

        report = evaluate_model_feature_drift(
            model_name="at_risk",
            feature_matrix_or_records=records,
            reference_distributions=multi_feature_refs,
            min_sample_size=200,
        )

        assert report.status == DriftStatus.HIGH_DRIFT
        assert report.max_psi_feature == "avg_score_overall"
        assert report.max_psi_value is not None and report.max_psi_value >= 0.25
        assert report.alert_raised is True

    def test_drift_evaluation_is_advisory_only_and_preserves_model(self, multi_feature_refs):
        """Evaluating drift produces reports but NEVER deletes, disables, or replaces loaded model artifacts."""
        records = [{"attendance_rate": 0.05, "avg_score_overall": 5.0} for _ in range(200)]

        model_before = load_verified_model("at_risk")

        report = evaluate_model_feature_drift(
            model_name="at_risk",
            feature_matrix_or_records=records,
            reference_distributions=multi_feature_refs,
            min_sample_size=200,
        )
        assert report.alert_raised is True

        model_after = load_verified_model("at_risk")
        assert model_after is model_before

    def test_load_reference_distributions_from_file_and_check_drift(self):
        """Verifies loading real JSON reference distributions and computing drift."""
        ref_dists = load_reference_distributions_from_file("at_risk")
        assert "attendance_rate" in ref_dists
        assert "avg_score_overall" in ref_dists
        assert ref_dists["attendance_rate"].reference_version == "1.0.0"

        records = [
            {
                "attendance_rate": 0.85,
                "homework_submission_rate": 0.90,
                "avg_score_overall": 75.0,
                "score_trend": 2.5,
                "doubt_thread_count": 5.0,
            }
            for _ in range(200)
        ]
        report = check_model_feature_drift("at_risk", records, min_sample_size=200)
        assert isinstance(report, ModelDriftReport)
        assert report.model_name == "at_risk"
        assert report.sample_count == 200
        assert report.status in (DriftStatus.NO_DRIFT, DriftStatus.WARNING, DriftStatus.HIGH_DRIFT)


# ===========================================================================
# 6. Concurrency and Integration Tests
# ===========================================================================

class TestMLModelIntegrityConcurrency:
    """Verifies that concurrent threads loading models do not cause race conditions or bypass checks."""

    def test_concurrent_model_loading_is_thread_safe(self):
        """Multiple threads loading models concurrently receive identical cached objects without race conditions."""
        errors: list[Exception] = []
        results: list[dict[str, Any]] = []

        def worker():
            try:
                bundle = load_verified_model("at_risk")
                results.append(bundle)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Errors during concurrent loading: {errors}"
        assert len(results) == 10
        first = results[0]
        for res in results[1:]:
            assert res is first

    def test_concurrent_feature_validation_thread_safe(self):
        """Multiple threads concurrently validating features execute thread-safely."""
        errors: list[Exception] = []
        cols = MODEL_MANIFEST["at_risk"]["expected_features"]
        valid_input = {
            "attendance_rate": 0.85,
            "homework_submission_rate": 0.90,
            "avg_score_overall": 75.0,
            "score_trend": 2.5,
            "doubt_thread_count": 5.0,
        }

        def validator_worker():
            try:
                for _ in range(50):
                    vec = validate_at_risk_features(valid_input, cols)
                    assert len(vec) == 5
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=validator_worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Errors during concurrent validation: {errors}"


# ===========================================================================
# 6. Stage 6R2 Adversarial Trust-Anchor Security Tests
# ===========================================================================

class TestStage6R2TrustAnchorSecurity:
    """
    Adversarial security tests proving that no candidate key, registry entry, key_id lookup,
    file, or PEM payload can bypass mandatory Ed25519 trust-anchor fingerprint validation.
    """

    def test_registered_key_with_valid_fingerprint_accepted(self, ephemeral_keypair):
        """A key registered in TrustedKeyRegistry with an approved fingerprint is accepted."""
        _, pub = ephemeral_keypair
        fp = compute_public_key_fingerprint(pub)
        reg = TrustedKeyRegistry()
        reg.register("key-valid", pub, status="active")

        with patch.object(settings, "ML_MODEL_TRUSTED_KEY_FINGERPRINTS", [fp]):
            loaded = load_public_key(key_id="key-valid", registry=reg, enforce_pinning=True)
            assert loaded is pub

    def test_registered_key_with_invalid_fingerprint_rejected(self, ephemeral_keypair):
        """A key registered in TrustedKeyRegistry with an UNAPPROVED fingerprint fails closed."""
        _, pub = ephemeral_keypair
        reg = TrustedKeyRegistry()
        reg.register("key-unapproved", pub, status="active")

        with patch.object(settings, "ML_MODEL_TRUSTED_KEY_FINGERPRINTS", ["0" * 64]):
            with pytest.raises(ManifestKeyError, match="not in approved trust-anchor allowlist"):
                load_public_key(key_id="key-unapproved", registry=reg, enforce_pinning=True)

    def test_unregistered_key_with_valid_fingerprint_accepted(self, ephemeral_keypair):
        """An unregistered key supplied as a raw object with an approved fingerprint is accepted."""
        _, pub = ephemeral_keypair
        fp = compute_public_key_fingerprint(pub)
        reg = TrustedKeyRegistry()  # Empty registry

        with patch.object(settings, "ML_MODEL_TRUSTED_KEY_FINGERPRINTS", [fp]):
            loaded = load_public_key(key_pem_or_path=pub, registry=reg, enforce_pinning=True)
            assert loaded is pub

    def test_unregistered_key_with_invalid_fingerprint_rejected(self, ephemeral_keypair):
        """An unregistered key supplied as a raw object with an UNAPPROVED fingerprint fails closed."""
        _, pub = ephemeral_keypair
        reg = TrustedKeyRegistry()

        with patch.object(settings, "ML_MODEL_TRUSTED_KEY_FINGERPRINTS", ["0" * 64]):
            with pytest.raises(ManifestKeyError, match="not in approved trust-anchor allowlist"):
                load_public_key(key_pem_or_path=pub, registry=reg, enforce_pinning=True)

    def test_key_id_lookup_cannot_bypass_fingerprint_validation(self, ephemeral_keypair):
        """Attacker registering key under plausible key_id cannot bypass fingerprint validation in production."""
        _, attacker_pub = ephemeral_keypair
        reg = TrustedKeyRegistry()
        reg.register("eduintel-ml-signer-2026-v1", attacker_pub, status="active")

        with patch.object(settings, "ENVIRONMENT", "production"):
            with patch.object(settings, "ML_MODEL_TRUSTED_KEY_FINGERPRINTS", ["0" * 64]):
                with pytest.raises(ManifestKeyError, match="not in approved trust-anchor allowlist"):
                    load_public_key(key_id="eduintel-ml-signer-2026-v1", registry=reg)

    def test_file_based_key_cannot_bypass_fingerprint_validation(self, tmp_path: Path, ephemeral_keypair):
        """A key loaded from a file path with an unapproved fingerprint fails closed in production."""
        _, unapproved_pub = ephemeral_keypair
        key_file = tmp_path / "unapproved_key.pem"
        key_file.write_bytes(
            unapproved_pub.public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        )

        with patch.object(settings, "ENVIRONMENT", "production"):
            with patch.object(settings, "ML_MODEL_TRUSTED_KEY_FINGERPRINTS", ["0" * 64]):
                with pytest.raises(ManifestKeyError, match="not in approved trust-anchor allowlist"):
                    load_public_key(key_pem_or_path=key_file)

    def test_raw_pem_key_cannot_bypass_fingerprint_validation(self, ephemeral_keypair):
        """A key loaded from raw PEM string with an unapproved fingerprint fails closed in production."""
        _, unapproved_pub = ephemeral_keypair
        pem_str = unapproved_pub.public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        ).decode("ascii")

        with patch.object(settings, "ENVIRONMENT", "production"):
            with patch.object(settings, "ML_MODEL_TRUSTED_KEY_FINGERPRINTS", ["0" * 64]):
                with pytest.raises(ManifestKeyError, match="not in approved trust-anchor allowlist"):
                    load_public_key(key_pem_or_path=pem_str)

    def test_missing_or_empty_trusted_fingerprint_in_production_fails_closed(self, ephemeral_keypair):
        """In production, empty or unconfigured fingerprint allowlist immediately fails closed."""
        _, pub = ephemeral_keypair

        with patch.object(settings, "ENVIRONMENT", "production"):
            with patch.object(settings, "ML_MODEL_TRUSTED_KEY_FINGERPRINTS", []):
                with pytest.raises(ManifestKeyError, match="missing or empty|strictly forbids model verification"):
                    load_public_key(pub)

    def test_malformed_trusted_fingerprint_configuration_fails_closed(self, ephemeral_keypair):
        """In production, a malformed (non-64-hex) fingerprint allowlist immediately fails closed."""
        _, pub = ephemeral_keypair

        with patch.object(settings, "ENVIRONMENT", "production"):
            with patch.object(settings, "ML_MODEL_TRUSTED_KEY_FINGERPRINTS", ["malformed-not-64-hex"]):
                with pytest.raises(ManifestKeyError, match="Malformed trusted key fingerprint"):
                    load_public_key(pub)

    def test_attacker_key_substitution_scenario_rejected(self, tmp_path: Path, valid_at_risk_manifest_dict: dict[str, Any]):
        """
        Adversarial Scenario:
        1. Attacker generates independent Ed25519 keypair.
        2. Attacker registers key under legitimate key_id in registry.
        3. Attacker signs a modified manifest.
        4. Application in production mode attempts to load and verify manifest.
        Result: Fails closed with ManifestKeyError before signature verification or model loading.
        """
        attacker_priv = ed25519.Ed25519PrivateKey.generate()
        attacker_pub = attacker_priv.public_key()
        attacker_fp = compute_public_key_fingerprint(attacker_pub)

        legitimate_fp = "3aa4fa48c199f6c741b8f5adade778519453b6bf36acebfd7f57ba958db3e634"
        assert attacker_fp != legitimate_fp

        reg = TrustedKeyRegistry()
        reg.register("eduintel-ml-signer-2026-v1", attacker_pub, status="active")

        # Attacker signs manifest
        attacker_manifest = dict(valid_at_risk_manifest_dict)
        attacker_manifest["algorithm"] = "sklearn.ensemble.MaliciousClassifier"
        signed = sign_manifest_dict(attacker_manifest, attacker_priv, key_id="eduintel-ml-signer-2026-v1")

        manifest_file = tmp_path / "at_risk_manifest.json"
        manifest_file.write_text(json.dumps(signed))

        with patch.object(settings, "ENVIRONMENT", "production"):
            with patch.object(settings, "ML_MODEL_TRUSTED_KEY_FINGERPRINTS", [legitimate_fp]):
                with pytest.raises(ManifestKeyError, match="not in approved trust-anchor allowlist"):
                    load_verified_manifest_from_file(manifest_file, registry=reg)

    def test_startup_initialization_with_approved_key(self, ephemeral_keypair):
        """Startup initialization registers public key whose fingerprint matches approved allowlist."""
        _, pub = ephemeral_keypair
        fp = compute_public_key_fingerprint(pub)
        pem_bytes = pub.public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)

        saved_keys = dict(GLOBAL_TRUSTED_KEY_REGISTRY._keys)
        try:
            GLOBAL_TRUSTED_KEY_REGISTRY.clear()
            with patch.object(settings, "ENVIRONMENT", "production"):
                with patch.object(settings, "ML_MODEL_TRUSTED_KEY_FINGERPRINTS", [fp]):
                    with patch("pathlib.Path.is_file", return_value=True):
                        with patch("pathlib.Path.read_bytes", return_value=pem_bytes):
                            _init_default_key_registry()
                            assert GLOBAL_TRUSTED_KEY_REGISTRY.get_key(settings.ML_MODEL_SIGNING_KEY_ID) is not None
        finally:
            GLOBAL_TRUSTED_KEY_REGISTRY._keys = dict(saved_keys)

    def test_approved_key_startup_restores_original_registry(self, ephemeral_keypair):
        """Verifies that ephemeral key registration during startup test does not corrupt original registry."""
        original_entry = GLOBAL_TRUSTED_KEY_REGISTRY.get_entry(settings.ML_MODEL_SIGNING_KEY_ID)
        original_pub = original_entry.public_key
        original_fp = original_entry.fingerprint

        _, pub = ephemeral_keypair
        fp = compute_public_key_fingerprint(pub)
        pem_bytes = pub.public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)

        saved_keys = dict(GLOBAL_TRUSTED_KEY_REGISTRY._keys)
        try:
            GLOBAL_TRUSTED_KEY_REGISTRY.clear()
            with patch.object(settings, "ENVIRONMENT", "production"):
                with patch.object(settings, "ML_MODEL_TRUSTED_KEY_FINGERPRINTS", [fp]):
                    with patch("pathlib.Path.is_file", return_value=True):
                        with patch("pathlib.Path.read_bytes", return_value=pem_bytes):
                            _init_default_key_registry()
                            # During test, it holds ephemeral key
                            assert GLOBAL_TRUSTED_KEY_REGISTRY.get_key(settings.ML_MODEL_SIGNING_KEY_ID) is not None
                            assert compute_public_key_fingerprint(
                                GLOBAL_TRUSTED_KEY_REGISTRY.get_key(settings.ML_MODEL_SIGNING_KEY_ID)
                            ) == fp
        finally:
            GLOBAL_TRUSTED_KEY_REGISTRY._keys = dict(saved_keys)

        # After cleanup, original key must be restored
        restored_entry = GLOBAL_TRUSTED_KEY_REGISTRY.get_entry(settings.ML_MODEL_SIGNING_KEY_ID)
        assert restored_entry.fingerprint == original_fp
        assert restored_entry.public_key == original_pub

    def test_ephemeral_key_does_not_leak_into_subsequent_test(self, ephemeral_keypair):
        """Ephemeral keys registered into GLOBAL_TRUSTED_KEY_REGISTRY are wiped by test isolation fixture."""
        _, pub = ephemeral_keypair
        custom_key_id = "ephemeral-leak-canary-key-id"

        # Register key
        GLOBAL_TRUSTED_KEY_REGISTRY.register(custom_key_id, pub, status="active")
        assert GLOBAL_TRUSTED_KEY_REGISTRY.get_key(custom_key_id) is not None

    def test_original_trusted_key_remains_available(self):
        """Authoritative default signing key is available in registry with genuine fingerprint."""
        entry = GLOBAL_TRUSTED_KEY_REGISTRY.get_entry(settings.ML_MODEL_SIGNING_KEY_ID)
        assert entry.status == "active"
        assert entry.fingerprint == "3aa4fa48c199f6c741b8f5adade778519453b6bf36acebfd7f57ba958db3e634"
        # Confirm that the leak canary key from test_ephemeral_key_does_not_leak_into_subsequent_test is NOT present
        with pytest.raises(ManifestKeyError, match="Unknown signing key_id"):
            GLOBAL_TRUSTED_KEY_REGISTRY.get_key("ephemeral-leak-canary-key-id")

    def test_startup_initialization_rejects_unapproved_model_directory_key(self, ephemeral_keypair):
        """Startup initialization in production fails closed if model directory key fingerprint is unapproved."""
        _, unapproved_pub = ephemeral_keypair
        pem_bytes = unapproved_pub.public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)

        with patch.object(settings, "ENVIRONMENT", "production"):
            with patch.object(settings, "ML_MODEL_TRUSTED_KEY_FINGERPRINTS", ["0" * 64]):
                with patch("pathlib.Path.is_file", return_value=True):
                    with patch("pathlib.Path.read_bytes", return_value=pem_bytes):
                        with pytest.raises(ManifestKeyError, match="does not match trusted allowlist in production"):
                            _init_default_key_registry()

    def test_startup_initialization_missing_production_trust_config_fails_closed(self, ephemeral_keypair):
        """Startup initialization in production fails closed if trusted allowlist is missing or empty."""
        _, pub = ephemeral_keypair
        pem_bytes = pub.public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)

        with patch.object(settings, "ENVIRONMENT", "production"):
            with patch.object(settings, "ML_MODEL_TRUSTED_KEY_FINGERPRINTS", []):
                with patch("pathlib.Path.is_file", return_value=True):
                    with patch("pathlib.Path.read_bytes", return_value=pem_bytes):
                        with pytest.raises(ManifestKeyError, match="missing or empty"):
                            _init_default_key_registry()
