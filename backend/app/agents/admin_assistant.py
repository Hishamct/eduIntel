from langgraph.graph import StateGraph, END
from typing import TypedDict
from datetime import date
from google.genai import types
from app.rag.client import _genai_client
from app.core.database import AsyncSessionLocal  # adjust if named differently
from app.admin.service import (
    get_student_teacher_counts,
    get_salary_summary,
    get_timetable_coverage,
    get_teacher_grading_performance,
    get_revenue_summary,
    get_attendance_stats,
)

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
                "month": {"type": "string", "description": "Optional month in YYYY-MM format, e.g. '2026-08'. Omit for all-time summary."},
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
                "class_section": {"type": "string", "description": "Optional class section filter, e.g. '10-A'."},
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
                "month": {"type": "string", "description": "Optional month in YYYY-MM format, e.g. '2026-08'. Omit for all-time summary."},
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
                "class_section": {"type": "string", "description": "Optional class section filter, e.g. '10-A'."},
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
    if "month" in args and args["month"]:
        year, month = args["month"].split("-")
        args = {**args, "month": date(int(year), int(month), 1)}
    return args


class AgentState(TypedDict):
    query: str
    history: list[dict]
    tool_calls: list[dict]      # [{"name": str, "args": dict}]
    tool_results: list[dict]    # [{"name": str, "result": dict}]
    answer: str


def decide_tools_node(state: AgentState) -> AgentState:
    history_text = ""
    for turn in state["history"][-6:]:
        role = "Admin" if turn["role"] == "user" else "Assistant"
        history_text += f"{role}: {turn['content']}\n"

    prompt = f"""{SYSTEM_SCOPE}

Conversation so far:
{history_text}

Admin's new message: {state['query']}

Decide which tool(s), if any, you need to call to answer this. Call as many as are relevant."""

    response = _genai_client.models.generate_content(
        model="gemini-3.6-flash",
        contents=prompt,
        config=types.GenerateContentConfig(tools=[ADMIN_TOOL]),
    )

    tool_calls = []
    candidate = response.candidates[0]
    for part in candidate.content.parts:
        if part.function_call:
            tool_calls.append({
                "name": part.function_call.name,
                "args": dict(part.function_call.args) if part.function_call.args else {},
            })

    return {**state, "tool_calls": tool_calls}


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

Admin's new message: {state['query']}

Data retrieved from tools:
{results_text}

Respond clearly and concisely, summarizing the relevant numbers in plain language. Don't just dump raw JSON — explain what it means. If no tools were relevant, respond according to the scope rules above."""

    response = _genai_client.models.generate_content(
        model="gemini-3.6-flash",
        contents=prompt,
    )

    return {**state, "answer": response.text}


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
    history = _admin_conversation_sessions.get(session_id, [])

    result = await admin_assistant_graph.ainvoke({
        "query": query,
        "history": history,
        "tool_calls": [],
        "tool_results": [],
        "answer": "",
    })

    history.append({"role": "user", "content": query})
    history.append({"role": "assistant", "content": result["answer"]})
    _admin_conversation_sessions[session_id] = history

    return {"answer": result["answer"], "tools_used": [tc["name"] for tc in result["tool_calls"]]}