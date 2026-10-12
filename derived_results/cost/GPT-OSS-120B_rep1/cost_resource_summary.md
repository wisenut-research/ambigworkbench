# Cost / Resource Analysis

Rows analyzed: 4710

## Metric Definitions

| Metric | Formula / Source | What It Measures | Notes |
|---|---|---|---|
| total_token_expenditure | `sum(total_tokens)` | Total recorded token budget spent by a condition. | Main cost metric. Runtime failures with missing telemetry can make this a lower bound. |
| failed_token_share | `sum(tokens for failed tasks) / sum(total_tokens)` | Fraction of recorded token budget spent on unsuccessful trajectories. | Main cost metric. Separates productive from unproductive computation. |
| tokens_per_success | `sum(total_tokens) / success_count` | Aggregate token cost per successful task. | Undefined when success count is zero. |
| input/output token split | JSONL `total_input_tokens`, `total_output_tokens` | Whether cost comes from context/prompt burden or generation verbosity. | Appendix robustness metric. |
| first_turn_input_tokens | first turn `input_tokens` | Initial prompt/context size for each task. | Appendix robustness metric; useful proxy for memory context pressure. |
| agent/oracle split | JSONL `agent_tokens`, `oracle_tokens` | Separates evaluated-agent inference from clarification/correction oracle inference. | Appendix robustness metric. |
| oracle clarification/correction split | JSONL oracle token subfields | Separates pre-action clarification from post-action correction feedback. | Appendix robustness metric. |
| e2e_latency_ms | JSONL `e2e_latency_ms` | Wall-clock end-to-end trajectory time. | Appendix robustness metric; affected by GPU load, network, vLLM queueing, and context length. |
| zero_token_runtime_failure_rate | `zero-token runtime failures / n` | Share of trajectories with missing token telemetry after runtime failure. | Appendix robustness metric and limitation check. |

## Main Cost Analysis By Identity

| Identity | n | Success rate | Total token expenditure | Successful-trajectory tokens | Failed-trajectory tokens | Failed token share | Tokens / success |
|---|---:|---:|---:|---:|---:|---:|---:|
| Bold | 1570 | 0.778 | 889483479 | 641365052 | 248118427 | 0.279 | 728487.7 |
| Cautious | 1570 | 0.719 | 900355685 | 568282742 | 332072943 | 0.369 | 797480.7 |
| Neutral | 1570 | 0.755 | 925341199 | 632616181 | 292725018 | 0.316 | 780878.6 |

## Main Cost Analysis By Run And Identity

| Run | Identity | n | Success rate | Total token expenditure | Failed token share | Tokens / success |
|---:|---|---:|---:|---:|---:|---:|
| 1 | Bold | 314 | 0.761 | 99722828 | 0.325 | 417250.3 |
| 1 | Cautious | 314 | 0.726 | 80288930 | 0.320 | 352144.4 |
| 1 | Neutral | 314 | 0.752 | 92626835 | 0.338 | 392486.6 |
| 2 | Bold | 314 | 0.783 | 143008586 | 0.297 | 581335.7 |
| 2 | Cautious | 314 | 0.774 | 130714322 | 0.272 | 537919.0 |
| 2 | Neutral | 314 | 0.815 | 136798874 | 0.255 | 534370.6 |
| 3 | Bold | 314 | 0.809 | 178805107 | 0.245 | 703957.1 |
| 3 | Cautious | 314 | 0.803 | 180377885 | 0.245 | 715785.3 |
| 3 | Neutral | 314 | 0.793 | 179562150 | 0.245 | 721133.1 |
| 4 | Bold | 314 | 0.780 | 211462037 | 0.274 | 863110.4 |
| 4 | Cautious | 314 | 0.809 | 203570965 | 0.241 | 801460.5 |
| 4 | Neutral | 314 | 0.796 | 215767994 | 0.238 | 863072.0 |
| 5 | Bold | 314 | 0.755 | 256484921 | 0.279 | 1082214.9 |
| 5 | Cautious | 314 | 0.484 | 305403583 | 0.581 | 2009234.1 |
| 5 | Neutral | 314 | 0.618 | 300585346 | 0.436 | 1549409.0 |

## Appendix Robustness By Identity

| Condition | Total tokens mean / median / p95 | Agent tokens sum | Oracle tokens sum | Oracle clarify / correct | Input / output tokens | First-turn input mean | Latency mean / p95 ms | Zero-token runtime failure rate |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Bold | 566550.0 / 451400.5 / 1413553.5 | 888126777 | 1356702 | 586185 / 770517 | 885445554 / 2681223 | 119037.8 | 19943.7 / 39124.6 | 0.001 |
| Cautious | 573475.0 / 438193.5 / 1404399.1 | 898804331 | 1551354 | 911600 / 639754 | 896290663 / 2513668 | 78695.0 | 19978.1 / 38028.1 | 0.001 |
| Neutral | 589389.3 / 446554.0 / 1454784.1 | 923868345 | 1472854 | 762111 / 710743 | 921269666 / 2598679 | 96496.4 | 20061.4 / 39511.4 | 0.000 |

## Kruskal-Wallis By Resource Metric

| Metric | H | p |
|---|---:|---:|
| total_tokens | 2.46945 | 0.290914 |
| agent_tokens | 2.52145 | 0.283449 |
| oracle_tokens | 38.7622 | 3.82736e-09 |
| oracle_clarification_tokens | 251.617 | 2.30221e-55 |
| oracle_correction_tokens | 25.2267 | 3.3273e-06 |
| input_tokens | 2.50596 | 0.285652 |
| output_tokens | 9.2498 | 0.00980465 |
| first_turn_input_tokens | 112.207 | 4.31186e-25 |
| total_turns | 32.1744 | 1.03136e-07 |
| correction_turns | 29.4616 | 4.00399e-07 |
| e2e_latency_ms | 0.395807 | 0.820449 |
