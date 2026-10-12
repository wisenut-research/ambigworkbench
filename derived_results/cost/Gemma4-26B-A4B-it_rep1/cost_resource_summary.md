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
| Bold | 1570 | 0.686 | 4014582560 | 2475017013 | 1539565547 | 0.383 | 3727560.4 |
| Cautious | 1570 | 0.710 | 3936470908 | 2359753775 | 1576717133 | 0.401 | 3530467.2 |
| Neutral | 1570 | 0.689 | 4106167738 | 2430605124 | 1675562614 | 0.408 | 3794979.4 |

## Main Cost Analysis By Run And Identity

| Run | Identity | n | Success rate | Total token expenditure | Failed token share | Tokens / success |
|---:|---|---:|---:|---:|---:|---:|
| 1 | Bold | 314 | 0.707 | 714088684 | 0.390 | 3216615.7 |
| 1 | Cautious | 314 | 0.678 | 707397092 | 0.403 | 3321113.1 |
| 1 | Neutral | 314 | 0.678 | 712343830 | 0.438 | 3344337.2 |
| 2 | Bold | 314 | 0.704 | 809938405 | 0.358 | 3664879.7 |
| 2 | Cautious | 314 | 0.710 | 749903978 | 0.392 | 3362798.1 |
| 2 | Neutral | 314 | 0.682 | 802321812 | 0.408 | 3749167.3 |
| 3 | Bold | 314 | 0.666 | 836586387 | 0.442 | 4002805.7 |
| 3 | Cautious | 314 | 0.713 | 798189633 | 0.426 | 3563346.6 |
| 3 | Neutral | 314 | 0.726 | 834231628 | 0.375 | 3658910.6 |
| 4 | Bold | 314 | 0.701 | 866460149 | 0.371 | 3938455.2 |
| 4 | Cautious | 314 | 0.745 | 860107539 | 0.399 | 3675673.2 |
| 4 | Neutral | 314 | 0.707 | 886120678 | 0.397 | 3991534.6 |
| 5 | Bold | 314 | 0.653 | 787508935 | 0.356 | 3841507.0 |
| 5 | Cautious | 314 | 0.704 | 820872666 | 0.383 | 3714356.0 |
| 5 | Neutral | 314 | 0.653 | 871149790 | 0.425 | 4249511.2 |

## Appendix Robustness By Identity

| Condition | Total tokens mean / median / p95 | Agent tokens sum | Oracle tokens sum | Oracle clarify / correct | Input / output tokens | First-turn input mean | Latency mean / p95 ms | Zero-token runtime failure rate |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Bold | 2557059.0 / 1892311.5 / 6888511.0 | 4011571288 | 3011272 | 2071161 / 940111 | 3988629212 / 22942076 | 1217521.2 | 106068.9 / 287029.3 | 0.029 |
| Cautious | 2507306.3 / 1884556.5 / 6773485.5 | 3933428824 | 3042084 | 2294020 / 748064 | 3911148495 / 22280329 | 828721.7 | 98517.1 / 239525.6 | 0.013 |
| Neutral | 2615393.5 / 1961710.5 / 6952471.2 | 4102769503 | 3398235 | 2515158 / 883077 | 4079622629 / 23146874 | 1144136.2 | 104366.5 / 265045.9 | 0.018 |

## Kruskal-Wallis By Resource Metric

| Metric | H | p |
|---|---:|---:|
| total_tokens | 1.01873 | 0.600878 |
| agent_tokens | 1.01391 | 0.602327 |
| oracle_tokens | 22.6985 | 1.17786e-05 |
| oracle_clarification_tokens | 52.7764 | 3.46531e-12 |
| oracle_correction_tokens | 36.4726 | 1.20248e-08 |
| input_tokens | 1.00479 | 0.60508 |
| output_tokens | 1.42209 | 0.491131 |
| first_turn_input_tokens | 186.019 | 4.04076e-41 |
| total_turns | 13.5521 | 0.00114075 |
| correction_turns | 43.265 | 4.02829e-10 |
| e2e_latency_ms | 7.59011 | 0.0224817 |
