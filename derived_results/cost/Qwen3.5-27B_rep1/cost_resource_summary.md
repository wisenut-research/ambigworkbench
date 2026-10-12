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
| Bold | 1570 | 0.726 | 763154844 | 510210018 | 252944826 | 0.331 | 669434.1 |
| Cautious | 1570 | 0.769 | 724454898 | 508884776 | 215570122 | 0.298 | 599714.3 |
| Neutral | 1570 | 0.785 | 687668268 | 484148900 | 203519368 | 0.296 | 558172.3 |

## Main Cost Analysis By Run And Identity

| Run | Identity | n | Success rate | Total token expenditure | Failed token share | Tokens / success |
|---:|---|---:|---:|---:|---:|---:|
| 1 | Bold | 314 | 0.752 | 95356716 | 0.285 | 404053.9 |
| 1 | Cautious | 314 | 0.771 | 94020035 | 0.292 | 388512.5 |
| 1 | Neutral | 314 | 0.777 | 100227792 | 0.290 | 410769.6 |
| 2 | Bold | 314 | 0.717 | 130246664 | 0.345 | 578874.1 |
| 2 | Cautious | 314 | 0.764 | 127090587 | 0.290 | 529544.1 |
| 2 | Neutral | 314 | 0.806 | 114242580 | 0.267 | 451551.7 |
| 3 | Bold | 314 | 0.720 | 154600686 | 0.322 | 684073.8 |
| 3 | Cautious | 314 | 0.768 | 152083883 | 0.310 | 631053.5 |
| 3 | Neutral | 314 | 0.799 | 140629932 | 0.269 | 560278.6 |
| 4 | Bold | 314 | 0.713 | 184527163 | 0.353 | 823782.0 |
| 4 | Cautious | 314 | 0.758 | 167264658 | 0.326 | 702792.7 |
| 4 | Neutral | 314 | 0.783 | 152439862 | 0.310 | 619674.2 |
| 5 | Bold | 314 | 0.729 | 198423615 | 0.333 | 866478.7 |
| 5 | Cautious | 314 | 0.787 | 183995735 | 0.269 | 744922.0 |
| 5 | Neutral | 314 | 0.758 | 180128102 | 0.327 | 756840.8 |

## Appendix Robustness By Identity

| Condition | Total tokens mean / median / p95 | Agent tokens sum | Oracle tokens sum | Oracle clarify / correct | Input / output tokens | First-turn input mean | Latency mean / p95 ms | Zero-token runtime failure rate |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Bold | 486085.9 / 424539.5 / 1055632.8 | 761697747 | 1457097 | 601682 / 855415 | 759439257 / 2258490 | 246362.7 | 58859.5 / 131083.2 | 0.008 |
| Cautious | 461436.2 / 382547.0 / 1063695.4 | 722588577 | 1866321 | 1273505 / 592816 | 719802703 / 2785874 | 205107.2 | 58819.7 / 126347.6 | 0.003 |
| Neutral | 438005.3 / 375854.0 / 990517.2 | 686024614 | 1643654 | 999262 / 644392 | 683403731 / 2620883 | 211693.3 | 55275.9 / 124205.7 | 0.004 |

## Kruskal-Wallis By Resource Metric

| Metric | H | p |
|---|---:|---:|
| total_tokens | 27.1339 | 1.28215e-06 |
| agent_tokens | 27.3595 | 1.1454e-06 |
| oracle_tokens | 67.1524 | 2.6184e-15 |
| oracle_clarification_tokens | 320.95 | 2.02619e-70 |
| oracle_correction_tokens | 101.345 | 9.84293e-23 |
| input_tokens | 27.6566 | 9.87314e-07 |
| output_tokens | 37.0751 | 8.89716e-09 |
| first_turn_input_tokens | 102.974 | 4.3598e-23 |
| total_turns | 4.8166 | 0.089968 |
| correction_turns | 117.104 | 3.72603e-26 |
| e2e_latency_ms | 12.9966 | 0.00150602 |
