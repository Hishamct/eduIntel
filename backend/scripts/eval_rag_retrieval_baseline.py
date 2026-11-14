"""
backend/scripts/eval_rag_retrieval_baseline.py

Authoritative Step 0 Baseline Retrieval Benchmark Script.
Evaluates pre-Phase 5 ChromaDB vector retrieval performance:
- Hit Rate@1, Hit Rate@3
- Mean Reciprocal Rank (MRR)
- Retrieval Latency distribution (Mean, Median p50, p95, p99, Min, Max)
across portal_help_docs and study_materials collections using the versioned eval set.

Evaluates both:
1. Raw Global Retrieval (measuring baseline vector search accuracy & latency on existing index)
2. Tenant-Scoped Retrieval (measuring current metadata isolation state before Step 4 migration)
"""

import json
import sys
import time
from pathlib import Path

# Ensure backend root is on sys.path
backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

from app.core.tenant import PILOT_INSTITUTION_UUID  # noqa: E402
from app.rag.client import (  # noqa: E402
    get_portal_help_collection,
    get_study_materials_collection,
)
from app.rag.service import build_chroma_tenant_filter  # noqa: E402

EVAL_SET_PATH = backend_dir / "app" / "rag" / "eval" / "eval_set.json"

# Relevance keywords for each non-adversarial question in eval_set.json
RELEVANCE_CRITERIA = {
    "How do I submit my homework?": ["submit homework", "to submit homework"],
    "How do I ask a doubt on the platform?": ["ask a doubt", "doubt forum"],
    "Where can I find study materials uploaded by my teachers?": ["find study materials", "study materials page"],
    "What does the Self-Evaluation page show me?": ["self-evaluation", "academic progress"],
    "What information appears on my dashboard right after I log in?": ["dashboard", "understanding your dashboard"],
    "I forgot my password, what should I do?": ["password", "reset your password", "forgot password"],
    "What is the domain of the sine and cosine functions?": ["domain", "sine", "cosine", "trigonometric"],
    "How does sin x behave as x increases from 0 to pi/2?": ["sin", "quadrant", "increases from 0 to 1"],
    "What are the key areas covered in the Algebra study notes?": ["algebra"],
    "What is the most common root cause of difficulty in Trigonometry, according to the study notes?": ["trigonometry"],
    "What do the Acids & Bases study notes cover?": ["acids", "bases"],
}


def evaluate_retrieval(eval_items, portal_col, study_col, apply_tenant_filter=False):
    pilot_filter = build_chroma_tenant_filter(str(PILOT_INSTITUTION_UUID)) if apply_tenant_filter else None

    latencies_ms = []
    reciprocal_ranks = []
    hits_at_1 = []
    hits_at_3 = []
    results = []

    for item in eval_items:
        query = item["query"]
        col_name = item["collection"]
        is_adversarial = "adversarial" in item.get("note", "").lower()
        col = portal_col if col_name == "portal_help_docs" else study_col
        where_filter = None if col_name == "portal_help_docs" else pilot_filter

        t0 = time.perf_counter()
        if where_filter:
            res = col.query(query_texts=[query], n_results=3, where=where_filter)
        else:
            res = col.query(query_texts=[query], n_results=3)
        t1 = time.perf_counter()

        elapsed_ms = (t1 - t0) * 1000
        latencies_ms.append(elapsed_ms)

        docs = res["documents"][0] if res.get("documents") else []
        distances = res["distances"][0] if res.get("distances") else []

        if not is_adversarial and query in RELEVANCE_CRITERIA:
            keywords = RELEVANCE_CRITERIA[query]
            rank = None
            for idx, doc in enumerate(docs):
                doc_lower = doc.lower()
                if any(kw.lower() in doc_lower for kw in keywords):
                    rank = idx + 1
                    break

            if rank is not None:
                rr = 1.0 / rank
                h1 = 1 if rank == 1 else 0
                h3 = 1 if rank <= 3 else 0
            else:
                rr = 0.0
                h1 = 0
                h3 = 0

            reciprocal_ranks.append(rr)
            hits_at_1.append(h1)
            hits_at_3.append(h3)

            results.append({
                "query": query,
                "collection": col_name,
                "type": "Standard",
                "latency_ms": elapsed_ms,
                "rank": rank if rank else "Miss (>3)",
                "rr": rr,
                "top_distance": distances[0] if distances else None,
            })
        else:
            results.append({
                "query": query,
                "collection": col_name,
                "type": "Adversarial",
                "latency_ms": elapsed_ms,
                "rank": "N/A (OOD)",
                "rr": None,
                "top_distance": distances[0] if distances else None,
            })

    latencies_sorted = sorted(latencies_ms)
    n = len(latencies_sorted)
    mean_lat = sum(latencies_sorted) / n
    p50_lat = latencies_sorted[int(n * 0.50)]
    p95_lat = latencies_sorted[min(int(n * 0.95), n - 1)]
    p99_lat = latencies_sorted[min(int(n * 0.99), n - 1)]
    min_lat = latencies_sorted[0]
    max_lat = latencies_sorted[-1]

    mean_rr = sum(reciprocal_ranks) / len(reciprocal_ranks) if reciprocal_ranks else 0.0
    hit_rate_1 = sum(hits_at_1) / len(hits_at_1) if hits_at_1 else 0.0
    hit_rate_3 = sum(hits_at_3) / len(hits_at_3) if hits_at_3 else 0.0

    return {
        "hit_rate_at_1": hit_rate_1,
        "hit_rate_at_3": hit_rate_3,
        "mean_reciprocal_rank": mean_rr,
        "hits_1_count": sum(hits_at_1),
        "hits_3_count": sum(hits_at_3),
        "total_standard": len(reciprocal_ranks),
        "total_adversarial": n - len(reciprocal_ranks),
        "latency_ms": {
            "min": min_lat,
            "mean": mean_lat,
            "p50": p50_lat,
            "p95": p95_lat,
            "p99": p99_lat,
            "max": max_lat,
        },
        "results": results,
    }


def run_benchmark():
    if not EVAL_SET_PATH.exists():
        print(f"Error: Eval set not found at {EVAL_SET_PATH}", file=sys.stderr)
        sys.exit(1)

    with open(EVAL_SET_PATH) as f:
        eval_items = json.load(f)

    portal_col = get_portal_help_collection()
    study_col = get_study_materials_collection()

    print(f"Loaded {len(eval_items)} evaluation queries from {EVAL_SET_PATH.name}")
    print(f"Collections: portal_help_docs ({portal_col.count()} docs), study_materials ({study_col.count()} docs)")
    print("=" * 80)

    # 1. Benchmark Raw Global Vector Retrieval
    print("BENCHMARK 1: RAW GLOBAL VECTOR RETRIEVAL (Baseline Index Performance)")
    raw_eval = evaluate_retrieval(eval_items, portal_col, study_col, apply_tenant_filter=False)

    print(f"{'Query':<45} | {'Col':<12} | {'Type':<11} | {'Rank':<10} | {'Dist':<6} | {'Lat (ms)'}")
    print("-" * 100)
    for r in raw_eval["results"]:
        dist_str = f"{r['top_distance']:.3f}" if r['top_distance'] is not None else "N/A"
        print(f"{r['query'][:45]:<45} | {r['collection'][:12]:<12} | {r['type']:<11} | {str(r['rank']):<10} | {dist_str:<6} | {r['latency_ms']:.1f}")

    print("-" * 80)
    print(f"Hit Rate @ 1:                  {raw_eval['hit_rate_at_1'] * 100:.2f}% ({raw_eval['hits_1_count']}/{raw_eval['total_standard']})")
    print(f"Hit Rate @ 3:                  {raw_eval['hit_rate_at_3'] * 100:.2f}% ({raw_eval['hits_3_count']}/{raw_eval['total_standard']})")
    print(f"Mean Reciprocal Rank (MRR):    {raw_eval['mean_reciprocal_rank']:.4f}")
    print(f"Latency p50: {raw_eval['latency_ms']['p50']:.1f}ms | p95: {raw_eval['latency_ms']['p95']:.1f}ms | mean: {raw_eval['latency_ms']['mean']:.1f}ms")
    print("=" * 80)

    # 2. Benchmark Tenant-Filtered Retrieval
    print("BENCHMARK 2: TENANT-FILTERED RETRIEVAL (Metadata Scoping State)")
    filtered_eval = evaluate_retrieval(eval_items, portal_col, study_col, apply_tenant_filter=True)
    print(f"Hit Rate @ 1:                  {filtered_eval['hit_rate_at_1'] * 100:.2f}% ({filtered_eval['hits_1_count']}/{filtered_eval['total_standard']})")
    print(f"Hit Rate @ 3:                  {filtered_eval['hit_rate_at_3'] * 100:.2f}% ({filtered_eval['hits_3_count']}/{filtered_eval['total_standard']})")
    print(f"Mean Reciprocal Rank (MRR):    {filtered_eval['mean_reciprocal_rank']:.4f}")
    print(f"Latency p50: {filtered_eval['latency_ms']['p50']:.1f}ms | p95: {filtered_eval['latency_ms']['p95']:.1f}ms | mean: {filtered_eval['latency_ms']['mean']:.1f}ms")
    print("=" * 80)

    # Combine into persistent output json
    master_report = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "eval_set": EVAL_SET_PATH.name,
        "collections": {
            "portal_help_docs": portal_col.count(),
            "study_materials": study_col.count(),
        },
        "global_vector_retrieval": raw_eval,
        "tenant_filtered_retrieval": filtered_eval,
    }

    out_path = backend_dir / "app" / "rag" / "eval" / "retrieval_baseline_metrics.json"
    with open(out_path, "w") as f:
        json.dump(master_report, f, indent=2)
    print(f"Authoritative Step 0 Baseline written to: {out_path}")


if __name__ == "__main__":
    run_benchmark()
