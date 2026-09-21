import uuid
from datetime import date
from typing import TypedDict

from google.genai import types
from langgraph.graph import END, StateGraph

from app.admin.service import (
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

SYSTEM_SCOPE = """You are the EduIntel AI Admin Assistant. You help the institute owner/admin understand what's happening on the platform — student and teacher counts, salary/payroll status, timetable coverage, teacher grading performance, revenue/fee collection, and attendance — without them needing to dig through dashboards themselves.

You have tools that query real, live data. Use them whenever the question is about actual numbers or status on the platform. Do not guess or estimate numbers yourself — only report what the tools return.

IMPORTANT — currency: This institute operates in India. Always express monetary amounts in Indian Rupees using the ₹ symbol (e.g. ₹42,500), never $ or USD. Use Indian-style comma grouping where natural (e.g. ₹1,37,000 rather than ₹137,000) if you can, but ₹ with standard grouping is acceptable too — the currency symbol is what matters most.

If the admin asks something entirely unrelated to running this institute (general chit-chat, unrelated topics), politely decline and steer back to what you can help with."""
# --- Tool declarations Gemini sees ---
TOOL_DECLARATIONS = [
    types.FunctionDeclaration(
        name="get_student_teacher_counts",
        description="Get the total number of enrolled students and total number of teachers on the platform.",
        parameters={"type": "object", "properties": {}, "required": []},
    ),
    types.FunctionDeclaration(
        name="get_salary_summary",
        description="Get salary/payroll summary: total payout, pending vs paid counts, base/bonus/deduction totals. Optionally filter to a specific month.",
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
        description="Get timetable period counts per class section, including how many periods have no teacher assigned. Optionally filter to one class section.",
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
        description="Get per-teacher homework grading stats: how many submissions each teacher has graded and their average grading turnaround time in hours.",
        parameters={"type": "object", "properties": {}, "required": []},
    ),
    types.FunctionDeclaration(
        name="get_revenue_summary",
        description="Get fee/revenue summary: total collected, pending, and overdue amounts. Optionally filter to a specific month.",
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
        description="Get attendance percentages overall and per class section, including present/absent/late breakdowns. Optionally filter to one class section.",
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


def _parse_month_arg(args: dict) -> dict:
    """Converts a 'YYYY-MM' string arg into a date object the service functions expect."""
    if args.get("month"):
        year, month = args["month"].split("-")
        args = {**args, "month": date(int(year), int(month), 1)}
    return args


class AgentState(TypedDict):
    query: str
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

    async with AsyncSessionLocal() as db:
        for call in state["tool_calls"]:
            func = TOOL_FUNCTIONS.get(call["name"])
            if not func:
                continue
            args = _parse_month_arg(call["args"])
            try:
                result = await func(db=db, **args)
                tool_results.append({"name": call["name"], "result": result})
            except Exception as e:
                tool_results.append({"name": call["name"], "result": {"error": str(e)}})

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

Respond clearly and concisely, summarizing the relevant numbers in plain language. Don't just dump raw JSON — explain what it means. If no tools were relevant, respond according to the scope rules above."""

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

_admin_conversation_sessions: dict[str, list[dict]] = {}


async def chat_with_admin_assistant(session_id: str, query: str) -> dict:
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
            f"(session={session_id}, pattern={matched_pattern!r})"
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

    history = _admin_conversation_sessions.get(session_id, [])
    trace_id = str(uuid.uuid4())

    result = await admin_assistant_graph.ainvoke(
        {
            "query": query,
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
    _admin_conversation_sessions[session_id] = history

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
