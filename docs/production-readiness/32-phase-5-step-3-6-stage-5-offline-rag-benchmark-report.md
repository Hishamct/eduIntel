# EduIntel — Phase 5 Step 3.6 Stage 5 / Stage 5R Implementation Report
## Offline RAG Benchmarking & CI Integration

**Parent Roadmap:** Phase 05 – Step 3 (Sub-Step 3.6: LangGraph Agent Hardening)  
**Parent Specification:** `docs/production-readiness/14-phase-5-ai-safety-and-governance-plan.md` (§3, Item 7)  
**Baseline Reference:** `docs/production-readiness/15-phase-5-step-0-baseline-report.md`  
**Audit Reference:** `Hisham-workspace/05-ai-and-ml/step-3-6-stage-5-final-acceptance-audit.md`  
**Date:** 2026-11-10  
**Branch:** `develop/production-readiness`  
**Status:** COMPLETE — Stage 5R Remediated (Awaiting Independent Final Acceptance Audit)

---

## 1. Executive Summary

Stage 5 establishes a deterministic, reproducible, hermetic offline RAG retrieval evaluation harness integrated directly into EduIntel's continuous integration (CI) pipeline. 

Following the initial Stage 5 implementation, an independent acceptance audit identified four specific correctness defects (`AUDIT-3.6-S5-01` through `AUDIT-3.6-S5-04`). Stage 5R addresses all four findings without weakening security invariants, altering historical baselines, or modifying protected Stage 1–4R files.

### 1.1 Remediation Summary (Stage 5R)
1. **AUDIT-3.6-S5-01 (OOD False-Positive Detection):**
   - Implemented calibrated distance threshold gating for OOD queries: `portal_help_docs` ($\tau = 0.82$) and `study_materials` ($\tau = 0.60$).
   - OOD queries returning results with distance $\le \tau$ are classified as `OOD_FALSE_POSITIVE`, incrementing `ood_false_positive_count`.
   - Added `max_ood_false_positive_count: int = 0` to `BenchmarkThresholds`. If any OOD query produces a false-positive retrieval, threshold gating immediately fails with CI exit code 1.
2. **AUDIT-3.6-S5-02 (Tenant Metadata Baseline Masking):**
   - Assigned deterministic test tenant ID (`00000000-0000-0000-0000-000000000001`) to baseline study queries in `offline_eval_dataset.json`.
   - Populated exact `expected_chunk_ids` using real UUIDs from `backend/chroma_data`.
   - Executed actual ChromaDB tenant queries with `where={"institution_id": ...}`.
   - Added corpus metadata inspection: when a query yields 0 results under tenant filtering, `_is_corpus_missing_tenant_metadata()` confirms that the expected chunks exist in the corpus and lack `institution_id` before classifying as `MISSING_TENANT_METADATA`.
   - Preserved all 38 legacy un-namespaced chunks and the exact historical 54.55% (6/11) tenant-filtered Hit@3 baseline without backfilling or schema alterations.
3. **AUDIT-3.6-S5-03 (Metric and Documentation Correctness):**
   - Documented ChromaDB cosine distance semantics ($d = 1 - \text{cosine\_similarity}$, lower distance = closer proximity).
   - Formally implemented and documented `Precision@K` and `Recall@K` with explicit denominators and graceful handling of empty retrieval sets and queries lacking relevance labels.
   - Added `min_global_precision_at_3: float = 0.25` and `min_global_recall_at_3: float = 0.80` to `BenchmarkThresholds`.
   - Added hand-calculated ground-truth unit tests verifying exact mathematical formulations.
4. **AUDIT-3.6-S5-04 (Benchmark Artifact Pollution):**
   - Added `backend/app/rag/eval/offline_retrieval_benchmark_results.json` to `.gitignore`.
   - Verified via `git check-ignore` and added automated test assertion.

---

## 2. Architecture & Design Principles

```
+----------------------------------------------------------------------------------------------------+
|                                    OFFLINE RAG BENCHMARK ARCHITECTURE                              |
+----------------------------------------------------------------------------------------------------+
                                                  │
                        ┌─────────────────────────┴─────────────────────────┐
                        ▼                                                   ▼
         Hermetic Embedding Engine                             Offline Evaluation Dataset
     [DeterministicOfflineEmbeddingFunction]                 [offline_eval_dataset.json (20 cases)]
     - Token feature hashing (SHA-256)                       - 11 Standard In-Domain Queries
     - L2 unit-normalization (||v|| = 1.0)                  - 3 Adversarial Out-of-Domain (OOD)
     - Zero external dependencies / network                  - 2 Tenant-Authorized Queries
     - Chromadb EmbeddingFunction compliant                  - 2 Cross-Tenant Penetration Probes
                        │                                    - 1 Missing Tenant Auth Refusal Probe
                        │                                    - 1 Legacy Metadata Deficit Probe
                        ▼                                                   │
     Ephemeral ChromaDB In-Memory Instance                                  │
     [chromadb.EphemeralClient]                                             │
     - Real chroma_data chunks imported                                     │
       (38 legacy study_materials, 12 portal_help)                          │
     - Isolated synthetic tenant test fixtures                              │
       (Tenant Alpha, Tenant Beta)                                          │
                        │                                                   │
                        └─────────────────────────┬─────────────────────────┘
                                                  ▼
                                      Production Retrieval Pipeline
                                    [OfflineRAGBenchmark.evaluate_query]
                                                  │
                 ┌────────────────────────────────┴────────────────────────────────┐
                 ▼                                                                 ▼
      Guardrails & Auth Pre-Flight                                     ChromaDB Query Execution
      - default_guardrails_engine.evaluate_input()                     - collection.query(n_results=3)
      - Missing tenant context -> AUTHORIZATION_REFUSAL                - Distance calculation (d = 1 - sim)
      - Prompt injection -> GUARDRAIL_REJECTED                         - Threshold gating (portal: 0.82, study: 0.60)
                 │                                                                 │
                 └────────────────────────────────┬────────────────────────────────┘
                                                  ▼
                                    Fine-Grained Result Classifier
                     ┌────────────────────────────┼────────────────────────────┐
                     ▼                            ▼                            ▼
              SUCCESS_HIT               LEGITIMATE_OOD_EMPTY         MISSING_TENANT_METADATA
         (Relevant chunk <= thresh)   (OOD or query dist > thresh)  (Query valid, 0 hits due to
                                                                   legacy chunks lacking tenant)
                     │                            │                            │
                     └────────────────────────────┼────────────────────────────┘
                                                  ▼
                                      Security & Metric Engine
                     - Global Hit@1, Hit@3, MRR, Precision@3, Recall@3
                     - Tenant-Filtered Hit@1, Hit@3, MRR, Precision@3, Recall@3
                     - OOD False Positive Count (Strict Target: 0)
                     - Cross-Tenant Leakage Detection (Zero Tolerance: target = 0)
                     - Unauthorized Access Detection (Zero Tolerance: target = 0)
                     - Legacy Metadata Deficit Counter (38 chunks)
                     - Operational Latency (p50, p95, mean)
                                                  │
                                                  ▼
                                       Gating & Threshold Report
                     - scripts/eval_rag_retrieval_offline.py (CLI exit 0 / 1)
                     - app/rag/eval/offline_retrieval_benchmark_results.json
                     - .github/workflows/ci.yml Integration
```

### 2.1 Production vs. Offline Evaluation Parity

| Component / Layer | Production Route (`POST /rag/query`) | Stage 5R Offline Benchmark | Parity Notes |
| :--- | :--- | :--- | :--- |
| **Input Guardrails** | `default_guardrails_engine.evaluate_input()` in `retrieve_and_generate()` | Invoked directly on all queries via `default_guardrails_engine.evaluate_input()` | **100% Identical** |
| **Tenant Filter Construction** | `build_chroma_tenant_filter(institution_id)` for `study_materials` | Invoked directly via `build_chroma_tenant_filter(item["tenant_context"])` | **100% Identical** |
| **Fail-Closed Auth** | Returns 403 / empty if tenant context missing on tenant collections | Classifies as `AUTHORIZATION_REFUSAL`, blocking retrieval | **100% Identical** |
| **ChromaDB Query** | `collection.query(query_texts=[...], n_results=top_k, where=where_clause)` | `col.query(query_texts=[query], n_results=top_k, where=where_clause)` | **100% Identical** |
| **Distance Gating** | Filters out chunks with cosine distance $> \tau$ | Filters out chunks with distance $> \tau$ (`portal_help_docs`: 0.82, `study_materials`: 0.60) | **100% Identical** |
| **LLM Generation** | Calls Gemini 1.5 Flash to synthesize response | **Omitted by design** (retrieval-only evaluation; zero external LLM dependencies) | **Documented Scope** |
| **Embedding Engine** | `GeminiEmbeddingFunction` (models/text-embedding-004) | `DeterministicOfflineEmbeddingFunction` (CPU token feature hasher) | **Hermetic Test-Only** |

### 2.2 Distance Metric & Mathematical Formulation of Retrieval Metrics

#### ChromaDB Distance Metric
ChromaDB collections configured with `hnsw:space: "cosine"` return cosine distances defined as:
$$d(\vec{u}, \vec{v}) = 1 - \frac{\vec{u} \cdot \vec{v}}{\|\vec{u}\|_2 \|\vec{v}\|_2}$$
- $d = 0.0$: Identical vectors ($\text{cosine similarity} = 1.0$).
- $d = 1.0$: Orthogonal vectors ($\text{cosine similarity} = 0.0$).
- Lower distance denotes higher semantic relevance. Distance exceeding the calibrated threshold $\tau$ indicates an irrelevant result.

#### Precision@K and Recall@K Formulations
For each query $q$ with top-$K$ retrieved document set $\mathcal{R}_K(q)$ ($K = 3$) and ground-truth relevant document set $\mathcal{G}(q)$:
$$\text{Precision@}K(q) = \frac{|\mathcal{R}_K(q) \cap \mathcal{G}(q)|}{K}$$
$$\text{Recall@}K(q) = \frac{|\mathcal{R}_K(q) \cap \mathcal{G}(q)|}{|\mathcal{G}(q)|}$$
- **Empty Retrieval Set:** If $\mathcal{R}_K(q) = \emptyset$, $\text{Precision@}K = 0.0$ and $\text{Recall@}K = 0.0$.
- **Empty Relevance Set (OOD queries):** If $\mathcal{G}(q) = \emptyset$, $\text{Precision@}K = \text{None}$ and $\text{Recall@}K = \text{None}$. These queries are excluded from in-domain precision and recall means and evaluated under the separate OOD false-positive metric.
- **Mean Precision / Recall:** Computed as the arithmetic mean across all valid in-domain queries.

---

## 3. Dataset Composition & Fine-Grained Status Taxonomy

The evaluation dataset (`backend/app/rag/eval/offline_eval_dataset.json`) contains 20 structured test cases:

| Query ID | Category | Collection | Tenant Context | Ground Truth IDs | Expected Behavior | Description |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `Q-PORTAL-01`..`06` | `portal_help` | `portal_help_docs` | `None` (Global) | 1 specific chunk each | `portal_hit` | Homework, doubts, materials, dashboard, password |
| `Q-PORTAL-07-OOD` | `portal_help` | `portal_help_docs` | `None` | `[]` | `refusal_ood` | Tuition fees payment (OOD probe) |
| `Q-STUDY-01`..`05` | `study_materials` | `study_materials` | `00000000-0000-0000-0000-000000000001` | 2 specific chunks each | `study_hit` | Math, Trigonometry, Chemistry from real syllabus |
| `Q-STUDY-06-OOD` | `study_materials` | `study_materials` | `00000000-0000-0000-0000-000000000001` | `[]` | `refusal_ood` | Newton's second law (OOD probe) |
| `Q-STUDY-07-OOD` | `study_materials` | `study_materials` | `00000000-0000-0000-0000-000000000001` | `[]` | `refusal_ood` | Theory of relativity (OOD probe) |
| `Q-TENANT-A-AUTH` | `tenant_isolation` | `study_materials` | `inst-alpha` | `tenant_alpha_physics_01` | `tenant_filtered_hit` | Tenant Alpha querying authorized Alpha syllabus |
| `Q-TENANT-A-PROBE-B` | `tenant_isolation` | `study_materials` | `inst-alpha` | `[]` | `zero_leakage_empty` | Tenant Alpha probing Tenant Beta chemistry guide |
| `Q-TENANT-B-AUTH` | `tenant_isolation` | `study_materials` | `inst-beta` | `tenant_beta_chem_01` | `tenant_filtered_hit` | Tenant Beta querying authorized Beta syllabus |
| `Q-TENANT-B-PROBE-A` | `tenant_isolation` | `study_materials` | `inst-beta` | `[]` | `zero_leakage_empty` | Tenant Beta probing Tenant Alpha mechanics guide |
| `Q-UNAUTHORIZED-MISSING-TENANT` | `tenant_isolation` | `study_materials` | `None` | `[]` | `auth_refusal` | Unauthenticated/missing tenant context query |
| `Q-LEGACY-UNNAMESPACED-AUDIT` | `legacy_metadata_audit`| `study_materials` | `00000000-0000-0000-0000-000000000001` | `[]` | `legacy_missing_metadata_empty` | Legacy chunk deficit audit query |

### 3.1 Mutually Exclusive Result Taxonomies
1. **`SUCCESS_HIT`**: In-domain query retrieved an expected chunk within top-$K$ with distance $\le \tau$.
2. **`LEGITIMATE_OOD_EMPTY`**: OOD query returned 0 documents or all retrieved documents exceeded distance threshold $\tau$.
3. **`OOD_FALSE_POSITIVE`**: OOD query returned documents with distance $\le \tau$ (strictly prohibited; causes threshold failure).
4. **`MISSING_TENANT_METADATA`**: Query is valid and in-domain, but 0 documents are returned under tenant filtering because chunks exist in the corpus without `institution_id` metadata.
5. **`AUTHORIZATION_REFUSAL`**: Query targeted a tenant-partitioned collection without tenant context; retrieval was halted fail-closed before query execution.
6. **`RETRIEVAL_FAILURE`**: In-domain query failed to retrieve relevant documents despite them being present and authorized in the index.

---

## 4. Benchmark Execution Results & Metrics

Execution of `backend/scripts/eval_rag_retrieval_offline.py`:

```
===================================================================================================================
EDUINTEL AI — OFFLINE RAG RETRIEVAL BENCHMARK (HERMETIC CI HARNESS)
Phase 5 – Step 3.6 – Stage 5
Timestamp: 2026-11-10T19:10:38Z
Zero-Network Guarantee: ACTIVE (Using DeterministicOfflineEmbeddingFunction)
===================================================================================================================

1. GLOBAL (UNFILTERED) VECTOR RETRIEVAL:
   Standard Queries Evaluated:    11
   Adversarial (OOD) Queries:     3
   Hit Rate @ 1:                  90.91% (10/11)
   Hit Rate @ 3:                  100.00% (11/11)
   Mean Reciprocal Rank (MRR):    0.9545
   Mean Precision @ 3:            0.3939
   Mean Recall @ 3:               0.8636
   OOD False Positive Count:      0 (Strict Target: 0)
   OOD Rejection Rate:            100.00% (3/3)

2. TENANT-FILTERED RETRIEVAL (Historical Baseline Fidelity):
   Standard Queries Evaluated:    11
   Hit Rate @ 1:                  54.55% (6/11)
   Hit Rate @ 3:                  54.55% (6/11)
   Mean Reciprocal Rank (MRR):    0.5455
   Mean Precision @ 3:            0.1818
   Mean Recall @ 3:               0.5455
   Missing Tenant Metadata:       5 queries affected (38 legacy chunks in study_materials)
   OOD False Positive Count:      0 (Strict Target: 0)
   Note: Reflects documented baseline state where 38 study_materials chunks lack institution_id.

3. MULTI-TENANT ISOLATION & SECURITY:
   Isolation Tests Executed:      5
   Cross-Tenant Leakage Count:    0 (Strict Target: 0)
   Unauthorized Result Count:     0 (Strict Target: 0)
   Authorization Refusals:        1 (Fail-Closed Verified)
   Clean Isolation Pass Rate:     100.00%

4. OPERATIONAL LATENCY:
   p50: 2.5ms | p95: 5.3ms | mean: 2.6ms | min: 0.2ms | max: 5.7ms

5. REGRESSION THRESHOLD EVALUATION:
   - global_hit_rate_at_3            : 1.0 (threshold: 0.9) -> PASSED [OK]
   - global_mrr                      : 0.9545454545454546 (threshold: 0.85) -> PASSED [OK]
   - global_precision_at_3           : 0.3939393939393939 (threshold: 0.25) -> PASSED [OK]
   - global_recall_at_3              : 0.8636363636363636 (threshold: 0.8) -> PASSED [OK]
   - tenant_filtered_hit_rate_at_3   : 0.5454545454545454 (threshold: 0.5) -> PASSED [OK]
   - ood_false_positive_count        : 0 (threshold: 0) -> PASSED [OK]
   - cross_tenant_leakage_count      : 0 (threshold: 0) -> PASSED [OK]
   - unauthorized_result_count       : 0 (threshold: 0) -> PASSED [OK]
===================================================================================================================
```

### 4.1 Comparative Baseline and Threshold Gating

| Evaluation Metric | Step 0 Baseline (Live Gemini) | Stage 5R Offline Harness | CI Gating Threshold | Compliance Status |
| :--- | :--- | :--- | :--- | :--- |
| **Global Hit@1** | 100.0% (11/11) | **90.91%** (10/11) | N/A | Informational |
| **Global Hit@3** | 100.0% (11/11) | **100.00%** (11/11) | $\ge 90.0\%$ | **PASSED** |
| **Global MRR** | 1.0000 | **0.9545** | $\ge 0.850$ | **PASSED** |
| **Global Precision@3** | Not evaluated | **0.3939** | $\ge 0.250$ | **PASSED** |
| **Global Recall@3** | Not evaluated | **0.8636** | $\ge 0.800$ | **PASSED** |
| **Tenant-Filtered Hit@1** | 54.55% (6/11) | **54.55%** (6/11) | N/A | Baseline Faithfulness |
| **Tenant-Filtered Hit@3** | 54.55% (6/11) | **54.55%** (6/11) | $\ge 50.0\%$ | **PASSED** |
| **Tenant-Filtered MRR** | 0.5455 | **0.5455** | N/A | Baseline Faithfulness |
| **OOD False Positives** | Not evaluated | **0** | **0 (Strict Target)** | **PASSED** |
| **Cross-Tenant Leaks** | Not evaluated | **0** | **0 (Zero Tolerance)** | **PASSED** |
| **Unauthorized Results** | Not evaluated | **0** | **0 (Zero Tolerance)** | **PASSED** |
| **Legacy Metadata Deficit** | 38 chunks | **38 chunks** | Exactly 38 | **ACCURATELY TRACKED** |
| **External API Calls** | 14 HTTP requests | **0 (Hermetic)** | 0 | **PASSED** |

---

## 5. Verification & Test Evidence

### 5.1 Stage 5R Test Suite (`backend/tests/test_offline_rag_benchmark.py`)
22 unit and integration tests passing in 3.87s:

```
tests/test_offline_rag_benchmark.py::TestDistanceThresholdAndOODDiscrimination::test_in_domain_above_distance_threshold_is_retrieval_failure PASSED [  4%]
tests/test_offline_rag_benchmark.py::TestDistanceThresholdAndOODDiscrimination::test_ood_above_distance_threshold_is_legitimate_empty PASSED [  9%]
tests/test_offline_rag_benchmark.py::TestDistanceThresholdAndOODDiscrimination::test_ood_below_distance_threshold_is_ood_false_positive PASSED [ 13%]
tests/test_offline_rag_benchmark.py::TestDistanceThresholdAndOODDiscrimination::test_distance_threshold_lower_distance_is_closer PASSED [ 18%]
tests/test_offline_rag_benchmark.py::TestDeterministicOfflineEmbeddingFunction::test_embedding_function_is_deterministic_and_unit_norm PASSED [ 22%]
tests/test_offline_rag_benchmark.py::TestDeterministicOfflineEmbeddingFunction::test_similar_text_has_higher_similarity_than_unrelated PASSED [ 27%]
tests/test_offline_rag_benchmark.py::TestDeterministicOfflineEmbeddingFunction::test_empty_string_handles_gracefully PASSED [ 31%]
tests/test_offline_rag_benchmark.py::TestFullBenchmarkExecutionAndThresholds::test_benchmark_runs_end_to_end_and_passes_all_thresholds PASSED [ 36%]
tests/test_offline_rag_benchmark.py::TestFullBenchmarkExecutionAndThresholds::test_cli_exits_with_code_1_on_ood_false_positive PASSED [ 40%]
tests/test_offline_rag_benchmark.py::TestFullBenchmarkExecutionAndThresholds::test_deterministic_repeatability PASSED [ 45%]
tests/test_offline_rag_benchmark.py::TestFullBenchmarkExecutionAndThresholds::test_benchmark_json_artifact_is_git_ignored PASSED [ 50%]
tests/test_offline_rag_benchmark.py::TestFullBenchmarkExecutionAndThresholds::test_cli_threshold_failure_returns_exit_code_1 PASSED [ 54%]
tests/test_offline_rag_benchmark.py::TestMultiTenantIsolationSecurity::test_missing_tenant_context_fails_closed PASSED [ 59%]
tests/test_offline_rag_benchmark.py::TestMultiTenantIsolationSecurity::test_cross_tenant_leakage_zero_tolerance PASSED [ 63%]
tests/test_offline_rag_benchmark.py::TestMultiTenantIsolationSecurity::test_unauthorized_missing_tenant_item_from_dataset_fails_closed PASSED [ 68%]
tests/test_offline_rag_benchmark.py::TestMultiTenantIsolationSecurity::test_tenant_a_retrieves_authorized_documents PASSED [ 72%]
tests/test_offline_rag_benchmark.py::TestRetrievalMetricCalculations::test_empty_results_and_missing_relevance_labels PASSED [ 77%]
tests/test_offline_rag_benchmark.py::TestRetrievalMetricCalculations::test_hit_rate_at_1_and_3_with_known_ranks PASSED [ 81%]
tests/test_offline_rag_benchmark.py::TestRetrievalMetricCalculations::test_precision_and_recall_at_k_hand_calculated PASSED [ 86%]
tests/test_offline_rag_benchmark.py::TestTenantFilteringAndLegacyDeficit::test_legacy_chunks_missing_tenant_metadata_reported PASSED [ 90%]
tests/test_offline_rag_benchmark.py::TestTenantFilteringAndLegacyDeficit::test_missing_tenant_metadata_vs_legitimate_ood_empty_classification PASSED [ 95%]
tests/test_offline_rag_benchmark.py::TestTenantFilteringAndLegacyDeficit::test_study_queries_execute_tenant_filtering_with_valid_tenant_context PASSED [100%]

======================= 22 passed, 37 warnings in 3.87s ========================
```

### 5.2 Regression Test Suite Execution
All related test suites were executed to verify zero regression across protected Stage 1–4R functionality:

| Test Module | Coverage Scope | Tests | Result | Duration |
| :--- | :--- | :--- | :--- | :--- |
| `test_offline_rag_benchmark.py` | Stage 5R Offline RAG benchmark & security | 22 | **22 PASSED** | 3.87s |
| `test_rag_tenant_isolation.py` | Production RAG multi-tenant isolation | 26 | **26 PASSED** | 5.17s |
| `test_ml_router_and_inference_hardening.py` | Stage 4/4R ML inference, shutdown quiescence, gates | 44 | **44 PASSED** | 4.12s |
| `test_ml_worksheet_generator.py` | Stage 3 worksheet generator & prompt injection | 29 | **29 PASSED** | 4.50s |
| `test_agent_hardening_and_timeouts.py` | Stage 1 worker pool capacity & timeouts | 22 | **22 PASSED** | 1.87s |
| **Total Test Execution** | **Comprehensive Phase 5 Suite** | **143** | **143 PASSED** | **19.53s** |

### 5.3 Code Quality & Linter Compliance
```bash
backend/venv/bin/python -m ruff check app/rag/eval/ scripts/eval_rag_retrieval_offline.py tests/test_offline_rag_benchmark.py
# Output: All checks passed!
```

---

## 6. Artifacts Created & Modified

### 6.1 Created Files
1. `backend/app/rag/eval/offline_eval_dataset.json`: 20 structured test cases with verified ground truth IDs, tenant context, and OOD labels.
2. `backend/app/rag/eval/offline_benchmark.py`: Offline benchmarking engine with calibrated distance gating, Precision@K, Recall@K, and OOD false-positive detection.
3. `backend/scripts/eval_rag_retrieval_offline.py`: Standalone CLI executable with tabular output and regression threshold gating.
4. `backend/tests/test_offline_rag_benchmark.py`: 22 automated unit and integration tests covering all 11 required test areas.
5. `docs/production-readiness/32-phase-5-step-3-6-stage-5-offline-rag-benchmark-report.md`: This comprehensive implementation report.
6. `Hisham-workspace/05-ai-and-ml/step-3-6-stage-5-remediation-notes.md`: Stage 5R engineering remediation notes.

### 6.2 Modified Files
1. `.gitignore`: Added `backend/app/rag/eval/offline_retrieval_benchmark_results.json` to prevent benchmark run output from polluting git status.
2. `.github/workflows/ci.yml`: Added standalone `Run Offline RAG Retrieval Benchmark` step to the `backend` test job.

### 6.3 Protected Files Integrity Verification
Zero modifications to protected Stage 1–4R files:
- `backend/app/core/worker_pool.py`: UNTOUCHED
- `backend/app/agents/portal_assistant.py`: UNTOUCHED
- `backend/app/agents/admin_assistant.py`: UNTOUCHED
- `backend/app/agents/task_registry.py`: UNTOUCHED
- `backend/app/agents/session_store.py`: UNTOUCHED
- `backend/app/ml/router.py`: UNTOUCHED
- `backend/app/ml/worksheet_generator.py`: UNTOUCHED

---

## 7. Conclusion & Status

Stage 5R remediation is **COMPLETE**.

All four findings from the independent acceptance audit (`AUDIT-3.6-S5-01` through `AUDIT-3.6-S5-04`) have been fully addressed:
- OOD false-positive detection is active with calibrated distance gating and zero tolerance (`max_ood_false_positive_count == 0`).
- The 5 baseline study queries execute tenant filtering with valid tenant context against ChromaDB, accurately tracking the 38 legacy un-namespaced chunks and preserving the 54.55% baseline without backfilling.
- Precision@K and Recall@K are implemented with explicit mathematical formulations, defined edge case handling, and hand-calculated tests.
- Benchmark run output is git-ignored and verified via automated test.

In strict compliance with project governance protocols:
- Zero database migrations or backfills were performed.
- Zero Git commits or pushes were executed.
- Stage 6 has NOT been started.
- Stage 5R awaits an **independent, strictly read-only acceptance audit**.
