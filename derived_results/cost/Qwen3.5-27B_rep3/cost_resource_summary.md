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
| Bold | 1570 | 0.754 | 679071300 | 458167025 | 220904275 | 0.325 | 573539.9 |
| Cautious | 1570 | 0.797 | 703103784 | 515134687 | 187969097 | 0.267 | 561584.5 |
| Neutral | 1570 | 0.827 | 682146905 | 522700524 | 159446381 | 0.234 | 525536.9 |

## Main Cost Analysis By Run And Identity

| Run | Identity | n | Success rate | Total token expenditure | Failed token share | Tokens / success |
|---:|---|---:|---:|---:|---:|---:|
| 1 | Bold | 314 | 0.729 | 96739183 | 0.363 | 422441.8 |
| 1 | Cautious | 314 | 0.739 | 92649488 | 0.340 | 399351.2 |
| 1 | Neutral | 314 | 0.793 | 98573098 | 0.266 | 395875.9 |
| 2 | Bold | 314 | 0.761 | 114894494 | 0.328 | 480730.1 |
| 2 | Cautious | 314 | 0.822 | 113752066 | 0.229 | 440899.5 |
| 2 | Neutral | 314 | 0.822 | 107703407 | 0.248 | 417455.1 |
| 3 | Bold | 314 | 0.748 | 136480663 | 0.333 | 580768.8 |
| 3 | Cautious | 314 | 0.796 | 142252215 | 0.262 | 569008.9 |
| 3 | Neutral | 314 | 0.841 | 134229357 | 0.200 | 508444.5 |
| 4 | Bold | 314 | 0.745 | 158921043 | 0.339 | 679149.8 |
| 4 | Cautious | 314 | 0.815 | 167700953 | 0.263 | 655081.8 |
| 4 | Neutral | 314 | 0.847 | 158156954 | 0.227 | 594575.0 |
| 5 | Bold | 314 | 0.787 | 172035917 | 0.284 | 696501.7 |
| 5 | Cautious | 314 | 0.815 | 186749062 | 0.263 | 729488.5 |
| 5 | Neutral | 314 | 0.831 | 183484089 | 0.239 | 703004.2 |

## Appendix Robustness By Identity

| Condition | Total tokens mean / median / p95 | Agent tokens sum | Oracle tokens sum | Oracle clarify / correct | Input / output tokens | First-turn input mean | Latency mean / p95 ms | Zero-token runtime failure rate |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Bold | 432529.5 / 371148.0 / 938816.0 | 677506093 | 1565207 | 699206 / 866001 | 675070532 / 2435561 | 212611.3 | 52655.7 / 113603.4 | 0.002 |
| Cautious | 447836.8 / 380926.0 / 970804.6 | 701013824 | 2089960 | 1547057 / 542903 | 698023501 / 2990323 | 195499.4 | 56619.5 / 119524.8 | 0.001 |
| Neutral | 434488.5 / 367786.0 / 937204.0 | 680273372 | 1873533 | 1311321 / 562212 | 677583729 / 2689643 | 209052.3 | 54209.3 / 116208.9 | 0.003 |

## Kruskal-Wallis By Resource Metric

| Metric | H | p |
|---|---:|---:|
| total_tokens | 1.80835 | 0.404875 |
| agent_tokens | 1.74533 | 0.417836 |
| oracle_tokens | 96.7708 | 9.69342e-22 |
| oracle_clarification_tokens | 463.07 | 2.78984e-101 |
| oracle_correction_tokens | 156.595 | 9.90649e-35 |
| input_tokens | 1.67569 | 0.432643 |
| output_tokens | 44.6311 | 2.03462e-10 |
| first_turn_input_tokens | 35.693 | 1.77567e-08 |
| total_turns | 6.24097 | 0.0441358 |
| correction_turns | 180.985 | 5.00817e-40 |
| e2e_latency_ms | 13.92 | 0.000949079 |
