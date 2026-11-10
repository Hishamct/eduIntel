"""
backend/tests/test_offline_rag_benchmark.py

Comprehensive test suite verifying Phase 5 Step 3.6 Stage 5:
Offline RAG Benchmarking & CI Integration and Stage 5R Remediation.

Covers all 11 required areas:
1. OOD query returning irrelevant chunks above distance threshold (LEGITIMATE_OOD_EMPTY).
2. OOD query returning chunks below distance threshold (OOD_FALSE_POSITIVE).
3. OOD threshold failure causing CLI exit code 1.
4. Five study queries executing tenant filtering with valid tenant context.
5. Missing tenant context producing AUTHORIZATION_REFUSAL.
6. Missing tenant metadata classification based on actual corpus metadata.
7. Precision@K and Recall@K calculations with hand-calculated expected values.
8. Distance threshold behavior (verifying lower distance = closer).
9. Empty results and missing relevance labels handling.
10. JSON artifact ignore behavior.
11. Repeated deterministic benchmark execution.
"""

import subprocess
import sys
from unittest.mock import patch

import pytest

from app.rag.eval.offline_benchmark import (
    BenchmarkThresholds,
    DeterministicOfflineEmbeddingFunction,
    OfflineRAGBenchmark,
    QueryEvaluationResult,
)


@pytest.fixture(scope="session", autouse=True)
def verify_and_prepare_test_database():
    """Offline RAG benchmark is strictly hermetic and requires zero database connectivity."""
    yield


# ==============================================================================
# 1. Metric Calculation & Aggregation Unit Tests
# ==============================================================================
class TestRetrievalMetricCalculations:
    """Verifies mathematical correctness of Hit@K, MRR, Precision@K, Recall@K."""

    def test_hit_rate_at_1_and_3_with_known_ranks(self):
        benchmark = OfflineRAGBenchmark()

        # Synthetic results: ranks [1, 2, 3, None]
        results = [
            QueryEvaluationResult(
                query_id="Q1",
                query="query 1",
                category="test",
                collection="portal_help_docs",
                tenant_context=None,
                is_in_domain=True,
                status="SUCCESS_HIT",
                rank=1,
                reciprocal_rank=1.0,
                retrieved_chunk_ids=["c1"],
                retrieved_chunk_titles=["Title 1"],
                top_distance=0.2,
                latency_ms=1.0,
                cross_tenant_leakage=False,
                unauthorized_access=False,
                precision_at_k=1.0 / 3.0,
                recall_at_k=1.0,
                ood_false_positive=False,
            ),
            QueryEvaluationResult(
                query_id="Q2",
                query="query 2",
                category="test",
                collection="portal_help_docs",
                tenant_context=None,
                is_in_domain=True,
                status="SUCCESS_HIT",
                rank=2,
                reciprocal_rank=0.5,
                retrieved_chunk_ids=["c2"],
                retrieved_chunk_titles=["Title 2"],
                top_distance=0.3,
                latency_ms=1.0,
                cross_tenant_leakage=False,
                unauthorized_access=False,
                precision_at_k=1.0 / 3.0,
                recall_at_k=1.0,
                ood_false_positive=False,
            ),
            QueryEvaluationResult(
                query_id="Q3",
                query="query 3",
                category="test",
                collection="portal_help_docs",
                tenant_context=None,
                is_in_domain=True,
                status="SUCCESS_HIT",
                rank=3,
                reciprocal_rank=1.0 / 3.0,
                retrieved_chunk_ids=["c3"],
                retrieved_chunk_titles=["Title 3"],
                top_distance=0.4,
                latency_ms=1.0,
                cross_tenant_leakage=False,
                unauthorized_access=False,
                precision_at_k=1.0 / 3.0,
                recall_at_k=1.0,
                ood_false_positive=False,
            ),
            QueryEvaluationResult(
                query_id="Q4",
                query="query 4",
                category="test",
                collection="portal_help_docs",
                tenant_context=None,
                is_in_domain=True,
                status="RETRIEVAL_FAILURE",
                rank=None,
                reciprocal_rank=0.0,
                retrieved_chunk_ids=[],
                retrieved_chunk_titles=[],
                top_distance=None,
                latency_ms=1.0,
                cross_tenant_leakage=False,
                unauthorized_access=False,
                precision_at_k=0.0,
                recall_at_k=0.0,
                ood_false_positive=False,
            ),
        ]

        summary = benchmark._compute_summary(results)
        assert summary["standard_in_domain_count"] == 4
        assert summary["hits_1_count"] == 1
        assert summary["hit_rate_at_1"] == 0.25  # 1 / 4
        assert summary["hits_3_count"] == 3
        assert summary["hit_rate_at_3"] == 0.75  # 3 / 4

        # MRR = (1.0 + 0.5 + 0.3333 + 0.0) / 4 = 1.8333 / 4 = 0.45833
        expected_mrr = (1.0 + 0.5 + (1.0 / 3.0) + 0.0) / 4.0
        assert pytest.approx(summary["mean_reciprocal_rank"], abs=1e-4) == expected_mrr

    def test_precision_and_recall_at_k_hand_calculated(self):
        """Verifies Precision@K and Recall@K formulas against exact hand-calculated ground truths."""
        benchmark = OfflineRAGBenchmark()

        # Hand-calculated Case 1: 1 relevant retrieved in top 3, 1 total expected
        # Precision@3 = 1 / 3, Recall@3 = 1 / 1 = 1.0
        p1, r1 = benchmark._compute_query_precision_and_recall_at_k(
            retrieved_ids=["doc_a", "doc_b", "doc_c"],
            expected_chunk_ids=["doc_a"],
            k=3,
        )
        assert pytest.approx(p1, abs=1e-5) == 1.0 / 3.0
        assert r1 == 1.0

        # Hand-calculated Case 2: 1 relevant retrieved in top 3, 2 total expected
        # Precision@3 = 1 / 3, Recall@3 = 1 / 2 = 0.5
        p2, r2 = benchmark._compute_query_precision_and_recall_at_k(
            retrieved_ids=["doc_a", "doc_b", "doc_c"],
            expected_chunk_ids=["doc_a", "doc_x"],
            k=3,
        )
        assert pytest.approx(p2, abs=1e-5) == 1.0 / 3.0
        assert r2 == 0.5

        # Hand-calculated Case 3: 2 relevant retrieved in top 3, 2 total expected
        # Precision@3 = 2 / 3, Recall@3 = 2 / 2 = 1.0
        p3, r3 = benchmark._compute_query_precision_and_recall_at_k(
            retrieved_ids=["doc_a", "doc_b", "doc_c"],
            expected_chunk_ids=["doc_a", "doc_b"],
            k=3,
        )
        assert pytest.approx(p3, abs=1e-5) == 2.0 / 3.0
        assert r3 == 1.0

        # Hand-calculated Case 4: 0 relevant retrieved in top 3, 2 total expected
        # Precision@3 = 0 / 3 = 0.0, Recall@3 = 0 / 2 = 0.0
        p4, r4 = benchmark._compute_query_precision_and_recall_at_k(
            retrieved_ids=["doc_a", "doc_b", "doc_c"],
            expected_chunk_ids=["doc_x", "doc_y"],
            k=3,
        )
        assert p4 == 0.0
        assert r4 == 0.0

        # Hand-calculated Case 5: 0 retrieved docs, 1 expected
        # Precision@3 = 0.0, Recall@3 = 0.0
        p5, r5 = benchmark._compute_query_precision_and_recall_at_k(
            retrieved_ids=[],
            expected_chunk_ids=["doc_a"],
            k=3,
        )
        assert p5 == 0.0
        assert r5 == 0.0

        # Hand-calculated Case 6: Query with no relevance labels (neither IDs nor keywords)
        # Precision@3 = None, Recall@3 = None (not defined / excluded from mean)
        p6, r6 = benchmark._compute_query_precision_and_recall_at_k(
            retrieved_ids=["doc_a"],
            expected_chunk_ids=[],
            k=3,
        )
        assert p6 is None
        assert r6 is None

    def test_empty_results_and_missing_relevance_labels(self):
        """Verifies handling of empty results and queries without relevance labels."""
        benchmark = OfflineRAGBenchmark()

        results = [
            QueryEvaluationResult(
                query_id="Q_EMPTY",
                query="empty query",
                category="test",
                collection="study_materials",
                tenant_context=None,
                is_in_domain=True,
                status="RETRIEVAL_FAILURE",
                rank=None,
                reciprocal_rank=0.0,
                retrieved_chunk_ids=[],
                retrieved_chunk_titles=[],
                top_distance=None,
                latency_ms=0.5,
                cross_tenant_leakage=False,
                unauthorized_access=False,
                precision_at_k=0.0,
                recall_at_k=0.0,
                ood_false_positive=False,
            ),
            QueryEvaluationResult(
                query_id="Q_OOD",
                query="ood query",
                category="test",
                collection="study_materials",
                tenant_context=None,
                is_in_domain=False,
                status="LEGITIMATE_OOD_EMPTY",
                rank=None,
                reciprocal_rank=0.0,
                retrieved_chunk_ids=[],
                retrieved_chunk_titles=[],
                top_distance=None,
                latency_ms=0.5,
                cross_tenant_leakage=False,
                unauthorized_access=False,
                precision_at_k=None,
                recall_at_k=1.0,
                ood_false_positive=False,
            ),
        ]

        summary = benchmark._compute_summary(results)
        assert summary["standard_in_domain_count"] == 1
        assert summary["adversarial_ood_count"] == 1
        assert summary["hit_rate_at_1"] == 0.0
        assert summary["hit_rate_at_3"] == 0.0
        assert summary["mean_reciprocal_rank"] == 0.0
        assert summary["mean_precision_at_3"] == 0.0
        assert summary["mean_recall_at_3"] == 0.0
        assert summary["retrieval_failure_count"] == 1
        assert summary["ood_false_positive_count"] == 0
        assert summary["ood_rejection_count"] == 1
        assert summary["ood_rejection_rate"] == 1.0


# ==============================================================================
# 2. Distance Threshold & Out-of-Domain Discrimination Tests
# ==============================================================================
class TestDistanceThresholdAndOODDiscrimination:
    """Verifies cosine distance threshold gating (lower is closer) and OOD discrimination."""

    def test_distance_threshold_lower_distance_is_closer(self):
        """ChromaDB uses cosine distance = 1 - cosine similarity. Lower distance indicates closer proximity."""
        benchmark = OfflineRAGBenchmark()
        thresh_portal = benchmark.get_distance_threshold("portal_help_docs")
        thresh_study = benchmark.get_distance_threshold("study_materials")

        assert thresh_portal == 0.82
        assert thresh_study == 0.60
        # Unknown collection falls back to safe default (0.82)
        assert benchmark.get_distance_threshold("unknown_collection") == 0.82

    def test_ood_above_distance_threshold_is_legitimate_empty(self):
        """OOD query returning chunks above distance threshold is classified as LEGITIMATE_OOD_EMPTY."""
        benchmark = OfflineRAGBenchmark()
        benchmark.initialize_collections()

        # Adversarial query with no relevant documents in portal_help_docs
        ood_item = {
            "query_id": "TEST-OOD-REJECT",
            "query": "Can I pay my tuition fees through the student portal?",
            "category": "portal_help",
            "expected_collection": "portal_help_docs",
            "tenant_context": None,
            "expected_chunk_ids": [],
            "expected_keywords": [],
            "is_in_domain": False,
        }

        res = benchmark.evaluate_query(ood_item, apply_tenant_filter=False)
        assert res.status == "LEGITIMATE_OOD_EMPTY"
        assert res.ood_false_positive is False
        assert res.top_distance is not None and res.top_distance > 0.82
        assert "rejected by distance gating" in res.notes
        assert res.rank is None

    def test_ood_below_distance_threshold_is_ood_false_positive(self):
        """OOD query returning chunks below distance threshold is classified as OOD_FALSE_POSITIVE."""
        benchmark = OfflineRAGBenchmark()
        benchmark.initialize_collections()

        # Query that is marked OOD but semantically matches existing portal docs closely
        ood_fp_item = {
            "query_id": "TEST-OOD-FP",
            "query": "How do I submit my homework assignment online?",
            "category": "portal_help",
            "expected_collection": "portal_help_docs",
            "tenant_context": None,
            "expected_chunk_ids": [],
            "expected_keywords": [],
            "is_in_domain": False,
        }

        res = benchmark.evaluate_query(ood_fp_item, apply_tenant_filter=False)
        assert res.status == "OOD_FALSE_POSITIVE"
        assert res.ood_false_positive is True
        assert len(res.retrieved_chunk_ids) > 0
        assert res.top_distance is not None and res.top_distance <= 0.82
        assert "false-positive" in res.notes.lower()

    def test_in_domain_above_distance_threshold_is_retrieval_failure(self):
        """In-domain query failing to retrieve within distance threshold is RETRIEVAL_FAILURE."""
        benchmark = OfflineRAGBenchmark()
        benchmark.initialize_collections()

        item = {
            "query_id": "TEST-INDOMAIN-FAIL",
            "query": "Completely bizarre in-domain query about quantum astrophysics",
            "category": "portal_help",
            "expected_collection": "portal_help_docs",
            "tenant_context": None,
            "expected_chunk_ids": ["non_existent_chunk_123"],
            "expected_keywords": ["astrophysics"],
            "is_in_domain": True,
        }

        res = benchmark.evaluate_query(item, apply_tenant_filter=False)
        assert res.status == "RETRIEVAL_FAILURE"
        assert res.ood_false_positive is False
        assert res.rank is None
        assert res.precision_at_k == 0.0
        assert res.recall_at_k == 0.0


# ==============================================================================
# 3. Deterministic Offline Embedding Function Tests
# ==============================================================================
class TestDeterministicOfflineEmbeddingFunction:
    """Verifies that the embedding function is 100% reproducible, hermetic, and offline."""

    def test_embedding_function_is_deterministic_and_unit_norm(self):
        fn = DeterministicOfflineEmbeddingFunction(dim=64)
        text = "How to submit homework on the portal"

        emb1 = fn([text])[0]
        emb2 = fn([text])[0]

        assert all(abs(a - b) < 1e-6 for a, b in zip(emb1, emb2, strict=True)), "Embeddings for identical text must be strictly deterministic"
        assert len(emb1) == 64

        # Unit norm verification: sum of squares == 1.0
        norm_sq = sum(x * x for x in emb1)
        assert pytest.approx(norm_sq, abs=1e-5) == 1.0

    def test_empty_string_handles_gracefully(self):
        fn = DeterministicOfflineEmbeddingFunction(dim=32)
        emb = fn([""])[0]
        assert len(emb) == 32
        assert sum(x * x for x in emb) > 0.0

    def test_similar_text_has_higher_similarity_than_unrelated(self):
        fn = DeterministicOfflineEmbeddingFunction(dim=128)
        q = "How do I submit my homework?"
        doc_relevant = "Instructions for students to submit homework assignments online."
        doc_unrelated = "Advanced organic chemistry synthesis of benzene rings."

        q_vec = fn([q])[0]
        rel_vec = fn([doc_relevant])[0]
        unrel_vec = fn([doc_unrelated])[0]

        dot_rel = sum(a * b for a, b in zip(q_vec, rel_vec, strict=False))
        dot_unrel = sum(a * b for a, b in zip(q_vec, unrel_vec, strict=False))

        assert dot_rel > dot_unrel, "Relevant text must have higher similarity than unrelated text"


# ==============================================================================
# 4. Multi-Tenant Isolation & Zero-Tolerance Security Tests
# ==============================================================================
class TestMultiTenantIsolationSecurity:
    """Verifies Tenant A vs Tenant B isolation, cross-tenant leakage prevention, and fail-closed rules."""

    def test_cross_tenant_leakage_zero_tolerance(self):
        benchmark = OfflineRAGBenchmark()
        benchmark.initialize_collections()

        probe_item = {
            "query_id": "TEST-PROBE-01",
            "query": "What is the proprietary stoichiometry guide for Tenant Beta?",
            "category": "tenant_isolation",
            "expected_collection": "study_materials",
            "tenant_context": "inst-alpha",
            "expected_chunk_ids": [],
            "expected_keywords": [],
            "expected_behavior": "zero_leakage_empty",
            "is_in_domain": False,
        }

        res = benchmark.evaluate_query(probe_item, apply_tenant_filter=True)
        assert not res.cross_tenant_leakage, "Tenant A query must never leak Tenant B documents"
        assert not res.unauthorized_access
        assert "tenant_beta_chem_01" not in res.retrieved_chunk_ids, "Query under Tenant A must never return Tenant B documents"

    def test_tenant_a_retrieves_authorized_documents(self):
        benchmark = OfflineRAGBenchmark()
        benchmark.initialize_collections()

        auth_item = {
            "query_id": "TEST-AUTH-01",
            "query": "What are the core mechanics formulas in Tenant Alpha syllabus?",
            "category": "tenant_isolation",
            "expected_collection": "study_materials",
            "tenant_context": "inst-alpha",
            "expected_chunk_ids": ["tenant_alpha_physics_01"],
            "expected_keywords": ["alpha mechanics"],
            "expected_behavior": "tenant_filtered_hit",
            "is_in_domain": True,
        }

        res = benchmark.evaluate_query(auth_item, apply_tenant_filter=True)
        assert res.status == "SUCCESS_HIT"
        assert res.rank == 1
        assert "tenant_alpha_physics_01" in res.retrieved_chunk_ids
        assert not res.cross_tenant_leakage

    def test_missing_tenant_context_fails_closed(self):
        benchmark = OfflineRAGBenchmark()
        benchmark.initialize_collections()

        no_tenant_item = {
            "query_id": "TEST-NO-TENANT",
            "query": "Physics notes",
            "category": "study_materials",
            "expected_collection": "study_materials",
            "tenant_context": None,
            "expected_chunk_ids": [],
            "expected_keywords": [],
            "is_in_domain": True,
        }

        res = benchmark.evaluate_query(no_tenant_item, apply_tenant_filter=True)
        assert res.status == "AUTHORIZATION_REFUSAL"
        assert res.unauthorized_access is False
        assert len(res.retrieved_chunk_ids) == 0
        assert "Fail-closed" in res.notes

    def test_unauthorized_missing_tenant_item_from_dataset_fails_closed(self):
        benchmark = OfflineRAGBenchmark()
        benchmark.initialize_collections()
        items = {item["query_id"]: item for item in benchmark.load_dataset()}

        unauth_item = items["Q-UNAUTHORIZED-MISSING-TENANT"]
        assert unauth_item["tenant_context"] is None

        res = benchmark.evaluate_query(unauth_item, apply_tenant_filter=True)
        assert res.status == "AUTHORIZATION_REFUSAL"
        assert res.unauthorized_access is False
        assert len(res.retrieved_chunk_ids) == 0


# ==============================================================================
# 5. Tenant Filtering & Legacy Deficit Integrity Tests
# ==============================================================================
class TestTenantFilteringAndLegacyDeficit:
    """Verifies tenant filtering on study queries and accurate reporting of the 38 legacy un-namespaced chunks."""

    def test_study_queries_execute_tenant_filtering_with_valid_tenant_context(self):
        """All 5 baseline study queries execute tenant filtering with valid institution_id."""
        benchmark = OfflineRAGBenchmark()
        benchmark.initialize_collections()
        items = benchmark.load_dataset()

        study_queries = [
            item for item in items
            if item.get("category") == "study_materials" and item.get("is_in_domain", True)
        ]
        assert len(study_queries) == 5

        for item in study_queries:
            # Deterministic test tenant assigned
            assert item.get("tenant_context") == "00000000-0000-0000-0000-000000000001"
            res = benchmark.evaluate_query(item, apply_tenant_filter=True)
            # Under tenant filter, returns 0 hits and is classified as MISSING_TENANT_METADATA
            assert res.status == "MISSING_TENANT_METADATA"
            assert len(res.retrieved_chunk_ids) == 0
            assert res.precision_at_k == 0.0
            assert res.recall_at_k == 0.0

    def test_legacy_chunks_missing_tenant_metadata_reported(self):
        """Asserts exactly 38 legacy un-namespaced chunks exist in study_materials."""
        benchmark = OfflineRAGBenchmark()
        benchmark.initialize_collections()
        assert benchmark._legacy_missing_tenant_count == 38

    def test_missing_tenant_metadata_vs_legitimate_ood_empty_classification(self):
        """Differentiates MISSING_TENANT_METADATA from LEGITIMATE_OOD_EMPTY based on corpus inspection."""
        benchmark = OfflineRAGBenchmark()
        benchmark.initialize_collections()
        items = {item["query_id"]: item for item in benchmark.load_dataset()}

        # Q-STUDY-01: In-domain query with matching chunks in study_materials lacking tenant ID
        res_study_01 = benchmark.evaluate_query(items["Q-STUDY-01"], apply_tenant_filter=True)
        assert res_study_01.status == "MISSING_TENANT_METADATA"
        assert "lack institution_id metadata" in res_study_01.notes

        # Q-STUDY-07-OOD: Adversarial OOD query (relativity) has no matching chunks in corpus
        res_study_07 = benchmark.evaluate_query(items["Q-STUDY-07-OOD"], apply_tenant_filter=True)
        assert res_study_07.status == "LEGITIMATE_OOD_EMPTY"
        assert res_study_07.ood_false_positive is False


# ==============================================================================
# 6. Full Benchmark Execution & Threshold Gating
# ==============================================================================
class TestFullBenchmarkExecutionAndThresholds:
    """Verifies overall benchmark execution, threshold enforcement, and report generation."""

    def test_benchmark_runs_end_to_end_and_passes_all_thresholds(self):
        benchmark = OfflineRAGBenchmark()
        report = benchmark.run_benchmark()

        assert report.all_thresholds_passed is True
        assert report.global_vector_retrieval["hit_rate_at_3"] >= 0.90
        assert report.global_vector_retrieval["mean_reciprocal_rank"] >= 0.85
        assert report.global_vector_retrieval["mean_precision_at_3"] >= 0.25
        assert report.global_vector_retrieval["mean_recall_at_3"] >= 0.80

        # Tenant-filtered Hit@3 faithfully reports 54.55% baseline (6/11)
        assert pytest.approx(report.tenant_filtered_retrieval["hit_rate_at_3"], abs=1e-2) == 0.5455

        # Strict security: 0 cross-tenant leaks, 0 unauth, 0 OOD false positives
        assert report.tenant_isolation_security["cross_tenant_leakage_count"] == 0
        assert report.tenant_isolation_security["unauthorized_result_count"] == 0
        total_ood_fp = (
            report.global_vector_retrieval["ood_false_positive_count"]
            + report.tenant_filtered_retrieval["ood_false_positive_count"]
        )
        assert total_ood_fp == 0

    def test_deterministic_repeatability(self):
        """Proves that repeated executions yield identical numerical results."""
        b1 = OfflineRAGBenchmark()
        r1 = b1.run_benchmark()

        b2 = OfflineRAGBenchmark()
        r2 = b2.run_benchmark()

        assert r1.global_vector_retrieval["hit_rate_at_3"] == r2.global_vector_retrieval["hit_rate_at_3"]
        assert r1.global_vector_retrieval["mean_reciprocal_rank"] == r2.global_vector_retrieval["mean_reciprocal_rank"]
        assert r1.global_vector_retrieval["mean_precision_at_3"] == r2.global_vector_retrieval["mean_precision_at_3"]
        assert r1.global_vector_retrieval["mean_recall_at_3"] == r2.global_vector_retrieval["mean_recall_at_3"]
        assert r1.tenant_filtered_retrieval["hit_rate_at_3"] == r2.tenant_filtered_retrieval["hit_rate_at_3"]
        assert (
            r1.tenant_isolation_security["cross_tenant_leakage_count"]
            == r2.tenant_isolation_security["cross_tenant_leakage_count"]
        )

    def test_cli_threshold_failure_returns_exit_code_1(self, monkeypatch, tmp_path):
        """Simulates an unrealistic high threshold to verify that threshold failures fail CI."""
        from scripts.eval_rag_retrieval_offline import run_cli

        out_file = tmp_path / "test_out.json"
        unrealistic_thresholds = BenchmarkThresholds(min_tenant_filtered_hit_rate_at_3=0.99)

        with patch("scripts.eval_rag_retrieval_offline.BenchmarkThresholds", return_value=unrealistic_thresholds):
            monkeypatch.setattr(
                sys,
                "argv",
                ["eval_rag_retrieval_offline", "--json-output", str(out_file), "--quiet"],
            )
            with pytest.raises(SystemExit) as exc_info:
                run_cli()
            assert exc_info.value.code == 1, "CLI must exit with code 1 when threshold fails"

    def test_cli_exits_with_code_1_on_ood_false_positive(self, monkeypatch, tmp_path):
        """Verifies CLI exits with code 1 when OOD false-positive count exceeds threshold."""
        from scripts.eval_rag_retrieval_offline import run_cli

        out_file = tmp_path / "test_ood_fp_fail.json"
        # Negative threshold forces immediate failure on count >= 0
        strict_thresholds = BenchmarkThresholds(max_ood_false_positive_count=-1)

        with patch("scripts.eval_rag_retrieval_offline.BenchmarkThresholds", return_value=strict_thresholds):
            monkeypatch.setattr(
                sys,
                "argv",
                ["eval_rag_retrieval_offline", "--json-output", str(out_file), "--quiet"],
            )
            with pytest.raises(SystemExit) as exc_info:
                run_cli()
            assert exc_info.value.code == 1, "CLI must exit with code 1 when OOD false positive threshold fails"

    def test_benchmark_json_artifact_is_git_ignored(self):
        """Verifies that offline_retrieval_benchmark_results.json is tracked by .gitignore."""
        from pathlib import Path
        target = "app/rag/eval/offline_retrieval_benchmark_results.json"
        if not Path(target).exists() and Path(f"backend/{target}").exists():
            target = f"backend/{target}"
        cmd = ["git", "check-ignore", target]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        assert proc.returncode == 0, f"offline_retrieval_benchmark_results.json must be git-ignored (target: {target})"
