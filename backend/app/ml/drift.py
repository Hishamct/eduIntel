"""
backend/app/ml/drift.py

Phase 5 Step 3.6 Stage 6 & 6R: Feature Drift Monitoring using Population Stability Index (PSI).
Calculates per-feature and aggregate PSI with Laplace smoothing, dedicated missing/invalid bins,
configurable thresholds, and strict valid-sample-size gating (N_valid >= 200).

CRITICAL OPERATIONAL INVARIANT:
Drift monitoring is diagnostic and advisory ONLY. It emits structured alerts and metrics,
and NEVER triggers automated model rollback, replacement, retraining, or deactivation.
"""

from __future__ import annotations

import datetime
import enum
import logging
import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.core.config import settings

logger = logging.getLogger(__name__)

DEFAULT_EPSILON: float = 1e-4  # 0.0001 Laplace smoothing constant
DEFAULT_MIN_SAMPLE_SIZE: int = 200
DEFAULT_WARNING_THRESHOLD: float = 0.10
DEFAULT_HIGH_THRESHOLD: float = 0.25


class DriftStatus(enum.StrEnum):
    """Statistically grounded feature drift classifications."""
    NO_DRIFT = "NO_DRIFT"                          # PSI < 0.10
    WARNING = "WARNING"                            # 0.10 <= PSI < 0.25
    HIGH_DRIFT = "HIGH_DRIFT"                      # PSI >= 0.25
    INSUFFICIENT_SAMPLE_SIZE = "INSUFFICIENT_SAMPLE_SIZE"  # Valid N < 200
    INVALID_REFERENCE = "INVALID_REFERENCE"        # Reference distribution is malformed/incompatible
    EVALUATION_FAILURE = "EVALUATION_FAILURE"      # Internal computation error


@dataclass(frozen=True)
class FeatureReferenceDistribution:
    """Pre-computed reference distribution for a specific model feature."""
    feature_name: str
    bin_edges: list[float]  # B+1 edges defining B standard intervals [e_0, e_1, ..., e_B]
    expected_proportions: list[float]  # Length B (standard bins) or B+1 (including missing bin)
    reference_version: str
    model_version: str
    sample_size: int = 1000

    def __post_init__(self):
        if len(self.bin_edges) < 2:
            raise ValueError(f"Feature '{self.feature_name}' must have at least 2 bin edges")
        # Ensure bin edges are non-decreasing
        for i in range(len(self.bin_edges) - 1):
            if self.bin_edges[i] > self.bin_edges[i + 1]:
                raise ValueError(
                    f"Feature '{self.feature_name}' bin edges must be non-decreasing: {self.bin_edges}"
                )
        num_standard_bins = len(self.bin_edges) - 1
        if len(self.expected_proportions) not in (num_standard_bins, num_standard_bins + 1):
            raise ValueError(
                f"Feature '{self.feature_name}' expected proportions length "
                f"({len(self.expected_proportions)}) must be {num_standard_bins} or {num_standard_bins + 1}"
            )


@dataclass
class FeatureDriftResult:
    feature_name: str
    psi: float | None
    status: DriftStatus
    actual_proportions: list[float]
    expected_proportions: list[float]
    bin_edges: list[float]
    sample_count: int
    missing_count: int
    message: str
    valid_sample_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "feature_name": self.feature_name,
            "psi": round(self.psi, 5) if self.psi is not None else None,
            "status": self.status.value,
            "actual_proportions": [round(p, 5) for p in self.actual_proportions],
            "expected_proportions": [round(p, 5) for p in self.expected_proportions],
            "bin_edges": self.bin_edges,
            "sample_count": self.sample_count,
            "valid_sample_count": self.valid_sample_count,
            "missing_count": self.missing_count,
            "message": self.message,
        }


@dataclass
class ModelDriftReport:
    model_name: str
    model_version: str
    reference_version: str
    sample_count: int
    status: DriftStatus
    max_psi_feature: str | None
    max_psi_value: float | None
    mean_psi_value: float | None
    features: dict[str, FeatureDriftResult]
    alert_raised: bool
    created_at: str = field(default_factory=lambda: datetime.datetime.now(datetime.UTC).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_name": self.model_name,
            "model_version": self.model_version,
            "reference_version": self.reference_version,
            "sample_count": self.sample_count,
            "status": self.status.value,
            "max_psi_feature": self.max_psi_feature,
            "max_psi_value": round(self.max_psi_value, 5) if self.max_psi_value is not None else None,
            "mean_psi_value": round(self.mean_psi_value, 5) if self.mean_psi_value is not None else None,
            "alert_raised": self.alert_raised,
            "created_at": self.created_at,
            "features": {k: v.to_dict() for k, v in self.features.items()},
        }


# ---------------------------------------------------------------------------
# Core PSI Math Engine
# ---------------------------------------------------------------------------

def calculate_single_feature_psi(
    values: Sequence[Any],
    reference: FeatureReferenceDistribution,
    min_sample_size: int | None = None,
    warning_threshold: float | None = None,
    high_threshold: float | None = None,
    epsilon: float = DEFAULT_EPSILON,
) -> FeatureDriftResult:
    """
    Computes Population Stability Index (PSI) for an array of observed feature values
    against an approved reference distribution.

    Formula:
        PSI = sum_{b=0}^{B} (P_b - Q_b) * ln((P_b + eps) / (Q_b + eps))

    Where:
        - B standard bins are defined by reference.bin_edges.
        - Bin B+1 is the dedicated MISSING / non-finite / invalid bin.
        - eps is Laplace smoothing constant to prevent zero-frequency log errors.
        - min_sample_size requires at least 200 VALID numeric observations.
    """
    min_n = min_sample_size if min_sample_size is not None else getattr(
        settings, "ML_FEATURE_DRIFT_MIN_SAMPLE_SIZE", DEFAULT_MIN_SAMPLE_SIZE
    )
    warn_thresh = warning_threshold if warning_threshold is not None else getattr(
        settings, "ML_FEATURE_DRIFT_WARNING_THRESHOLD", DEFAULT_WARNING_THRESHOLD
    )
    high_thresh = high_threshold if high_threshold is not None else getattr(
        settings, "ML_FEATURE_DRIFT_HIGH_THRESHOLD", DEFAULT_HIGH_THRESHOLD
    )

    if warn_thresh < 0 or high_thresh <= warn_thresh:
        raise ValueError(
            f"Invalid drift thresholds: warning_threshold ({warn_thresh}) must be non-negative "
            f"and strictly less than high_threshold ({high_thresh})"
        )

    n_samples = len(values)

    # 1. Partition values into standard bins + dedicated MISSING bin
    bin_edges = reference.bin_edges
    num_standard_bins = len(bin_edges) - 1
    total_bins = num_standard_bins + 1  # extra bin for missing/invalid
    bin_counts = [0] * total_bins

    missing_count = 0
    valid_numeric_count = 0

    for v in values:
        if v is None or isinstance(v, bool) or not isinstance(v, (int, float)):
            bin_counts[num_standard_bins] += 1
            missing_count += 1
            continue

        f_val = float(v)
        if not math.isfinite(f_val):
            bin_counts[num_standard_bins] += 1
            missing_count += 1
            continue

        valid_numeric_count += 1

        # Binning: standard intervals [e_i, e_{i+1})
        if f_val < bin_edges[0]:
            bin_counts[0] += 1
        elif f_val >= bin_edges[-1]:
            bin_counts[num_standard_bins - 1] += 1
        else:
            placed = False
            for b in range(num_standard_bins):
                lower = bin_edges[b]
                upper = bin_edges[b + 1]
                if b == num_standard_bins - 1:
                    if lower <= f_val <= upper:
                        bin_counts[b] += 1
                        placed = True
                        break
                else:
                    if lower <= f_val < upper:
                        bin_counts[b] += 1
                        placed = True
                        break
            if not placed:
                bin_counts[num_standard_bins] += 1
                missing_count += 1
                valid_numeric_count -= 1

    actual_proportions = [count / n_samples for count in bin_counts] if n_samples > 0 else []

    # 2. Strict Valid Numeric Sample Size Gate (S6-03)
    # At least min_n valid numeric observations are required for a production drift verdict.
    # Missing, non-numeric, NaN, infinite, and invalid observations do not count toward valid sample size.
    if valid_numeric_count < min_n:
        return FeatureDriftResult(
            feature_name=reference.feature_name,
            psi=None,
            status=DriftStatus.INSUFFICIENT_SAMPLE_SIZE,
            actual_proportions=actual_proportions,
            expected_proportions=list(reference.expected_proportions),
            bin_edges=list(reference.bin_edges),
            sample_count=n_samples,
            valid_sample_count=valid_numeric_count,
            missing_count=missing_count,
            message=(
                f"Valid numeric sample size {valid_numeric_count} is below required minimum of {min_n} "
                f"observations (total raw: {n_samples}, missing/invalid: {missing_count}). "
                "Production drift verdict cannot be determined."
            ),
        )

    # 3. Standardize Expected Proportions Q_b (length total_bins)
    expected_raw = list(reference.expected_proportions)
    if len(expected_raw) == num_standard_bins:
        expected_proportions = expected_raw + [0.0]
    else:
        expected_proportions = expected_raw

    sum_exp = sum(expected_proportions)
    if sum_exp > 0:
        expected_proportions = [q / sum_exp for q in expected_proportions]
    else:
        return FeatureDriftResult(
            feature_name=reference.feature_name,
            psi=None,
            status=DriftStatus.INVALID_REFERENCE,
            actual_proportions=actual_proportions,
            expected_proportions=expected_proportions,
            bin_edges=bin_edges,
            sample_count=n_samples,
            valid_sample_count=valid_numeric_count,
            missing_count=missing_count,
            message="Reference distribution proportions sum to zero or are invalid.",
        )

    # 4. Compute PSI with Laplace smoothing
    psi = 0.0
    for b in range(total_bins):
        p = actual_proportions[b]
        q = expected_proportions[b]
        term = (p - q) * math.log((p + epsilon) / (q + epsilon))
        psi += term

    psi = max(0.0, psi)

    # 5. Determine Classification
    if psi >= high_thresh:
        status = DriftStatus.HIGH_DRIFT
        msg = f"Significant feature drift detected: PSI = {psi:.4f} >= {high_thresh}"
    elif psi >= warn_thresh:
        status = DriftStatus.WARNING
        msg = f"Moderate feature drift detected: PSI = {psi:.4f} >= {warn_thresh}"
    else:
        status = DriftStatus.NO_DRIFT
        msg = f"No significant drift: PSI = {psi:.4f} < {warn_thresh}"

    return FeatureDriftResult(
        feature_name=reference.feature_name,
        psi=psi,
        status=status,
        actual_proportions=actual_proportions,
        expected_proportions=expected_proportions,
        bin_edges=bin_edges,
        sample_count=n_samples,
        valid_sample_count=valid_numeric_count,
        missing_count=missing_count,
        message=msg,
    )


def evaluate_model_feature_drift(
    model_name: str,
    feature_matrix_or_records: list[dict[str, Any]] | dict[str, list[Any]],
    reference_distributions: dict[str, FeatureReferenceDistribution],
    min_sample_size: int | None = None,
    warning_threshold: float | None = None,
    high_threshold: float | None = None,
) -> ModelDriftReport:
    """
    Evaluates Population Stability Index across all features of a model.
    Produces per-feature diagnostics and an aggregate summary without masking
    individual feature drift. Advisory only: raises alert flags but never mutates runtime models.
    """
    first_ref = next(iter(reference_distributions.values()), None)
    model_version = first_ref.model_version if first_ref else "unknown"
    ref_version = first_ref.reference_version if first_ref else "unknown"

    # Normalize input into column-oriented dict: feature_name -> list of values
    col_data: dict[str, list[Any]] = {}
    total_samples = 0

    if isinstance(feature_matrix_or_records, dict):
        col_data = {k: list(v) for k, v in feature_matrix_or_records.items()}
        if col_data:
            total_samples = len(next(iter(col_data.values())))
    elif isinstance(feature_matrix_or_records, list):
        total_samples = len(feature_matrix_or_records)
        for feat in reference_distributions.keys():
            col_data[feat] = []
        for record in feature_matrix_or_records:
            if isinstance(record, dict):
                for feat in reference_distributions.keys():
                    col_data[feat].append(record.get(feat))

    results: dict[str, FeatureDriftResult] = {}
    valid_psis: list[float] = []
    has_insufficient = False
    has_warning = False
    has_high = False

    for feat_name, ref in reference_distributions.items():
        vals = col_data.get(feat_name, [])
        res = calculate_single_feature_psi(
            values=vals,
            reference=ref,
            min_sample_size=min_sample_size,
            warning_threshold=warning_threshold,
            high_threshold=high_threshold,
        )
        results[feat_name] = res

        if res.status == DriftStatus.INSUFFICIENT_SAMPLE_SIZE:
            has_insufficient = True
        elif res.status == DriftStatus.HIGH_DRIFT:
            has_high = True
            if res.psi is not None:
                valid_psis.append(res.psi)
        elif res.status == DriftStatus.WARNING:
            has_warning = True
            if res.psi is not None:
                valid_psis.append(res.psi)
        elif res.status == DriftStatus.NO_DRIFT:
            if res.psi is not None:
                valid_psis.append(res.psi)

    # Determine aggregate severity: maximum status across all features
    if has_high:
        overall_status = DriftStatus.HIGH_DRIFT
    elif has_warning:
        overall_status = DriftStatus.WARNING
    elif has_insufficient:
        overall_status = DriftStatus.INSUFFICIENT_SAMPLE_SIZE
    else:
        overall_status = DriftStatus.NO_DRIFT

    max_psi_feature = None
    max_psi_val = None
    mean_psi_val = None

    if valid_psis:
        # Find feature with maximum PSI
        best_feat = max(
            (f for f in results.values() if f.psi is not None),
            key=lambda x: x.psi or 0.0,
            default=None,
        )
        if best_feat:
            max_psi_feature = best_feat.feature_name
            max_psi_val = best_feat.psi
        mean_psi_val = sum(valid_psis) / len(valid_psis)

    alert_raised = overall_status in (DriftStatus.WARNING, DriftStatus.HIGH_DRIFT)

    if alert_raised:
        logger.warning(
            "[ML Drift Alert] Model '%s' (v%s) exhibited %s feature drift! Max PSI: %s on feature '%s'. Advisory only.",
            model_name,
            model_version,
            overall_status.value,
            f"{max_psi_val:.4f}" if max_psi_val is not None else "None",
            max_psi_feature,
        )

    return ModelDriftReport(
        model_name=model_name,
        model_version=model_version,
        reference_version=ref_version,
        sample_count=total_samples,
        status=overall_status,
        max_psi_feature=max_psi_feature,
        max_psi_value=max_psi_val,
        mean_psi_value=mean_psi_val,
        features=results,
        alert_raised=alert_raised,
    )


# ---------------------------------------------------------------------------
# Pre-computed Reference Distributions Loader
# ---------------------------------------------------------------------------

def load_reference_distributions_from_file(
    path_or_model_name: str | Path,
    signed_manifest: Any | None = None,
) -> dict[str, FeatureReferenceDistribution]:
    """
    Loads and cryptographically verifies pre-computed reference distributions for a model from disk.
    Accepts a Path or a model name (e.g., 'at_risk', 'weak_topic').
    When signed_manifest is provided, verifies that the reference distribution SHA-256 matches
    the manifest digest and conforms to model identity and feature schema.
    """
    import json

    from app.ml.manifest import (
        ModelIntegrityError,
        load_verified_manifest_from_file,
        verify_reference_distribution,
    )

    candidate = Path(path_or_model_name)
    resolved_path: Path | None = None

    if candidate.is_file():
        resolved_path = candidate
    else:
        filename = f"{candidate.stem if candidate.suffix else candidate.name}_reference_distribution.json"
        models_dir = Path(__file__).resolve().parent / "models"
        search_paths = [
            models_dir / filename,
            Path.cwd() / "app" / "ml" / "models" / filename,
            Path.cwd() / "backend" / "app" / "ml" / "models" / filename,
            Path.cwd() / filename,
        ]
        for sp in search_paths:
            if sp.is_file():
                resolved_path = sp
                break

    if not resolved_path or not resolved_path.is_file():
        raise FileNotFoundError(f"Reference distribution file not found for: {path_or_model_name}")

    # Cryptographic binding check: verify against signed manifest
    manifest_to_check = signed_manifest
    if manifest_to_check is None and isinstance(path_or_model_name, str):
        # Attempt to load manifest for model_name
        manifest_filename = f"{path_or_model_name}_manifest.json"
        models_dir = Path(__file__).resolve().parent / "models"
        cand_man = models_dir / manifest_filename
        if cand_man.is_file():
            try:
                manifest_to_check = load_verified_manifest_from_file(cand_man)
            except Exception as exc:
                logger.debug("[Drift] Could not load manifest '%s': %s", cand_man, exc)

    if manifest_to_check is not None:
        # Strict digest and feature alignment verification
        verify_reference_distribution(manifest_to_check, resolved_path)
    elif getattr(settings, "ENVIRONMENT", "development") == "production":
        raise ModelIntegrityError(
            f"Reference distribution at '{resolved_path.name}' lacks verified signed manifest binding in production."
        )

    data = json.loads(resolved_path.read_text(encoding="utf-8"))
    model_version = data.get("model_version", "1.0.0")
    ref_version = data.get("reference_version", "1.0.0")
    sample_size = data.get("sample_size", 1000)
    raw_features = data.get("features", {})

    distributions: dict[str, FeatureReferenceDistribution] = {}
    for feat_name, spec in raw_features.items():
        distributions[feat_name] = FeatureReferenceDistribution(
            feature_name=feat_name,
            bin_edges=spec["bin_edges"],
            expected_proportions=spec["expected_proportions"],
            reference_version=ref_version,
            model_version=model_version,
            sample_size=sample_size,
        )
    return distributions


def check_model_feature_drift(
    model_name: str,
    observations: list[dict[str, Any]] | dict[str, list[Any]],
    min_sample_size: int | None = None,
    warning_threshold: float | None = None,
    high_threshold: float | None = None,
    signed_manifest: Any | None = None,
) -> ModelDriftReport:
    """
    Convenience function that loads reference distributions and evaluates feature drift.
    Advisory only: produces structured diagnostics and logs, does not alter runtime models.
    """
    ref_dists = load_reference_distributions_from_file(model_name, signed_manifest=signed_manifest)
    return evaluate_model_feature_drift(
        model_name=model_name,
        feature_matrix_or_records=observations,
        reference_distributions=ref_dists,
        min_sample_size=min_sample_size,
        warning_threshold=warning_threshold,
        high_threshold=high_threshold,
    )
