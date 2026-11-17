# AmbigWorkBench

This repository accompanies *Cumulative Memory Changes Agent Behavior Under
Ambiguity: Repeated-Task Evidence on Performance and Cost*.

It is a deliberately minimal package. It contains the task suite,
deterministic evaluator, experiment runner, prompt-condition workspaces,
serving configurations, intervention scripts, analysis code, and compact
derived outputs. It does not include raw session transcripts, credentials,
model weights, or internal review material.

Software and data are kept together in this repository. `SHA256SUMS` lists a
checksum for every file; verify them from the repository root with
`shasum -a 256 -c SHA256SUMS`.

## Contents

| Path | Paper section | Description |
|---|---|---|
| `benchmark/tasks/ambig_queries.json` | §3.1 | 314 ambiguous task variants with dimension and level labels and WorkBench answer keys |
| `benchmark/seed/` | §3.1 | deterministic initial state for the five task databases |
| `runner/`, `seed_manager.py` | §§3.3--3.4 | multi-turn runner, clarification and correction response models, state evaluator, task reset, cumulative-memory protocol, and action-precision instrumentation |
| `workspace/` | §3.2 | prompt conditions, WorkBench tools, and initial task databases |
| `openclaw-config/` | §3.4 | OpenClaw configuration used in the experiments, with `<gpu-host>` placeholders |
| `configs/profiles/` | Appendix N.3 | model-specific OpenClaw and vLLM settings for GPT-OSS-120B, GPT-OSS-20B, Qwen3.5-27B, and Gemma4-26B-A4B-it |
| `scripts/run_full_cumul.sh` | §3.3 | five cumulative runs for one replicate, three conditions interleaved in one process (GPT-OSS-120B, Qwen3.5-27B, GPT-OSS-20B) |
| `scripts/run_full_cumul_parallel.sh`, `scripts/run_gemma4_reps.sh` | §3.4 | the same protocol with the three conditions as concurrent processes (Gemma4-26B-A4B-it) |
| `scripts/run_gate_strip_ablation.sh` | §5.3.4 | matched-line removal intervention |
| `scripts/build_random_strip_size_matched.py`, `scripts/build_nongating_loadmatched.py` | §5.3.5 | corpora for the matched-line-retaining low-load and zero-match high-load controls |
| `scripts/run_content_volume_control.sh` | §5.3.5 | targeted GPT-OSS content–volume controls |
| `scripts/content_volume_control_analysis.py` | §5.3.5 | compact summary of the content–volume controls |
| `scripts/run_seeding_ablation.sh` | §5.3.6 | cross-model matched-line memory-injection intervention |
| `scripts/run_seeding_control_ablation.sh` | §5.3.6 | token-matched unmatched-line control |
| `scripts/run_sharedmem_ablation.sh` | §5.3.3 | shared-starting-memory intervention |
| `scripts/paired_intervention_analysis.py` | §§5.3.3--5.3.6 | paired analyses with bootstrap intervals clustered by the 80 source WorkBench tasks, task-order quartiles, and manipulation checks |
| `analysis/`, `scripts/make_figures.py` | §5 and appendices | main aggregation, behavior, performance, cost, and code for Figures 2--5 |
| `scripts/tables/` | §5 and appendices | regenerates every data table in the paper (28 tables) from run JSONL and memory snapshots |
| `derived_results/` | §5 and appendices | plain-text statistical and per-replicate cost outputs reported in the paper |

The operational identifier `soul` denotes an agent instance assigned a prompt
condition: `soul-a` is Neutral, `soul-b` is Cautious, and `soul-c` is Bold.

## Environment

- Python 3.10 or later
- Docker with OpenClaw version 2026.3.3
- A vLLM server configured from the matching `configs/profiles/` entry
- `OPENAI_API_KEY` for the GPT-4o-mini clarification and correction response models
- `VLLM_METRICS=http://<gpu-host>:9022/metrics` for token accounting

Install the Python dependencies with:

```bash
python3 -m pip install -r requirements.txt
```

Replace `<gpu-host>` in `openclaw-config/openclaw.json` and
`openclaw-config/agents/*/agent/models.json`, then mount
`openclaw-config/` at `/home/node/.openclaw` and `workspace/` at
`/home/node/.openclaw/workspace` in the OpenClaw gateway container. The
included `docker-compose.experiment.yml` is the experiment-specific override
used with an OpenClaw checkout.

## Main Experiment

From the repository root, one replicate is run as follows:

```bash
export OPENAI_API_KEY=<response-model-key>
export VLLM_METRICS=http://<gpu-host>:9022/metrics
RUN_PREFIX=<MODEL>_rep1 RESULTS_DIR=results/<MODEL> \
  bash scripts/run_full_cumul.sh
```

Run 1 starts from empty memory. Runs 2--5 preserve `patterns.md`; after every
run, the script archives `patterns_runN.md`. Each task begins from the same
database seed in `benchmark/seed/`.

Execution schedule: the GPT-OSS-120B, Qwen3.5-27B, and GPT-OSS-20B baselines
interleave the three conditions in one process (`run_full_cumul.sh`). The
Gemma4-26B-A4B-it baselines run them as three concurrent processes
(`run_full_cumul_parallel.sh`, launched by `run_gemma4_reps.sh`). Among the
interventions, the GPT-OSS Run-5 reruns (matched-line removal, shared memory,
and both content-volume controls) are concurrent, and the Qwen and Gemma
memory-injection runs are interleaved. The scripts below default to the
schedule used for the reported runs.

The full raw JSONL trajectories are not included in this repository
because they contain verbose model transcripts and total several gigabytes.
The runner regenerates them. The exact aggregate outputs used for the paired,
content-volume, and cost checks are included under `derived_results/`.

To run the paired analysis on regenerated results:

```bash
python3 scripts/paired_intervention_analysis.py --results-root results
```

Use `--extra-results-root` if intervention variants are stored in a second results
tree and `--sharedmem-glob` if the shared-memory run uses a custom path.

To regenerate the paper's data tables from the results tree:

```bash
python3 scripts/tables/make_tables.py --results-root results \
  [--extra-results-root <second results tree>] [--out derived_results/tables]
```

Each table is written as the LaTeX body rows printed in the paper
(`<out>/tab_<label>.tex`). Run discovery, the replicate filter (1--3), and
rounding (half up) are shared in `scripts/tables/common.py`; each module's
docstrings state the aggregation and any coding rule for its tables
(`behavior.py`, `performance.py`, `memory.py`, `interventions.py`). Bold cells
that mark values discussed in the text, and the example memory lines in the
sample-lines table, were chosen by hand; the scripts list them explicitly and
verify the lines' provenance. A full run takes about a minute and under 1 GB of
memory. The outputs for the reported runs are in `derived_results/tables/`.

The targeted content-volume controls are prepared and run with:

```bash
python3 scripts/build_random_strip_size_matched.py \
  --rep GPT-OSS-120B_rep1 --seeds 1 2 3
python3 scripts/build_nongating_loadmatched.py \
  --rep GPT-OSS-120B_rep1 --seed 1
bash scripts/run_content_volume_control.sh random 1
bash scripts/run_content_volume_control.sh nongating-loadmatched 1
python3 scripts/content_volume_control_analysis.py --results-root results
```

Repeat the random control with seeds 2 and 3. These targeted controls run the
three prompt conditions concurrently, matching the reported control runs, as
do `run_gate_strip_ablation.sh` (set `PARALLEL=0` to interleave) and
`run_sharedmem_ablation.sh`.

## Known issue

In the experiments, `workspace/soul-b/wb-analytics.py` (Cautious) matched the
`traffic_source` labels exactly (`social_media`, `search_engine`), while the
seed data use `social media` and `search engine`. The Cautious tool therefore
returned zero for `visits_social_media` and `visits_search_engine`; the Neutral
and Bold tools normalize these labels. This affects four of the 314 variants
(AOB_analytics_0040_a/b/c, AOB_analytics_0148_a). Excluding them changes any
condition-run success rate by at most 0.010 and changes no regime label
(paper, Appendix J).

The repository ships the tools as run, so the scripts reproduce the reported
numbers. For new experiments, apply the fix before running:

```bash
cp workspace/soul-a/wb-analytics.py workspace/soul-b/wb-analytics.py
```

(`soul-c`'s version differs in code style only and behaves identically on the
seed data.)

## Licenses

Original runner, analysis, intervention, and configuration code is provided
under the Apache License 2.0; see `LICENSE`. Files derived from WorkBench,
including the task seeds and workspace tools, retain the WorkBench MIT terms;
see `THIRD_PARTY_LICENSES/WORKBENCH_LICENSE.txt`.

## Citation

```bibtex
@inproceedings{kang2027cumulative,
  title     = {Cumulative Memory Changes Agent Behavior Under Ambiguity:
               Repeated-Task Evidence on Performance and Cost},
  author    = {Kang, Chaelin and Yang, Jaeseok and Jang, Junghoon},
  booktitle = {Findings of the Association for Computational Linguistics: EACL 2027},
  year      = {2027}
}
```
