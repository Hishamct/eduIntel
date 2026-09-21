"""
app/observability/tracing.py

Lightweight LangGraph node tracing: a decorator that times each node in
admin_assistant_graph / portal_assistant_graph and appends a step record to
the graph's own state, so the whole run's step-by-step path travels with
the state and can be persisted once the graph finishes (see
app/observability/service.py: log_agent_trace).

Why state, not a direct db write from inside the node: LangGraph node
functions (decide_tools_node, generate_node, etc.) are plain sync/async
functions with no db session passed in — the same reason
generate_text_with_usage()'s LLMCallUsage is threaded through state instead
of logged from inside llm_client.py. Tracing follows that same established
pattern rather than inventing a new one: compute/accumulate in the agent,
log via db once a session is available in the router.

Known limitation (worth knowing, not a bug): if a node raises, LangGraph
aborts the whole graph.invoke()/ainvoke() call and no state is returned at
all — so a crashed run currently produces no trace, the same as before
tracing existed. Nothing is worse off; a full "partial trace on crash"
would need LangGraph's own error-branch handling, which is more than this
capstone-scope feature needs.
"""

import functools
import inspect
import time
from collections.abc import Callable


def traced_node(node_name: str) -> Callable:
    """
    Decorator for a LangGraph node function — works on both sync (def) and
    async (async def) node functions, since this codebase has both
    (decide_tools_node/generate_node are sync, execute_tools_node is async).

    Appends one step dict to the returned state's "trace_steps" list:
        {"node_name": str, "step_order": int, "duration_ms": int, "status": "ok"}

    step_order is just len(prior steps) — so steps come out in run order
    without needing a separate counter threaded through state.
    """

    def decorator(fn: Callable) -> Callable:
        if inspect.iscoroutinefunction(fn):

            @functools.wraps(fn)
            async def async_wrapper(state: dict) -> dict:
                started_at = time.monotonic()
                new_state = await fn(state)
                duration_ms = round((time.monotonic() - started_at) * 1000)
                prior_steps = (
                    new_state.get("trace_steps") or state.get("trace_steps") or []
                )
                new_state["trace_steps"] = prior_steps + [
                    {
                        "node_name": node_name,
                        "step_order": len(prior_steps),
                        "duration_ms": duration_ms,
                        "status": "ok",
                    }
                ]
                return new_state

            return async_wrapper

        @functools.wraps(fn)
        def sync_wrapper(state: dict) -> dict:
            started_at = time.monotonic()
            new_state = fn(state)
            duration_ms = round((time.monotonic() - started_at) * 1000)
            prior_steps = new_state.get("trace_steps") or state.get("trace_steps") or []
            new_state["trace_steps"] = prior_steps + [
                {
                    "node_name": node_name,
                    "step_order": len(prior_steps),
                    "duration_ms": duration_ms,
                    "status": "ok",
                }
            ]
            return new_state

        return sync_wrapper

    return decorator
