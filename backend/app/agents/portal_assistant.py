import uuid
from typing import TypedDict

from langgraph.graph import END, StateGraph

from app.core.llm_client import LLMCallUsage, generate_text_with_usage
from app.guardrails.prompt_injection import (
    INJECTION_REFUSAL_MESSAGE,
    check_for_prompt_injection,
)
from app.observability.tracing import traced_node
from app.rag.client import get_portal_help_collection

SYSTEM_SCOPE = """You are the EduIntel AI Portal Assistant — you help students understand how to use the platform itself: submitting homework, using the doubt forum, finding study materials, checking their dashboard, and account basics like password resets.

You are NOT a subject-matter tutor. If a student asks a homework/academic question (math, physics, etc.), politely redirect them to the Doubt Forum instead of answering it yourself.

Stay strictly within onboarding/how-to-use-the-platform topics. If asked something unrelated to the platform, politely decline and steer back to platform help.

CRITICAL: Only answer using the "Relevant help articles" section below. If the help articles do not contain the answer, respond only with:
"I don't have information on that in our help docs — please check with your teacher or try the Doubt Forum."
Do NOT use outside/general knowledge to fill gaps, even if you think you know the answer."""

# Below this distance, we don't trust the retrieval enough to even try generating.
# ChromaDB default distance is cosine distance (lower = more similar).
RELEVANCE_DISTANCE_THRESHOLD = 0.45

FALLBACK_ANSWER = (
    "I couldn't find anything relevant to that in our help docs. "
    "Please check with your teacher or post in the Doubt Forum."
)


class AgentState(TypedDict):
    query: str
    history: list[dict]  # [{"role": "user"/"assistant", "content": str}]
    retrieved_context: str
    is_relevant: bool
    answer: str
    grounded: bool
    llm_usage: LLMCallUsage | None
    trace_steps: list[dict]


@traced_node("retrieve")
def retrieve_node(state: AgentState) -> AgentState:
    collection = get_portal_help_collection()
    results = collection.query(
        query_texts=[state["query"]],
        n_results=3,
        include=["documents", "distances"],
    )

    documents = results["documents"][0] if results["documents"] else []
    distances = results["distances"][0] if results["distances"] else []

    is_relevant = bool(distances) and min(distances) <= RELEVANCE_DISTANCE_THRESHOLD

    context = (
        "\n\n---\n\n".join(documents)
        if documents
        else "No relevant help articles found."
    )

    return {**state, "retrieved_context": context, "is_relevant": is_relevant}


@traced_node("generate")
def generate_node(state: AgentState) -> AgentState:
    # don't even call the LLM if retrieval found nothing relevant.
    # Saves an API call and guarantees the fallback message is used.
    if not state["is_relevant"]:
        return {
            **state,
            "answer": FALLBACK_ANSWER,
            "grounded": False,
            "llm_usage": None,
        }

    history_text = ""
    for turn in state["history"][-6:]:  # last 6 turns, keeps prompt small
        role = "Student" if turn["role"] == "user" else "Assistant"
        history_text += f"{role}: {turn['content']}\n"

    prompt = f"""{SYSTEM_SCOPE}

Relevant help articles:
{state["retrieved_context"]}

Conversation so far:
{history_text}

Student's new message: {state["query"]}

Respond helpfully and concisely, grounded strictly in the help articles above."""

    answer, usage = generate_text_with_usage(prompt)
    return {**state, "answer": answer, "grounded": True, "llm_usage": usage}


graph = StateGraph(AgentState)
graph.add_node("retrieve", retrieve_node)
graph.add_node("generate", generate_node)
graph.set_entry_point("retrieve")
graph.add_edge("retrieve", "generate")
graph.add_edge("generate", END)

portal_assistant_graph = graph.compile()


# Simple in-memory session store: {session_id: [{"role":..., "content":...}, ...]}
# resets on server restart, not persisted to Postgres

_conversation_sessions: dict[str, list[dict]] = {}


def chat_with_portal_assistant(session_id: str, query: str) -> dict:
    # Guardrail: check for prompt-injection attempts BEFORE this text ever
    # reaches an LLM prompt or the retrieval pipeline. Flagged messages
    # are refused immediately and never enter conversation history as a
    # "real" turn that could poison later context.
    is_flagged, matched_pattern = check_for_prompt_injection(query)
    if is_flagged:
        print(
            f"[guardrail] Blocked prompt-injection attempt in portal assistant "
            f"(session={session_id}, pattern={matched_pattern!r})"
        )
        return {
            "answer": INJECTION_REFUSAL_MESSAGE,
            "grounded": False,
            "blocked": True,
            "block_reason": matched_pattern,
            "llm_usage": None,
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

    history = _conversation_sessions.get(session_id, [])
    trace_id = str(uuid.uuid4())

    result = portal_assistant_graph.invoke(
        {
            "query": query,
            "history": history,
            "retrieved_context": "",
            "is_relevant": False,
            "answer": "",
            "grounded": False,
            "llm_usage": None,
            "trace_steps": [],
        }
    )

    history.append({"role": "user", "content": query})
    history.append({"role": "assistant", "content": result["answer"]})
    _conversation_sessions[session_id] = history

    return {
        "answer": result["answer"],
        "grounded": result["grounded"],
        "blocked": False,
        "block_reason": None,
        # None whenever the fallback answer was used (no material found) —
        # see app/observability/service.py: log_llm_usage, which treats
        # None as a safe no-op.
        "llm_usage": result["llm_usage"],
        "trace_id": trace_id,
        "trace_steps": result["trace_steps"],
    }
