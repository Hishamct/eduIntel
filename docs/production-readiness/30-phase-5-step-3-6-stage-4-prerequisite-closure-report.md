# EduIntel — Phase 5 Step 3.6 Stage 4 Prerequisite Closure Report
## Final Production Prerequisite Closure: Lifespan Quiescence & Legacy Scope Retirement

**Parent Roadmap:** Phase 05 – Step 3 (Sub-Step 3.6: LangGraph Agent Hardening)  
**Parent Specification:** `docs/production-readiness/14-phase-5-ai-safety-and-governance-plan.md` (§3, Item 6)  
**Concurrency Remediation Report:** `docs/production-readiness/29-phase-5-step-3-6-stage-4-concurrency-remediation-report.md`  
**Accepted Implementation Plan:** `Hisham-workspace/05-ai-and-ml/step-3-6-implementation-plan.md` (Version 3.1)  
**Date:** 2026-11-10  
**Status:** COMPLETE (Ready for Final Independent Acceptance Audit)

---

## 1. Executive Summary

The independent concurrency remediation audit evaluated the physical worker lifecycle and semaphore capacity controls implemented in Stage 4 and returned a verdict of **CONDITIONALLY ACCEPTED**.

The audit identified two remaining operational prerequisites required before Stage 4 can achieve full production acceptance:
1. **PREREQ-3.6-S4-01**: `wait_for_ml_quiescence()` was implemented and verified in the router module but was not integrated into the FastAPI application `lifespan` shutdown handler in `backend/app/main.py`. As a result, server termination (e.g., during deployments or pod restarts) did not trigger graceful draining of in-flight ML inference threads, worksheet compilation workers, or detached telemetry tasks.
2. **PREREQ-3.6-S4-02**: The unsafe legacy context manager `ml_inference_capacity_scope()` remained exposed in `backend/app/ml/router.py`. While unused in EduIntel production routes, its presence created a dangerous trap for future developers who might assume it was cancellation-safe.

This engineering effort resolves both prerequisites completely:
- Integrated `wait_for_ml_quiescence(timeout=5.0)` into the `backend/app/main.py` `lifespan` teardown sequence with defensive non-fatal exception handling.
- Hardened `wait_for_ml_quiescence` using non-cancelling `asyncio.wait(active, timeout=timeout)` so that reaching the shutdown deadline never prematurely cancels underlying OS worker threads or releases their semaphore permits.
- Formally retired `ml_inference_capacity_scope()`, converting it into an explicit `RuntimeError` failure boundary that instructs callers to adopt `run_with_inference_capacity()`.
- Added 7 comprehensive lifespan and deprecation tests in `backend/tests/test_ml_router_and_inference_hardening.py` covering all required shutdown and worker lifecycle edge cases.
- Validated 100% green test passes across all ML suites (113/113) and regression suites (61/61) with zero ruff lint errors and strict preservation of all protected files.

---

## 2. Prerequisite Remediation Details

### 2.1 PREREQ-3.6-S4-01: FastAPI Lifespan Integration & Quiescence Hardening

#### Implementation in `backend/app/main.py`
In `backend/app/main.py`, the `lifespan` context manager handles startup and shutdown hooks for the FastAPI application. The ML quiescence drain was integrated immediately after the `yield` statement:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1. Startup: Validate guardrail regex patterns (ADR-0010)
    ...
    # 2. Startup: Verify unprivileged database role
    ...
    yield

    # 3. Shutdown sequence: Graceful ML & Telemetry Quiescence (Phase 5 Step 3.6 Stage 4)
    try:
        from app.ml.router import wait_for_ml_quiescence

        await wait_for_ml_quiescence(timeout=5.0)
    except Exception as exc:
        logger.warning("[shutdown] Non-fatal error during ML quiescence drain: %s", exc)
```

#### Non-Cancelling Shutdown Quiescence in `backend/app/ml/router.py`
The drain helper was hardened to use `asyncio.wait` rather than `asyncio.wait_for(asyncio.gather(...))`. In Python asyncio, `wait_for` cancels its child future on timeout, which in turn cancels gathered tasks. Cancelling a worker task during shutdown would prematurely execute its done callback, releasing the semaphore permit while the underlying OS thread is still executing in the thread pool.

By utilizing `asyncio.wait(active, timeout=timeout)`, pending tasks are **not cancelled** when the deadline expires:

```python
async def wait_for_ml_quiescence(timeout: float = 5.0) -> int:
    """
    Waits up to `timeout` seconds for active ML inference, worksheet generation,
    and detached telemetry tasks to reach physical completion during shutdown.
    Returns the count of tasks that did not complete before the timeout (0 if clean).
    Does NOT claim that physical threads have terminated if the deadline expired.
    """
    active = set(_ACTIVE_ML_INFERENCE_TASKS | _ACTIVE_WORKSHEET_TASKS | _ACTIVE_DETACHED_TELEMETRY_TASKS)
    if not active:
        logger.info("[ML Router] Shutdown quiescence: 0 active ML/telemetry tasks.")
        return 0
    logger.info(
        "[ML Router] Awaiting shutdown quiescence for %d active ML/telemetry tasks (timeout=%.1fs)...",
        len(active),
        timeout,
    )
    done, pending = await asyncio.wait(active, timeout=timeout)
    for t in done:
        if not t.cancelled():
            _ = t.exception()

    if not pending:
        logger.info("[ML Router] Shutdown quiescence achieved: all %d tasks completed cleanly.", len(active))
        return 0

    logger.warning(
        "[ML Router] Shutdown quiescence deadline (%.1fs) reached with %d task(s) still executing in thread pool. "
        "Underlying OS worker threads remain running and are not forcibly terminated.",
        timeout,
        len(pending),
    )
    return len(pending)
```

**Key Invariants:**
1. **Thread Truthfulness:** The logger explicitly records that underlying OS worker threads continue executing in the thread pool and are not forcibly terminated.
2. **Non-Fatal Resilience:** Any exception during shutdown logging or draining is logged as a warning and never raises out of `lifespan`, allowing the application process to terminate cleanly.
3. **No Premature Permit Release:** If a worker thread is still running after 5 seconds, its task remains in `_ACTIVE_ML_INFERENCE_TASKS` and its semaphore permit remains held until the OS thread physically completes.

---

### 2.2 PREREQ-3.6-S4-02: Legacy Context Manager Retirement

#### Implementation in `backend/app/ml/router.py`
All production routes in `backend/app/ml/router.py` were already refactored to execute via `run_with_inference_capacity()`. To prevent accidental reintroduction of the unsafe pattern, `ml_inference_capacity_scope()` was retired:

```python
@asynccontextmanager
async def ml_inference_capacity_scope():
    """
    DEPRECATED & RETIRED in Phase 5 Step 3.6 Stage 4.

    Context-manager scoping cannot safely retain physical worker capacity under
    caller cancellation when operations execute in background OS threads.
    Use `await run_with_inference_capacity(coro_or_func, *args, **kwargs)` instead.
    """
    raise RuntimeError(
        "ml_inference_capacity_scope() has been retired because context-manager scoping "
        "cannot guarantee physical worker capacity retention under asyncio cancellation. "
        "Use run_with_inference_capacity() instead."
    )
    yield  # pragma: no cover
```

Attempting to enter this context manager immediately raises a descriptive `RuntimeError`. A dedicated unit test asserts this behavior.

---

## 3. Verification & Test Evidence

### 3.1 Test Coverage Additions

Seven new unit tests were added to `backend/tests/test_ml_router_and_inference_hardening.py`:

| Class | Test Name | Purpose / Invariant Verified |
| :--- | :--- | :--- |
| `TestMLInferencePhysicalWorkerLifecycle` | `test_legacy_context_manager_retired_and_raises_runtime_error` | Proves calling `async with ml_inference_capacity_scope():` raises `RuntimeError` pointing to `run_with_inference_capacity`. |
| `TestFastAPIShutdownLifespanQuiescence` | `test_lifespan_shutdown_with_no_active_ml_operations` | Verifies clean shutdown return (0 tasks) when no ML operations are executing. |
| `TestFastAPIShutdownLifespanQuiescence` | `test_lifespan_shutdown_with_active_inference_worker` | Verifies lifespan shutdown waits for active OS inference thread to finish before exiting. |
| `TestFastAPIShutdownLifespanQuiescence` | `test_lifespan_shutdown_with_active_worksheet_worker` | Verifies lifespan shutdown awaits and drains active worksheet generator task from `_ACTIVE_WORKSHEET_TASKS`. |
| `TestFastAPIShutdownLifespanQuiescence` | `test_lifespan_shutdown_with_detached_telemetry_running` | Verifies lifespan shutdown awaits and drains background telemetry task from `_ACTIVE_DETACHED_TELEMETRY_TASKS`. |
| `TestFastAPIShutdownLifespanQuiescence` | `test_lifespan_shutdown_worker_still_running_after_deadline` | Verifies deadline expiration times out gracefully, does NOT cancel the thread, and keeps the task in `_ACTIVE_ML_INFERENCE_TASKS` until it physically completes. |
| `TestFastAPIShutdownLifespanQuiescence` | `test_lifespan_shutdown_cleanup_callbacks_and_task_registries_after_completion` | Verifies callbacks fire and registries drain to 0 when tasks complete during lifespan shutdown. |

### 3.2 Test Results Summary

1. **ML Router & Inference Hardening Suite (`tests/test_ml_router_and_inference_hardening.py`)**:
   - **37/37 PASSED** in 3.91s (100% green).
2. **ML Worksheet Generator Suite (`tests/test_ml_worksheet_generator.py`)**:
   - **29/29 PASSED** in 12.10s (100% green).
3. **ML Diagnostics IDOR Suite (`tests/test_ml_diagnostics_idor.py`)**:
   - **47/47 PASSED** in 3.53s (100% green).
4. **Total Stage 4 ML Hardening Tests:**
   - **113/113 PASSED** (0 failures, 0 errors).
5. **Stage 1, 2R, and 3 Regression Suites:**
   - `tests/test_admin_assistant_hardening_and_timeouts.py`: **13/13 PASSED** in 2.19s.
   - `tests/test_agent_hardening_and_timeouts.py`: **22/22 PASSED** in 1.45s.
   - `tests/test_agent_router_and_checkout.py`: **26/26 PASSED** in 0.94s.
   - Total Regression Suite: **61/61 PASSED** (100% green).
6. **Code Formatting & Linting (`ruff check`)**:
   - `backend/app/main.py`: 0 errors.
   - `backend/app/ml/router.py`: 0 errors.
   - `backend/tests/test_ml_router_and_inference_hardening.py`: 0 errors.

---

## 4. Preservation of Architectural Invariants

- **Protected Core Worker Infrastructure:** `backend/app/core/worker_pool.py` was **strictly untouched** (0 modifications).
- **Protected Agent Core:** `backend/app/agents/portal_assistant.py`, `backend/app/agents/admin_assistant.py`, `backend/app/agents/task_registry.py`, and `backend/app/agents/session_store.py` were **strictly untouched** (0 modifications).
- **No Git State Mutation:** Zero commits created, zero branches created, zero pushes executed.
- **Stage 5 Isolation:** Stage 5 (Teacher Assistant Hardening) remains strictly unstarted.

---

## 5. Conclusion & Audit Readiness

Both prerequisite findings (`PREREQ-3.6-S4-01` and `PREREQ-3.6-S4-02`) have been fully resolved and verified with empirical real-thread tests. Phase 5 Step 3.6 Stage 4 is now ready for final independent acceptance audit.

