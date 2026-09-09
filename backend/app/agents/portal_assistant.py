from langgraph.graph import StateGraph, END
from typing import TypedDict
from app.rag.client import get_portal_help_collection, _genai_client

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

    context = "\n\n---\n\n".join(documents) if documents else "No relevant help articles found."

    return {**state, "retrieved_context": context, "is_relevant": is_relevant}


def generate_node(state: AgentState) -> AgentState:
    #don't even call the LLM if retrieval found nothing relevant.
    # Saves an API call and guarantees the fallback message is used.
    if not state["is_relevant"]:
        return {**state, "answer": FALLBACK_ANSWER, "grounded": False}

    history_text = ""
    for turn in state["history"][-6:]:  # last 6 turns, keeps prompt small
        role = "Student" if turn["role"] == "user" else "Assistant"
        history_text += f"{role}: {turn['content']}\n"

    prompt = f"""{SYSTEM_SCOPE}

Relevant help articles:
{state['retrieved_context']}

Conversation so far:
{history_text}

Student's new message: {state['query']}

Respond helpfully and concisely, grounded strictly in the help articles above."""

    response = _genai_client.models.generate_content(
        model="gemini-3.6-flash",
        contents=prompt,
    )

    return {**state, "answer": response.text, "grounded": True}


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
    history = _conversation_sessions.get(session_id, [])

    result = portal_assistant_graph.invoke({
        "query": query,
        "history": history,
        "retrieved_context": "",
        "is_relevant": False,
        "answer": "",
        "grounded": False,
    })

    history.append({"role": "user", "content": query})
    history.append({"role": "assistant", "content": result["answer"]})
    _conversation_sessions[session_id] = history

    return {"answer": result["answer"], "grounded": result["grounded"]}