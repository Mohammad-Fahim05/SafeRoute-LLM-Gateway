# SafeRoute Comprehensive AI Systems Evaluation Report

**Generated:** 2026-10-26T19:05:42.992457+00:00

## 1. Gateway Performance, Reliability & Accounting

- **Total Measured Requests:** 50
- **Request Success Rate:** 100.0%
- **Request Error Rate:** 0.0%
- **Latency (p50):** 12.05 ms
- **Latency (p95):** 49.92 ms
- **Latency (p99):** 101.6 ms
- **Streaming Mean TTFT:** 51.55 ms
- **Exact Cache Hit / Miss Correctness:** Verified
- **Error Mapping (504/500/502):** Verified
- **SQLite Usage Accounting Correctness:** Verified (59 records logged)

## 2. Semantic Cache Safety & Isolation

- **Numeric Entity Mismatch Rejection:** Enforced (Safe)
- **Cross-Tenant Cache Isolation:** Enforced (Zero Leakage)
- **Evaluation Accuracy:** 60.0%
- **Confusion Matrix:** TP=0, TN=3, FP=0, FN=2
- **Unsafe Reuse Rate:** 0.0%

## 3. Hybrid RAG Retrieval Quality

- **Benchmark Queries Tested:** 5
- **Mean Recall@3:** 1.0
- **Mean Reciprocal Rank (MRR):** 1.0
- **Mean nDCG@3:** 1.0
- **Retrieval Latency (p50):** 4.11 ms
- **Retrieval Latency (p95):** 4.52 ms
- **Answer Faithfulness:** 100.0%
