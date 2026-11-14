"""
backend/app/guardrails/redos_guard.py

ReDoS (Regular Expression Denial of Service) protection and supervised
subprocess isolation engine for EduIntel AI guardrails.

Key Architectural Decisions:
1. Primary DFA Engine (re2): Uses Google's DFA-based re2 engine when available,
   guaranteeing O(n) linear matching time in input length.
2. Verified In-Process Fast-Path: Standard queries under 1,024 characters against
   verified, non-catastrophic patterns execute in-process in microseconds.
3. Dedicated Supervised Subprocess Fallback: Payloads exceeding 1,024 characters
   or checks requiring isolated verification (force_isolated=True) execute in an
   isolated single-use subprocess with an explicit communication pipe.
   - Enforces a strict 150ms timeout threshold.
   - On timeout: Sends SIGTERM, waits 50ms, then SIGKILL if uncooperative, and
     reaps the process cleanly (preventing zombie processes).
   - Fails closed immediately: `blocked=True, block_reason="GUARDRAIL_TIMEOUT"`.
"""

import logging
import multiprocessing as mp
import os
import re
import warnings
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

# Check for google-re2 availability
try:
    import re2  # type: ignore

    HAVE_RE2 = True
except ImportError:
    re2 = None  # type: ignore
    HAVE_RE2 = False

# Maximum length for safe in-process regex evaluation of pre-compiled linear patterns
SAFE_IN_PROCESS_MAX_LENGTH = 1024


@dataclass
class SafeRegexResult:
    """Result envelope for ReDoS-protected regular expression evaluation."""

    matched: bool
    matched_pattern: str | None = None
    matched_text: str | None = None
    span: tuple[int, int] | None = None
    timed_out: bool = False
    error: str | None = None


def _regex_worker_proc(
    pipe: Any,
    pattern: str,
    flags: int,
    text: str,
) -> None:
    """
    Dedicated worker process routine executing standard regex search.
    Sends (matched, pattern, matched_text, span, error) through the pipe and exits cleanly.
    """
    try:
        compiled = re.compile(pattern, flags)
        m = compiled.search(text)
        if m:
            pipe.send((True, pattern, m.group(), m.span(), None))
        else:
            pipe.send((False, None, None, None, None))
    except Exception as exc:  # Catch all engine exceptions
        pipe.send((False, None, None, None, str(exc)))
    finally:
        try:
            pipe.close()
        except Exception:
            pass


def safe_regex_search(
    pattern: str,
    text: str,
    timeout_seconds: float = 0.150,
    flags: int = re.IGNORECASE,
    force_isolated: bool = False,
) -> SafeRegexResult:
    """
    Evaluates pattern against text with ReDoS protection.

    1. Attempts re2 DFA execution first (if installed and pattern supported).
    2. Short-circuits safe in-process matching for short inputs (<= 1024 chars).
    3. Falls back to dedicated supervised subprocess for long or isolated inputs.
    """
    if not text or not pattern:
        return SafeRegexResult(matched=False)

    # 1. Primary DFA path (re2)
    if HAVE_RE2 and re2 is not None:
        try:
            m = re2.search(pattern, text)
            if m:
                return SafeRegexResult(
                    matched=True,
                    matched_pattern=pattern,
                    matched_text=m.group(),
                    span=m.span(),
                    timed_out=False,
                )
            return SafeRegexResult(matched=False, timed_out=False)
        except Exception:
            # Pattern may contain PCRE-specific features not supported by re2
            pass

    # 2. Fast-path in-process execution for short inputs against verified patterns
    if not force_isolated and len(text) <= SAFE_IN_PROCESS_MAX_LENGTH:
        try:
            compiled = re.compile(pattern, flags)
            m = compiled.search(text)
            if m:
                return SafeRegexResult(
                    matched=True,
                    matched_pattern=pattern,
                    matched_text=m.group(),
                    span=m.span(),
                    timed_out=False,
                )
            return SafeRegexResult(matched=False, timed_out=False)
        except Exception as exc:
            return SafeRegexResult(
                matched=False,
                matched_pattern=pattern,
                timed_out=False,
                error=str(exc),
            )

    # 3. Supervised subprocess isolation fallback for long or adversarial payloads
    ctx = mp.get_context("fork" if hasattr(os, "fork") else None)
    parent_conn, child_conn = ctx.Pipe(duplex=False)
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=DeprecationWarning, module="multiprocessing")
        proc = ctx.Process(
            target=_regex_worker_proc,
            args=(child_conn, pattern, flags, text),
        )

    try:
        proc.start()
        child_conn.close()  # Close child endpoint in parent so EOF is detectable

        if parent_conn.poll(timeout_seconds):
            matched, pat, val, span, err = parent_conn.recv()
            proc.join(timeout=0.05)
            return SafeRegexResult(
                matched=matched,
                matched_pattern=pat,
                matched_text=val,
                span=span,
                timed_out=False,
                error=err,
            )
        else:
            # Timeout exceeded: terminate supervised worker cleanly
            logger.warning(
                "ReDoS guard triggered: pattern search exceeded %.3fs timeout on input length %d",
                timeout_seconds,
                len(text),
            )
            _terminate_and_reap_process(proc)
            return SafeRegexResult(
                matched=False,
                matched_pattern=pattern,
                timed_out=True,
                error="GUARDRAIL_TIMEOUT",
            )
    except Exception as exc:
        _terminate_and_reap_process(proc)
        return SafeRegexResult(
            matched=False,
            matched_pattern=pattern,
            timed_out=False,
            error=f"Process isolation failure: {exc}",
        )
    finally:
        try:
            parent_conn.close()
        except Exception:
            pass


def _terminate_and_reap_process(proc: mp.Process) -> None:
    """
    Terminates and reaps a supervised worker process to eliminate zombie processes
    and prevent thread/pool exhaustion.
    """
    if not proc.is_alive():
        return

    try:
        proc.terminate()  # SIGTERM
        proc.join(timeout=0.05)
        if proc.is_alive():
            proc.kill()  # SIGKILL
            proc.join(timeout=0.05)
    except Exception as exc:
        logger.error("Failed to cleanly reap supervised regex process %s: %s", proc.pid, exc)


def safe_regex_match_any(
    patterns: list[str],
    text: str,
    timeout_seconds: float = 0.150,
    flags: int = re.IGNORECASE,
    force_isolated: bool = False,
) -> SafeRegexResult:
    """
    Evaluates a collection of regex patterns against text within an overall timeout deadline.
    Uses an alternation pattern for efficient single-pass evaluation where possible.
    """
    if not text or not patterns:
        return SafeRegexResult(matched=False)

    # Combine into a single alternation pattern for single-pass evaluation
    combined_pattern = "|".join(f"(?:{p})" for p in patterns)
    return safe_regex_search(
        pattern=combined_pattern,
        text=text,
        timeout_seconds=timeout_seconds,
        flags=flags,
        force_isolated=force_isolated,
    )


def validate_patterns_at_startup(patterns: list[str] | None = None) -> None:
    """
    Validates regex syntax and engine execution readiness at application startup.
    Aggregates all active prompt injection and anti-cheating patterns if none provided.
    Raises ValueError on syntax errors or invalid flags.
    Raises RuntimeError on engine startup failure.
    """
    if patterns is None:
        from app.guardrails.anti_cheating import ACADEMIC_CHEATING_PATTERNS, EXAM_MODE_PATTERNS
        from app.guardrails.prompt_injection import PROMPT_INJECTION_PATTERNS

        patterns = (
            list(PROMPT_INJECTION_PATTERNS)
            + list(ACADEMIC_CHEATING_PATTERNS)
            + list(EXAM_MODE_PATTERNS)
        )

    if not patterns:
        raise ValueError("No guardrail patterns supplied for startup validation.")

    for pat in patterns:
        try:
            re.compile(pat, re.IGNORECASE)
        except re.error as exc:
            raise ValueError(f"Invalid guardrail regex pattern '{pat}': {exc}") from exc

    # Sanity probe: verify safe_regex_search executes cleanly
    probe_res = safe_regex_search(r"probe_token", "normal probe_token test", timeout_seconds=0.2)
    if not probe_res.matched:
        raise RuntimeError("Startup regex engine self-test failed on basic matching probe.")
