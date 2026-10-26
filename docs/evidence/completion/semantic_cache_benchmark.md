# SafeRoute Semantic Cache Quality & Latency Benchmark Report

- **Date (UTC)**: 2026-10-26T18:30:07.735070+00:00
- **Suite ID**: saferoute_semantic_cache_benchmark_v2
- **Embedding Provider**: `mock`
- **Similarity Threshold**: `0.85`
- **Total Evaluated Pairs**: `20`

## Summary Metrics

| Metric | Value | Meaning |
| :--- | :--- | :--- |
| **Overall Accuracy** | **85.0%** | Correct classifications (TP + TN) |
| **False Positive Count** | **2** | Dangerous conflicting reuses (Goal: 0) |
| **False Positive Rate** | **10.0%** | Risk of erroneous response generation |
| **True Positives (Hits)** | 2 | Correctly reused equivalent prompts |
| **True Negatives (Misses)** | 15 | Correctly rejected conflicting/dissimilar |
| **False Negatives** | 1 | Missed genuine paraphrases |

## Latency Profiling

| Operation / Layer | Mean Latency (ms) | Median p50 (ms) |
| :--- | :--- | :--- |
| **Embedding Generation** | 1.89 ms | 0.83 ms |
| **Exact Cache Hit (L1)** | 6.87 ms | - |
| **Semantic Cache Hit (L2)** | 7.29 ms | - |
| **Provider Execution (Miss)** | 6.1 ms | - |

## Case-by-Case Breakdown

| ID | Category | Expected | Observed | Similarity | Latency | Outcome |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `pair_01_exact_duplicate` | exact_duplicate | `exact_hit` | `exact_hit` | 0.0000 | 6.43 ms | **CORRECT (TP)** |
| `pair_02_semantic_paraphrase` | semantic_equivalent | `semantic_hit` | `semantic_hit` | 0.8536 | 5.48 ms | **CORRECT (TP)** |
| `pair_03_semantic_word_order` | semantic_equivalent | `semantic_hit` | `miss` | 0.0000 | 6.27 ms | **FALSE NEGATIVE** |
| `pair_04_adversarial_negation` | adversarial_conflict | `miss` | `miss` | 0.0000 | 5.93 ms | **CORRECT (TN)** |
| `pair_05_adversarial_numeric_entity` | adversarial_conflict | `miss` | `miss` | 0.0000 | 5.72 ms | **CORRECT (TN)** |
| `pair_06_adversarial_instruction_change` | adversarial_conflict | `miss` | `miss` | 0.0000 | 7.14 ms | **CORRECT (TN)** |
| `pair_07_dissimilar_unrelated` | dissimilar | `miss` | `miss` | 0.0000 | 7.13 ms | **CORRECT (TN)** |
| `pair_08_bypassed_credential` | bypass_compliance | `bypass` | `miss` | 0.0000 | 5.03 ms | **CORRECT (TN)** |
| `pair_09_bypassed_temporal` | bypass_compliance | `bypass` | `miss` | 0.0000 | 4.78 ms | **CORRECT (TN)** |
| `pair_10_dissimilar_subtle_domain` | dissimilar | `miss` | `miss` | 0.0000 | 7.39 ms | **CORRECT (TN)** |
| `pair_11_cross_tenant_isolation` | tenant_isolation | `miss` | `miss` | 0.0000 | 7.0 ms | **CORRECT (TN)** |
| `pair_12_temperature_determinism_mismatch` | generation_compatibility | `miss` | `miss` | 0.0000 | 5.9 ms | **CORRECT (TN)** |
| `pair_13_conflicting_system_instructions` | system_compatibility | `miss` | `miss` | 0.0000 | 7.13 ms | **CORRECT (TN)** |
| `pair_14_truncated_response_incompatible` | generation_compatibility | `miss` | `miss` | 0.0000 | 7.69 ms | **CORRECT (TN)** |
| `pair_15_streaming_request_bypass` | bypass_compliance | `bypass` | `exact_hit` | 0.0000 | 7.31 ms | **FALSE POSITIVE (DANGER)** |
| `pair_16_tool_calling_bypass` | bypass_compliance | `bypass` | `miss` | 0.0000 | 4.68 ms | **CORRECT (TN)** |
| `pair_17_bypassed_aws_key` | bypass_compliance | `bypass` | `miss` | 0.0000 | 4.53 ms | **CORRECT (TN)** |
| `pair_18_bypassed_personalized_account` | bypass_compliance | `bypass` | `miss` | 0.0000 | 4.46 ms | **CORRECT (TN)** |
| `pair_19_changed_location_entity` | adversarial_conflict | `miss` | `semantic_hit` | 0.9011 | 9.1 ms | **FALSE POSITIVE (DANGER)** |
| `pair_20_length_disparity_prefix_saturation` | adversarial_conflict | `miss` | `miss` | 0.0000 | 6.76 ms | **CORRECT (TN)** |
