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
| Bold | 1570 | 0.661 | 923706890 | 530824217 | 392882673 | 0.425 | 889891.0 |
| Cautious | 1570 | 0.700 | 812955022 | 517595133 | 295359889 | 0.363 | 739722.5 |
| Neutral | 1570 | 0.691 | 1038363215 | 632549195 | 405814020 | 0.391 | 957016.8 |

## Main Cost Analysis By Run And Identity

| Run | Identity | n | Success rate | Total token expenditure | Failed token share | Tokens / success |
|---:|---|---:|---:|---:|---:|---:|
| 1 | Bold | 314 | 0.646 | 86337377 | 0.492 | 425307.3 |
| 1 | Cautious | 314 | 0.729 | 71331055 | 0.329 | 311489.3 |
| 1 | Neutral | 314 | 0.682 | 86437044 | 0.405 | 403911.4 |
| 2 | Bold | 314 | 0.691 | 134381972 | 0.402 | 619271.8 |
| 2 | Cautious | 314 | 0.752 | 120865442 | 0.300 | 512141.7 |
| 2 | Neutral | 314 | 0.771 | 139413184 | 0.300 | 576087.5 |
| 3 | Bold | 314 | 0.697 | 188473660 | 0.419 | 860610.3 |
| 3 | Cautious | 314 | 0.755 | 170041425 | 0.305 | 717474.4 |
| 3 | Neutral | 314 | 0.774 | 193730800 | 0.282 | 797246.1 |
| 4 | Bold | 314 | 0.685 | 237676624 | 0.405 | 1105472.7 |
| 4 | Cautious | 314 | 0.732 | 203170456 | 0.329 | 883349.8 |
| 4 | Neutral | 314 | 0.768 | 253249920 | 0.275 | 1050829.5 |
| 5 | Bold | 314 | 0.586 | 276837257 | 0.437 | 1504550.3 |
| 5 | Cautious | 314 | 0.532 | 247546644 | 0.472 | 1482315.2 |
| 5 | Neutral | 314 | 0.462 | 365532267 | 0.560 | 2520912.2 |

## Appendix Robustness By Identity

| Condition | Total tokens mean / median / p95 | Agent tokens sum | Oracle tokens sum | Oracle clarify / correct | Input / output tokens | First-turn input mean | Latency mean / p95 ms | Zero-token runtime failure rate |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Bold | 588348.3 / 444970.0 / 1525492.2 | 922121249 | 1585641 | 638828 / 946813 | 920181758 / 1939491 | 107102.9 | 19931.6 / 38807.9 | 0.001 |
| Cautious | 517805.7 / 409353.5 / 1286386.4 | 811365586 | 1589436 | 896681 / 692755 | 809824547 / 1541039 | 67814.9 | 18001.3 / 33281.7 | 0.000 |
| Neutral | 661377.8 / 473058.0 / 1791006.2 | 1036783548 | 1579667 | 788949 / 790718 | 1034963990 / 1819558 | 95570.3 | 19320.4 / 37424.6 | 0.000 |

## Kruskal-Wallis By Resource Metric

| Metric | H | p |
|---|---:|---:|
| total_tokens | 32.8701 | 7.28361e-08 |
| agent_tokens | 32.966 | 6.9426e-08 |
| oracle_tokens | 1.81944 | 0.402637 |
| oracle_clarification_tokens | 167.344 | 4.58804e-37 |
| oracle_correction_tokens | 54.6562 | 1.35379e-12 |
| input_tokens | 32.8648 | 7.30299e-08 |
| output_tokens | 79.2931 | 6.0494e-18 |
| first_turn_input_tokens | 76.823 | 2.08016e-17 |
| total_turns | 0.0557166 | 0.972526 |
| correction_turns | 71.3749 | 3.1706e-16 |
| e2e_latency_ms | 23.2022 | 9.15588e-06 |
