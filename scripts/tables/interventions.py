"""Intervention tables (Section 5.3 and the Intervention Details appendix).

Every table here compares a Run-5 intervention rerun with an unmodified Run 5
(or Run 4) of the same replicate. All cells are rates over the 314 task
variants of one condition in one run:

  success      = e2e_success                     (denominator: all 314 records)
  under-action = exec_count < gt_count            (denominator: records whose
  over-action  = exec_count > gt_count             action_precision is applicable)

Success and under-action come from `content_volume_control_analysis.rates`,
per-task lookups from `paired_intervention_analysis.by_task`, so the tables
and the shipped analysis scripts share one definition. Every run used here is
checked to cover each of the 314 benchmark task variants exactly once per
condition (benchmark/tasks/ambig_queries.json).

Intervention runs are found in either layout:
  released runners : <root>/interventions/<arm>/..., <root>/interventions/seeding/<arm>/...
  paper runs       : <root>/_ablation/<arm>/...,      <root>/gate_inject_rebuttal/<arm>/...
and GPT-OSS-20B in <root>/GPT-OSS-20B/ (flat run directories or per-replicate
sub-directories). `_parallel_tmp` per-condition copies are skipped by Ctx.glob.

Numbers are printed with round-half-up to three decimals (two for the
under-action columns of tab:shared-memory) and the leading zero dropped, as in
the paper. None of these tables prints a bootstrap CI; the CIs quoted in the
text come from scripts/paired_intervention_analysis.py.
"""
from __future__ import annotations

import json
from pathlib import Path

from common import REPO_DIR, Ctx, latex_rows, mean, parse_run_dir, rnd, se

import content_volume_control_analysis as cva  # rates(): success + under-action per condition
import paired_intervention_analysis as pia     # by_task(), load_task_clusters()

TASKS_FILE = REPO_DIR / "benchmark" / "tasks" / "ambig_queries.json"
SOURCE = "GPT-OSS-120B"       # model whose memory is stripped / shared / injected
SOURCE_REP = f"{SOURCE}_rep1"
# Cliff threshold of Eq. (regime): a Delta cell on success or under-action is
# shaded (\sig) when |Delta| >= TAU ("shading as in Table run1-vs-run5").
TAU = 0.10
MACRO = {"Cautious": r"\cautious", "Neutral": r"\neutral", "Bold": r"\boldid"}
ROWS = cva.SOULS  # (soul_id, name) in the paper's row order: Cautious, Neutral, Bold
MIDRULE = r"\midrule"

# Parent directories of the intervention arms, released layout first.
GPTOSS_PARENTS = ("interventions", "_ablation")
SEEDING_PARENTS = ("interventions/seeding", "gate_inject_rebuttal")


# ---- loading ----------------------------------------------------------------

def _slim(rec: dict) -> dict:
    """Keep only the fields the rate definitions read. Full records carry the
    whole transcript (0.1-0.4 GB per run file, ~45 run files across these
    tables), so caching them would not fit in memory."""
    ap = rec.get("action_precision") or {}
    return {
        "soul_id": rec.get("soul_id"),
        "task_id": rec.get("task_id"),
        "timestamp": rec.get("timestamp"),
        "eval": {"e2e_success": (rec.get("eval") or {}).get("e2e_success")},
        "action_precision": {k: ap.get(k) for k in ("applicable", "exec_count", "gt_count") if k in ap},
    }


def _load_slim(ctx: Ctx, path: Path) -> list[dict]:
    key = ("interventions:slim", str(path))
    if key not in ctx._cache:
        out = []
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    out.append(_slim(json.loads(line)))
                except json.JSONDecodeError:
                    continue  # a dropped line is caught by the completeness check below
        ctx._cache[key] = out
    return ctx._cache[key]


def _task_ids(ctx: Ctx) -> frozenset:
    key = ("interventions:tasks",)
    if key not in ctx._cache:
        ctx._cache[key] = frozenset(pia.load_task_clusters(TASKS_FILE))
    return ctx._cache[key]


def _run(ctx: Ctx, files: list[Path], what: str) -> list[dict]:
    """Records of one run, given its JSONL file(s).

    A merged file and per-condition files may coexist (released runners), so
    keep one record per (condition, task) - the rule of
    content_volume_control_analysis.read_jsonls - then require that every
    condition covers each benchmark task exactly once (n = 314 per cell)."""
    if not files:
        raise FileNotFoundError(f"no JSONL for {what}")
    unique = {}
    for path in files:
        for rec in _load_slim(ctx, path):
            unique[(rec["soul_id"], rec["task_id"])] = rec
    records = list(unique.values())
    tasks = _task_ids(ctx)
    for soul, name in ROWS:
        got = {r["task_id"] for r in records if r["soul_id"] == soul}
        if got != tasks:
            raise RuntimeError(f"{what} {name}: {len(got & tasks)}/{len(tasks)} benchmark tasks"
                               f" ({len(got - tasks)} unknown) in {[str(p) for p in files]}")
    return records


def _arm_files(ctx: Ctx, parents: tuple[str, ...], rel: str) -> list[Path]:
    return sorted({p for parent in parents for p in ctx.glob(f"{parent}/{rel}/**/*.jsonl")})


def _arm(ctx: Ctx, parents: tuple[str, ...], rel: str) -> list[dict]:
    """Records of an intervention arm `<parent>/<rel>/**/*.jsonl` (any parent, any root)."""
    return _run(ctx, _arm_files(ctx, parents, rel), rel)


def _baseline(ctx: Ctx, model: str, rep: int, run: int = 5) -> list[dict]:
    path = ctx.baseline_run_files(model).get((rep, run))
    return _run(ctx, [path] if path else [], f"{model} rep{rep} run{run}")


def _strip(ctx: Ctx, rep: int) -> list[dict]:
    return _arm(ctx, GPTOSS_PARENTS, f"{SOURCE}_rep{rep}_run5_stripped")


def _random_strip(ctx: Ctx, seed: int) -> list[dict]:
    return _arm(ctx, GPTOSS_PARENTS, f"{SOURCE_REP}_run5_random_stripped_size_matched/seed_{seed:02d}")


def _nongating_loadmatched(ctx: Ctx) -> list[dict]:
    return _arm(ctx, GPTOSS_PARENTS, f"{SOURCE_REP}_run5_nongating_loadmatched/seed_01")


def _sharedmem(ctx: Ctx) -> list[dict]:
    # run_sharedmem_ablation.sh writes _ablation/<rep>_run5_sharedmem_neutral/seed_01;
    # interventions/sharedmem is the alternative layout accepted by
    # paired_intervention_analysis.py.
    files = (_arm_files(ctx, GPTOSS_PARENTS, f"{SOURCE_REP}_run5_sharedmem_neutral/seed_01")
             or ctx.glob("interventions/sharedmem/**/*.jsonl"))
    return _run(ctx, files, "shared-starting-memory run")


def _seeding(ctx: Ctx, model: str, rep: int, arm: str) -> list[dict]:
    """arm = 'inj' (matched lines appended) or 'ctl' (token-matched unmatched
    lines, deletion seed 1); directory names as in paired_intervention_analysis."""
    if arm == "inj":
        rel = f"{model}_rep{rep}_run5_injected_from_{SOURCE_REP}"
    else:
        rel = f"{model}_rep{rep}_run5_injected_control_nongating_from_{SOURCE_REP}/seed_01"
    return _arm(ctx, SEEDING_PARENTS, rel)


def _runs_20b(ctx: Ctx) -> dict[tuple[int, int], list[dict]]:
    """{(rep, run): records} for GPT-OSS-20B. The paper tree stores run
    directories flat under GPT-OSS-20B/, so Ctx.baseline_run_files (which
    expects GPT-OSS-20B/<rep dir>/<run dir>) does not see them."""
    found: dict[tuple[int, int], Path] = {}
    for pat in ("GPT-OSS-20B/GPT-OSS-20B_rep*_run*/*.jsonl",
                "GPT-OSS-20B/GPT-OSS-20B_rep*/GPT-OSS-20B_rep*_run*/*.jsonl"):
        for path in ctx.glob(pat):
            rep, run = parse_run_dir(path.parent.name)
            if rep is None:
                continue
            if found.setdefault((rep, run), path) != path:
                raise RuntimeError(f"two GPT-OSS-20B runs for rep{rep} run{run}: {found[(rep, run)]}, {path}")
    return {k: _run(ctx, [found[k]] if k in found else [], f"GPT-OSS-20B rep{k[0]} run{k[1]}")
            for k in ((rep, run) for rep in (1, 2, 3) for run in (1, 2, 3, 4, 5))}


# ---- rates and formatting -----------------------------------------------------

def _over(records: list[dict], soul: str) -> float:
    app = [r["action_precision"] for r in records
           if r["soul_id"] == soul and (r["action_precision"] or {}).get("applicable")]
    return sum((a.get("exec_count") or 0) > (a.get("gt_count") or 0) for a in app) / len(app)


def _rates(records: list[dict]) -> dict[str, dict[str, float]]:
    """{condition: {"succ", "under", "over"}}."""
    su = cva.rates(records)
    return {name: {"succ": su[name][0], "under": su[name][1], "over": _over(records, soul)}
            for soul, name in ROWS}


def _dec(x, nd: int = 3) -> str:
    """Round half up and drop the leading zero: 0.5234 -> '.523', -0.3185 -> '-.319'."""
    s = rnd(x, nd)
    if s.startswith("0."):
        return s[1:]
    if s.startswith("-0."):
        return "-" + s[2:]
    return s


def _signed(x, nd: int = 3) -> str:
    """'$+$.272' / '$-$.318'; a value that rounds to zero is printed with '+'."""
    mag = _dec(abs(x), nd)
    return ("$-$" if x < 0 and float(mag) != 0 else "$+$") + mag


def _range(xs, nd: int = 3) -> str:
    lo, hi = _dec(min(xs), nd), _dec(max(xs), nd)
    return lo if lo == hi else f"{lo}--{hi}"


def _with_groups(groups: list[list[list[str]]]) -> str:
    """Row groups separated by \\midrule, as in the per-replicate tables."""
    return f"\n{MIDRULE}\n".join(latex_rows(g) for g in groups)


# ---- tables -------------------------------------------------------------------

def tab_ablation(ctx: Ctx) -> str:
    """tab:ablation - matched-line removal, GPT-OSS-120B replicates 1-3.

    Compared runs, per replicate r: the original Run 5 (GPT-OSS-120B_rep{r}
    run 5) vs. Run 5' rerun from the Run-4 memory with every line matching
    PROHIBITIVE / CONDITIONAL / ASK_FIRST removed (<arm>/GPT-OSS-120B_rep{r}_run5_stripped).
    Columns: success, under-action, over-action, each as Run 5 | Run 5' | Delta.
    Aggregation: rate per replicate (n = 314 tasks per condition per
    replicate), then mean {\\tiny +- SE} across the three replicates (SE =
    sample SD / sqrt(3)); Delta = per-replicate (Run 5' - Run 5), then mean and
    SE of those three differences (not the difference of the rounded means).
    Shading: the Delta cell of success or under-action gets \\sig when
    |mean Delta| >= tau = 0.10; over-action is never shaded.
    Rounding: half up, three decimals, leading zero dropped."""
    summary = ablation_summary(ctx)
    rows = []
    for _, name in ROWS:
        cells = []
        for metric in ("succ", "under", "over"):
            o_m, o_se, s_m, s_se, d_m, d_se = summary[name][metric]
            for m, e in ((o_m, o_se), (s_m, s_se)):
                cells.append(f"{_dec(m)}{{\\tiny$\\pm${_dec(e)}}}")
            d = f"{_signed(d_m)}{{\\tiny$\\pm${_dec(d_se)}}}"
            if metric in ("succ", "under") and abs(d_m) >= TAU:
                d = f"\\sig{{{d}}}"
            cells.append(d)
        rows.append([" " + MACRO[name].ljust(len(r"\cautious"))] + cells)
    return latex_rows(rows)


def ablation_summary(ctx: Ctx) -> dict[str, dict[str, tuple[float, ...]]]:
    """Matched-line removal summary shared by tab:ablation and the
    gate-stripping figure (scripts/make_figures.py): for each condition and
    metric ("succ", "under", "over"), the tuple (Run 5 mean, SE, Run 5' mean,
    SE, Delta mean, SE) over replicates 1-3, as rates in [0, 1]."""
    per_rep = {rep: (_rates(_baseline(ctx, SOURCE, rep)), _rates(_strip(ctx, rep))) for rep in (1, 2, 3)}
    out: dict[str, dict[str, tuple[float, ...]]] = {}
    for _, name in ROWS:
        out[name] = {}
        for metric in ("succ", "under", "over"):
            orig = [per_rep[rep][0][name][metric] for rep in (1, 2, 3)]
            strip = [per_rep[rep][1][name][metric] for rep in (1, 2, 3)]
            # Delta is averaged per replicate from exact rates; differencing the
            # rounded column means instead gives e.g. +.216 / +.196 (pre-camera-ready).
            delta = [b - a for a, b in zip(orig, strip)]
            out[name][metric] = (mean(orig), se(orig), mean(strip), se(strip), mean(delta), se(delta))
    return out


def _seeding_table(ctx: Ctx, model: str) -> str:
    groups = []
    for rep in (1, 2, 3):
        arms = [_rates(_baseline(ctx, model, rep)), _rates(_seeding(ctx, model, rep, "inj")),
                _rates(_seeding(ctx, model, rep, "ctl"))]
        group = []
        for i, (_, name) in enumerate(ROWS):
            lead = f"\\multirow{{3}}{{*}}{{{rep}}}" if i == 0 else ""
            group.append([lead, MACRO[name]]
                         + [_dec(a[name]["succ"]) for a in arms]
                         + [_dec(a[name]["under"]) for a in arms])
        groups.append(group)
    return _with_groups(groups)


def tab_seeding_detail(ctx: Ctx) -> str:
    """tab:seeding-detail - memory injection into Qwen3.5-27B, replicates 1-3.

    Compared runs, per replicate r: Baseline = Qwen replicate r's original Run 5;
    Injection = Run 5 rerun from Qwen's own Run-4 memory with all matched lines
    of GPT-OSS-120B rep1 Run 4 appended (<arm>/Qwen3.5-27B_rep{r}_run5_injected_from_GPT-OSS-120B_rep1);
    Control = token-matched unmatched GPT-OSS lines appended instead
    (..._injected_control_nongating_from_GPT-OSS-120B_rep1/seed_01).
    Aggregation: none - one run per cell, n = 314 tasks per cell.
    Columns: success (Baseline, Injection, Control), then under-action.
    Rounding: half up, three decimals, leading zero dropped."""
    return _seeding_table(ctx, "Qwen3.5-27B")


def tab_seeding_detail_gemma(ctx: Ctx) -> str:
    """tab:seeding-detail-gemma - the same injection / control overlays applied
    to Gemma4-26B-A4B-it replicates 1-3, each compared with that replicate's
    original Run 5 (Gemma4-26B-A4B-it_rep{r}_run5_injected_from_GPT-OSS-120B_rep1
    and ..._injected_control_nongating_from_GPT-OSS-120B_rep1/seed_01).
    One run per cell, n = 314 tasks per cell; half up, three decimals."""
    return _seeding_table(ctx, "Gemma4-26B-A4B-it")


def tab_shared_memory(ctx: Ctx) -> str:
    """tab:shared-memory - GPT-OSS-120B replicate 1, single seed.

    Compared runs: Run 4 (reference; the run that wrote the corpora), the
    original Run 5 (each condition starts from its own Run-4 corpus), and the
    shared-starting-memory rerun of Run 5 in which all three conditions start
    from the Neutral rep-1 Run-4 corpus (<arm>/GPT-OSS-120B_rep1_run5_sharedmem_neutral/seed_01).
    One run per cell, n = 314 tasks per cell. Success is printed to three
    decimals, under-action to two (half up, leading zero dropped)."""
    arms = [_rates(_baseline(ctx, SOURCE, 1, run=4)), _rates(_baseline(ctx, SOURCE, 1, run=5)),
            _rates(_sharedmem(ctx))]
    rows = []
    for _, name in ROWS:
        cells = []
        for a in arms:
            cells += [_dec(a[name]["succ"], 3), _dec(a[name]["under"], 2)]
        rows.append([" " + MACRO[name]] + cells)
    return latex_rows(rows)


def _quartile_tasks(records: list[dict], soul: str) -> list[list[str]]:
    """Task ids of one condition split into four execution-order quartiles.

    Same rule as section C of paired_intervention_analysis.py (inline there):
    sort the condition's records by timestamp and cut at int(q * n / 4), giving
    78/79/78/79 tasks for n = 314."""
    rs = sorted((r for r in records if r["soul_id"] == soul), key=lambda r: r["timestamp"])
    n = len(rs)
    return [[r["task_id"] for r in rs[int(q * n / 4):int((q + 1) * n / 4)]] for q in range(4)]


def tab_sharedmem_quartiles(ctx: Ctx) -> str:
    """tab:sharedmem-quartiles - success by execution-order quartile.

    Compared runs: the shared-starting-memory rerun of GPT-OSS-120B rep1 Run 5
    vs. the original (own-memory) rep1 Run 5. Quartiles are cut on each
    condition's execution order in the shared run (n = 78 or 79 variants per
    cell); the own-memory columns use the same task ids looked up in the
    original Run 5 (execution order of the original run is not used).
    spr. = max - min of the three exact condition rates in that quartile.
    Rounding: half up, three decimals, leading zero dropped."""
    shared, own = _sharedmem(ctx), _baseline(ctx, SOURCE, 1)
    quart = {soul: _quartile_tasks(shared, soul) for soul, _ in ROWS}
    lookup = {soul: (pia.by_task(shared, soul), pia.by_task(own, soul)) for soul, _ in ROWS}
    rows = []
    for q in range(4):
        cells = []
        for which in (0, 1):  # 0 = shared run, 1 = own memory on the same tasks
            vals = [mean(lookup[soul][which][t][0] for t in quart[soul][q]) for soul, _ in ROWS]
            cells += [_dec(v) for v in vals] + [_dec(max(vals) - min(vals))]
        rows.append([f" {q + 1}"] + cells)
    return latex_rows(rows)


def tab_20b_runs(ctx: Ctx) -> str:
    """tab:20b-runs - GPT-OSS-20B check, replicates 1-3 x Runs 1-5.

    No intervention: the five cumulative baseline runs of GPT-OSS-20B under
    the GPT-OSS-120B protocol. One run per cell, n = 314 tasks per cell;
    columns are success and under-action for Cautious, Neutral, Bold.
    Rounding: half up, three decimals, leading zero dropped."""
    runs = _runs_20b(ctx)
    groups = []
    for rep in (1, 2, 3):
        group = []
        for run in (1, 2, 3, 4, 5):
            r = _rates(runs[(rep, run)])
            lead = f"\\multirow{{5}}{{*}}{{{rep}}}" if run == 1 else ""
            group.append([lead, str(run)]
                         + [c for _, name in ROWS for c in (_dec(r[name]["succ"]), _dec(r[name]["under"]))])
        groups.append(group)
    return _with_groups(groups)


def tab_content_volume_control(ctx: Ctx) -> str:
    """tab:content-volume-control - GPT-OSS-120B replicate 1 load controls.

    Compared runs (all Run 5 of rep1, n = 314 tasks per condition):
      Original high load      original Run 5
      Matched-line removal    <arm>/GPT-OSS-120B_rep1_run5_stripped
      Unmatched-line removal  <arm>/GPT-OSS-120B_rep1_run5_random_stripped_size_matched/seed_01..03,
                              printed as min--max over the three deletion seeds
      Zero-match high load    <arm>/GPT-OSS-120B_rep1_run5_nongating_loadmatched/seed_01
    Columns: success and under-action per arm.
    Rounding: half up, three decimals, leading zero dropped (range ends rounded
    separately)."""
    orig, matched = _rates(_baseline(ctx, SOURCE, 1)), _rates(_strip(ctx, 1))
    seeds = [_rates(_random_strip(ctx, s)) for s in (1, 2, 3)]
    high = _rates(_nongating_loadmatched(ctx))
    rows = []
    for _, name in ROWS:
        cells = [_dec(orig[name]["succ"]), _dec(orig[name]["under"]),
                 _dec(matched[name]["succ"]), _dec(matched[name]["under"]),
                 _range([s[name]["succ"] for s in seeds]), _range([s[name]["under"] for s in seeds]),
                 _dec(high[name]["succ"]), _dec(high[name]["under"])]
        rows.append([" " + MACRO[name].ljust(len(r"\cautious"))] + cells)
    return latex_rows(rows)


TABLES = {
    "tab:ablation": tab_ablation,
    "tab:seeding-detail": tab_seeding_detail,
    "tab:seeding-detail-gemma": tab_seeding_detail_gemma,
    "tab:shared-memory": tab_shared_memory,
    "tab:sharedmem-quartiles": tab_sharedmem_quartiles,
    "tab:20b-runs": tab_20b_runs,
    "tab:content-volume-control": tab_content_volume_control,
}
