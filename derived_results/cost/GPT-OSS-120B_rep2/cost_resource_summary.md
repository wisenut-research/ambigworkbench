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
| Bold | 1570 | 0.708 | 789375131 | 515032111 | 274343020 | 0.348 | 709869.7 |
| Cautious | 1570 | 0.711 | 823017605 | 551686672 | 271330933 | 0.330 | 737471.0 |
| Neutral | 1570 | 0.710 | 898689276 | 593380774 | 305308502 | 0.340 | 806722.9 |

## Main Cost Analysis By Run And Identity

| Run | Identity | n | Success rate | Total token expenditure | Failed token share | Tokens / success |
|---:|---|---:|---:|---:|---:|---:|
| 1 | Bold | 314 | 0.713 | 79093326 | 0.372 | 353095.2 |
| 1 | Cautious | 314 | 0.732 | 71781960 | 0.353 | 312095.5 |
| 1 | Neutral | 314 | 0.678 | 89540002 | 0.405 | 420375.6 |
| 2 | Bold | 314 | 0.713 | 119536080 | 0.370 | 533643.2 |
| 2 | Cautious | 314 | 0.752 | 119252664 | 0.286 | 505307.9 |
| 2 | Neutral | 314 | 0.650 | 136455386 | 0.465 | 668899.0 |
| 3 | Bold | 314 | 0.739 | 159991960 | 0.318 | 689620.5 |
| 3 | Cautious | 314 | 0.758 | 168732135 | 0.287 | 708958.6 |
| 3 | Neutral | 314 | 0.790 | 184625384 | 0.268 | 744457.2 |
| 4 | Bold | 314 | 0.752 | 204702926 | 0.307 | 867385.3 |
| 4 | Cautious | 314 | 0.758 | 211197910 | 0.259 | 887386.2 |
| 4 | Neutral | 314 | 0.764 | 226453628 | 0.285 | 943556.8 |
| 5 | Bold | 314 | 0.624 | 226050839 | 0.385 | 1153320.6 |
| 5 | Cautious | 314 | 0.554 | 252052936 | 0.432 | 1448580.1 |
| 5 | Neutral | 314 | 0.666 | 261614876 | 0.350 | 1251745.8 |

## Appendix Robustness By Identity

| Condition | Total tokens mean / median / p95 | Agent tokens sum | Oracle tokens sum | Oracle clarify / correct | Input / output tokens | First-turn input mean | Latency mean / p95 ms | Zero-token runtime failure rate |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Bold | 502786.7 / 403958.5 / 1269269.6 | 787909547 | 1465584 | 619206 / 846378 | 786166860 / 1742687 | 93805.5 | 18450.1 / 35011.7 | 0.000 |
| Cautious | 524215.0 / 415937.0 / 1373008.2 | 821439466 | 1578139 | 876516 / 701623 | 819860481 / 1578985 | 67245.5 | 18425.7 / 33996.9 | 0.001 |
| Neutral | 572413.6 / 452375.0 / 1384951.9 | 897125760 | 1563516 | 802680 / 760836 | 895329873 / 1795887 | 92678.8 | 19332.7 / 36876.4 | 0.000 |

## Kruskal-Wallis By Resource Metric

| Metric | H | p |
|---|---:|---:|
| total_tokens | 21.148 | 2.55718e-05 |
| agent_tokens | 21.1572 | 2.54548e-05 |
| oracle_tokens | 13.3392 | 0.0012689 |
| oracle_clarification_tokens | 182.608 | 2.22375e-40 |
| oracle_correction_tokens | 23.7887 | 6.82882e-06 |
| input_tokens | 21.1586 | 2.54376e-05 |
| output_tokens | 24.3729 | 5.09916e-06 |
| first_turn_input_tokens | 54.7281 | 1.30602e-12 |
| total_turns | 9.39927 | 0.00909861 |
| correction_turns | 28.2616 | 7.29568e-07 |
| e2e_latency_ms | 7.02635 | 0.0298022 |
