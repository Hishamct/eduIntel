"""
RAG faithfulness / groundedness evaluation harness for EduIntel AI.

Runs the real retrieve_and_generate() pipeline against a curated eval set
covering both ChromaDB collections (portal_help_docs, study_materials),
then scores each answer with RAGAS.

Judge LLM: Groq (NOT Gemini). This is deliberate — the app's own RAG
generation already uses Gemini, and Gemini rate limits have bitten this
project before. Keeping the eval's judge calls on Groq means running the
eval never competes with, or gets blocked by, the same quota the live app
depends on.

Metrics used (both reference-free, LLM-judge only, no embeddings model
required):
- Faithfulness: is the generated answer actually grounded in the
  retrieved context, or does it add unsupported claims?
- LLMContextPrecisionWithoutReference: are the retrieved chunks actually
  relevant to the question, or mostly noise?

Deliberately NOT included (documented scope decisions, not oversights):
- context_recall: needs a hand-written "ideal answer" per question — too
  much curation time this close to submission.
- answer_relevancy: needs an embedding model, adding a new dependency/API
  surface for one extra metric.

Usage (run from the `backend` folder, same place you run uvicorn from):
    python -m app.rag.eval.eval_rag

Requires (add to requirements.txt if missing):
    ragas
    langchain-groq
    mlflow
    pandas
"""
import json
import sys
import time
import types
from pathlib import Path

# --- Workaround for a ragas 0.4.x packaging bug ---
# ragas/llms/base.py unconditionally imports ChatVertexAI from
# langchain_community.chat_models.vertexai, a submodule that newer
# langchain-community releases (0.4.x) removed entirely. We never use
# Vertex AI (Groq is our judge LLM), so we stub the module out in
# sys.modules before ragas is imported — this satisfies the import
# without needing the real package, and the stub class is never
# instantiated.
if "langchain_community.chat_models.vertexai" not in sys.modules:
    _fake_vertexai_module = types.ModuleType("langchain_community.chat_models.vertexai")

    class ChatVertexAI:  # dummy stand-in — never instantiated, we use Groq
        pass

    _fake_vertexai_module.ChatVertexAI = ChatVertexAI
    sys.modules["langchain_community.chat_models.vertexai"] = _fake_vertexai_module

import mlflow
import pandas as pd
from google.genai.errors import APIError
from groq import APIStatusError as GroqAPIStatusError
from langchain_groq import ChatGroq
from ragas import evaluate, EvaluationDataset, RunConfig
from ragas.llms import LangchainLLMWrapper
from ragas.metrics import Faithfulness, LLMContextPrecisionWithoutReference

from app.core.config import settings

# --- ADJUST THIS IMPORT to wherever retrieve_and_generate actually lives ---
# Based on what you showed me, it's the function with signature
# retrieve_and_generate(query, collection_name="study_materials", n_results=3)
# living alongside ingest_study_material() / debug_query_study_materials().
from app.rag.service import retrieve_and_generate  # noqa: E402

# generate_text()'s Groq fallback model (openai/gpt-oss-120b) has been
# pinned near its 200k-token/day cap all evening and isn't clearing fast
# enough between retries for this eval run to complete. Rather than wait
# out the full rolling-window recovery, point it at a different Groq
# model for the duration of THIS SCRIPT ONLY — llm_client.py itself is
# untouched, so the app's actual production fallback choice is unaffected.
import app.core.llm_client as _llm_client  # noqa: E402
if hasattr(_llm_client, "GROQ_FALLBACK_MODEL"):
    print(f"[eval] Overriding Groq fallback model for this run: "
          f"{_llm_client.GROQ_FALLBACK_MODEL} -> openai/gpt-oss-20b")
    _llm_client.GROQ_FALLBACK_MODEL = "openai/gpt-oss-20b"
    # (Deliberately NOT llama-3.1-8b-instant here — that's what the RAGAS
    # judge below uses, and we want generation and judging on separate
    # models so they don't compete for the same daily quota again.)
else:
    print("[eval] WARNING: couldn't find GROQ_FALLBACK_MODEL on llm_client — "
          "check the actual constant name in app/core/llm_client.py and "
          "update this override to match.")

EVAL_SET_PATH = Path(__file__).parent / "eval_set.json"
RESULTS_PATH = Path(__file__).parent / "eval_results.csv"
MLFLOW_EXPERIMENT = "eduintel-rag-eval"

FAITHFULNESS_COL = "faithfulness"
CONTEXT_PRECISION_COL = "llm_context_precision_without_reference"


def load_eval_set() -> list[dict]:
    with open(EVAL_SET_PATH) as f:
        return json.load(f)


# retrieve_and_generate() calls Gemini directly (not the Groq-fallback
# generate_text() used elsewhere in the app), and this project's Gemini
# free tier allows only 5 requests/minute for gemini-3.6-flash. 13s
# between calls keeps us under that; if we still get rate-limited
# (shared quota, clock drift, etc.) we back off and retry rather than
# crashing the whole 28-question run.
SECONDS_BETWEEN_CALLS = 3  # Groq's free tier allows 30 req/min, far looser than Gemini's daily cap
MAX_RETRIES_ON_RATE_LIMIT = 3
RATE_LIMIT_BACKOFF_SECONDS = 60


TRANSIENT_STATUS_CODES = {429, 500, 503, 504}  # rate limit + Gemini server overload/timeout


def call_with_retry(item: dict):
    for attempt in range(1, MAX_RETRIES_ON_RATE_LIMIT + 1):
        try:
            return retrieve_and_generate(
                query=item["query"],
                collection_name=item["collection"],
                n_results=item.get("n_results", 3),
            )
        except APIError as e:
            # Gemini-side errors (generate_text tries Gemini first)
            status = getattr(e, "code", None)
            is_transient = status in TRANSIENT_STATUS_CODES or "RESOURCE_EXHAUSTED" in str(e) or "UNAVAILABLE" in str(e)
            if is_transient and attempt < MAX_RETRIES_ON_RATE_LIMIT:
                print(f"  Transient Gemini error ({status}), attempt {attempt}/{MAX_RETRIES_ON_RATE_LIMIT}, "
                      f"waiting {RATE_LIMIT_BACKOFF_SECONDS}s before retry...")
                time.sleep(RATE_LIMIT_BACKOFF_SECONDS)
            else:
                raise
        except GroqAPIStatusError as e:
            # Groq-side errors — generate_text() falls back to Groq when
            # Gemini fails, and Groq's own daily/per-minute limits can
            # still be hit (as happened here: 509 tokens over a 200k/day
            # cap). These usually clear within a minute since the quota
            # is a rolling window, so a short backoff is worth it rather
            # than failing the whole eval run.
            status = getattr(e, "status_code", None)
            is_transient = status in TRANSIENT_STATUS_CODES or "rate_limit" in str(e).lower()
            if is_transient and attempt < MAX_RETRIES_ON_RATE_LIMIT:
                print(f"  Transient Groq error ({status}), attempt {attempt}/{MAX_RETRIES_ON_RATE_LIMIT}, "
                      f"waiting {RATE_LIMIT_BACKOFF_SECONDS}s before retry...")
                time.sleep(RATE_LIMIT_BACKOFF_SECONDS)
            else:
                raise
    raise RuntimeError(f"Gave up after {MAX_RETRIES_ON_RATE_LIMIT} retries on transient errors: {item['query']!r}")


def run_retrieval(eval_items: list[dict]) -> list[dict]:
    """Calls the REAL RAG pipeline for every eval question — not a mock —
    so the eval reflects actual retrieval + generation behavior."""
    records = []
    for i, item in enumerate(eval_items, start=1):
        print(f"[{i}/{len(eval_items)}] ({item['collection']}) {item['query']}")
        result = call_with_retry(item)
        contexts = [s["chunk_text"] for s in result.get("sources", [])]
        records.append({
            "user_input": item["query"],
            "response": result["answer"],
            "retrieved_contexts": contexts or ["(no context retrieved)"],
            "collection": item["collection"],
        })
        time.sleep(SECONDS_BETWEEN_CALLS)
    return records


def run_eval():
    eval_items = load_eval_set()
    print(f"Running retrieval for {len(eval_items)} eval questions...\n")
    records = run_retrieval(eval_items)

    dataset = EvaluationDataset.from_list([
        {k: v for k, v in r.items() if k != "collection"} for r in records
    ])

    # llama-3.1-8b-instant returned 404 model_not_found on this account
    # (not a quota issue — it's just not enabled/available here), so the
    # judge uses the same gpt-oss-20b model as generation instead. This is
    # safe token-budget-wise: retrieval fully finishes before scoring
    # starts, so the two phases never compete concurrently for the same
    # quota, only sequentially.
    judge_llm = LangchainLLMWrapper(
        ChatGroq(model="openai/gpt-oss-20b", api_key=settings.GROQ_API_KEY)
    )

    metrics = [
        Faithfulness(llm=judge_llm),
        LLMContextPrecisionWithoutReference(llm=judge_llm),
    ]

    # A first run hit a wave of TimeoutErrors on the judge calls — RAGAS
    # fires scoring calls concurrently by default, and that concurrency
    # was outrunning Groq's responses, not Groq itself being slow.
    # Capping concurrency and raising the per-call timeout fixes it.
    run_config = RunConfig(max_workers=3, timeout=180)

    print("\nScoring with RAGAS (Groq judge)...")
    result = evaluate(dataset=dataset, metrics=metrics, run_config=run_config)

    df = result.to_pandas()
    df["collection"] = [r["collection"] for r in records]
    df.to_csv(RESULTS_PATH, index=False)
    print(f"\nSaved per-question results to {RESULTS_PATH}")

    summary = df.groupby("collection")[[FAITHFULNESS_COL, CONTEXT_PRECISION_COL]].mean()
    print("\n=== Summary by collection ===")
    print(summary)

    overall = df[[FAITHFULNESS_COL, CONTEXT_PRECISION_COL]].mean()
    print("\n=== Overall ===")
    print(overall)

    mlflow.set_experiment(MLFLOW_EXPERIMENT)
    with mlflow.start_run(run_name="rag-eval"):
        mlflow.log_metric("faithfulness_overall", float(overall[FAITHFULNESS_COL]))
        mlflow.log_metric("context_precision_overall", float(overall[CONTEXT_PRECISION_COL]))
        for collection, row in summary.iterrows():
            mlflow.log_metric(f"faithfulness_{collection}", float(row[FAITHFULNESS_COL]))
            mlflow.log_metric(f"context_precision_{collection}", float(row[CONTEXT_PRECISION_COL]))
        mlflow.log_artifact(str(RESULTS_PATH))
        mlflow.log_artifact(str(EVAL_SET_PATH))

    print(f"\nLogged to MLflow experiment: {MLFLOW_EXPERIMENT}")
    print("Run `mlflow ui` from the backend folder to view it.")


if __name__ == "__main__":
    run_eval()