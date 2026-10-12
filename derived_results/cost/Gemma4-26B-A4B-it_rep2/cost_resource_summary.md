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
| Bold | 1570 | 0.699 | 3695416005 | 2343867410 | 1351548595 | 0.366 | 3365588.3 |
| Cautious | 1570 | 0.713 | 3624463304 | 2218509663 | 1405953641 | 0.388 | 3236128.0 |
| Neutral | 1570 | 0.704 | 3686601446 | 2218909563 | 1467691883 | 0.398 | 3333274.4 |

## Main Cost Analysis By Run And Identity

| Run | Identity | n | Success rate | Total token expenditure | Failed token share | Tokens / success |
|---:|---|---:|---:|---:|---:|---:|
| 1 | Bold | 314 | 0.707 | 626699800 | 0.382 | 2822972.1 |
| 1 | Cautious | 314 | 0.732 | 614720087 | 0.344 | 2672696.0 |
| 1 | Neutral | 314 | 0.739 | 635746104 | 0.390 | 2740284.9 |
| 2 | Bold | 314 | 0.707 | 721626997 | 0.378 | 3250572.1 |
| 2 | Cautious | 314 | 0.745 | 705152674 | 0.371 | 3013473.0 |
| 2 | Neutral | 314 | 0.720 | 708622070 | 0.342 | 3135495.9 |
| 3 | Bold | 314 | 0.710 | 782887903 | 0.356 | 3510708.1 |
| 3 | Cautious | 314 | 0.688 | 778632331 | 0.444 | 3604779.3 |
| 3 | Neutral | 314 | 0.701 | 802218591 | 0.410 | 3646448.1 |
| 4 | Bold | 314 | 0.713 | 816160690 | 0.356 | 3643574.5 |
| 4 | Cautious | 314 | 0.713 | 768666127 | 0.361 | 3431545.2 |
| 4 | Neutral | 314 | 0.704 | 770948652 | 0.407 | 3488455.4 |
| 5 | Bold | 314 | 0.659 | 748040615 | 0.361 | 3613722.8 |
| 5 | Cautious | 314 | 0.688 | 757292085 | 0.410 | 3505981.9 |
| 5 | Neutral | 314 | 0.659 | 769066029 | 0.435 | 3715294.8 |

## Appendix Robustness By Identity

| Condition | Total tokens mean / median / p95 | Agent tokens sum | Oracle tokens sum | Oracle clarify / correct | Input / output tokens | First-turn input mean | Latency mean / p95 ms | Zero-token runtime failure rate |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Bold | 2353768.2 / 1780700.0 / 6100787.5 | 3692383755 | 3032250 | 2112340 / 919910 | 3669746548 / 22637207 | 1139933.4 | 101984.4 / 259780.6 | 0.020 |
| Cautious | 2308575.4 / 1777715.5 / 6048392.0 | 3621438141 | 3025163 | 2307153 / 718010 | 3599253724 / 22184417 | 755838.1 | 99896.1 / 254162.0 | 0.018 |
| Neutral | 2348153.8 / 1712066.5 / 6647051.5 | 3683443601 | 3157845 | 2319530 / 838315 | 3661089446 / 22354155 | 1035171.9 | 101664.7 / 282141.1 | 0.024 |

## Kruskal-Wallis By Resource Metric

| Metric | H | p |
|---|---:|---:|
| total_tokens | 1.88779 | 0.389109 |
| agent_tokens | 1.88779 | 0.389108 |
| oracle_tokens | 5.06583 | 0.0794271 |
| oracle_clarification_tokens | 40.533 | 1.57893e-09 |
| oracle_correction_tokens | 29.2991 | 4.34301e-07 |
| input_tokens | 1.889 | 0.388875 |
| output_tokens | 1.19037 | 0.551459 |
| first_turn_input_tokens | 242.216 | 2.53253e-53 |
| total_turns | 13.3055 | 0.00129049 |
| correction_turns | 42.4799 | 5.96503e-10 |
| e2e_latency_ms | 2.28944 | 0.318312 |
