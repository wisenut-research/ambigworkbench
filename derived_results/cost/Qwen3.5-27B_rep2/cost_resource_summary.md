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
| Bold | 1570 | 0.780 | 675795571 | 488409344 | 187386227 | 0.277 | 551669.9 |
| Cautious | 1570 | 0.783 | 685304732 | 480343712 | 204961020 | 0.299 | 557611.7 |
| Neutral | 1570 | 0.793 | 750337387 | 532784665 | 217552722 | 0.290 | 602680.6 |

## Main Cost Analysis By Run And Identity

| Run | Identity | n | Success rate | Total token expenditure | Failed token share | Tokens / success |
|---:|---|---:|---:|---:|---:|---:|
| 1 | Bold | 314 | 0.726 | 94984604 | 0.344 | 416599.1 |
| 1 | Cautious | 314 | 0.768 | 83918200 | 0.276 | 348208.3 |
| 1 | Neutral | 314 | 0.761 | 101815737 | 0.327 | 426007.3 |
| 2 | Bold | 314 | 0.803 | 119766666 | 0.242 | 475264.5 |
| 2 | Cautious | 314 | 0.803 | 105870484 | 0.274 | 420121.0 |
| 2 | Neutral | 314 | 0.822 | 129310260 | 0.274 | 501202.6 |
| 3 | Bold | 314 | 0.815 | 134092067 | 0.237 | 523797.1 |
| 3 | Cautious | 314 | 0.790 | 132572962 | 0.292 | 534568.4 |
| 3 | Neutral | 314 | 0.796 | 143082094 | 0.285 | 572328.4 |
| 4 | Bold | 314 | 0.771 | 156404956 | 0.289 | 646301.5 |
| 4 | Cautious | 314 | 0.783 | 167605349 | 0.319 | 681322.6 |
| 4 | Neutral | 314 | 0.793 | 176336392 | 0.283 | 708178.3 |
| 5 | Bold | 314 | 0.787 | 170547278 | 0.286 | 690474.8 |
| 5 | Cautious | 314 | 0.771 | 195337737 | 0.311 | 807180.7 |
| 5 | Neutral | 314 | 0.793 | 199792904 | 0.291 | 802381.1 |

## Appendix Robustness By Identity

| Condition | Total tokens mean / median / p95 | Agent tokens sum | Oracle tokens sum | Oracle clarify / correct | Input / output tokens | First-turn input mean | Latency mean / p95 ms | Zero-token runtime failure rate |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Bold | 430443.0 / 392464.5 / 852886.5 | 674370479 | 1425092 | 636645 / 788447 | 672204970 / 2165509 | 220676.7 | 49492.9 / 95611.4 | 0.001 |
| Cautious | 436499.8 / 362108.0 / 997625.7 | 683054148 | 2250584 | 1723710 / 526874 | 679892511 / 3161637 | 193874.9 | 57723.1 / 123299.9 | 0.003 |
| Neutral | 477921.9 / 388716.5 / 1118765.1 | 748297122 | 2040265 | 1412536 / 627729 | 745066932 / 3230190 | 207954.7 | 60822.4 / 134342.1 | 0.004 |

## Kruskal-Wallis By Resource Metric

| Metric | H | p |
|---|---:|---:|
| total_tokens | 11.2341 | 0.00363543 |
| agent_tokens | 11.517 | 0.0031559 |
| oracle_tokens | 223.934 | 2.36296e-49 |
| oracle_clarification_tokens | 608.549 | 7.1657e-133 |
| oracle_correction_tokens | 97.6985 | 6.09596e-22 |
| input_tokens | 11.7603 | 0.00279442 |
| output_tokens | 209.166 | 3.80405e-46 |
| first_turn_input_tokens | 93.1565 | 5.90627e-21 |
| total_turns | 35.3407 | 2.11766e-08 |
| correction_turns | 111.059 | 7.65486e-25 |
| e2e_latency_ms | 47.2527 | 5.48525e-11 |
