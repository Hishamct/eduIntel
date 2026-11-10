"""
backend/scripts/eval_rag_retrieval_offline.py

CLI entrypoint for running the Offline RAG Retrieval Benchmark.
Executes hermetically without network access, live Gemini/Groq APIs,
external embeddings, or production database connections.

Usage:
    cd backend && python -m scripts.eval_rag_retrieval_offline
    cd backend && python -m scripts.eval_rag_retrieval_offline --json-output app/rag/eval/offline_retrieval_benchmark_results.json
"""

import argparse
import json
import sys
import time
from dataclasses import asdict
from pathlib import Path

# Ensure backend root is on sys.path
backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from app.rag.eval.offline_benchmark import (  # noqa: E402
    BenchmarkThresholds,
    OfflineRAGBenchmark,
)


def format_table_row(query: str, col: str, qtype: str, status: str, rank: str, dist: str, lat: str) -> str:
    return f"{query:<45} | {col:<12} | {qtype:<10} | {status:<24} | {rank:<6} | {dist:<6} | {lat}"


def run_cli():
    parser = argparse.ArgumentParser(
        description="EduIntel Offline RAG Retrieval Benchmark (Phase 5 Step 3.6 Stage 5)"
    )
    parser.add_argument(
        "--json-output",
        type=str,
        default=str(backend_dir / "app" / "rag" / "eval" / "offline_retrieval_benchmark_results.json"),
        help="Path to write machine-readable JSON report",
    )
    parser.add_argument(
        "--dataset",
        type=str,
        default=None,
        help="Custom dataset path",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress detailed per-query rows",
    )
    args = parser.parse_args()

    dataset_path = Path(args.dataset) if args.dataset else None
    thresholds = BenchmarkThresholds()

    print("=" * 115)
    print("EDUINTEL AI — OFFLINE RAG RETRIEVAL BENCHMARK (HERMETIC CI HARNESS)")
    print("Phase 5 – Step 3.6 – Stage 5")
    print(f"Timestamp: {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}")
    print("Zero-Network Guarantee: ACTIVE (Using DeterministicOfflineEmbeddingFunction)")
    print("=" * 115)

    benchmark = OfflineRAGBenchmark(dataset_path=dataset_path, thresholds=thresholds)
    report = benchmark.run_benchmark()

    # Print Summary Tables
    if not args.quiet:
        print("\nDETAILED RETRIEVAL RESULTS:")
        print(f"{'Query':<45} | {'Collection':<12} | {'Category':<10} | {'Status':<24} | {'Rank':<6} | {'Dist':<6} | {'Lat (ms)'}")
        print("-" * 115)
        for r in report.query_results:
            rank_str = str(r["rank"]) if r["rank"] is not None else "-"
            dist_str = f"{r['top_distance']:.3f}" if r["top_distance"] is not None else "-"
            q_short = r["query"][:43] + ".." if len(r["query"]) > 45 else r["query"]
            print(
                format_table_row(
                    q_short,
                    r["collection"][:12],
                    r["category"][:10],
                    r["status"],
                    rank_str,
                    dist_str,
                    f"{r['latency_ms']:.1f}",
                )
            )
        print("-" * 115)

    # 1. Global Vector Retrieval
    g = report.global_vector_retrieval
    print("\n1. GLOBAL (UNFILTERED) VECTOR RETRIEVAL:")
    print(f"   Standard Queries Evaluated:    {g['standard_in_domain_count']}")
    print(f"   Adversarial (OOD) Queries:     {g['adversarial_ood_count']}")
    print(f"   Hit Rate @ 1:                  {g['hit_rate_at_1'] * 100:.2f}% ({g['hits_1_count']}/{g['standard_in_domain_count']})")
    print(f"   Hit Rate @ 3:                  {g['hit_rate_at_3'] * 100:.2f}% ({g['hits_3_count']}/{g['standard_in_domain_count']})")
    print(f"   Mean Reciprocal Rank (MRR):    {g['mean_reciprocal_rank']:.4f}")
    print(f"   Mean Precision @ 3:            {g['mean_precision_at_3']:.4f}")
    print(f"   Mean Recall @ 3:               {g['mean_recall_at_3']:.4f}")
    print(f"   OOD False Positive Count:      {g['ood_false_positive_count']} (Strict Target: 0)")
    print(f"   OOD Rejection Rate:            {g['ood_rejection_rate'] * 100:.2f}% ({g['ood_rejection_count']}/{g['adversarial_ood_count']})")

    # 2. Tenant-Filtered Retrieval
    tf = report.tenant_filtered_retrieval
    print("\n2. TENANT-FILTERED RETRIEVAL (Historical Baseline Fidelity):")
    print(f"   Standard Queries Evaluated:    {tf['standard_in_domain_count']}")
    print(f"   Hit Rate @ 1:                  {tf['hit_rate_at_1'] * 100:.2f}% ({tf['hits_1_count']}/{tf['standard_in_domain_count']})")
    print(f"   Hit Rate @ 3:                  {tf['hit_rate_at_3'] * 100:.2f}% ({tf['hits_3_count']}/{tf['standard_in_domain_count']})")
    print(f"   Mean Reciprocal Rank (MRR):    {tf['mean_reciprocal_rank']:.4f}")
    print(f"   Mean Precision @ 3:            {tf['mean_precision_at_3']:.4f}")
    print(f"   Mean Recall @ 3:               {tf['mean_recall_at_3']:.4f}")
    print(f"   Missing Tenant Metadata:       {tf['missing_tenant_metadata_count']} queries affected ({report.legacy_chunks_missing_tenant_metadata} legacy chunks in study_materials)")
    print(f"   OOD False Positive Count:      {tf['ood_false_positive_count']} (Strict Target: 0)")
    print("   Note: Reflects documented baseline state where 38 study_materials chunks lack institution_id.")

    # 3. Multi-Tenant Isolation & Security
    sec = report.tenant_isolation_security
    print("\n3. MULTI-TENANT ISOLATION & SECURITY:")
    print(f"   Isolation Tests Executed:      {sec['isolation_tests_executed']}")
    print(f"   Cross-Tenant Leakage Count:    {sec['cross_tenant_leakage_count']} (Strict Target: 0)")
    print(f"   Unauthorized Result Count:     {sec['unauthorized_result_count']} (Strict Target: 0)")
    print(f"   Authorization Refusals:        {sec['authorization_refusal_count']} (Fail-Closed Verified)")
    print(f"   Clean Isolation Pass Rate:     {sec['clean_isolation_pass_rate'] * 100:.2f}%")

    # 4. Latency
    lat = report.operational_metrics["latency_ms"]
    print("\n4. OPERATIONAL LATENCY:")
    print(f"   p50: {lat['p50']:.1f}ms | p95: {lat['p95']:.1f}ms | mean: {lat['mean']:.1f}ms | min: {lat['min']:.1f}ms | max: {lat['max']:.1f}ms")

    # 5. Threshold Validation
    print("\n5. REGRESSION THRESHOLD EVALUATION:")
    for metric_name, t_data in report.threshold_evaluation.items():
        pass_symbol = "PASSED [OK]" if t_data["passed"] else "FAILED [X]"
        print(f"   - {metric_name:<32}: {t_data['value']} (threshold: {t_data['target']}) -> {pass_symbol}")

    print("=" * 115)

    # Write JSON output
    out_path = Path(args.json_output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(asdict(report), f, indent=2)
    print(f"Machine-readable JSON report written to: {out_path}")

    if not report.all_thresholds_passed:
        print("\n::error::Offline RAG Benchmark failed mandatory regression or security thresholds!", file=sys.stderr)
        sys.exit(1)

    print("\nOffline RAG Retrieval Benchmark completed successfully with 100% threshold compliance.")
    sys.exit(0)


if __name__ == "__main__":
    run_cli()

