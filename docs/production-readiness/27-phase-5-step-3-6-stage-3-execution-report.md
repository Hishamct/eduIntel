# EduIntel — Phase 5 Step 3.6 Stage 3 Execution Report
## Admin Assistant Hardening: Async Graph Execution, Bounded Workers, Timeouts, Recursion Limits & Session Safety

**Parent Roadmap:** Phase 05 – Step 3 (Sub-Step 3.6: LangGraph Agent Hardening)  
**Parent Specification:** `docs/production-readiness/14-phase-5-ai-safety-and-governance-plan.md` (§3, Item 6)  
**Accepted Implementation Plan:** `Hisham-workspace/05-ai-and-ml/step-3-6-implementation-plan.md` (Version 3.1)  
**Stage 1 Acceptance Reference:** `Hisham-workspace/05-ai-and-ml/step-3-6-stage-1-final-audit.md` (Verdict: ACCEPTED)  
**Stage 2R Acceptance Reference:** `Hisham-workspace/05-ai-and-ml/step-3-6-stage-2R-final-audit.md` (Verdict: ACCEPTED)  
**Date:** 2026-11-10  
**Status:** COMPLETE (Stage 3 of 5)

---

## 1. Executive Summary

Stage 3 of Phase 5 Step 3.6 has hardened the administrative agent pipeline (**Admin Assistant**, `app/agents/admin_assistant.py`) and integrated robust lifecycle and admission safety barriers into the FastAPI router layer (`app/agents/router.py`). Stage 3 directly builds on the accepted foundations of Stage 1 (`WorkerTrackingRegistry` and bounded thread pools) and Stage 2R (`SessionTaskTrackingRegistry`, unified quiescence checks, and delayed lease release).

All synchronous blocking inference operations in the Admin Assistant (`decide_tools_with_usage` and `generate_text_with_usage`) are now offloaded from the asyncio event loop thread into `LLM_WORKER_POOL` (capacity: 16 active, 32 queued) using `submit_tracked()`. Every tool execution within `execute_tools_node` is strictly bounded by a 7.0-second await budget and operates within a short-lived tenant-scoped database session (`tenant_session_scope`) enforcing PostgreSQL Row-Level Security (`app.current_institution_id`), parameter validation via strict Pydantic models, and idempotency tracking via `tool_execution_records`.

The LangGraph tool-augmented administrative pipeline executes asynchronously via `admin_assistant_graph.ainvoke` with an explicit recursion limit of 6 (`recursion_limit=6`) and an overall graph deadline of 30.0s. Strict enveloping timeouts ($\tau_{\text{decide}} = 8.0\text{s} + \tau_{\text{tools}} = 7.0\text{s} + \tau_{\text{generate}} = 11.0\text{s} + \text{safety margin} = 4.0\text{s} = \tau_{\text{graph}} = 30.0\text{s} < \tau_{\text{router}} = 35.0\text{s} < \tau_{\text{lease}} = 60.0\text{s}$) preserve a 5.0-second safety envelope for output guardrail evaluation, state serialization, and atomic database turn commits.

Router admission enforcement for `admin_assistant_chat` strictly complies with **Mandatory Directives 1 & 2**: incoming turns verify unified session quiescence (`is_session_quiescent_unified`) across both physical worker threads and asyncio graph tasks **BEFORE** reserving PostgreSQL generation leases, rejecting conflicting submissions with HTTP 409 (`Retry-After: 1`).

All 13 deterministic tests in `backend/tests/test_admin_assistant_hardening_and_timeouts.py`—including an end-to-end 12-step reproduction of Scenario A against live PostgreSQL—pass in **1.06 seconds**. The complete suite of related agent tests (128+ tests across 5 test suites) and full workspace regressions pass **100% green** with zero regressions.

---

## 2. Delivered Architecture & Component Details

### 2.1 State Schema Hardening (`AgentState`)
`backend/app/agents/admin_assistant.py`:
- Expanded `AgentState` TypedDict to include:
  - `generation_fence: int | None`
  - `generation_owner_token: uuid.UUID | str | None`
  - `institution_id: uuid.UUID | str | None`
  - `status: str | None` ("RUNNING", "COMPLETED", "FAILED")
- Initialized state with `status="RUNNING"`, fence, owner token, and tenant identifier.

### 2.2 Async Offloading & Node-Level Timeouts
1. **`decide_tools_node` (8.0s timeout):**
   - Offloaded synchronous `decide_tools_with_usage` into `LLM_WORKER_POOL.submit_tracked(...)`.
   - Evaluated under `asyncio.wait_for(asyncio.wrap_future(fut), timeout=8.0)`.
   - On timeout: sets `tracker.is_abandoned = True`, logs a warning with session metadata, and sets `status="FAILED"`, `block_reason="timeout"`, and a polite degradation message.
   - On pool capacity exhaustion (`WorkerCapacityExhaustedError`): gracefully returns `status="FAILED"`, `block_reason="worker_capacity_exhausted"`.
2. **`execute_tools_node` (7.0s timeout per tool):**
   - Evaluated under `asyncio.wait_for(func(db=tool_db, tenant_id=tenant_id, **clean_args), timeout=7.0)`.
   - Operates within short-lived `tenant_session_scope(inst_uuid)` setting PostgreSQL RLS session variable `app.current_institution_id`.
   - Integrates with `tool_execution_records`: records timeouts explicitly via `fail_tool_execution(tool_db, record.id, record.lease_generation, err_msg)`.
   - Returns structured `{"status": "timeout", "error": err_msg}` in `tool_results` to allow `generate_node` to explain tool unavailability to the admin.
3. **`generate_node` (11.0s timeout):**
   - Offloaded synchronous `generate_text_with_usage` into `LLM_WORKER_POOL.submit_tracked(...)`.
   - Evaluated under `asyncio.wait_for(asyncio.wrap_future(fut), timeout=11.0)`.
   - On timeout: sets `tracker.is_abandoned = True`, logs warning, and sets `status="FAILED"`, `block_reason="timeout"`.
   - Enforces untrusted output boundary wrapping (`<untrusted_tool_output>`) and output guardrail evaluation (`evaluate_output`) for PII redaction and metaprompt leak prevention.

### 2.3 Graph Invocation & Recursion Limit
- Entry point `_async_chat_with_admin_assistant` compiles `admin_assistant_graph` and invokes it asynchronously:
  ```python
  final_state = await asyncio.wait_for(
      admin_assistant_graph.ainvoke(
          initial_state,
          config={"recursion_limit": 6},
      ),
      timeout=30.0,
  )
  ```
- Gracefully catches `GraphRecursionError` and returns structured degradation response without uncaught exceptions.
- Provides clean dual execution entry point `chat_with_admin_assistant`: returns coroutine if event loop is running; invokes `asyncio.run(coro)` if called synchronously. Zero mock introspection.

### 2.4 Tracing Decorator Integration
- Decorated `_async_decide_tools_node` with `@traced_node("decide_tools")` and `_async_generate_node` with `@traced_node("generate")`.
- Because the decorated targets are `async def` functions, `inspect.iscoroutinefunction()` is `True`, causing `@traced_node` to wrap them with `async_wrapper`, safely awaiting node coroutines and appending step execution telemetry (`trace_steps`) without sync wrapper type errors.

### 2.5 Router Admission Barrier & Lifecycle Management (`router.py`)
In `admin_assistant_chat`:
1. **Pre-Lease Quiescence Check (Mandatory Directives 1 & 2):**
   ```python
   if not is_session_quiescent_unified(tenant.institution_id, session_uuid):
       raise HTTPException(
           status_code=status.HTTP_409_CONFLICT,
           detail="Previous generation workers are still active for this session. Please retry shortly.",
           headers={"Retry-After": "1"},
       )
   ```
2. **ContextVar Scope & Safe Restoration:**
   Captured `token_fence = current_generation_fence.set(lease_result.fence)` and `token_owner = current_generation_owner_token.set(lease_result.owner_token)` upon entry; restored both via `.reset(token)` in the outer `finally:` block.
3. **Task Tracking Registry:**
   Registered `gen_task = asyncio.create_task(chat_with_admin_assistant(...))` in `SessionTaskTrackingRegistry.register_task(...)` with matching fence and owner token.
4. **Router 35.0s Shield & Non-Premature Lease Handling:**
   Awaited `gen_task` under `asyncio.wait_for(asyncio.shield(gen_task), timeout=35.0)`.
   On `TimeoutError`: returns HTTP 504 without clearing the PostgreSQL lease, spawning background cleanup coordinator `_release_lease_when_quiescent(...)` that holds the lease until all physical workers and `gen_task` finish.
5. **Worker Capacity Schedulability:**
   Catches `WorkerCapacityExhaustedError`, releases lease, and returns HTTP 503 (`Retry-After: 5`).

---

## 3. Scenario A End-to-End Lifecycle Verification

The 12-step Scenario A lifecycle was reproduced deterministically against a real PostgreSQL database with `DatabaseSessionStore`:

| Step | Action | Observed Result | Compliance Status |
|:---:|:---|:---|:---:|
| **1** | Turn 1 arrives; checks quiescence. | `is_session_quiescent_unified` returns `True`. | PASS |
| **2** | Turn 1 acquires generation lease. | PostgreSQL lease granted (`fence=1`, unique `owner_token`). | PASS |
| **3** | Turn 1 offloads blocking call to `LLM_WORKER_POOL`. | Physical future registered in `WorkerTrackingRegistry`. | PASS |
| **4** | Worker exceeds 8.0s timeout; `decide_tools_node` unblocks. | Node catches timeout, marks `tracker.is_abandoned = True`. Physical thread continues running. | PASS |
| **5** | Turn 1 finishes graph execution. | Graph returns structured failure answer; `gen_task` unregisters from `SessionTaskTrackingRegistry`. | PASS |
| **6** | Turn 1 commits assistant response atomically. | `commit_turn_atomic()` commits turn and clears DB generation lease (`generation_lease_owner = None`). | PASS |
| **7** | Abandoned physical worker is still running. | Worker thread continues executing in background. | PASS |
| **8** | Physical worker finishes; invokes callback. | `_physical_future_done_callback()` runs, removes worker from `WorkerTrackingRegistry`. Callback does NOT attempt to release generation lease (already cleared or owned by newer generation). | PASS |
| **9** | Turn 2 attempts admission while abandoned worker was running. | `is_session_quiescent_unified` returned `False`! HTTP 409 Conflict raised. DB lease checkout BLOCKED. | PASS |
| **10** | Turn 2 waits for physical worker to finish. | Thread completes, registry unregisters future. `is_session_quiescent_unified` transitions to `True`. | PASS |
| **11** | Turn 2 retries admission after quiescence. | `is_session_quiescent_unified` returns `True`. | PASS |
| **12** | Turn 2 acquires new generation lease. | PostgreSQL lease granted (`fence=2`, new `owner_token`). Zero collision or race conditions. | PASS |

---

## 4. Verification & Test Evidence

### 4.1 Test Suite Breakdown
| Test Suite | Total Tests | Passed | Failed | Duration | Scope Verified |
|:---|:---:|:---:|:---:|:---:|:---|
| `test_admin_assistant_hardening_and_timeouts.py` | 13 | 13 | 0 | 1.06s | Admin async execution, pool offload, 8s/7s/11s timeouts, Scenario A reproduction, ContextVars, dual dispatcher |
| `test_admin_assistant_security.py` | 17 | 17 | 0 | 1.37s | Tool RLS fencing, argument validation, prompt injection defense, SQL pattern blocking |
| `test_admin_ai_tenant_isolation.py` | 35 | 35 | 0 | 3.94s | Multi-tenant scoping, database isolation, cross-institution barriers |
| `test_agent_hardening_and_timeouts.py` | 22 | 22 | 0 | 0.98s | Stage 1 & Stage 2/2R regression verification |
| `test_agent_router_and_checkout.py` | 26 | 26 | 0 | 1.70s | Lease fencing, atomic turn commits, terminal states |
| `test_ai_provider_and_idempotency.py` | 28 | 28 | 0 | 2.50s | Tool idempotency records, provider fallbacks |
| `test_guardrail_integration_flows.py` | 18 | 18 | 0 | 2.29s | Guardrail pipelines, synchronous test compatibility (`test_tool_output_untrusted_fencing_and_sanitization`) |
| **Core Hardening & Safety Total** | **159** | **159** | **0** | **13.84s** | **100% Pass** |

### 4.2 Linter & Quality Assurance
- `cd backend && venv/bin/ruff check app/agents/admin_assistant.py app/agents/router.py tests/test_admin_assistant_hardening_and_timeouts.py`:
  - Result: `All checks passed!` (0 warnings, 0 errors).

### 4.3 Architecture Boundary & Git Status
- `backend/app/core/worker_pool.py`: **0 changes** (Strictly preserved).
- `backend/app/agents/task_registry.py`: **0 changes** (Strictly preserved).
- `backend/app/agents/portal_assistant.py`: **0 changes** (Strictly preserved).
- `backend/app/agents/session_store.py`: **0 changes** (Strictly preserved).
- Database migrations: **0 changes**.
- Git: Clean working boundary; zero commits, zero pushes.

---

## 5. Acceptance Status & Next Steps

Stage 3 implementation is **COMPLETE** and verified against all architectural directives.

Readiness for Independent Audit:
- Stage 3 is ready for an independent, read-only technical acceptance audit.
- Stage 4 (Worksheet Generator & ML Router Hardening) will commence only upon formal audit acceptance and authorization.

