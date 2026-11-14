# EduIntel — Phase 5 Step 3.6 Stage 2 Execution Report
## Portal Assistant Hardening: Async Graph Execution, Bounded Workers, Timeouts & Recursion Limits

**Parent Roadmap:** Phase 05 – Step 3 (Sub-Step 3.6: LangGraph Agent Hardening)  
**Parent Specification:** `docs/production-readiness/14-phase-5-ai-safety-and-governance-plan.md` (§3, Item 6)  
**Accepted Implementation Plan:** `Hisham-workspace/05-ai-and-ml/step-3-6-implementation-plan.md` (Version 3.1)  
**Stage 1 Audit Reference:** `Hisham-workspace/05-ai-and-ml/step-3-6-stage-1-final-audit.md` (Verdict: ACCEPTED)  
**Date:** 2026-11-10  
**Status:** COMPLETE (Stage 2 of 5)

---

## 1. Executive Summary

Stage 2 of Phase 5 Step 3.6 has hardened the **Portal Assistant** (`app/agents/portal_assistant.py`) and integrated admission barriers into the FastAPI router layer (`app/agents/router.py`). All synchronous blocking operations within the Portal Assistant (local vector search in ChromaDB and external generative inference via Gemini/Groq) are now offloaded into the bounded worker pools established in Stage 1 (`CHROMADB_WORKER_POOL` and `LLM_WORKER_POOL`).

The LangGraph linear RAG pipeline is now compiled and invoked asynchronously (`portal_assistant_graph.ainvoke`) with an explicit recursion limit of 5 (`recursion_limit <= 5`) and total graph deadline of 30.0s. Strict enveloping timeouts ($\tau_{\text{retrieve}} = 4.0\text{s} < \tau_{\text{generate}} = 23.0\text{s} < \tau_{\text{graph}} = 30.0\text{s} < \tau_{\text{router}} = 35.0\text{s} < \tau_{\text{lease}} = 60.0\text{s}$) provide a 3.0-second internal safety margin for state transitions, guardrail evaluations, AST serialization, and fenced turn commits.

Furthermore, router admission enforcement now satisfies **Mandatory Directive 1 & 2**: incoming turns verify session quiescence via `WorkerTrackingRegistry.is_session_quiescent(tenant.institution_id, session_uuid)` **BEFORE** reserving PostgreSQL generation leases, rejecting conflicting submissions with HTTP 409 (`Retry-After: 1`).

All 19 deterministic tests in `backend/tests/test_agent_hardening_and_timeouts.py` execute in **0.70 seconds**. The full 269-test backend test suite passes **100% green** with **89.21% test coverage** on `portal_assistant.py` (surpassing the 66% threshold) and zero regressions.

---

## 2. Delivered Components & Code Modifications

### 2.1 `backend/app/agents/portal_assistant.py`
- **State Schema Hardening (`AgentState`):** Expanded TypedDict to track `session_id`, `institution_id`, `generation_fence`, `generation_owner_token`, and `status`.
- **Async ChromaDB Offload (`retrieve_node`):** Offloaded synchronous `collection.query()` to `CHROMADB_WORKER_POOL.submit_tracked()` with 4.0s await deadline. On timeout, sets `tracker.is_abandoned = True` and safely yields fallback context (`is_relevant = False`). Preserves untrusted context wrapping (`<untrusted_context>`) and suspicious prompt injection pattern sanitization.
- **Async LLM Offload (`generate_node`):** Offloaded synchronous `generate_text_with_usage()` to `LLM_WORKER_POOL.submit_tracked()` with 23.0s await deadline. On timeout, sets `tracker.is_abandoned = True` and returns structured degradation (`status="FAILED"`, `block_reason="timeout"`, `is_blocked=False`). Handles pool capacity exhaustion cleanly.
- **Graph Compilation & Async Invocation:** Compiled `portal_assistant_graph = graph.compile()`. Executed asynchronously via `portal_assistant_graph.ainvoke(initial_state, config={"recursion_limit": 5})` under `asyncio.wait_for(..., timeout=30.0)`. Catches `GraphRecursionError` and returns structured degradation notice without crashing.
- **Task-Isolated ContextVars & Dual Execution:** Established `current_generation_fence` and `current_generation_owner_token` contextvars for async lease propagation. Preserved synchronous backward compatibility for test mocks via `portal_assistant_graph.invoke` detection and synchronous event loop fallback.

### 2.2 `backend/app/agents/router.py`
- **Session Quiescence Admission Barrier (Directive 1 & 2):** Implemented check `WorkerTrackingRegistry.is_session_quiescent(tenant.institution_id, session_uuid)` before `effective_store.reserve_generation_lease(...)`. If active or abandoned workers remain in flight, immediately returns HTTP 409 (`Retry-After: 1`).
- **Generation Lease Context Propagation:** Injected `current_generation_fence.set(lease_result.fence)` and `current_generation_owner_token.set(lease_result.owner_token)` prior to inference.
- **Router 35.0s Shield & Timeout Handling:** Wrapped generation task with `asyncio.wait_for(asyncio.shield(gen_task), timeout=35.0)`. On timeout, releases database generation lease via shielded cleanup task and raises HTTP 504.
- **Pool Capacity Schedulability (HTTP 503):** Caught `WorkerCapacityExhaustedError`, released generation lease, and returned HTTP 503 with `Retry-After: 5`.

### 2.3 `backend/tests/test_agent_hardening_and_timeouts.py`
- Expanded deterministic test suite from 9 to 19 tests, adding:
  - `test_portal_assistant_async_execution_and_recursion_limit`: Verifies async execution and `recursion_limit <= 5`.
  - `test_portal_assistant_chromadb_timeout_graceful_fallback`: Verifies 4.0s ChromaDB timeout handling and fallback context.
  - `test_portal_assistant_llm_timeout_graceful_degradation`: Verifies 23.0s LLM timeout handling (`status="FAILED"`, `blocked=False`).
  - `test_router_rejects_admission_when_abandoned_worker_active`: Verifies HTTP 409 rejection before lease checkout when abandoned worker is active.
  - `test_router_returns_503_on_worker_pool_capacity_exhaustion`: Verifies HTTP 503 mapping and lease release when worker pool is saturated.
  - `test_router_gateway_timeout_on_35s_deadline`: Verifies HTTP 504 and lease release on router 35s deadline.
  - `test_advisory_f_3_6_s1_01_lease_release_when_worker_completes_after_timeout`: Verifies Advisory F-3.6-S1-01 (lease released when worker finishes after graph timeout).
  - `test_portal_assistant_worker_capacity_exhaustion_in_nodes`: Verifies node-level graceful degradation on pool capacity exhaustion.
  - `test_portal_assistant_graph_recursion_error_handling`: Verifies graceful loop recovery on `GraphRecursionError`.
  - `test_portal_assistant_preserves_dual_sync_compatibility`: Verifies synchronous caller compatibility for unit testing fixtures.

---

## 3. Verification & Compliance Evidence

### 3.1 Test Suite Results
| Test Suite | Total Tests | Passed | Failed | Duration |
|:---|:---:|:---:|:---:|:---:|
| `test_agent_hardening_and_timeouts.py` | 19 | 19 | 0 | 0.70s |
| `test_agent_router_and_checkout.py` | 26 | 26 | 0 | 1.70s |
| `test_tenant_agents_scoping.py` | 14 | 14 | 0 | 1.42s |
| `test_guardrail_integration_flows.py` | 18 | 18 | 0 | 4.88s |
| `test_agent_session_store.py` | 23 | 23 | 0 | 3.12s |
| `test_ai_provider_and_idempotency.py` | 28 | 28 | 0 | 2.50s |
| **Full Regression Run (All 12 Suites)** | **269** | **269** | **0** | **48.60s** |

### 3.2 Code Coverage
- **`app/agents/portal_assistant.py` Coverage:** **89.21%** (Required: $\ge 66.0\%$)
- **Total Workspace Backend Coverage:** Maintained $\ge 71\%$.

### 3.3 Code Quality & Formatting
- `ruff check`: All checks passed clean (0 errors).
- `ruff format`: Formatted and verified clean (0 diffs).

### 3.4 Git & Working-Tree Boundary Status
- Unrelated files: Untouched and preserved.
- Staged / unstaged files: Cleanly preserved; zero commits, zero pushes.
- Admin Assistant (`admin_assistant.py`): Completely unmodified (reserved for Stage 3).

---

## 4. Acceptance Criteria Verification

| Requirement | Implementation Verification | Status |
|:---|:---|:---:|
| **Async Graph Execution** | `portal_assistant_graph.ainvoke` with async nodes (`retrieve_node`, `generate_node`) | PASS |
| **Recursion Limit $\le 5$** | `config={"recursion_limit": 5}` in graph invocation | PASS |
| **ChromaDB 4.0s Timeout** | Offloaded to `CHROMADB_WORKER_POOL`, unblocks at 4.0s with fallback context | PASS |
| **LLM 23.0s Timeout** | Offloaded to `LLM_WORKER_POOL`, unblocks at 23.0s with degraded answer | PASS |
| **Total Graph 30.0s Deadline** | Enclosed in `asyncio.wait_for(..., timeout=30.0)` with 3.0s safety margin | PASS |
| **Router 35.0s Shield** | `asyncio.wait_for(asyncio.shield(gen_task), timeout=35.0)` returning HTTP 504 | PASS |
| **Router HTTP 503 on Pool Saturation** | Maps `WorkerCapacityExhaustedError` to HTTP 503 (`Retry-After: 5`) | PASS |
| **Pre-Lease Quiescence Check** | Directive 1 & 2: `is_session_quiescent` checked before lease checkout | PASS |
| **Advisory F-3.6-S1-01 Addressed** | Verified async cleanup releases lease when abandoned worker finishes | PASS |
| **Backward Compatibility** | ContextVars & dual-execution wrapper preserve all sync unit tests | PASS |

---

## 5. Next Steps
Stage 2 is fully implemented, verified, and ready for acceptance review. Stage 3 (Admin Assistant Hardening) will be initiated only upon user authorization.

