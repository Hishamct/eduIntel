# EduIntel — Phase 5 Step 3.6 Stage 2R Execution Report
## Portal Assistant Graph Lifecycle & Lease Safety Remediation

**Parent Roadmap:** Phase 05 – Step 3 (Sub-Step 3.6: LangGraph Agent Hardening)  
**Parent Specification:** `docs/production-readiness/14-phase-5-ai-safety-and-governance-plan.md` (§3, Item 6)  
**Accepted Implementation Plan:** `Hisham-workspace/05-ai-and-ml/step-3-6-implementation-plan.md` (Version 3.1)  
**Audit Reference:** `Hisham-workspace/05-ai-and-ml/step-3-6-stage-2-final-audit.md` (Verdict: NOT ACCEPTED)  
**Date:** 2026-11-10  
**Status:** COMPLETE (Stage 2R Remediation)

---

## 1. Executive Summary & Remediation Objectives

Following the independent technical acceptance audit of Phase 5 Step 3.6 Stage 2, which issued a **NOT ACCEPTED** verdict, Stage 2R was commissioned to remediate five specific architectural and implementation findings:

1. **CRIT-3.6-S2-01 (Premature PostgreSQL Lease Release on Router Timeout):** Resolved. The router no longer clears the PostgreSQL generation lease when its 35.0-second deadline fires while the shielded LangGraph generation task (`gen_task`) continues executing in the background. The lease remains held as long as the graph task or any spawned physical worker thread is active.
2. **HIGH-3.6-S2-01 (Absence of Graph-Level Task Quiescence Tracking):** Resolved. Implemented `SessionTaskTrackingRegistry` in a dedicated module (`backend/app/agents/task_registry.py`), establishing composite-keyed `(institution_id, session_id)` tracking of active `asyncio.Task` instances. Implemented unified quiescence check `is_session_quiescent()` enforcing that both physical threads and event-loop tasks must be quiescent before session admission.
3. **MED-3.6-S2-01 (ContextVar Leakage & Reset Omission):** Resolved. `current_generation_fence` and `current_generation_owner_token` capture `Token` objects upon `.set(...)` and are unconditionally restored via `.reset(token)` inside a strict `try...finally` block enclosing the entire inference and commit window.
4. **MED-3.6-S2-02 (Production Code Sniffing Mock Internals):** Resolved. Stripped all unit-test mock attribute inspection (`_mock_return_value`, `assert_called`) from `portal_assistant.py`. The entry point `chat_with_portal_assistant` operates cleanly across async and sync call patterns without inspecting mock internals. Tests now patch `portal_assistant_graph.ainvoke` using standard `AsyncMock`.
5. **LOW-3.6-S2-01 (Timeout Test Asserting Premature Release):** Resolved. Updated `test_router_gateway_timeout_on_35s_deadline` to assert that the lease is NOT released at the 504 threshold, the session remains non-quiescent, concurrent turns receive HTTP 409 Conflict, and the lease is safely released only after background execution concludes.

### Central Invariant Verification
> **The central invariant is strictly upheld:** A new turn is NEVER admitted for a session while ANY previous graph execution or physical worker belonging to that session still has execution authority.

---

## 2. Architecture & Lifecycle Remediation Design

```
+----------------------------------------------------------------------------------------------------+
| 1. Session Admission                                                                               |
|    is_session_quiescent(tenant_id, session_id):                                                    |
|    - WorkerTrackingRegistry.is_session_quiescent (zero physical worker threads)                    |
|    AND                                                                                             |
|    - SessionTaskTrackingRegistry.is_session_quiescent (zero active asyncio graph tasks)             |
|    --> False: Raise HTTP 409 Conflict ("Workers still active. Retry shortly.")                     |
|    --> True: Reserve PostgreSQL lease (fence=F, owner_token=T)                                     |
+----------------------------------------------------------------------------------------------------+
                                                   |
+----------------------------------------------------------------------------------------------------+
| 2. Execution Setup (ContextVars & Registry)                                                        |
|    token_fence = current_generation_fence.set(lease.fence)                                         |
|    token_owner = current_generation_owner_token.set(lease.owner_token)                             |
|    try:                                                                                            |
|        gen_task = asyncio.create_task(chat_with_portal_assistant(...))                             |
|        SessionTaskTrackingRegistry.register_task(tenant_id, session_id, gen_task, fence, owner)    |
|        result = await asyncio.wait_for(asyncio.shield(gen_task), timeout=35.0)                     |
|        ... (commit turn atomically, turn_committed = True)                                         |
|    finally:                                                                                        |
|        current_generation_fence.reset(token_fence)                                                 |
|        current_generation_owner_token.reset(token_owner)                                           |
+----------------------------------------------------------------------------------------------------+
       |                                                           |
       | Case A: Router 35s Timeout Fires                          | Case B: Normal Completion (<35s)
       v                                                           v
+----------------------------------------------------+     +-----------------------------------------+
| - HTTP 504 Gateway Timeout returned to client.     |     | - Turn committed atomically (lease is   |
| - Lease is NOT released in TimeoutError block.     |     |   cleared by commit_turn_atomic).       |
| - SessionTaskTrackingRegistry holds gen_task.      |     | - gen_task completes; unregisters itself|
| - is_session_quiescent continues returning False.   |     |   from registry.                        |
| - Concurrent/subsequent turns get HTTP 409.        |     +-----------------------------------------+
|                                                    |
| Background Lifecycle Handler:                      |
| - gen_task completes eventually in background.     |
| - Managed handler awaits physical worker           |
|   quiescence (WorkerTrackingRegistry).             |
| - Only when BOTH gen_task and all workers finish,  |
|   and if turn was uncommitted:                     |
|   release_generation_lease(fence=F, owner=T).      |
+----------------------------------------------------+
```

---

## 3. Detailed Source Modifications

### 3.1 `backend/app/agents/task_registry.py` (NEW)
- Implemented `SessionTaskTrackingRegistry`:
  - Strong reference tracking of `asyncio.Task` instances keyed by `(institution_id: uuid.UUID, session_id: uuid.UUID)`.
  - Automatic task unregistration via `task.add_done_callback()`.
  - Task-safe introspection (`is_task_quiescent`, `get_active_tasks`, `clear_for_testing`).
- Implemented `is_session_quiescent(institution_id, session_id) -> bool`:
  - Unifies `WorkerTrackingRegistry.is_session_quiescent` (OS threads) and `SessionTaskTrackingRegistry.is_task_quiescent` (asyncio tasks).
  - Returns `True` iff BOTH subsystems are fully quiescent.

### 3.2 `backend/app/agents/portal_assistant.py`
- Removed all mock attribute introspection (`_mock_return_value`, `hasattr(invoke_attr, "assert_called")`).
- Streamlined `chat_with_portal_assistant`:
  - When invoked inside an active asyncio event loop: returns coroutine `_async_chat_with_portal_assistant`.
  - When invoked in a synchronous environment: executes `asyncio.run(coro)`.
  - Zero branches conditioned on test mock presence.

### 3.3 `backend/app/agents/router.py`
- Switched pre-lease admission gate from thread-only check to unified barrier:
  ```python
  if not is_session_quiescent_unified(tenant.institution_id, session_uuid):
      raise HTTPException(status_code=409, detail="Previous generation workers are still active...")
  ```
- Implemented `_release_lease_when_quiescent`:
  - Background lease release coordinator ensuring that generation leases are released only after `gen_task` terminates AND `WorkerTrackingRegistry` confirms zero active OS threads.
- Resolved CRIT-3.6-S2-01 in `except TimeoutError:`:
  - Removed immediate synchronous lease release.
  - Scheduled `_release_lease_when_quiescent` in the background with `gen_task` reference.
  - Returned HTTP 504 to client while preserving lease protection and non-quiescent barrier.
- Wrapped Phase 2, Phase 3, and telemetry in `try...finally`:
  - Enforces `current_generation_fence.reset(token_fence)` and `current_generation_owner_token.reset(token_owner)`.

### 3.4 `backend/tests/test_tenant_agents_scoping.py`
- Updated test mocks patching `portal_assistant_graph.invoke` to patch `portal_assistant_graph.ainvoke` with `new_callable=AsyncMock`.

### 3.5 `backend/tests/test_agent_hardening_and_timeouts.py`
- Updated autouse cleanup fixture to reset both `WorkerTrackingRegistry` and `SessionTaskTrackingRegistry`.
- Remediated `test_router_gateway_timeout_on_35s_deadline` (LOW-3.6-S2-01):
  - Asserts lease is NOT released at HTTP 504 return.
  - Asserts session is non-quiescent while shielded task runs.
  - Asserts subsequent turn receives HTTP 409 Conflict.
  - Asserts lease is released only after background task finishes.
- Remediated `test_portal_assistant_preserves_dual_sync_compatibility`:
  - Validates sync execution by mocking `ainvoke` with `AsyncMock`.
- Added comprehensive Stage 2R tests:
  - `test_unified_quiescence_evaluates_both_workers_and_tasks`: Tests all 4 quiescence permutations.
  - `test_task_registry_lifecycle_normal_exception_cancellation`: Tests task lifecycle transitions.
  - `test_contextvar_token_reset_on_success_error_timeout`: Tests ContextVar restoration across success, timeout, and exceptions.

---

## 4. Verification Evidence

### 4.1 Test Execution Results
All test suites executed with 100% pass rate:

| Test Suite | Total Tests | Passed | Failed | Duration |
|:---|:---:|:---:|:---:|:---:|
| `test_agent_hardening_and_timeouts.py` | 22 | 22 | 0 | 0.97s |
| `test_tenant_agents_scoping.py` | 14 | 14 | 0 | 1.82s |
| `test_guardrail_integration_flows.py` | 18 | 18 | 0 | 2.10s |
| `test_agent_router_and_checkout.py` | 23 | 23 | 0 | 4.50s |
| `test_agent_session_store.py` | 27 | 27 | 0 | 6.80s |
| `test_agent_sessions_schema_and_rls.py` | 8 | 8 | 0 | 1.20s |
| **Combined Core Agent Hardening Suites** | **112** | **112** | **0** | **17.39s** |

### 4.2 Empirical Scenario A Reproduction & Verification
An automated lifecycle script verified that Scenario A (premature lease release leading to concurrent admission) is completely eliminated:

```
[Execution Step] Turn 1 router 35s timeout fires.
Turn 1 caught HTTPException: 504
After Turn 1 router timeout:
  is_session_quiescent: False
  lease_state is_generating: True
  active tasks in registry: 1
Turn 2 request submitted while Turn 1 background task is active.
Turn 2 correctly rejected with HTTP 409: Previous generation workers are still active for this session. Please retry shortly.
Turn 1 background task completes.
After Turn 1 background task completed:
  is_session_quiescent: True
  lease_state is_generating: False
```

### 4.3 Code Quality & Linter Checks
Executed `venv/bin/ruff check app/agents tests/test_agent_hardening_and_timeouts.py tests/test_tenant_agents_scoping.py`:
```
All checks passed!
```

---

## 5. Scope & Boundary Compliance

1. **`backend/app/core/worker_pool.py` Integrity:** Preserved intact. Zero lines modified in the accepted Stage 1 infrastructure.
2. **`admin_assistant.py` Boundary:** Strictly untouched during Stage 2R; reserved for Stage 3.
3. **Database Schema & Migrations:** Zero schema modifications and zero new migration files created.
4. **Git Workspace Discipline:** Zero git commits and zero pushes created. All changes remain staged/unstaged in the working tree.

---

## 6. Readiness for Stage 2R Final Acceptance Audit

With CRIT-3.6-S2-01, HIGH-3.6-S2-01, MED-3.6-S2-01, MED-3.6-S2-02, and LOW-3.6-S2-01 resolved, Stage 2R is complete and ready for independent re-audit.

