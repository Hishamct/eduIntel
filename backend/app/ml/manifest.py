"""
backend/app/ml/manifest.py

Phase 5 Step 3.6 Stage 6 & 6R: ML Model Integrity & Signed Manifests.
Provides cryptographically verifiable model manifests using Ed25519 digital signatures,
trust-anchor pinning, key identifier resolution, reference distribution binding,
and authoritative feature schema validation.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519

from app.core.config import settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class MLServiceError(Exception):
    """Base exception for ML service failures."""


class ModelIntegrityError(MLServiceError):
    """Base exception for model integrity, digest, or verification failures."""


class ModelSignatureError(ModelIntegrityError):
    """Raised when Ed25519 signature verification fails, is missing, or is invalid."""


class ManifestValidationError(ModelIntegrityError):
    """Raised when manifest schema is malformed, missing fields, or has incompatible versions."""


class ManifestKeyError(ModelIntegrityError):
    """Raised when the public verification key is invalid, missing, unapproved, or untrusted."""


class IncompatibleModelError(ModelIntegrityError):
    """Raised when model feature schema is incompatible with runtime expectations."""


class FeatureValidationError(MLServiceError):
    """Raised when inference features are invalid, missing, infinite, or out of bounds."""


# ---------------------------------------------------------------------------
# Canonical Serialization
# ---------------------------------------------------------------------------

def canonical_json_bytes(data: dict[str, Any]) -> bytes:
    """
    Produces a deterministic, canonical UTF-8 JSON byte representation of a dictionary.
    Keys are sorted recursively and compact separators (',', ':') are enforced with
    no trailing whitespace.
    """
    def _sort(obj: Any) -> Any:
        if isinstance(obj, dict):
            return {k: _sort(v) for k, v in sorted(obj.items())}
        if isinstance(obj, list):
            return [_sort(x) for x in obj]
        return obj

    sorted_obj = _sort(data)
    return json.dumps(sorted_obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


# ---------------------------------------------------------------------------
# Fingerprint & Key Trust Helpers
# ---------------------------------------------------------------------------

def compute_public_key_fingerprint(pub_key: ed25519.Ed25519PublicKey) -> str:
    """Computes the standard DER SubjectPublicKeyInfo SHA-256 fingerprint in lowercase hex."""
    der_bytes = pub_key.public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return hashlib.sha256(der_bytes).hexdigest().lower()


def compute_raw_public_key_fingerprint(pub_key: ed25519.Ed25519PublicKey) -> str:
    """Computes the raw 32-byte public key SHA-256 fingerprint in lowercase hex."""
    raw_bytes = pub_key.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return hashlib.sha256(raw_bytes).hexdigest().lower()


# ---------------------------------------------------------------------------
# Trusted Key Registry
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TrustedKeyEntry:
    key_id: str
    public_key: ed25519.Ed25519PublicKey
    fingerprint: str
    status: str  # "active", "deprecated", "revoked"
    created_at: str
    expires_at: str | None = None


class TrustedKeyRegistry:
    """Explicit in-memory registry of approved signing keys supporting controlled rotation and revocation."""

    def __init__(self) -> None:
        self._keys: dict[str, TrustedKeyEntry] = {}

    def register_key(self, entry: TrustedKeyEntry) -> None:
        self._keys[entry.key_id] = entry

    def register(
        self,
        key_id: str,
        public_key: ed25519.Ed25519PublicKey,
        status: str = "active",
        created_at: str = "2026-11-11T00:00:00Z",
        expires_at: str | None = None,
    ) -> TrustedKeyEntry:
        fp = compute_public_key_fingerprint(public_key)
        entry = TrustedKeyEntry(
            key_id=key_id,
            public_key=public_key,
            fingerprint=fp,
            status=status,
            created_at=created_at,
            expires_at=expires_at,
        )
        self._keys[key_id] = entry
        return entry

    def get_entry(self, key_id: str) -> TrustedKeyEntry:
        if key_id not in self._keys:
            raise ManifestKeyError(f"Unknown signing key_id '{key_id}' not found in trusted key registry")
        entry = self._keys[key_id]
        if entry.status == "revoked":
            raise ManifestKeyError(f"Signing key '{key_id}' has been explicitly revoked")
        return entry

    def get_key(self, key_id: str) -> ed25519.Ed25519PublicKey:
        return self.get_entry(key_id).public_key

    def revoke_key(self, key_id: str) -> None:
        if key_id in self._keys:
            curr = self._keys[key_id]
            self._keys[key_id] = TrustedKeyEntry(
                key_id=curr.key_id,
                public_key=curr.public_key,
                fingerprint=curr.fingerprint,
                status="revoked",
                created_at=curr.created_at,
                expires_at=curr.expires_at,
            )

    def is_registered(self, fingerprint: str) -> bool:
        """Checks whether a key with this fingerprint is registered in the process-local registry.
        NOTE: Registry registration is purely an index and is NOT proof of cryptographic trust."""
        norm = fingerprint.lower().strip()
        for entry in self._keys.values():
            if entry.fingerprint.lower() == norm and entry.status != "revoked":
                return True
        return False

    def get_fingerprints(self) -> list[str]:
        return [e.fingerprint.lower() for e in self._keys.values() if e.status != "revoked"]

    def clear(self) -> None:
        self._keys.clear()


GLOBAL_TRUSTED_KEY_REGISTRY: TrustedKeyRegistry = TrustedKeyRegistry()


# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class FeatureSpec:
    name: str
    type: str  # "float" or "int"
    min: float
    max: float
    order: int

    def validate_value(self, val: Any) -> float:
        """Validates that a feature value matches type, is numeric, finite, and within bounds."""
        if isinstance(val, bool) or not isinstance(val, (int, float)):
            raise TypeError(f"Feature '{self.name}' must be numeric (int/float), got {type(val).__name__}")
        f_val = float(val)
        if not math.isfinite(f_val):
            raise ValueError(f"Feature '{self.name}' is non-finite (got {val})")
        if f_val < self.min or f_val > self.max:
            raise ValueError(
                f"Feature '{self.name}' value {f_val} out of domain bounds [{self.min}, {self.max}]"
            )
        return f_val


@dataclass
class SignedModelManifest:
    model_name: str
    model_version: str
    artifact_filename: str
    sha256: str
    algorithm: str
    feature_schema_version: str
    features: list[FeatureSpec]
    created_at: str
    key_id: str = "eduintel-ml-signer-2026-v1"
    reference_distribution: dict[str, Any] | None = None
    compatibility: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    signature: str | None = None  # Base64-encoded Ed25519 signature

    @property
    def expected_features(self) -> list[str]:
        """Returns feature names strictly ordered by positional index."""
        sorted_feats = sorted(self.features, key=lambda f: f.order)
        return [f.name for f in sorted_feats]

    @property
    def feature_bounds(self) -> dict[str, tuple[float, float]]:
        return {f.name: (f.min, f.max) for f in self.features}

    def validate_features(self, features: dict[str, Any]) -> list[float]:
        """
        Authoritative schema validator: uses verified manifest metadata to validate
        presence, exact naming, lack of extra keys, types, finiteness, domain bounds,
        and one-hot subject constraints.
        """
        if not isinstance(features, dict):
            raise FeatureValidationError("Inference features must be provided as a dictionary")

        expected = self.expected_features
        extra_features = set(features.keys()) - set(expected)
        if extra_features:
            raise FeatureValidationError(f"Unexpected extra feature(s) provided: {sorted(extra_features)}")

        vector: list[float] = []
        sorted_specs = sorted(self.features, key=lambda f: f.order)

        for spec in sorted_specs:
            if spec.name not in features:
                raise FeatureValidationError(f"Missing required feature: '{spec.name}'")

            val = features[spec.name]
            try:
                f_val = spec.validate_value(val)
            except (TypeError, ValueError) as exc:
                raise FeatureValidationError(str(exc)) from exc

            # Subject one-hot columns constraint
            if spec.name.startswith("subject_"):
                if f_val not in (0.0, 1.0):
                    raise FeatureValidationError(f"One-hot feature '{spec.name}' must be 0 or 1, got {f_val}")

            vector.append(f_val)

        return vector

    def to_dict(self, include_signature: bool = True) -> dict[str, Any]:
        d: dict[str, Any] = {
            "model_name": self.model_name,
            "model_version": self.model_version,
            "artifact_filename": self.artifact_filename,
            "sha256": self.sha256.lower(),
            "algorithm": self.algorithm,
            "feature_schema_version": self.feature_schema_version,
            "key_id": self.key_id,
            "features": [
                {
                    "name": f.name,
                    "type": f.type,
                    "min": f.min,
                    "max": f.max,
                    "order": f.order,
                }
                for f in sorted(self.features, key=lambda f: f.order)
            ],
            "created_at": self.created_at,
            "compatibility": self.compatibility,
            "metadata": self.metadata,
        }
        if self.reference_distribution is not None:
            d["reference_distribution"] = self.reference_distribution
        if include_signature and self.signature is not None:
            d["signature"] = self.signature
        return d

    def canonical_bytes_for_signing(self) -> bytes:
        """Returns canonical JSON bytes of the manifest excluding any signature field."""
        return canonical_json_bytes(self.to_dict(include_signature=False))


# ---------------------------------------------------------------------------
# Key Management & Cryptography
# ---------------------------------------------------------------------------

def load_public_key(
    key_pem_or_path: str | Path | bytes | None = None,
    key_id: str | None = None,
    registry: TrustedKeyRegistry | None = None,
    enforce_pinning: bool | None = None,
) -> ed25519.Ed25519PublicKey:
    """
    Loads an Ed25519 public verification key with mandatory trust-anchor pinning.
    No candidate key may be returned before mandatory trust-anchor validation.
    In production environments or when enforce_pinning is enabled, the key's SHA-256
    fingerprint must match settings.ML_MODEL_TRUSTED_KEY_FINGERPRINTS.
    Registry membership is NOT proof of trust; every candidate key is evaluated against the allowlist.
    """
    reg = registry or GLOBAL_TRUSTED_KEY_REGISTRY

    candidate_key: ed25519.Ed25519PublicKey | None = None

    # 1. Resolve candidate public key from requested source
    if isinstance(key_pem_or_path, ed25519.Ed25519PublicKey):
        candidate_key = key_pem_or_path
    elif key_pem_or_path is not None:
        raw_data: bytes | None = None

        if isinstance(key_pem_or_path, (str, Path)):
            p = Path(key_pem_or_path)
            if p.is_file():
                raw_data = p.read_bytes()
            elif isinstance(key_pem_or_path, str) and "BEGIN PUBLIC KEY" in key_pem_or_path:
                raw_data = key_pem_or_path.encode("utf-8")
            elif isinstance(key_pem_or_path, str):
                try:
                    candidate_bytes = bytes.fromhex(key_pem_or_path)
                    if len(candidate_bytes) == 32:
                        raw_data = candidate_bytes
                except ValueError:
                    pass
                if raw_data is None:
                    try:
                        candidate_bytes = base64.b64decode(key_pem_or_path)
                        if len(candidate_bytes) == 32:
                            raw_data = candidate_bytes
                    except Exception:
                        pass
        elif isinstance(key_pem_or_path, bytes):
            raw_data = key_pem_or_path

        if raw_data is None:
            raise ManifestKeyError(f"Provided public key source is invalid or does not exist: {key_pem_or_path}")

        try:
            if len(raw_data) == 32 and b"BEGIN" not in raw_data:
                candidate_key = ed25519.Ed25519PublicKey.from_public_bytes(raw_data)
            else:
                loaded = serialization.load_pem_public_key(raw_data)
                if not isinstance(loaded, ed25519.Ed25519PublicKey):
                    raise ManifestKeyError(
                        f"Loaded public key is of type {type(loaded).__name__}, expected Ed25519PublicKey"
                    )
                candidate_key = loaded
        except Exception as exc:
            if isinstance(exc, ManifestKeyError):
                raise
            raise ManifestKeyError(f"Failed to load Ed25519 public key: {exc}") from exc

    elif key_id:
        # Resolve candidate key from registry if present
        try:
            candidate_key = reg.get_key(key_id)
        except ManifestKeyError as exc:
            # If not in registry and in production, fail closed immediately
            if getattr(settings, "ENVIRONMENT", "development") == "production":
                raise ManifestKeyError(f"Signing key_id '{key_id}' is not registered in trusted key registry") from exc
            # In dev mode, fall through to settings/file fallback

    # Fallback to settings / model directory if candidate_key not yet resolved
    if candidate_key is None:
        raw_data = None
        if settings.ML_MODEL_SIGNING_PUBLIC_KEY:
            raw_data = settings.ML_MODEL_SIGNING_PUBLIC_KEY.encode("utf-8")
        else:
            key_path = Path(settings.ML_MODEL_SIGNING_PUBLIC_KEY_PATH)
            if not key_path.is_absolute():
                models_dir = Path(__file__).resolve().parent / "models"
                candidates = [
                    key_path,
                    models_dir / key_path.name,
                    Path.cwd() / key_path,
                    Path.cwd() / "backend" / key_path,
                ]
                for cand in candidates:
                    if cand.is_file():
                        raw_data = cand.read_bytes()
                        break
            elif key_path.is_file():
                raw_data = key_path.read_bytes()

        if not raw_data:
            raise ManifestKeyError(
                f"Ed25519 model signing public key could not be located. "
                f"Configured path: '{settings.ML_MODEL_SIGNING_PUBLIC_KEY_PATH}'"
            )

        try:
            if len(raw_data) == 32 and b"BEGIN" not in raw_data:
                candidate_key = ed25519.Ed25519PublicKey.from_public_bytes(raw_data)
            else:
                loaded = serialization.load_pem_public_key(raw_data)
                if not isinstance(loaded, ed25519.Ed25519PublicKey):
                    raise ManifestKeyError(
                        f"Loaded public key is of type {type(loaded).__name__}, expected Ed25519PublicKey"
                    )
                candidate_key = loaded
        except Exception as exc:
            if isinstance(exc, ManifestKeyError):
                raise
            raise ManifestKeyError(f"Failed to load Ed25519 public key: {exc}") from exc

    # 2. Mandatory Trust-Anchor Validation across ALL key sources
    # Candidate key MUST NOT be returned without passing fingerprint verification
    fingerprint = compute_public_key_fingerprint(candidate_key)
    raw_fingerprint = compute_raw_public_key_fingerprint(candidate_key)
    approved_fps = [fp.lower().strip() for fp in getattr(settings, "ML_MODEL_TRUSTED_KEY_FINGERPRINTS", []) if fp]
    is_prod = (getattr(settings, "ENVIRONMENT", "development") == "production")
    trust_dev_keys = getattr(settings, "ML_MODEL_TRUST_DEV_KEYS", True)

    must_pin = enforce_pinning if enforce_pinning is not None else (is_prod or not trust_dev_keys)

    # In production or when pinning is enforced, allowlist must be explicit and non-empty
    if must_pin:
        if not approved_fps:
            raise ManifestKeyError(
                "Trust-anchor error: ML_MODEL_TRUSTED_KEY_FINGERPRINTS is missing or empty. "
                "Production mode strictly forbids model verification without an explicit trusted fingerprint allowlist."
            )
        for afp in approved_fps:
            if len(afp) != 64 or not all(c in "0123456789abcdef" for c in afp):
                raise ManifestKeyError(
                    f"Malformed trusted key fingerprint in configuration: '{afp}'. Must be a 64-character SHA-256 hex digest."
                )

    is_approved = (fingerprint in approved_fps) or (raw_fingerprint in approved_fps)

    if must_pin and not is_approved:
        raise ManifestKeyError(
            f"Ed25519 public key rejected: fingerprint '{fingerprint}' is not in approved trust-anchor allowlist. "
            f"Production mode forbids unapproved public keys or unauthenticated environment overrides."
        )

    # In dev mode, if fingerprint allowlist is configured, enforce unless dev keys are explicitly trusted
    if not is_approved and approved_fps and not (trust_dev_keys and not is_prod):
        raise ManifestKeyError(
            f"Ed25519 public key fingerprint '{fingerprint}' not in configured allowlist."
        )

    # 3. Check key revocation in registry if key_id is specified
    if key_id:
        try:
            entry = reg.get_entry(key_id)
            if entry.status == "revoked":
                raise ManifestKeyError(f"Signing key '{key_id}' has been revoked")
        except ManifestKeyError as exc:
            if "revoked" in str(exc):
                raise
            if is_prod:
                raise

    return candidate_key


# Pre-register default active key into registry if file exists and matches trust anchor
def _init_default_key_registry() -> None:
    models_dir = Path(__file__).resolve().parent / "models"
    key_file = models_dir / "model_signing_public_key.pem"
    if not key_file.is_file():
        return

    try:
        raw = key_file.read_bytes()
        key = serialization.load_pem_public_key(raw)
        if not isinstance(key, ed25519.Ed25519PublicKey):
            return

        fp = compute_public_key_fingerprint(key)
        raw_fp = compute_raw_public_key_fingerprint(key)
        approved_fps = [f.lower().strip() for f in getattr(settings, "ML_MODEL_TRUSTED_KEY_FINGERPRINTS", []) if f]
        is_prod = (getattr(settings, "ENVIRONMENT", "development") == "production")
        trust_dev = getattr(settings, "ML_MODEL_TRUST_DEV_KEYS", True)

        is_approved = (fp in approved_fps) or (raw_fp in approved_fps)

        if is_prod or not trust_dev:
            if not approved_fps:
                raise ManifestKeyError(
                    "Production startup failed: ML_MODEL_TRUSTED_KEY_FINGERPRINTS is missing or empty."
                )
            for afp in approved_fps:
                if len(afp) != 64 or not all(c in "0123456789abcdef" for c in afp):
                    raise ManifestKeyError(
                        f"Malformed trusted key fingerprint in configuration: '{afp}'."
                    )
            if not is_approved:
                raise ManifestKeyError(
                    f"Model directory public key fingerprint '{fp}' does not match trusted allowlist in production. "
                    f"Startup rejected: unapproved key cannot be registered into trust registry."
                )

        if is_approved:
            GLOBAL_TRUSTED_KEY_REGISTRY.register(
                key_id=settings.ML_MODEL_SIGNING_KEY_ID,
                public_key=key,
                status="active",
            )
        else:
            logger.warning(
                "[Manifest] Model directory public key '%s' (fp: %s) is not in approved allowlist. "
                "Refusing to register unapproved key into trusted key registry.",
                key_file.name,
                fp,
            )
    except Exception as exc:
        if getattr(settings, "ENVIRONMENT", "development") == "production":
            logger.error("[Manifest] Failed to initialize default key registry: %s", exc)
            raise
        logger.debug("[Manifest] Could not pre-register default key: %s", exc)


_init_default_key_registry()


# ---------------------------------------------------------------------------
# Signing & Verification
# ---------------------------------------------------------------------------

def sign_manifest_dict(
    manifest_dict: dict[str, Any],
    private_key: ed25519.Ed25519PrivateKey,
    key_id: str | None = None,
) -> dict[str, Any]:
    """
    Signs a manifest dictionary using an Ed25519 private key.
    Injects key_id and returns a new dictionary containing the canonical fields plus a base64-encoded 'signature'.
    """
    payload = {k: v for k, v in manifest_dict.items() if k != "signature"}
    if key_id:
        payload["key_id"] = key_id
    elif "key_id" not in payload:
        payload["key_id"] = settings.ML_MODEL_SIGNING_KEY_ID

    canon_bytes = canonical_json_bytes(payload)
    sig_bytes = private_key.sign(canon_bytes)
    result = dict(payload)
    result["signature"] = base64.b64encode(sig_bytes).decode("ascii")
    return result


def parse_manifest_dict(raw: dict[str, Any]) -> SignedModelManifest:
    """Parses and validates the structure, types, and schema of a manifest dictionary."""
    if not isinstance(raw, dict):
        raise ManifestValidationError(f"Manifest must be a dictionary, got {type(raw).__name__}")

    required_fields = [
        "model_name",
        "model_version",
        "artifact_filename",
        "sha256",
        "algorithm",
        "feature_schema_version",
        "features",
    ]
    missing = [f for f in required_fields if f not in raw]
    if missing:
        raise ManifestValidationError(f"Manifest missing required fields: {missing}")

    sha256_val = str(raw["sha256"]).lower().strip()
    if len(sha256_val) != 64 or not all(c in "0123456789abcdef" for c in sha256_val):
        raise ManifestValidationError(f"Manifest 'sha256' is malformed: '{raw['sha256']}'")

    raw_features = raw["features"]
    if not isinstance(raw_features, list) or not raw_features:
        raise ManifestValidationError("Manifest 'features' must be a non-empty list")

    features: list[FeatureSpec] = []
    seen_names = set()
    seen_orders = set()

    for idx, f in enumerate(raw_features):
        if not isinstance(f, dict):
            raise ManifestValidationError(f"Feature at index {idx} must be a dictionary")
        for k in ("name", "type", "min", "max"):
            if k not in f:
                raise ManifestValidationError(f"Feature at index {idx} missing '{k}'")
        fname = str(f["name"])
        if fname in seen_names:
            raise ManifestValidationError(f"Duplicate feature name '{fname}' in manifest")
        seen_names.add(fname)

        order = int(f.get("order", idx))
        if order in seen_orders:
            raise ManifestValidationError(f"Duplicate feature order index {order} in manifest")
        seen_orders.add(order)

        try:
            f_min = float(f["min"])
            f_max = float(f["max"])
        except (ValueError, TypeError) as exc:
            raise ManifestValidationError(f"Feature '{fname}' has invalid bounds: {exc}") from exc

        if f_min > f_max:
            raise ManifestValidationError(f"Feature '{fname}' min {f_min} exceeds max {f_max}")

        features.append(
            FeatureSpec(
                name=fname,
                type=str(f["type"]).lower(),
                min=f_min,
                max=f_max,
                order=order,
            )
        )

    features.sort(key=lambda x: x.order)

    # Reference distribution spec validation if provided
    ref_dist = raw.get("reference_distribution")
    if ref_dist is not None:
        if not isinstance(ref_dist, dict):
            raise ManifestValidationError("Manifest 'reference_distribution' must be a dictionary")
        for r_field in ("filename", "sha256", "version"):
            if r_field not in ref_dist:
                raise ManifestValidationError(f"Reference distribution missing required field: '{r_field}'")
        ref_sha = str(ref_dist["sha256"]).lower().strip()
        if len(ref_sha) != 64 or not all(c in "0123456789abcdef" for c in ref_sha):
            raise ManifestValidationError(f"Reference distribution SHA-256 is malformed: '{ref_dist['sha256']}'")

    key_id = str(raw.get("key_id", settings.ML_MODEL_SIGNING_KEY_ID))

    return SignedModelManifest(
        model_name=str(raw["model_name"]),
        model_version=str(raw["model_version"]),
        artifact_filename=str(raw["artifact_filename"]),
        sha256=sha256_val,
        algorithm=str(raw["algorithm"]),
        feature_schema_version=str(raw["feature_schema_version"]),
        features=features,
        created_at=str(raw.get("created_at", "")),
        key_id=key_id,
        reference_distribution=ref_dist,
        compatibility=raw.get("compatibility", {}),
        metadata=raw.get("metadata", {}),
        signature=raw.get("signature"),
    )


def verify_reference_distribution(
    manifest: SignedModelManifest,
    ref_source: Path | str | dict[str, Any],
) -> dict[str, Any]:
    """
    Verifies that a reference distribution is bound to the signed manifest,
    matches the expected SHA-256 digest, and is fully compatible with model identity and feature schema.
    """
    if manifest.reference_distribution is None:
        raise ModelIntegrityError(
            f"Model manifest '{manifest.model_name}' has no bound reference distribution metadata. "
            f"Production requires reference distributions to be pinned by signed manifest."
        )

    expected_sha = manifest.reference_distribution["sha256"].lower().strip()
    ref_data: dict[str, Any]

    if isinstance(ref_source, (str, Path)):
        ref_path = Path(ref_source)
        if not ref_path.is_file():
            raise ModelIntegrityError(f"Reference distribution file not found at {ref_path}")

        # Compute SHA-256 over raw file bytes
        file_bytes = ref_path.read_bytes()
        computed_sha = hashlib.sha256(file_bytes).hexdigest().lower()
        if computed_sha != expected_sha:
            raise ModelIntegrityError(
                f"Reference distribution digest mismatch for '{manifest.model_name}': "
                f"manifest expects SHA-256 {expected_sha}, file has {computed_sha}"
            )

        try:
            ref_data = json.loads(file_bytes.decode("utf-8"))
        except Exception as exc:
            raise ManifestValidationError(f"Malformed JSON in reference distribution at {ref_path}: {exc}") from exc
    elif isinstance(ref_source, dict):
        ref_data = ref_source
    else:
        raise ModelIntegrityError(f"Unsupported reference distribution source type: {type(ref_source).__name__}")

    # Validate model identity and version compatibility
    if ref_data.get("model_name") != manifest.model_name:
        raise ManifestValidationError(
            f"Reference distribution model_name '{ref_data.get('model_name')}' does not match "
            f"manifest model_name '{manifest.model_name}'"
        )

    if ref_data.get("model_version") != manifest.model_version:
        raise ManifestValidationError(
            f"Reference distribution model_version '{ref_data.get('model_version')}' does not match "
            f"manifest model_version '{manifest.model_version}'"
        )

    # Validate feature list alignment
    ref_features = list(ref_data.get("features", {}).keys())
    expected_feats = manifest.expected_features
    if set(ref_features) != set(expected_feats):
        diff = set(ref_features).symmetric_difference(set(expected_feats))
        raise ManifestValidationError(
            f"Reference distribution features do not match manifest features. Discrepancies: {sorted(diff)}"
        )

    return ref_data


def verify_manifest_signature(
    manifest_dict_or_obj: dict[str, Any] | SignedModelManifest,
    public_key: ed25519.Ed25519PublicKey | None = None,
    signature_bytes_or_str: bytes | str | None = None,
    registry: TrustedKeyRegistry | None = None,
) -> SignedModelManifest:
    """
    Verifies the Ed25519 digital signature of a model manifest.
    Resolves verification key via key_id in registry if public_key is omitted.
    Fails closed on any signature mismatch, corruption, missing key, revoked key, or untrusted payload.
    """
    reg = registry or GLOBAL_TRUSTED_KEY_REGISTRY

    if isinstance(manifest_dict_or_obj, SignedModelManifest):
        manifest_obj = manifest_dict_or_obj
        raw_dict = manifest_obj.to_dict(include_signature=False)
        sig = signature_bytes_or_str or manifest_obj.signature
    else:
        raw_dict = dict(manifest_dict_or_obj)
        sig = signature_bytes_or_str or raw_dict.pop("signature", None)
        manifest_obj = parse_manifest_dict(raw_dict)

    if not sig:
        raise ModelSignatureError(
            f"No Ed25519 digital signature provided for manifest '{manifest_obj.model_name}'"
        )

    # Resolve public key if not explicitly passed
    resolved_key: ed25519.Ed25519PublicKey
    if public_key is not None:
        is_prod = (getattr(settings, "ENVIRONMENT", "development") == "production")
        if is_prod:
            # Mandatorily validate caller-supplied public_key against trust-anchor in production
            load_public_key(key_pem_or_path=public_key, key_id=manifest_obj.key_id, registry=reg, enforce_pinning=True)
        resolved_key = public_key
    else:
        resolved_key = load_public_key(key_id=manifest_obj.key_id, registry=reg)

    # Check key_id revocation in registry
    if manifest_obj.key_id:
        try:
            entry = reg.get_entry(manifest_obj.key_id)
            if entry.status == "revoked":
                raise ManifestKeyError(f"Signing key '{manifest_obj.key_id}' has been revoked")
        except ManifestKeyError as exc:
            if "revoked" in str(exc):
                raise
            # If not in registry and in dev mode with explicit public_key, permit
            if getattr(settings, "ENVIRONMENT", "development") == "production":
                raise

    # Decode signature bytes
    if isinstance(sig, bytes):
        if len(sig) == 64:
            sig_bytes = sig
        else:
            try:
                sig_bytes = base64.b64decode(sig.strip())
            except Exception:
                try:
                    sig_bytes = bytes.fromhex(sig.strip().decode("ascii"))
                except Exception:
                    sig_bytes = sig
    elif isinstance(sig, str):
        sig_str = sig.strip()
        try:
            sig_bytes = base64.b64decode(sig_str)
        except Exception:
            try:
                sig_bytes = bytes.fromhex(sig_str)
            except Exception as exc:
                raise ModelSignatureError(f"Malformed signature encoding: {exc}") from exc
    else:
        raise ModelSignatureError(f"Unsupported signature type: {type(sig).__name__}")

    if len(sig_bytes) != 64:
        raise ModelSignatureError(
            f"Invalid Ed25519 signature length: expected 64 bytes, got {len(sig_bytes)}"
        )

    # Reconstruct canonical byte payload
    payload_dict = {k: v for k, v in raw_dict.items() if k != "signature"}
    canon_bytes = canonical_json_bytes(payload_dict)

    try:
        resolved_key.verify(sig_bytes, canon_bytes)
    except InvalidSignature as exc:
        raise ModelSignatureError(
            f"Ed25519 signature verification failed for model '{manifest_obj.model_name}'. "
            f"Manifest content may have been tampered with or signed with an untrusted key."
        ) from exc
    except Exception as exc:
        raise ModelSignatureError(f"Cryptographic verification error: {exc}") from exc

    manifest_obj.signature = base64.b64encode(sig_bytes).decode("ascii")
    logger.debug("[Manifest] Verified Ed25519 signature for model '%s' (key_id: %s)", manifest_obj.model_name, manifest_obj.key_id)
    return manifest_obj


def load_verified_manifest_from_file(
    manifest_path: str | Path,
    public_key: ed25519.Ed25519PublicKey | None = None,
    signature_path: str | Path | None = None,
    registry: TrustedKeyRegistry | None = None,
) -> SignedModelManifest:
    """
    Loads, parses, and cryptographically verifies a model manifest from disk.
    Supports either an embedded signature field inside the JSON or a detached signature file (.sig).
    """
    path = Path(manifest_path)
    if not path.is_file():
        raise ModelIntegrityError(f"Manifest file not found: {path}")

    try:
        raw_content = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ManifestValidationError(f"Failed to parse manifest JSON at {path}: {exc}") from exc

    sig_data: str | bytes | None = None
    if signature_path:
        sig_p = Path(signature_path)
        if sig_p.is_file():
            sig_data = sig_p.read_bytes()
    else:
        sig_candidate = path.with_suffix(path.suffix + ".sig")
        if sig_candidate.is_file():
            sig_data = sig_candidate.read_bytes()

    parsed = parse_manifest_dict(raw_content)

    if public_key is None:
        public_key = load_public_key(key_id=parsed.key_id, registry=registry)

    return verify_manifest_signature(
        manifest_dict_or_obj=raw_content,
        public_key=public_key,
        signature_bytes_or_str=sig_data,
        registry=registry,
    )
