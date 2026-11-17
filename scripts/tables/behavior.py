"""Behavior-metric tables: profile, omnibus/pairwise tests, spread, profile
shift, PCA, and memory-load correlations.

Per-task metrics (one value per task record; baseline runs, replicates 1-3,
runs 1-5, 314 tasks x 3 conditions per run):
  clarification_turn_share  clarification_turns / total_turns
  first_action_latency      FAL: 1-based index of the first turn whose
                            commands_executed contains a non-read command
                            (has_write_op, shared with scripts/make_figures.py).
                            Undefined when no turn qualifies; see coding rules.
  action_count_ratio        exec_count / gt_count (0 when gt_count is 0)
  over_action_rate          1[exec_count > gt_count]
  under_action_rate         1[exec_count < gt_count]
  success_rate              eval.e2e_success
The three action metrics come from `action_precision` and are defined only when
it is marked applicable (true for every baseline record). Memory load is the
first turn's input_tokens.

FAL coding rule (paper Appendix "Terminology"): tasks without a qualifying turn
are EXCLUDED from FAL means (profile, omnibus, spread, PCA, profile shift) and
CODED AS 0 in the pairwise tests and the memory-load correlations.

Tables
------
tab:L-behavior-profile  For each (model, condition, replicate), the mean of a
    metric over all task records of the five runs; cell = mean +- SE (ddof=1)
    over the three replicate means. FAL at 2 dp, others at 3 dp.
tab:L-omnibus  Kruskal-Wallis test across the three conditions on task-level
    values, run separately in each replicate (runs pooled); cell = the largest
    of the three per-replicate p-values, 3 significant digits.
tab:pairwise-{gptoss,qwen,gemma}  Two-sided Mann-Whitney U on task-level
    values pooled over replicates and runs (4,710 per condition); 2 significant
    digits plus Bonferroni marker (*** <0.001, ** <0.01, * <0.0167, else ns).
    A p-value that underflows to 0 is printed as "< 10^-300".
tab:L-spread  Cell mean mu per (replicate, run, condition); spread = max - min
    over conditions per (replicate, run); cell = mean +- SE over replicates.
    r5/r1 = ratio of the Run 5 and Run 1 means as printed (3 dp), at 2 dp.
tab:L-drift  Behavior vector b = [q, FAL, ratio, OA, UA] of cell means per
    (replicate, condition, run); shift = 1 - cos(b_run1, b_run5) on the raw
    (unnormalized) vectors; cell = mean +- SE over replicates. The largest mean
    is bold.
tab:pca-centroids / tab:pca-distances  scripts/make_figures.py::compute_pca:
    45 cells per model (replicate x run x condition means of the five metrics),
    z-normalized with the population SD, sklearn PCA(2). Centroid = mean PC
    score of a condition's 15 cells; distance = Euclidean distance between
    centroids in the PC1-PC2 plane. The largest and smallest distances in the
    table are bold.
tab:memload-corr  For each (model, condition), Spearman rho over the 15
    (replicate, run) cells between the mean first-turn input tokens and the
    cell means of clarification share, FAL (coded 0), OA, UA, and success.
    Bold marks the correlations discussed in the text (editorial; see
    MEMLOAD_BOLD).
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from fractions import Fraction

import numpy as np
from scipy import stats

from common import MODELS, REPS, RUNS, has_write_op, latex_rows, mean, pm, rnd, se

CONDITIONS = ("Bold", "Cautious", "Neutral")  # column order of most tables
PCA_ORDER = ("Bold", "Neutral", "Cautious")  # column order of the PCA/pairwise-style tables
PAIRS = (("Bold", "Neutral"), ("Bold", "Cautious"), ("Neutral", "Cautious"))

# paper metric name -> Task attribute
METRIC_ATTR = {
    "clarification_turn_share": "clarif",
    "first_action_latency": "fal",
    "action_count_ratio": "ratio",
    "over_action_rate": "oa",
    "under_action_rate": "ua",
    "success_rate": "succ",
}
FIVE = ("clarification_turn_share", "first_action_latency", "action_count_ratio",
        "over_action_rate", "under_action_rate")
PROFILE_METRICS = ("clarification_turn_share", "first_action_latency", "over_action_rate", "under_action_rate")
SPREAD_METRICS = PROFILE_METRICS + ("success_rate",)
MEMLOAD_METRICS = ("clarification_turn_share", "first_action_latency", "over_action_rate",
                   "under_action_rate", "success_rate")

# Bold cells in tab:memload-corr. The paper bolds the correlations it discusses
# in the text; the choice is not a threshold rule on rho or p (e.g. GPT-OSS
# Cautious FAL, rho=-0.602, p=0.018, is plain while GPT-OSS Cautious UA,
# rho=+0.593, p=0.020, is bold), so the positions are listed explicitly.
MEMLOAD_BOLD = {
    ("GPT-OSS-120B", "Bold", "first_action_latency"),
    ("GPT-OSS-120B", "Neutral", "clarification_turn_share"),
    ("GPT-OSS-120B", "Neutral", "over_action_rate"),
    ("GPT-OSS-120B", "Cautious", "clarification_turn_share"),
    ("GPT-OSS-120B", "Cautious", "under_action_rate"),
    ("Qwen3.5-27B", "Bold", "first_action_latency"),
    ("Qwen3.5-27B", "Bold", "over_action_rate"),
    ("Qwen3.5-27B", "Neutral", "clarification_turn_share"),
    ("Qwen3.5-27B", "Cautious", "clarification_turn_share"),
    ("Gemma4-26B-A4B-it", "Cautious", "clarification_turn_share"),
}


# ---- per-task extraction ---------------------------------------------------

@dataclass(frozen=True)
class Task:
    rep: int
    run: int
    cond: str
    clarif: float | None  # None when total_turns is 0
    fal: int | None       # None when no turn has a non-read command
    ratio: float | None   # None when action_precision is not applicable
    oa: int | None
    ua: int | None
    succ: int
    mem: int              # first-turn input tokens


def _task(rep: int, run: int, cond: str, rec: dict) -> Task:
    ct = rec.get("clarification_turns", 0) or 0
    tt = rec.get("total_turns", 0) or 0
    turns = rec.get("turns") or []
    fal = None
    for i, turn in enumerate(turns):
        if has_write_op(turn.get("commands_executed", [])):
            fal = i + 1
            break
    ap = rec.get("action_precision", {})
    ratio = oa = ua = None
    if isinstance(ap, dict) and ap.get("applicable"):
        gt, ex = ap.get("gt_count", 0), ap.get("exec_count", 0)
        ratio = ex / gt if gt else 0
        oa, ua = int(ex > gt), int(ex < gt)
    return Task(
        rep=rep, run=run, cond=cond,
        clarif=ct / tt if tt else None,
        fal=fal, ratio=ratio, oa=oa, ua=ua,
        succ=int(bool((rec.get("eval") or {}).get("e2e_success"))),
        mem=int(turns[0].get("input_tokens") or 0) if turns else 0,
    )


def tasks(ctx, model: str) -> list[Task]:
    """All baseline task records of `model` (replicates 1-3), in file order."""
    key = ("behavior.tasks", model)
    if key not in ctx._cache:
        ctx._cache[key] = [_task(rep, run, cond, rec) for rep, run, cond, rec in ctx.records(model)]
    return ctx._cache[key]


def values(rows, metric: str, fal_zero: bool = False) -> list[float]:
    """Task-level values of `metric`; undefined values are dropped, except FAL,
    which is coded 0 when `fal_zero` is set (pairwise tests, memory load)."""
    attr = METRIC_ATTR[metric]
    out = []
    for t in rows:
        v = getattr(t, attr)
        if v is None and attr == "fal" and fal_zero:
            v = 0
        if v is not None:
            out.append(float(v))
    return out


def select(rows, **match) -> list[Task]:
    return [t for t in rows if all(getattr(t, k) == v for k, v in match.items())]


def cells(ctx, model: str) -> dict[tuple[int, int, str], list[Task]]:
    """{(rep, run, cond): task records}, keys in first-seen (file) order."""
    key = ("behavior.cells", model)
    if key not in ctx._cache:
        groups: dict[tuple[int, int, str], list[Task]] = {}
        for t in tasks(ctx, model):
            groups.setdefault((t.rep, t.run, t.cond), []).append(t)
        ctx._cache[key] = groups
    return ctx._cache[key]


def cell_means(ctx, model: str, metric: str, fal_zero: bool = False) -> dict[tuple[int, int, str], float]:
    """{(rep, run, cond): mean of task-level values} for one metric."""
    return {k: mean(values(v, metric, fal_zero)) for k, v in cells(ctx, model).items()}


# ---- formatting -------------------------------------------------------------

def texttt(name: str) -> str:
    return r"\texttt{" + name.replace("_", r"\_") + "}"


def bold(s: str, on: bool = True) -> str:
    return r"\textbf{" + s + "}" if on else s


def signed(x: float, nd: int) -> str:
    """'+0.161' / '-0.397' (sign of the unrounded value; half-up magnitude)."""
    return ("-" if x < 0 else "+") + rnd(abs(x), nd)


def sci(p: float, sig: int) -> str:
    """p-value as 'm $\\times$ $10^{e}$' with `sig` significant digits (half up).
    scipy returns exactly 0 when the p-value underflows; the paper prints that
    as '< $10^{-300}$'."""
    if p < 1e-300:
        return "< $10^{-300}$"
    d = Decimal(repr(float(p)))
    e = d.adjusted()
    q = Decimal(1).scaleb(-(sig - 1))
    m = d.scaleb(-e).quantize(q, rounding=ROUND_HALF_UP)
    if m >= 10:  # e.g. 9.995 -> 10.0 rolls over to the next decade
        m, e = (m / 10).quantize(q, rounding=ROUND_HALF_UP), e + 1
    return f"{m} $\\times$ $10^{{{e}}}$"


def marker(p: float) -> str:
    """Bonferroni markers for three pairwise contrasts (alpha = 0.05/3)."""
    return "***" if p < 0.001 else "**" if p < 0.01 else "*" if p < 0.0167 else "ns"


# ---- tables -------------------------------------------------------------------

def behavior_profile(ctx) -> str:
    rows = []
    for model in MODELS:
        ts = tasks(ctx, model)
        for metric in PROFILE_METRICS:
            nd = 2 if metric == "first_action_latency" else 3
            row = [model, texttt(metric)]
            for cond in CONDITIONS:
                # one value per replicate: mean over all task records of runs 1-5
                per_rep = [mean(values(select(ts, rep=r, cond=cond), metric)) for r in REPS]
                row.append(pm(mean(per_rep), se(per_rep), nd))
            rows.append(row)
    return latex_rows(rows)


def omnibus(ctx) -> str:
    rows = []
    for metric in FIVE:
        row = [texttt(metric)]
        for model in MODELS:
            ts = tasks(ctx, model)
            ps = []
            for r in REPS:
                groups = [values(select(ts, rep=r, cond=c), metric) for c in CONDITIONS]
                ps.append(stats.kruskal(*groups).pvalue)
            row.append(sci(max(ps), 3))  # caption: largest per-replicate p
        rows.append(row)
    return latex_rows(rows)


def _pairwise(model: str):
    def table(ctx) -> str:
        ts = tasks(ctx, model)
        rows = []
        for metric in FIVE:
            row = [texttt(metric)]
            for a, b in PAIRS:
                x = values(select(ts, cond=a), metric, fal_zero=True)
                y = values(select(ts, cond=b), metric, fal_zero=True)
                p = stats.mannwhitneyu(x, y, alternative="two-sided").pvalue
                row.append(f"{sci(p, 2)} {marker(p)}")
            rows.append(row)
        return latex_rows(rows)
    return table


def spread(ctx) -> str:
    rows = []
    for model in MODELS:
        for metric in SPREAD_METRICS:
            cm = cell_means(ctx, model, metric)
            row = [model, texttt(metric)]
            run_means = {}
            for run in RUNS:
                sp = [max(cm[(r, run, c)] for c in CONDITIONS) - min(cm[(r, run, c)] for c in CONDITIONS)
                      for r in REPS]
                run_means[run] = mean(sp)
                row.append(pm(run_means[run], se(sp), 3))
            # ratio of the printed (3 dp) means, so the column agrees with the row
            ratio = Fraction(Decimal(rnd(run_means[5], 3))) / Fraction(Decimal(rnd(run_means[1], 3)))
            row.append(rnd(ratio, 2))
            rows.append(row)
    return latex_rows(rows)


def profile_shift(ctx) -> str:
    stats_by_cell = {}
    for model in MODELS:
        cms = {m: cell_means(ctx, model, m) for m in FIVE}  # FAL excluded when undefined
        for cond in CONDITIONS:
            shifts = []
            for r in REPS:
                b1 = np.array([cms[m][(r, 1, cond)] for m in FIVE])
                b5 = np.array([cms[m][(r, 5, cond)] for m in FIVE])
                shifts.append(1.0 - float(b1 @ b5 / (np.linalg.norm(b1) * np.linalg.norm(b5))))
            stats_by_cell[(model, cond)] = (mean(shifts), se(shifts))
    top = max(stats_by_cell, key=lambda k: stats_by_cell[k][0])
    rows = [[model] + [bold(pm(*stats_by_cell[(model, c)], 3), (model, c) == top) for c in CONDITIONS]
            for model in MODELS]
    return latex_rows(rows)


def pca(ctx, model: str):
    """Port of scripts/make_figures.py::compute_pca (replicates 1-3).
    Returns (cell keys, PC scores, explained variance ratio)."""
    from sklearn.decomposition import PCA

    key = ("behavior.pca", model)
    if key in ctx._cache:
        return ctx._cache[key]
    # cell order = make_figures collect() order (replicate, run, first-seen condition)
    vals = {k: {m: values(v, m) for m in FIVE} for k, v in cells(ctx, model).items()}  # FAL excluded
    keys = [k for k, v in vals.items() if all(v[m] for m in FIVE)]
    if len(keys) != len(REPS) * len(RUNS) * len(CONDITIONS):
        raise RuntimeError(f"{model}: expected 45 PCA cells, found {len(keys)}")
    X = np.array([[np.mean(vals[k][m]) for m in FIVE] for k in keys])
    Z = (X - X.mean(axis=0)) / (X.std(axis=0) + 1e-12)
    p = PCA(n_components=2)
    Y = p.fit_transform(Z)
    ctx._cache[key] = (keys, Y, p.explained_variance_ratio_)
    return ctx._cache[key]


def centroids(ctx, model: str) -> dict[str, np.ndarray]:
    keys, Y, _ = pca(ctx, model)
    return {c: Y[[i for i, k in enumerate(keys) if k[2] == c]].mean(axis=0) for c in CONDITIONS}


def pca_centroids(ctx) -> str:
    rows = []
    for model in MODELS:
        _, _, var = pca(ctx, model)
        cen = centroids(ctx, model)
        row = [model] + [rnd(v * 100, 1) + r"\%" for v in (var[0], var[1], var[0] + var[1])]
        row += [f"({signed(cen[c][0], 2)}, {signed(cen[c][1], 2)})" for c in PCA_ORDER]
        rows.append(row)
    return latex_rows(rows)


def pca_distances(ctx) -> str:
    dist = {}
    for model in MODELS:
        cen = centroids(ctx, model)
        for a, b in PAIRS:
            dist[(model, a, b)] = float(np.linalg.norm(cen[a] - cen[b]))
    extremes = {max(dist, key=dist.get), min(dist, key=dist.get)}  # bold: table max and min
    rows = [[model] + [bold(rnd(dist[(model, a, b)], 2), (model, a, b) in extremes) for a, b in PAIRS]
            for model in MODELS]
    return latex_rows(rows)


def memload_corr(ctx) -> str:
    rows = []
    for model in MODELS:
        mem = {k: mean([t.mem for t in v]) for k, v in cells(ctx, model).items()}
        cms = {m: cell_means(ctx, model, m, fal_zero=True) for m in MEMLOAD_METRICS}
        for cond in PCA_ORDER:
            keys = [(r, run, cond) for r in REPS for run in RUNS]  # 15 cells
            row = [model, cond]
            for m in MEMLOAD_METRICS:
                rho = stats.spearmanr([mem[k] for k in keys], [cms[m][k] for k in keys]).statistic
                row.append(bold(signed(rho, 3), (model, cond, m) in MEMLOAD_BOLD))
            rows.append(row)
    return latex_rows(rows)


TABLES = {
    "tab:L-behavior-profile": behavior_profile,
    "tab:L-omnibus": omnibus,
    "tab:pairwise-gptoss": _pairwise("GPT-OSS-120B"),
    "tab:pairwise-qwen": _pairwise("Qwen3.5-27B"),
    "tab:pairwise-gemma": _pairwise("Gemma4-26B-A4B-it"),
    "tab:L-spread": spread,
    "tab:L-drift": profile_shift,
    "tab:pca-centroids": pca_centroids,
    "tab:pca-distances": pca_distances,
    "tab:memload-corr": memload_corr,
}
