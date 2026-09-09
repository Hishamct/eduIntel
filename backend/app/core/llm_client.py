from google import genai
from google.genai import types
from groq import Groq
from app.core.config import settings

_gemini_client = genai.Client(api_key=settings.GEMINI_API_KEY)
_groq_client = Groq(api_key=settings.GROQ_API_KEY)

GEMINI_MODEL = "gemini-3.6-flash"
GROQ_FALLBACK_MODEL = "openai/gpt-oss-120b"


def _is_rate_limit_error(e: Exception) -> bool:
    """
    Gemini raises different exception types depending on SDK version
    (google.genai.errors.ClientError / APIError are common). Checking the
    message text instead of a specific exception class keeps this working
    even if the exact error type differs in your installed SDK version.
    """
    msg = str(e)
    return "RESOURCE_EXHAUSTED" in msg or "429" in msg or "quota" in msg.lower()


def generate_text(prompt: str) -> str:
    """
    Plain text generation, no tool-calling.
    Tries Gemini first, falls back to Groq if Gemini is rate-limited.
    Used by both agents' final answer-generation step.
    """
    try:
        response = _gemini_client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
        )
        return response.text
    except Exception as e:
        if not _is_rate_limit_error(e):
            raise
        groq_response = _groq_client.chat.completions.create(
            model=GROQ_FALLBACK_MODEL,
            messages=[{"role": "user", "content": prompt}],
        )
        return groq_response.choices[0].message.content


def decide_tools(prompt: str, tool: types.Tool) -> list[dict]:
    """
    Tool-calling decision step (Admin Assistant only). Gemini-only —
    if Gemini is rate-limited here, we degrade gracefully to "no tools"
    rather than replicating function-calling on Groq (different schema),
    so the assistant still answers, just without live data for that turn.
    """
    try:
        response = _gemini_client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(tools=[tool]),
        )
    except Exception as e:
        if not _is_rate_limit_error(e):
            raise
        return []  # degrade gracefully — generate_node still answers, without tool data

    tool_calls = []
    candidate = response.candidates[0]
    for part in candidate.content.parts:
        if part.function_call:
            tool_calls.append({
                "name": part.function_call.name,
                "args": dict(part.function_call.args) if part.function_call.args else {},
            })
    return tool_calls