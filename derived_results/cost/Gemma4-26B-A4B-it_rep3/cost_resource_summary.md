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
| Bold | 1570 | 0.666 | 4101329804 | 2374554420 | 1726775384 | 0.421 | 3924717.5 |
| Cautious | 1570 | 0.713 | 3995112799 | 2442066199 | 1553046600 | 0.389 | 3570252.7 |
| Neutral | 1570 | 0.684 | 4106218065 | 2502101383 | 1604116682 | 0.391 | 3823294.3 |

## Main Cost Analysis By Run And Identity

| Run | Identity | n | Success rate | Total token expenditure | Failed token share | Tokens / success |
|---:|---|---:|---:|---:|---:|---:|
| 1 | Bold | 314 | 0.726 | 696451040 | 0.364 | 3054609.8 |
| 1 | Cautious | 314 | 0.707 | 707228008 | 0.407 | 3185711.7 |
| 1 | Neutral | 314 | 0.691 | 731870145 | 0.392 | 3372673.5 |
| 2 | Bold | 314 | 0.688 | 837200182 | 0.459 | 3875926.8 |
| 2 | Cautious | 314 | 0.758 | 793875097 | 0.347 | 3335609.7 |
| 2 | Neutral | 314 | 0.717 | 821494008 | 0.388 | 3651084.5 |
| 3 | Bold | 314 | 0.669 | 880300737 | 0.400 | 4191908.3 |
| 3 | Cautious | 314 | 0.723 | 856714649 | 0.399 | 3774073.3 |
| 3 | Neutral | 314 | 0.694 | 879055140 | 0.404 | 4032363.0 |
| 4 | Bold | 314 | 0.621 | 839236523 | 0.424 | 4303777.0 |
| 4 | Cautious | 314 | 0.672 | 801217719 | 0.427 | 3797240.4 |
| 4 | Neutral | 314 | 0.678 | 848588969 | 0.378 | 3983985.8 |
| 5 | Bold | 314 | 0.624 | 848141322 | 0.450 | 4327251.6 |
| 5 | Cautious | 314 | 0.704 | 836077326 | 0.367 | 3783155.3 |
| 5 | Neutral | 314 | 0.640 | 825209803 | 0.390 | 4105521.4 |

## Appendix Robustness By Identity

| Condition | Total tokens mean / median / p95 | Agent tokens sum | Oracle tokens sum | Oracle clarify / correct | Input / output tokens | First-turn input mean | Latency mean / p95 ms | Zero-token runtime failure rate |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Bold | 2612312.0 / 1957506.5 / 6837333.6 | 4098430684 | 2899120 | 1933329 / 965791 | 4076390508 / 22040176 | 1233579.1 | 103620.5 / 283173.4 | 0.031 |
| Cautious | 2544657.8 / 1913563.0 / 6828228.0 | 3992038036 | 3074763 | 2348701 / 726062 | 3970424954 / 21613082 | 847121.7 | 97201.1 / 262488.0 | 0.019 |
| Neutral | 2615425.5 / 1984855.0 / 7067292.7 | 4102856125 | 3361940 | 2500678 / 861262 | 4080489499 / 22366626 | 1183247.9 | 103873.0 / 281423.0 | 0.027 |

## Kruskal-Wallis By Resource Metric

| Metric | H | p |
|---|---:|---:|
| total_tokens | 1.13464 | 0.567044 |
| agent_tokens | 1.13444 | 0.5671 |
| oracle_tokens | 23.1794 | 9.26099e-06 |
| oracle_clarification_tokens | 77.8323 | 1.25581e-17 |
| oracle_correction_tokens | 45.9106 | 1.07312e-10 |
| input_tokens | 1.13944 | 0.565683 |
| output_tokens | 0.67512 | 0.713509 |
| first_turn_input_tokens | 207.111 | 1.06262e-45 |
| total_turns | 4.65691 | 0.0974462 |
| correction_turns | 55.1875 | 1.03797e-12 |
| e2e_latency_ms | 6.80009 | 0.0333718 |
