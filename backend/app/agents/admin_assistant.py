import re
import time
import uuid
from collections import OrderedDict
from datetime import date
from typing import TypedDict

from google.genai import types
from langgraph.graph import END, StateGraph
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.admin.service import (
    TenantAggregationBlockedError,
    get_attendance_stats,
    get_revenue_summary,
    get_salary_summary,
    get_student_teacher_counts,
    get_teacher_grading_performance,
    get_timetable_coverage,
)
from app.core.database import AsyncSessionLocal  # adjust if named differently
from app.core.llm_client import (
    LLMCallUsage,
    decide_tools_with_usage,
    generate_text_with_usage,
)
from app.guardrails.prompt_injection import (
    INJECTION_REFUSAL_MESSAGE,
    check_for_prompt_injection,
)
from app.observability.tracing import traced_node

SYSTEM_SCOPE = """You are the EduIntel AI Admin Assistant. You help the institute owner/admin
understand what's happening on the platform — student and teacher counts, salary/payroll status,
timetable coverage, teacher grading performance, revenue/fee collection, and attendance — without
them needing to dig through dashboards themselves.

You have tools that query real, live data. Use them whenever the question is about actual
numbers or status on the platform. Do not guess or estimate numbers yourself — only report what
the tools return.

IMPORTANT — currency: This institute operates in India. Always express monetary amounts in Indian
Rupees using the ₹ symbol (e.g. ₹42,500), never $ or USD. Use Indian-style comma grouping where
natural (e.g. ₹1,37,000 rather than ₹137,000) if you can, but ₹ with standard grouping is acceptable
too — the currency symbol is what matters most.

If the admin asks something entirely unrelated to running this institute (general chit-chat,
unrelated topics), politely decline and steer back to what you can help with."""
# --- Tool declarations Gemini sees ---
TOOL_DECLARATIONS = [
    types.FunctionDeclaration(
        name="get_student_teacher_counts",
        description="Get the total number of enrolled students and total number of teachers on the platform.",
        parameters={"type": "object", "properties": {}, "required": []},
    ),
    types.FunctionDeclaration(
        name="get_salary_summary",
        description=(
            "Get salary/payroll summary: total payout, pending vs paid counts, "
            "base/bonus/deduction totals. Optionally filter to a specific month."
        ),
        parameters={
            "type": "object",
            "properties": {
                "month": {
                    "type": "string",
                    "description": "Optional month in YYYY-MM format, e.g. '2026-08'. Omit for all-time summary.",
                },
            },
            "required": [],
        },
    ),
    types.FunctionDeclaration(
        name="get_timetable_coverage",
        description=(
            "Get timetable period counts per class section, including how many periods have "
            "no teacher assigned. Optionally filter to one class section."
        ),
        parameters={
            "type": "object",
            "properties": {
                "class_section": {
                    "type": "string",
                    "description": "Optional class section filter, e.g. '10-A'.",
                },
            },
            "required": [],
        },
    ),
    types.FunctionDeclaration(
        name="get_teacher_grading_performance",
        description=(
            "Get per-teacher homework grading stats: how many submissions each teacher has graded "
            "and their average grading turnaround time in hours."
        ),
        parameters={"type": "object", "properties": {}, "required": []},
    ),
    types.FunctionDeclaration(
        name="get_revenue_summary",
        description=(
            "Get fee/revenue summary: total collected, pending, and overdue amounts. "
            "Optionally filter to a specific month."
        ),
        parameters={
            "type": "object",
            "properties": {
                "month": {
                    "type": "string",
                    "description": "Optional month in YYYY-MM format, e.g. '2026-08'. Omit for all-time summary.",
                },
            },
            "required": [],
        },
    ),
    types.FunctionDeclaration(
        name="get_attendance_stats",
        description=(
            "Get attendance percentages overall and per class section, including "
            "present/absent/late breakdowns. Optionally filter to one class section."
        ),
        parameters={
            "type": "object",
            "properties": {
                "class_section": {
                    "type": "string",
                    "description": "Optional class section filter, e.g. '10-A'.",
                },
            },
            "required": [],
        },
    ),
]

ADMIN_TOOL = types.Tool(function_declarations=TOOL_DECLARATIONS)

# Maps tool name -> actual async function
TOOL_FUNCTIONS = {
    "get_student_teacher_counts": get_student_teacher_counts,
    "get_salary_summary": get_salary_summary,
    "get_timetable_coverage": get_timetable_coverage,
    "get_teacher_grading_performance": get_teacher_grading_performance,
    "get_revenue_summary": get_revenue_summary,
    "get_attendance_stats": get_attendance_stats,
}


# --- Strict Input Validation Schemas for Admin Reporting Tools ---

DANGEROUS_SQL_PATTERNS = re.compile(
    r"\b(SELECT|INSERT|UPDATE|DELETE|DROP|ALTER|TRUNCATE|EXEC|EXECUTE|UNION|GRANT|REVOKE|--|;)\b",
    re.IGNORECASE,
)


class StudentTeacherCountsArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SalarySummaryArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    month: date | str | None = Field(
        default=None,
        description="Optional month in YYYY-MM format, e.g. '2026-08'. Omit for all-time summary.",
    )

    @field_validator("month")
    @classmethod
    def validate_and_convert_month(cls, v: date | str | None) -> date | None:
        if v is None:
            return None
        if isinstance(v, date):
            return v
        v = str(v).strip()
        if not v:
            return None
        if DANGEROUS_SQL_PATTERNS.search(v):
            raise ValueError("SQL tokens and dangerous expressions are not permitted in arguments.")
        if not re.match(r"^\d{4}-(0[1-9]|1[0-2])$", v):
            raise ValueError("Month must be in YYYY-MM format with valid month (01-12), e.g. '2026-08'")
        year, month = v.split("-")
        return date(int(year), int(month), 1)


class TimetableCoverageArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    class_section: str | None = Field(
        default=None,
        max_length=20,
        description="Optional class section filter, e.g. '10-A'.",
    )

    @field_validator("class_section")
    @classmethod
    def validate_class_section(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = str(v).strip()
        if not v:
            return None
        if DANGEROUS_SQL_PATTERNS.search(v):
            raise ValueError("SQL tokens and dangerous expressions are not permitted in arguments.")
        if not re.match(r"^[A-Za-z0-9\-_ ]{1,20}$", v):
            raise ValueError("Class section must be alphanumeric (e.g. '10-A') and at most 20 characters.")
        return v


class TeacherGradingPerformanceArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RevenueSummaryArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    month: date | str | None = Field(
        default=None,
        description="Optional month in YYYY-MM format, e.g. '2026-08'. Omit for all-time summary.",
    )

    @field_validator("month")
    @classmethod
    def validate_and_convert_month(cls, v: date | str | None) -> date | None:
        if v is None:
            return None
        if isinstance(v, date):
            return v
        v = str(v).strip()
        if not v:
            return None
        if DANGEROUS_SQL_PATTERNS.search(v):
            raise ValueError("SQL tokens and dangerous expressions are not permitted in arguments.")
        if not re.match(r"^\d{4}-(0[1-9]|1[0-2])$", v):
            raise ValueError("Month must be in YYYY-MM format with valid month (01-12), e.g. '2026-08'")
        year, month = v.split("-")
        return date(int(year), int(month), 1)


class AttendanceStatsArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    class_section: str | None = Field(
        default=None,
        max_length=20,
        description="Optional class section filter, e.g. '10-A'.",
    )

    @field_validator("class_section")
    @classmethod
    def validate_class_section(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = str(v).strip()
        if not v:
            return None
        if DANGEROUS_SQL_PATTERNS.search(v):
            raise ValueError("SQL tokens and dangerous expressions are not permitted in arguments.")
        if not re.match(r"^[A-Za-z0-9\-_ ]{1,20}$", v):
            raise ValueError("Class section must be alphanumeric (e.g. '10-A') and at most 20 characters.")
        return v


APPROVED_TOOL_SCHEMAS = {
    "get_student_teacher_counts": StudentTeacherCountsArgs,
    "get_salary_summary": SalarySummaryArgs,
    "get_timetable_coverage": TimetableCoverageArgs,
    "get_teacher_grading_performance": TeacherGradingPerformanceArgs,
    "get_revenue_summary": RevenueSummaryArgs,
    "get_attendance_stats": AttendanceStatsArgs,
}


class AgentState(TypedDict):
    query: str
    tenant_id: str
    history: list[dict]
    tool_calls: list[dict]  # [{"name": str, "args": dict}]
    tool_results: list[dict]  # [{"name": str, "result": dict}]
    answer: str
    decide_tools_usage: LLMCallUsage | None
    generate_usage: LLMCallUsage | None
    trace_steps: list[dict]


@traced_node("decide_tools")
def decide_tools_node(state: AgentState) -> AgentState:
    history_text = ""
    for turn in state["history"][-6:]:
        role = "Admin" if turn["role"] == "user" else "Assistant"
        history_text += f"{role}: {turn['content']}\n"

    prompt = f"""{SYSTEM_SCOPE}

Conversation so far:
{history_text}

Admin's new message: {state["query"]}

Decide which tool(s), if any, you need to call to answer this. Call as many as are relevant."""

    tool_calls, usage = decide_tools_with_usage(prompt, ADMIN_TOOL)
    return {**state, "tool_calls": tool_calls, "decide_tools_usage": usage}


@traced_node("execute_tools")
async def execute_tools_node(state: AgentState) -> AgentState:
    tool_results = []

    if not state["tool_calls"]:
        return {**state, "tool_results": []}

    tenant_id = state.get("tenant_id")

    async with AsyncSessionLocal() as db:
        for call in state["tool_calls"]:
            tool_name = call.get("name", "")
            raw_args = call.get("args") or {}

            # 1. Enforce strict tool whitelist — explicitly block arbitrary SQL tools or unapproved calls
            if tool_name not in TOOL_FUNCTIONS or tool_name not in APPROVED_TOOL_SCHEMAS:
                tool_results.append({
                    "name": tool_name,
                    "result": {
                        "error": (
                            f"Tool '{tool_name}' is not authorized. "
                            "Arbitrary queries and unapproved tools are prohibited."
                        )
                    },
                })
                continue

            # 2. Enforce fail-closed requirement on tenant context
            if not tenant_id:
                tool_results.append({
                    "name": tool_name,
                    "result": {
                        "status": "unavailable",
                        "error": "Trusted tenant context is required for administrative reporting tools.",
                    },
                })
                continue

            # 3. Enforce typed Pydantic validation on arguments
            schema_cls = APPROVED_TOOL_SCHEMAS[tool_name]
            try:
                validated_model = schema_cls(**raw_args)
                clean_args = validated_model.model_dump()
            except Exception as val_err:
                tool_results.append({
                    "name": tool_name,
                    "result": {
                        "error": f"Argument validation rejected for '{tool_name}': {val_err}"
                    },
                })
                continue

            # 4. Execute approved reporting tool function with tenant binding
            func = TOOL_FUNCTIONS[tool_name]
            try:
                result = await func(db=db, tenant_id=tenant_id, **clean_args)
                # 5. Scrub sensitive internal database identifiers from LLM prompt context
                if isinstance(result, dict) and "pending_teacher_ids" in result:
                    result = {k: v for k, v in result.items() if k != "pending_teacher_ids"}
                tool_results.append({"name": tool_name, "result": result})
            except TenantAggregationBlockedError as blocked_err:
                tool_results.append({
                    "name": tool_name,
                    "result": {
                        "status": "unavailable",
                        "error": (
                            f"Reporting data for '{tool_name}' is currently unavailable for your institution: "
                            f"{blocked_err}"
                        ),
                    },
                })
            except Exception:
                # 6. Safe error handling: never leak database credentials, connection strings, or internal tracebacks
                tool_results.append({
                    "name": tool_name,
                    "result": {"error": "Reporting query execution failed safely."},
                })

    return {**state, "tool_results": tool_results}


@traced_node("generate")
def generate_node(state: AgentState) -> AgentState:
    history_text = ""
    for turn in state["history"][-6:]:
        role = "Admin" if turn["role"] == "user" else "Assistant"
        history_text += f"{role}: {turn['content']}\n"

    if state["tool_results"]:
        results_text = "\n\n".join(
            f"Tool: {r['name']}\nResult: {r['result']}" for r in state["tool_results"]
        )
    else:
        results_text = "No tools were called for this question."

    prompt = f"""{SYSTEM_SCOPE}

Conversation so far:
{history_text}

Admin's new message: {state["query"]}

Data retrieved from tools:
{results_text}

Respond clearly and concisely, summarizing the relevant numbers in plain language.
Don't just dump raw JSON — explain what it means. If no tools were relevant,
respond according to the scope rules above."""

    answer, usage = generate_text_with_usage(prompt)
    return {**state, "answer": answer, "generate_usage": usage}


graph = StateGraph(AgentState)
graph.add_node("decide_tools", decide_tools_node)
graph.add_node("execute_tools", execute_tools_node)
graph.add_node("generate", generate_node)
graph.set_entry_point("decide_tools")
graph.add_edge("decide_tools", "execute_tools")
graph.add_edge("execute_tools", "generate")
graph.add_edge("generate", END)

admin_assistant_graph = graph.compile()

MAX_ADMIN_SESSIONS = 1000
MAX_TURNS_PER_SESSION = 20  # 10 user + 10 assistant turns
SESSION_TTL_SECONDS = 86400  # 24 hours

_admin_conversation_sessions: OrderedDict[str, dict] = OrderedDict()


def _get_namespaced_session(namespaced_key: str) -> list[dict]:
    """Retrieve session history with TTL validation and LRU touch."""
    now = time.time()
    session = _admin_conversation_sessions.get(namespaced_key)
    if not session:
        return []
    if now - session.get("last_accessed", 0) > SESSION_TTL_SECONDS:
        _admin_conversation_sessions.pop(namespaced_key, None)
        return []
    _admin_conversation_sessions.move_to_end(namespaced_key)
    return list(session.get("history", []))


def _save_namespaced_session(namespaced_key: str, history: list[dict]) -> None:
    """Save session history with turn bounding, LRU ordering, and capacity eviction."""
    now = time.time()
    trimmed_history = history[-MAX_TURNS_PER_SESSION:]
    if namespaced_key in _admin_conversation_sessions:
        _admin_conversation_sessions.move_to_end(namespaced_key)
    _admin_conversation_sessions[namespaced_key] = {
        "history": trimmed_history,
        "last_accessed": now,
    }
    while len(_admin_conversation_sessions) > MAX_ADMIN_SESSIONS:
        _admin_conversation_sessions.popitem(last=False)


def _reset_admin_conversation_sessions() -> None:
    """Testing helper to clear in-memory admin sessions."""
    _admin_conversation_sessions.clear()


async def chat_with_admin_assistant(
    session_id: str,
    query: str,
    tenant_id: str,
    user_id: uuid.UUID | str,
) -> dict:
    if not tenant_id:
        raise ValueError("Trusted tenant_id is required for admin assistant.")
    if not user_id:
        raise ValueError("User ID is required for admin assistant.")

    # Guardrail: check for prompt-injection attempts BEFORE this text ever
    # reaches the tool-decision prompt or the generation prompt. This
    # matters especially here because a successful injection against the
    # Admin Assistant could try to manipulate which tools get called or
    # how real institute data (revenue, salaries) gets summarized —
    # higher stakes than the student-facing Portal Assistant.
    is_flagged, matched_pattern = check_for_prompt_injection(query)
    if is_flagged:
        print(
            f"[guardrail] Blocked prompt-injection attempt in admin assistant "
            f"(tenant={tenant_id}, session={session_id}, pattern={matched_pattern!r})"
        )
        return {
            "answer": INJECTION_REFUSAL_MESSAGE,
            "tools_used": [],
            "blocked": True,
            "block_reason": matched_pattern,
            "llm_usage": {},
            # Blocked turns never reach the graph, so there's no node
            # timing to report — still tagged with a trace_id and a single
            # "blocked" step rather than an empty trace, so a blocked
            # request is visible in the agent-traces view too, not just
            # silently absent from it.
            "trace_id": str(uuid.uuid4()),
            "trace_steps": [
                {
                    "node_name": "guardrail_check",
                    "step_order": 0,
                    "duration_ms": 0,
                    "status": "blocked",
                    "error_message": matched_pattern,
                }
            ],
        }

    scoped_session_key = f"{tenant_id}:{user_id}:{session_id}"
    history = _get_namespaced_session(scoped_session_key)
    trace_id = str(uuid.uuid4())

    result = await admin_assistant_graph.ainvoke(
        {
            "query": query,
            "tenant_id": tenant_id,
            "history": history,
            "tool_calls": [],
            "tool_results": [],
            "answer": "",
            "decide_tools_usage": None,
            "generate_usage": None,
            "trace_steps": [],
        }
    )

    history.append({"role": "user", "content": query})
    history.append({"role": "assistant", "content": result["answer"]})
    _save_namespaced_session(scoped_session_key, history)

    return {
        "answer": result["answer"],
        "tools_used": [tc["name"] for tc in result["tool_calls"]],
        "blocked": False,
        "block_reason": None,
        # Two LLM calls happen per admin turn (decide_tools, then generate)
        # — both are returned here (rather than logged inside this function,
        # which has no db session) so the router can log each with its own
        # endpoint tag. See app/observability/service.py: log_llm_usage.
        "llm_usage": {
            "admin-assistant/decide_tools": result["decide_tools_usage"],
            "admin-assistant/generate": result["generate_usage"],
        },
        # Per-node step timings for this turn, same "compute here, log via
        # db in the router" pattern as llm_usage above. See
        # app/observability/service.py: log_agent_trace.
        "trace_id": trace_id,
        "trace_steps": result["trace_steps"],
    }
