# EduIntel — Phase 5 Step 3.6 Stage 4 Concurrency Remediation Report
## Targeted Concurrency Remediation & Final Verification

**Parent Roadmap:** Phase 05 – Step 3 (Sub-Step 3.6: LangGraph Agent Hardening)  
**Parent Specification:** `docs/production-readiness/14-phase-5-ai-safety-and-governance-plan.md` (§3, Item 6)  
**Stage 4 Execution Report:** `docs/production-readiness/28-phase-5-step-3-6-stage-4-execution-report.md`  
**Accepted Implementation Plan:** `Hisham-workspace/05-ai-and-ml/step-3-6-implementation-plan.md` (Version 3.1)  
**Date:** 2026-11-10  
**Status:** COMPLETE (Stage 4 Concurrency Remediation)

---

## 1. Executive Summary

A post-audit engineering review of Phase 5 Step 3.6 Stage 4 identified a potential concurrency leak:
> *An asyncio semaphore context manager (`async with ml_inference_capacity_scope():`) is released when the awaiting coroutine is cancelled or times out, even though the underlying `asyncio.to_thread()` operation continues executing in a physical worker thread.*

Under high request loads or rapid client disconnects, premature release of the semaphore permitted newly arriving requests to acquire semaphore slots while earlier physical threads were still running. This caused actual OS thread concurrency in the inference pool to exceed the configured bound of 16 concurrent executions. Additionally, detached background telemetry tasks spawned in `generate_worksheet` lacked strong references, exposing them to premature garbage collection by Python's event loop.

To remediate these issues, targeted architectural corrections were implemented:
1. **Deferred Semaphore Release via Shielded Task Execution (`run_with_inference_capacity`):**
   - Inference tasks are scheduled as uncancelled `asyncio.Task` instances tracked in `_ACTIVE_ML_INFERENCE_TASKS`.
   - The semaphore permit is held across caller cancellations and timeouts; it is released **strictly once** via a task done callback when the underlying physical thread finishes.
   - The client request awaits `asyncio.shield(worker_task)`, ensuring caller disconnects raise `asyncio.CancelledError` immediately without prematurely returning the permit.
2. **Detached Telemetry Strong Reference Retention:**
   - Background telemetry tasks spawned by `generate_worksheet` upon client timeout or disconnect are tracked in `_ACTIVE_DETACHED_TELEMETRY_TASKS` with a completion callback to prevent garbage collection during event-loop turns.
3. **Graceful Subsystem Quiescence (`wait_for_ml_quiescence`):**
   - Provides a unified drain helper for `_ACTIVE_ML_INFERENCE_TASKS`, `_ACTIVE_WORKSHEET_TASKS`, and `_ACTIVE_DETACHED_TELEMETRY_TASKS` during server teardown.
4. **Endpoint Protection Across All Inference Routes:**
   - Updated `predict_at_risk`, `predict_at_risk_admin`, `explain_at_risk`, `predict_weak_topics`, `diagnose_student_endpoint`, and `diagnose_with_recommendations` to execute via `run_with_inference_capacity()`.
5. **Deterministic Real-Thread Verification:**
   - Added `TestMLInferencePhysicalWorkerLifecycle` with 4 deterministic tests using real OS threads and `threading.Event`, empirically proving that cancellation does not release the permit until the thread physically terminates.

All 30 tests in `test_ml_router_and_inference_hardening.py`, all 29 tests in `test_ml_worksheet_generator.py`, and all 47 tests in `test_ml_diagnostics_idor.py` pass **100% green** (106 tests in 21.66s), with zero regressions in Stage 1, 2R, and 3 suites (61 tests in 3.26s).

---

## 2. Root Cause Analysis & Empirical Reproduction

### 2.1 Mechanism of Defect
The previous Stage 4 implementation used a standard asynchronous context manager:
```python
@asynccontextmanager
async def ml_inference_capacity_scope():
    await asyncio.wait_for(ML_INFERENCE_SEMAPHORE.acquire(), timeout=5.0)
    try:
        yield
    finally:
        ML_INFERENCE_SEMAPHORE.release()
```
When a client disconnected or the endpoint timed out, an `asyncio.CancelledError` was injected into the awaiting endpoint coroutine. The Python runtime executed the `finally:` block immediately, calling `ML_INFERENCE_SEMAPHORE.release()`.

However, `asyncio.to_thread()` dispatches work to `concurrent.futures.ThreadPoolExecutor`. OS threads in Python cannot be interrupted or cancelled by `asyncio.CancelledError`. Consequently, the physical OS thread continued executing `model.predict_proba()` or `TreeExplainer.shap_values()`, while the semaphore permit was already restored. A new incoming request could acquire this permit, leading to physical pool oversubscription beyond the configured limit of 16.

### 2.2 Empirical Proof
A diagnostic script configured `ML_INFERENCE_SEMAPHORE` to 1 permit and executed a worker function blocking on a `threading.Event`:
1. Worker 1 acquired the permit and entered its OS thread.
2. The awaiting coroutine was cancelled.
3. Under the old context-manager pattern, `ML_INFERENCE_SEMAPHORE._value` immediately returned to 1 while Worker 1's OS thread remained active.
4. Worker 2 was admitted and entered the thread pool, demonstrating that 2 physical threads were active simultaneously against a configured limit of 1.

---

## 3. Technical Implementation

### 3.1 Shielded Capacity Orchestration (`backend/app/ml/router.py`)
Implemented `run_with_inference_capacity` to decouple client-side cancellation from semaphore release:

```python
_ACTIVE_ML_INFERENCE_TASKS: set[asyncio.Task] = set()
_ACTIVE_WORKSHEET_TASKS: set[asyncio.Task] = set()
_ACTIVE_DETACHED_TELEMETRY_TASKS: set[asyncio.Task] = set()

async def run_with_inference_capacity(coro_or_func, *args, **kwargs):
    """
    Acquires an ML inference semaphore slot before scheduling worker.
    Guarantees that cancellation or timeout of the awaiting request does NOT
    release the semaphore while the underlying physical worker is still running.
    Releases the semaphore permit exactly once when physical execution completes.
    """
    try:
        await asyncio.wait_for(
            ML_INFERENCE_SEMAPHORE.acquire(),
            timeout=ML_INFERENCE_ACQUIRE_TIMEOUT,
        )
    except TimeoutError as te:
        logger.warning("[ML Router] ML inference capacity exhausted (16 concurrent). HTTP 503 returned.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="ML inference service is currently at maximum capacity. Please retry shortly.",
            headers={"Retry-After": "5"},
        ) from te

    semaphore_released = False

    async def _execute_work():
        if inspect.iscoroutinefunction(coro_or_func):
            return await coro_or_func(*args, **kwargs)
        elif callable(coro_or_func):
            res = coro_or_func(*args, **kwargs)
            if inspect.isawaitable(res):
                return await res
            return res
        elif inspect.isawaitable(coro_or_func):
            return await coro_or_func
        else:
            return coro_or_func

    worker_task: asyncio.Task = asyncio.create_task(_execute_work())
    _ACTIVE_ML_INFERENCE_TASKS.add(worker_task)

    def _on_inference_done(t: asyncio.Task) -> None:
        nonlocal semaphore_released
        _ACTIVE_ML_INFERENCE_TASKS.discard(t)
        if not t.cancelled():
            _ = t.exception()
        if not semaphore_released:
            semaphore_released = True
            ML_INFERENCE_SEMAPHORE.release()

    worker_task.add_done_callback(_on_inference_done)

    # Shield worker_task so caller cancellation does NOT abort worker
    # and does NOT release semaphore prematurely while physical thread continues
    return await asyncio.shield(worker_task)
```

### 3.2 Detached Telemetry Strong Reference Retention
In `backend/app/ml/router.py` (`generate_worksheet`), detached telemetry persistence tasks are now registered:
```python
if worker_usage and (request_timed_out_or_cancelled or not db.is_active):
    bg_task = asyncio.create_task(
        _persist_background_detached_usage(worker_usage, tenant.institution_id)
    )
    _ACTIVE_DETACHED_TELEMETRY_TASKS.add(bg_task)
    bg_task.add_done_callback(_ACTIVE_DETACHED_TELEMETRY_TASKS.discard)
```

### 3.3 Graceful Subsystem Quiescence
```python
async def wait_for_ml_quiescence(timeout: float = 5.0) -> None:
    active = list(_ACTIVE_ML_INFERENCE_TASKS | _ACTIVE_WORKSHEET_TASKS | _ACTIVE_DETACHED_TELEMETRY_TASKS)
    if not active:
        return
    logger.info("[ML Router] Awaiting quiescence for %d active ML/telemetry tasks...", len(active))
    try:
        await asyncio.wait_for(
            asyncio.gather(*active, return_exceptions=True),
            timeout=timeout,
        )
    except TimeoutError:
        logger.warning("[ML Router] Shutdown timeout reached with active tasks still executing in thread pool.")
```

### 3.4 Endpoint Integration Matrix
All 6 inference endpoints were transitioned from `async with ml_inference_capacity_scope():` to `await run_with_inference_capacity(...)`:
1. `GET /ml/predict/at-risk/{student_id}`
2. `GET /ml/predict/at-risk-admin/{student_id}`
3. `GET /ml/explain/at-risk/{student_id}`
4. `GET /ml/predict/weak-topics/{student_id}`
5. `GET /ml/diagnose/{student_id}`
6. `GET /ml/diagnose-with-recommendations/{student_id}`

The `ml_inference_capacity_scope()` async context manager is retained for backward compatibility.

---

## 4. Empirical Test Verification

### 4.1 New Test Suite (`TestMLInferencePhysicalWorkerLifecycle`)
Added to `backend/tests/test_ml_router_and_inference_hardening.py`:

| Test Name | Verification Objective | Mechanism |
|---|---|---|
| `test_physical_thread_retains_semaphore_permit_under_cancellation` | Verifies semaphore permit is held across caller cancellation until real OS thread completes. | Uses `threading.Event`, `asyncio.to_thread`, asserts `sem._value == 0` after cancel, asserts concurrent request rejected with HTTP 503, unblocks event, asserts `sem._value == 1`. |
| `test_endpoint_cancellation_preserves_semaphore_until_thread_completes` | Verifies HTTP endpoint `/ml/predict/at-risk/{student_id}` retains permit when request task is cancelled. | Mocks underlying inference with blocking thread, cancels HTTP client request task, asserts permit retained, verifies second request receives 503, unblocks, verifies subsequent request succeeds (200 OK). |
| `test_detached_telemetry_strong_reference_retention` | Verifies background telemetry tasks are tracked in `_ACTIVE_DETACHED_TELEMETRY_TASKS` until execution ends. | Creates paused background task, asserts inclusion in active registry, releases pause event, awaits task, asserts clean removal. |
| `test_wait_for_ml_quiescence_lifecycle` | Verifies `wait_for_ml_quiescence` awaits active inference and worksheet tasks. | Registers tasks in `_ACTIVE_ML_INFERENCE_TASKS` and `_ACTIVE_WORKSHEET_TASKS`, calls `wait_for_ml_quiescence(timeout=1.0)`, asserts all tasks drained to 0. |

### 4.2 Comprehensive Test Execution Matrix

| Test Suite | Purpose | Tests | Result | Runtime |
|---|---|:---:|:---:|:---:|
| `test_ml_router_and_inference_hardening.py` | Full ML router hardening + physical worker lifecycle suite | 30 | **PASS** | 2.86s |
| `test_ml_worksheet_generator.py` | Worksheet generator guardrails, provider failover, PDF rendering | 29 | **PASS** | 9.80s |
| `test_ml_diagnostics_idor.py` | ML diagnostic authorization, IDOR, timetable RBAC | 47 | **PASS** | 2.20s |
| **Combined ML Subsystem Suite** | **Total ML tests** | **106** | **PASS** | **14.86s** |

### 4.3 Preservation & Regression Matrix (Stages 1, 2R, 3)

| Test Suite | Scope | Tests | Result | Runtime |
|---|---|:---:|:---:|:---:|
| `test_admin_assistant_hardening_and_timeouts.py` | Stage 3 Admin Assistant timeouts, worker pool, lease lifecycle | 13 | **PASS** | 0.85s |
| `test_agent_hardening_and_timeouts.py` | Stage 1 & 2R Portal Assistant worker bounds, quiescence, lease safety | 22 | **PASS** | 1.15s |
| `test_agent_router_and_checkout.py` | Fencing tokens, idempotency, client turn unique index, checkout | 26 | **PASS** | 1.26s |
| **Regression Total** | **Stages 1, 2R, 3 Safety Verification** | **61** | **PASS** | **3.26s** |

### 4.4 Static Analysis
```bash
backend/venv/bin/python -m ruff check backend/app/ml/ backend/tests/test_ml_router_and_inference_hardening.py
```
**Output:** `All checks passed!` (0 lint errors).

---

## 5. Architectural Invariants Maintained

1. **Physical Thread Pool Isolation:** Physical OS worker threads running ML inference or worksheet generation never directly manipulate `asyncio.Semaphore` objects. All semaphore permits are acquired and released exclusively on the asyncio event loop thread.
2. **Zero Premature Capacity Release:** An awaiting client disconnection, gateway timeout, or cancellation cannot prematurely restore capacity while an OS thread continues executing. Capacity is restored if and only if the underlying worker reaches completion.
3. **No Reference Leaks:** Detached background tasks retain strong references in memory sets until task completion, preventing garbage collection by Python's runtime during event-loop yields.
4. **Preservation of Accepted Stages:**
   - `backend/app/core/worker_pool.py`: 0 changes.
   - `backend/app/agents/portal_assistant.py`: 0 changes.
   - `backend/app/agents/admin_assistant.py`: 0 changes.
   - `backend/app/agents/task_registry.py`: 0 changes.
   - `backend/app/agents/session_store.py`: 0 changes.
5. **Zero Git Modifications:** No commits, pushes, merges, stashes, or branch switches performed.
6. **Bounded Scope:** Stage 5 has strictly NOT been started.

