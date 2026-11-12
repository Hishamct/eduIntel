# EduIntel — Phase 5 Step 3.6 Stage 4R Remediation Report
## Shutdown Quiescence Remediation & Concurrency Admission Hardening

**Parent Roadmap:** Phase 05 – Step 3 (Sub-Step 3.6: LangGraph Agent Hardening)  
**Parent Specification:** `docs/production-readiness/14-phase-5-ai-safety-and-governance-plan.md` (§3, Item 6)  
**Previous Implementation Report:** `docs/production-readiness/30-phase-5-step-3-6-stage-4-prerequisite-closure-report.md`  
**Previous Audit Reference:** `Hisham-workspace/05-ai-and-ml/step-3-6-stage-4-final-acceptance-audit.md` (Verdict: NOT ACCEPTED)  
**Date:** 2026-11-10  
**Status:** COMPLETE (Awaiting Final Independent Acceptance Audit)

---

## 1. Executive Summary

The independent final acceptance audit of Stage 4 prerequisite closure issued a **NOT ACCEPTED** verdict due to a demonstrated shutdown race in `wait_for_ml_quiescence()`. While PREREQ-3.6-S4-01 (FastAPI lifespan hook) and PREREQ-3.6-S4-02 (legacy context manager retirement) were verified, the audit demonstrated:
1. **Single-Snapshot Quiescence Leak:** The shutdown drain in `backend/app/ml/router.py:wait_for_ml_quiescence()` took only a single snapshot of active task registries at entry. When an in-flight worksheet worker completed during the drain window, its done callback (`_on_worker_task_done`) spawned a detached telemetry task (`_persist_background_detached_usage`) into `_ACTIVE_DETACHED_TELEMETRY_TASKS`. Because the initial snapshot completed with the parent worker, `wait_for_ml_quiescence()` returned `0` (clean quiescence reported) while the background telemetry write was still running. Subsequent event loop closure by Uvicorn truncated database writes.
2. **Absence of Shutdown Admission Gate:** New inference or worksheet generation requests arriving while shutdown was in progress were admitted and registered after the initial snapshot, escaping the drain.
3. **Cross-Test Contamination & Pytest Deadlock:** During randomized test execution (`pytest-randomly`), testing shutdown quiescence set `_ML_SHUTDOWN_IN_PROGRESS = True` in process memory. Unbounded `while not started_event.is_set(): await asyncio.sleep(0.01)` loops in subsequent tests waited indefinitely because workers were rejected with HTTP 503 before starting.

This engineering effort (Stage 4R) completely remediates all three findings:
- Replaced the single-snapshot quiescence wait with an **iterative, deadline-bounded drain loop** that repeatedly inspects all three task registries until all are empty or the shared deadline expires.
- Implemented a **two-phase shutdown admission gate** (`_ML_SHUTDOWN_IN_PROGRESS`) in `run_with_inference_capacity()` and `generate_worksheet()` that rejects new admissions with HTTP 503 (`Retry-After: 5`) and releases semaphore slots if shutdown begins while awaiting acquisition.
- Implemented **cross-test fixture isolation** and **defensive asynchronous test waits** with bounded timeouts that fail fast and surface task exceptions immediately upon admission failure.
- Verified 100% green test passes across all 120 ML hardening tests (44/44 in router hardening, 29/29 in worksheet generator, 47/47 in IDOR diagnostics) and 61/61 regression tests across Stages 1–3, with 0 ruff lint errors and strict preservation of all protected files.

---

## 2. Root Cause Analysis & Demonstrated Flaws

### 2.1 The Single-Snapshot Quiescence Flaw
In the initial Stage 4 implementation, `wait_for_ml_quiescence()` executed:
```python
# Unsafe single-snapshot drain (OLD)
active = set(_ACTIVE_ML_INFERENCE_TASKS | _ACTIVE_WORKSHEET_TASKS | _ACTIVE_DETACHED_TELEMETRY_TASKS)
done, pending = await asyncio.wait(active, timeout=timeout)
return len(pending)
```
When a worksheet generation task was active at shutdown start, it was included in `active`. When that worker finished its CPU/IO work in the thread pool, its done callback scheduled:
```python
bg_task = asyncio.create_task(_persist_background_detached_usage(worker_usage, tenant.institution_id))
_ACTIVE_DETACHED_TELEMETRY_TASKS.add(bg_task)
```
Because `active` was a static snapshot taken at function entry, `bg_task` was absent from `active`. When the parent task finished, `asyncio.wait(active)` returned `done={parent_task}`, `pending=set()`, and `wait_for_ml_quiescence()` reported `0` pending tasks even though `bg_task` was actively executing in `_ACTIVE_DETACHED_TELEMETRY_TASKS`.

### 2.2 Unbounded Test Waits and Flag Leakage
When a shutdown test activated `_ML_SHUTDOWN_IN_PROGRESS = True`, the flag persisted across tests within the same pytest process. When `pytest-randomly` executed `test_physical_thread_retains_semaphore_permit_under_cancellation` next, the test called:
```python
worker_task = asyncio.create_task(run_with_inference_capacity(slow_worker))
while not started_event.is_set():
    await asyncio.sleep(0.01)
```
Because the shutdown gate was active, `run_with_inference_capacity()` immediately raised `HTTPException(503)` and never invoked `slow_worker`. The worker thread never started, `started_event.set()` was never called, and the unbounded `while` loop spun forever, locking up pytest for over 20 minutes until manual intervention.

---

## 3. Remediation Implementation Details

### 3.1 Iterative, Deadline-Bounded Drain Loop (`backend/app/ml/router.py`)
`wait_for_ml_quiescence()` was completely redesigned to iteratively drain all active tasks against a single absolute monotonic deadline:

```python
async def wait_for_ml_quiescence(timeout: float = 5.0) -> int:
    """
    Waits iteratively up to `timeout` seconds for active ML inference, worksheet generation,
    and detached telemetry tasks to reach physical completion during shutdown.
    Activates `_ML_SHUTDOWN_IN_PROGRESS = True` before the first drain snapshot to reject
    new incoming admissions.
    Re-inspects task registries across iterations to ensure tasks scheduled by completion
    callbacks (such as detached telemetry) are completely drained.
    Returns the count of tasks that did not complete before the timeout (0 if clean).
    Does NOT cancel pending tasks or claim that physical threads have terminated if the deadline expired.
    """
    global _ML_SHUTDOWN_IN_PROGRESS
    _ML_SHUTDOWN_IN_PROGRESS = True

    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    iteration = 0

    while True:
        active = set(_ACTIVE_ML_INFERENCE_TASKS | _ACTIVE_WORKSHEET_TASKS | _ACTIVE_DETACHED_TELEMETRY_TASKS)
        if not active:
            logger.info(
                "[ML Router] Shutdown quiescence achieved: all task registries empty (iterations=%d).",
                iteration,
            )
            return 0

        remaining_time = deadline - loop.time()
        if remaining_time <= 0:
            logger.warning(
                "[ML Router] Shutdown quiescence deadline (%.1fs) reached with %d task(s) still executing in thread pool "
                "(inference=%d, worksheet=%d, telemetry=%d). "
                "Underlying OS worker threads remain running and are not forcibly terminated.",
                timeout,
                len(active),
                len(_ACTIVE_ML_INFERENCE_TASKS),
                len(_ACTIVE_WORKSHEET_TASKS),
                len(_ACTIVE_DETACHED_TELEMETRY_TASKS),
            )
            return len(active)

        iteration += 1
        logger.info(
            "[ML Router] Shutdown quiescence iteration %d: awaiting %d active task(s) (remaining=%.2fs)...",
            iteration,
            len(active),
            remaining_time,
        )

        done, pending = await asyncio.wait(active, timeout=remaining_time)
        for t in done:
            if not t.cancelled():
                _ = t.exception()
```

**Key Architectural Invariants:**
1. **Single Monotonic Deadline:** `deadline = loop.time() + timeout` is calculated once. Each iteration computes `remaining_time = deadline - loop.time()`. The timeout never resets or extends between iterations.
2. **Dynamic Registry Re-Inspection:** On every loop turn, `active = set(...)` re-evaluates the union of all 3 registries. If a completion callback adds a new detached telemetry task to `_ACTIVE_DETACHED_TELEMETRY_TASKS`, it is captured and awaited on the subsequent iteration.
3. **Clean Quiescence Verification:** Quiescence returns `0` if and only if all three registries are genuinely empty (`not active`).
4. **Non-Cancelling Safety:** If the deadline expires, pending tasks are not cancelled, and worker threads are not aborted. Remaining counts are logged accurately.

### 3.2 Two-Phase Shutdown Admission Gate (`backend/app/ml/router.py`)
To prevent race conditions where incoming HTTP requests are admitted during the shutdown window:
1. `_ML_SHUTDOWN_IN_PROGRESS: bool = False` is set to `True` at the entry of `wait_for_ml_quiescence()`.
2. In `run_with_inference_capacity()`:
   - Checked immediately before attempting `ML_INFERENCE_SEMAPHORE.acquire()`.
   - Checked again immediately after acquiring the semaphore slot. If shutdown initiated while the coroutine was waiting in the semaphore queue, the permit is immediately released via `ML_INFERENCE_SEMAPHORE.release()` and HTTP 503 is returned with `Retry-After: 5`.
3. In `generate_worksheet()`:
   - Checked immediately before attempting `WORKSHEET_GENERATION_SEMAPHORE.acquire()`.
   - Checked again immediately after acquiring the semaphore slot. If shutdown initiated while waiting in the queue, the permit is released via `WORKSHEET_GENERATION_SEMAPHORE.release()` and HTTP 503 is returned with `Retry-After: 5`.
4. A dedicated reset helper `_reset_ml_shutdown_state_for_testing()` is provided for deterministic test fixture teardown.

### 3.3 Test Suite Isolation & Defensive Wait Harness (`backend/tests/test_ml_router_and_inference_hardening.py`)
1. **Module-Level Auto-Use Fixture:**
   ```python
   @pytest.fixture(autouse=True)
   def reset_ml_shutdown_state_module_fixture():
       _reset_ml_shutdown_state_for_testing()
       yield
       _reset_ml_shutdown_state_for_testing()
   ```
   Ensures that every test begins and ends with `_ML_SHUTDOWN_IN_PROGRESS = False`, eliminating test-ordering side effects under `pytest-randomly`.

2. **Defensive Asynchronous Wait Helper:**
   Replaced all unbounded `while not started_event.is_set(): await asyncio.sleep(0.01)` loops with `assert_event_set_within`:
   ```python
   async def assert_event_set_within(
       event: threading.Event,
       task: asyncio.Task | None = None,
       timeout: float = 3.0,
       description: str = "worker startup",
   ) -> None:
       loop = asyncio.get_running_loop()
       deadline = loop.time() + timeout
       while not event.is_set():
           if task is not None and task.done():
               exc = task.exception()
               if exc:
                   raise RuntimeError(
                       f"Worker admission aborted prematurely because task failed: {exc}"
                   ) from exc
               raise RuntimeError("Worker task completed before setting event.")
           if loop.time() >= deadline:
               raise TimeoutError(f"Timed out after {timeout}s waiting for {description}.")
           await asyncio.sleep(0.01)
   ```
   If a task is rejected during admission (e.g. HTTP 503), the helper detects `task.done()` immediately and raises an actionable `RuntimeError` rather than hanging indefinitely.

---

## 4. Verification Evidence

### 4.1 Test Suites Executed

| Test Suite File | Tests | Status | Execution Time |
| :--- | :---: | :---: | :---: |
| `tests/test_ml_router_and_inference_hardening.py` | 44 | **PASSED** | 3.82s |
| `tests/test_ml_worksheet_generator.py` | 29 | **PASSED** | (Combined with IDOR) |
| `tests/test_ml_diagnostics_idor.py` | 47 | **PASSED** | 13.65s (76 total) |
| `tests/test_admin_assistant_hardening_and_timeouts.py` | 13 | **PASSED** | (Combined regression) |
| `tests/test_agent_hardening_and_timeouts.py` | 22 | **PASSED** | (Combined regression) |
| `tests/test_agent_router_and_checkout.py` | 26 | **PASSED** | 3.74s (61 total) |
| **Total Test Verification** | **181** | **ALL PASSED** | **100% Green** |

### 4.2 New Tests Added in Stage 4R
1. `test_composite_worksheet_worker_to_telemetry_quiescence_race`: Empirically simulates a worksheet worker that completes during the drain and spawns detached telemetry. Confirms the iterative loop waits for both the parent worker and the spawned telemetry task, achieving clean quiescence (`returns 0`, `0 tasks in registry`).
2. `test_shutdown_admission_gate_rejects_new_inference_admissions`: Verifies that `run_with_inference_capacity()` rejects admissions with HTTP 503 when the shutdown gate is active.
3. `test_shutdown_admission_gate_rejects_new_worksheet_admissions`: Verifies that `generate_worksheet()` rejects admissions with HTTP 503 when the shutdown gate is active.
4. `TestStage4RShutdownIsolationAndDefensiveWaits`:
   - `test_shutdown_flag_does_not_contaminate_next_test_stage_a`: Sets shutdown flag during test.
   - `test_shutdown_flag_does_not_contaminate_next_test_stage_b`: Verifies flag was cleanly reset before the next test executed.
   - `test_rejected_worker_surfaces_immediately_without_unbounded_loop`: Verifies that `assert_event_set_within` immediately raises when an admitted task fails with 503.
   - `test_existing_shutdown_admission_rejection_when_gate_is_active`: Directly exercises admission rejection under an active gate.

### 4.3 Static Analysis
- **Tool:** `backend/venv/bin/python -m ruff check backend/app/main.py backend/app/ml/ backend/tests/test_ml_router_and_inference_hardening.py`
- **Output:** `All checks passed!` (0 lint errors).

---

## 5. Protected Files & Scope Integrity

The following protected files from Stages 1–3 were verified to be **strictly untouched** during Stage 4 and Stage 4R:

| File Path | Stage Accepted | Status in Stage 4R |
| :--- | :--- | :--- |
| `backend/app/core/worker_pool.py` | Stage 1 | **Untouched** (0 lines changed) |
| `backend/app/agents/portal_assistant.py` | Stage 2R | **Untouched** (0 lines changed) |
| `backend/app/agents/admin_assistant.py` | Stage 3 | **Untouched** (0 lines changed) |
| `backend/app/agents/task_registry.py` | Stage 2R | **Untouched** (0 lines changed) |
| `backend/app/agents/session_store.py` | Stage 1 | **Untouched** (0 lines changed) |

Additional scope invariants:
- Zero database migrations introduced.
- Zero Git commits or pushes executed.
- Stage 5 strictly unstarted.

---

## 6. Readiness for Independent Acceptance Audit

All remediation requirements specified in the Stage 4 Final Acceptance Audit have been resolved:
- Demonstrated quiescence race condition eliminated via iterative multi-cycle drain.
- Shutdown admission gate verified and active.
- Cross-test fixture isolation and defensive waits established.
- All test suites passing with 100% reproducibility.

Stage 4R is now submitted for independent, read-only final acceptance audit.

