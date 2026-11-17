"""Performance and cost tables: Run 1 vs Run 5 rates, clarification and
correction behavior, tokens per success, failed-token share, and success by
ambiguity dimension and level.

Data: the cumulative baseline runs read through `common.Ctx.records`
(replicates 1-3, runs 1-5, 314 tasks per condition per run).

Per-task quantities (same definitions as
analysis/behavior_vector_analysis.py::record_to_behavior and
analysis/cost_resource_analysis.py::per_task_row):
  success       eval.e2e_success (equal to `completed` in every baseline cell)
  under_action  1[gt_count > 0 and exec_count < gt_count]   (record.action_precision)
  over_action   1[gt_count > 0 and exec_count > gt_count]
  clar_turns    number of turns flagged is_clarification
  clar_cost     input + output tokens of those turns
                + oracle_clarify_input_tokens + oracle_clarify_output_tokens
  corr_turns    record field correction_turns
  total_tokens  record field total_tokens
  dims, level   record fields ambiguity_dimensions, ambiguity_level

Aggregation: unless a table says otherwise, a replicate-level value is computed
first (over the 314 tasks of one run, or over the tasks of runs 1-5 pooled), and
the printed cell is the mean of the three replicate values, +- the standard
error across replicates (sample SD with ddof=1, / sqrt(3)). Replicate values
are exact fractions, and SEs are evaluated to 50 significant digits before
rounding, so half-up rounding (`common.rnd`) never depends on binary floating
point.
"""
from __future__ import annotations

from collections import defaultdict
from decimal import Decimal, localcontext
from fractions import Fraction

from common import MODELS, RUNS, Ctx, rnd

TAU = Fraction(1, 10)  # regime threshold tau = 0.10 (Eq. regime)
CONDITIONS = ("Bold", "Neutral", "Cautious")  # appendix row/column order
CONDITIONS_ALPHA = ("Bold", "Cautious", "Neutral")  # order of the L-* cost tables
CONDITIONS_CLIFF = ("Cautious", "Neutral", "Bold")  # order of tab:run1-vs-run5
COND_MACRO = {"Cautious": r"\cautious", "Neutral": r"\neutral", "Bold": r"\boldid"}
SHORT_NAME = {"GPT-OSS-120B": "GPT-OSS", "Qwen3.5-27B": "Qwen", "Gemma4-26B-A4B-it": "Gemma"}
DIMENSIONS = ("Goal", "Process", "Priority", "Behavior")
LEVELS = (1, 2, 3, 4)
REGIME_SEVERITY = {"stable": 0, "drift": 1, "cliff": 2}


# ---- per-task rows ----------------------------------------------------------

def _task(rep: int, run: int, cond: str, rec: dict) -> dict:
    turns = rec.get("turns") or []
    ap = rec.get("action_precision") or {}
    gt = int(ap.get("gt_count") or 0)
    ex = int(ap.get("exec_count") or 0)
    clar = [t for t in turns if t.get("is_clarification")]
    dims = rec.get("ambiguity_dimensions") or []
    if not isinstance(dims, list):
        dims = [dims]
    return {
        "rep": rep,
        "run": run,
        "cond": cond,
        "success": int(bool((rec.get("eval") or {}).get("e2e_success"))),
        "under_action": int(bool(gt) and ex < gt),
        "over_action": int(bool(gt) and ex > gt),
        "clar_turns": len(clar),
        "clar_cost": sum(int(t.get("input_tokens") or 0) + int(t.get("output_tokens") or 0) for t in clar)
        + int(rec.get("oracle_clarify_input_tokens") or 0)
        + int(rec.get("oracle_clarify_output_tokens") or 0),
        "corr_turns": int(rec.get("correction_turns") or 0),
        "total_tokens": int(rec.get("total_tokens") or 0),
        "dims": {str(d) for d in dims},
        "level": rec.get("ambiguity_level"),
    }


def task_rows(ctx: Ctx, model: str) -> list[dict]:
    """Compact per-task rows for `model` (cached on ctx)."""
    key = ("performance.task_rows", model)
    if key not in ctx._cache:
        ctx._cache[key] = [_task(rep, run, cond, rec) for rep, run, cond, rec in ctx.records(model)]
    return ctx._cache[key]


def _groups(ctx: Ctx, model: str) -> dict[tuple[int, int, str], list[dict]]:
    """{(rep, run, cond): rows}; checks the design is balanced (same n everywhere)."""
    key = ("performance.groups", model)
    if key not in ctx._cache:
        g: dict[tuple[int, int, str], list[dict]] = defaultdict(list)
        for row in task_rows(ctx, model):
            g[(row["rep"], row["run"], row["cond"])].append(row)
        sizes = {len(v) for v in g.values()}
        if len(g) != 3 * len(RUNS) * 3 or len(sizes) != 1:
            raise RuntimeError(f"{model}: unbalanced baseline cells ({len(g)} cells, sizes {sorted(sizes)})")
        ctx._cache[key] = dict(g)
    return ctx._cache[key]


def _reps(ctx: Ctx, model: str) -> list[int]:
    return sorted({k[0] for k in _groups(ctx, model)})


def _rows(ctx: Ctx, model: str, cond: str, rep: int, runs=RUNS) -> list[dict]:
    g = _groups(ctx, model)
    return [row for run in runs for row in g[(rep, run, cond)]]


# ---- exact statistics -----------------------------------------------------------

def frac_mean(values) -> Fraction:
    values = [Fraction(v) for v in values]
    return sum(values, Fraction(0)) / len(values)


def frac_se(values) -> Fraction:
    """SE of the mean (ddof=1), as a Fraction carrying 50 significant digits of
    the square root, so that `rnd` rounds the true value."""
    values = [Fraction(v) for v in values]
    n = len(values)
    if n < 2:
        return Fraction(0)
    m = sum(values, Fraction(0)) / n
    var_of_mean = sum(((v - m) ** 2 for v in values), Fraction(0)) / (n - 1) / n
    with localcontext() as c:
        c.prec = 50
        root = (Decimal(var_of_mean.numerator) / Decimal(var_of_mean.denominator)).sqrt()
    return Fraction(root)


def rate(rows: list[dict], field: str) -> Fraction:
    return Fraction(sum(r[field] for r in rows), len(rows))


# ---- formatting -------------------------------------------------------------------

def commas(s: str) -> str:
    """Thousands separators for a rounded decimal string ('27130' -> '27,130')."""
    return format(Decimal(s), ",")


def nolead(s: str) -> str:
    """'0.729' -> '.729' (the run1-vs-run5 style for rates)."""
    return s.replace("0.", ".", 1) if s.lstrip("-").startswith("0.") else s


def mean_pm(values, nd: int, thousands: bool = False) -> str:
    m, s = rnd(frac_mean(values), nd), rnd(frac_se(values), nd)
    if thousands:
        m, s = commas(m), commas(s)
    return f"{m} $\\pm$ {s}"


def bold(s: str, on: bool) -> str:
    return f"\\textbf{{{s}}}" if on else s


def row(cells: list[str]) -> str:
    # One leading space, as in the paper source, so the output diffs cleanly.
    return " " + " & ".join(cells) + r" \\"


# ---- regimes (Eq. regime) ---------------------------------------------------------

def regime(ctx: Ctx, model: str, cond: str) -> str:
    """cliff if Run4->Run5 success change <= -tau and under-action change >= +tau;
    drift if |s5 - s1| >= tau/2 (and not cliff); stable otherwise. s and u are
    means across replicates of per-replicate rates."""
    reps = _reps(ctx, model)

    def m(field: str, run: int) -> Fraction:
        return frac_mean(rate(_rows(ctx, model, cond, rep, (run,)), field) for rep in reps)

    if m("success", 5) - m("success", 4) <= -TAU and m("under_action", 5) - m("under_action", 4) >= TAU:
        return "cliff"
    if abs(m("success", 5) - m("success", 1)) >= TAU / 2:
        return "drift"
    return "stable"


def system_regime(ctx: Ctx, model: str) -> str:
    """A system receives the most severe label observed among its conditions."""
    return max((regime(ctx, model, c) for c in CONDITIONS), key=REGIME_SEVERITY.__getitem__)


# ---- tables -------------------------------------------------------------------------

def run1_vs_run5(ctx: Ctx) -> str:
    """tab:run1-vs-run5 -- success, under-action and over-action rates at Run 1
    and Run 5, per model (blocks GPT-OSS, Qwen, Gemma) and condition (Cautious,
    Neutral, Bold).

    Per replicate, a rate is count / 314 over the tasks of that run (exact
    fraction). Cells: mean across the three replicates with the SE across
    replicates in \\tiny; Delta = mean(Run 5) - mean(Run 1), computed exactly
    and then rounded (not the difference of the printed values). Three
    decimals, half up, leading zero dropped, signs typeset as $+$/$-$.

    Shading (\\sig): cliff-signature changes, i.e. |Delta| >= tau = 0.10 on the
    success or under-action column (exact comparison); over-action Deltas are
    never shaded.
    """
    metrics = (("success", True), ("under_action", True), ("over_action", False))
    lines: list[str] = []
    for i, model in enumerate(MODELS):
        if i:
            lines.append(r"\midrule")
        lines.append(f"\\multirow{{3}}{{*}}{{{SHORT_NAME[model]}}}")
        reps = _reps(ctx, model)
        for cond in CONDITIONS_CLIFF:
            cells = ["", COND_MACRO[cond].ljust(9)]
            for field, shade_rule in metrics:
                per_run = {run: [rate(_rows(ctx, model, cond, rep, (run,)), field) for rep in reps] for run in (1, 5)}
                for run in (1, 5):
                    m, s = rnd(frac_mean(per_run[run]), 3), rnd(frac_se(per_run[run]), 3)
                    cells.append(f"{nolead(m)}{{\\tiny$\\pm${nolead(s)}}}")
                delta = frac_mean(per_run[5]) - frac_mean(per_run[1])
                d = f"{'$-$' if delta < 0 else '$+$'}{nolead(rnd(abs(delta), 3))}"
                cells.append(f"\\sig{{{d}}}" if shade_rule and abs(delta) >= TAU else d)
            # The first cell is empty because the model name sits in the
            # \multirow line; the macro is padded to one width as in the source.
            lines.append(" & ".join(cells) + r" \\")
    return "\n".join(lines)


def _clarif_table(ctx: Ctx, model: str) -> str:
    reps = _reps(ctx, model)
    lines = []
    for cond in CONDITIONS:
        turns, tokens = [], []
        for run in RUNS:
            per_rep = [_rows(ctx, model, cond, rep, (run,)) for rep in reps]
            turns.append(mean_pm([rate(r, "clar_turns") for r in per_rep], 2))
            tokens.append(mean_pm([rate(r, "clar_cost") for r in per_rep], 0, thousands=True))
        lines.append(row([cond] + turns + tokens))
    return "\n".join(lines)


_CLARIF_DOC = """{label} -- {model} clarification turns and clarification token cost
    per task, by condition (Bold, Neutral, Cautious) and run (r1..r5).

    Per replicate and run: mean over the 314 tasks of (a) the number of turns
    flagged is_clarification and (b) the clarification cost (agent input+output
    tokens on those turns plus the clarification model's oracle_clarify tokens).
    Cells: mean +- SE across the three replicates; turns to 2 decimals, tokens
    to integers with thousands separators; half up. No emphasis.
    """


def clarif_gptoss(ctx: Ctx) -> str:
    return _clarif_table(ctx, "GPT-OSS-120B")


def clarif_qwen(ctx: Ctx) -> str:
    return _clarif_table(ctx, "Qwen3.5-27B")


def clarif_gemma(ctx: Ctx) -> str:
    return _clarif_table(ctx, "Gemma4-26B-A4B-it")


clarif_gptoss.__doc__ = _CLARIF_DOC.format(label="tab:clarif-gptoss", model="GPT-OSS-120B")
clarif_qwen.__doc__ = _CLARIF_DOC.format(label="tab:clarif-qwen", model="Qwen3.5-27B")
clarif_gemma.__doc__ = _CLARIF_DOC.format(label="tab:clarif-gemma", model="Gemma4-26B-A4B-it")


def clarif_correction(ctx: Ctx) -> str:
    """tab:L-clarif-correction -- clarification investment vs correction recovery
    per (model, condition), pooled over runs 1-5.

    Per replicate (tasks of runs 1-5 pooled, 5 x 314 per condition):
      clarif_turns              mean clarification turns per task
      clarif_token_cost         mean clarification cost per task (as in tab:clarif-*)
      correction_turns (all)    mean correction_turns per task
      correction_turns (failed) mean correction_turns over tasks with
                                e2e_success = False only
    Cells: mean +- SE across the three replicates; turns to 2 decimals, tokens
    to integers with thousands separators; half up.

    Emphasis (\\textbf): the caption states no rule; the printed table contrasts
    the two poles of the condition axis, Cautious vs Bold, within each model
    (the Cautious/Bold ratios quoted in Sec. RQ4). In the three turn-count
    columns the larger of the two poles is bold (it is Cautious for
    clarification turns and Bold for both correction columns in every model);
    in the clarification-token column both poles are bold. Neutral is never
    bold, even where it is the column maximum (clarification tokens for GPT-OSS
    and Gemma).
    """
    columns = (  # (field, failed tasks only, decimals, thousands, emphasis mode)
        ("clar_turns", False, 2, False, "larger_pole"),
        ("clar_cost", False, 0, True, "both_poles"),
        ("corr_turns", False, 2, False, "larger_pole"),
        ("corr_turns", True, 2, False, "larger_pole"),
    )
    lines = []
    for model in MODELS:
        reps = _reps(ctx, model)
        vals: dict[tuple[int, str], list[Fraction]] = {}
        for j, (field, failed_only, _, _, _) in enumerate(columns):
            for cond in CONDITIONS_ALPHA:
                per_rep = []
                for rep in reps:
                    rs = _rows(ctx, model, cond, rep)
                    if failed_only:
                        rs = [r for r in rs if not r["success"]]
                    per_rep.append(rate(rs, field))
                vals[(j, cond)] = per_rep
        for cond in CONDITIONS_ALPHA:
            cells = [model, cond]
            for j, (_, _, nd, thousands, mode) in enumerate(columns):
                if mode == "both_poles":
                    on = cond in ("Cautious", "Bold")
                else:
                    larger = max(("Cautious", "Bold"), key=lambda c: frac_mean(vals[(j, c)]))
                    on = cond == larger
                cells.append(bold(mean_pm(vals[(j, cond)], nd, thousands), on))
            lines.append(row(cells))
    return "\n".join(lines)


def _tps_means(ctx: Ctx, model: str, cond: str) -> dict[int, Fraction]:
    """{run: mean across replicates of (sum total_tokens / number of successes)}."""
    out = {}
    for run in RUNS:
        per_rep = []
        for rep in _reps(ctx, model):
            rs = _rows(ctx, model, cond, rep, (run,))
            n_succ = sum(r["success"] for r in rs)
            if not n_succ:
                raise ValueError(f"{model} rep{rep} run{run} {cond}: no successes")
            per_rep.append(Fraction(sum(r["total_tokens"] for r in rs), n_succ))
        out[run] = frac_mean(per_rep)
    return out


def tokens_per_success(ctx: Ctx) -> str:
    """tab:L-tokens-per-success -- tokens per successful task (Eq. cost, rho)
    per (model, condition) and run, and the Run 5 / Run 1 ratio.

    Per replicate and run: sum of total_tokens over all 314 tasks (including
    failures) / number of tasks with e2e_success. Run cells: mean across the
    three replicates, in millions, 2 decimals + 'M'. r5/r1: ratio of the two
    replicate means (mean Run 5 / mean Run 1), not the mean of per-replicate
    ratios; 2 decimals + '$\\times$'. Half up.

    Emphasis (\\textbf; no rule in the caption, so the printed pattern is
    implemented as): r5/r1 is bold in every row of a system whose regime
    (Eq. regime, most severe label among its conditions) is cliff; the Run 5
    cell is bold in the single row with the largest r5/r1 (the headline
    increase quoted in Sec. RQ4).
    """
    data = {(m, c): _tps_means(ctx, m, c) for m in MODELS for c in CONDITIONS_ALPHA}
    ratio = {k: v[5] / v[1] for k, v in data.items()}
    top = max(ratio, key=ratio.__getitem__)
    cliff = {m: system_regime(ctx, m) == "cliff" for m in MODELS}
    lines = []
    for model in MODELS:
        for cond in CONDITIONS_ALPHA:
            means = data[(model, cond)]
            cells = [model, cond]
            for run in RUNS:
                cells.append(bold(f"{rnd(means[run] / 10**6, 2)}M", run == 5 and (model, cond) == top))
            cells.append(bold(f"{rnd(ratio[(model, cond)], 2)}$\\times$", cliff[model]))
            lines.append(row(cells))
    return "\n".join(lines)


def failed_share(ctx: Ctx) -> str:
    """tab:L-failed-share -- share of tokens spent on failed task trajectories
    at Run 1 and Run 5 per (model, condition).

    Per replicate and run: sum of total_tokens over tasks with e2e_success =
    False / sum of total_tokens over all 314 tasks. Run cells: mean across the
    three replicates (replicate-level shares averaged, not pooled token sums),
    3 decimals, half up.

    Delta(r5-r1) convention: the paper prints the difference of the two
    *printed* (rounded) values, e.g. Gemma Bold 0.389 - 0.379 = +0.010 although
    the unrounded difference is +0.0107 (and Gemma Cautious +0.001 vs +0.0017).
    This is reproduced exactly: Delta = rnd(Run 5) - rnd(Run 1) in decimal
    arithmetic, printed with an explicit sign and 3 decimals.

    Emphasis (\\textbf; no rule in the caption): the Run 5 and Delta cells of
    the row with the largest Run 1 -> Run 5 increase are bold (GPT-OSS
    Cautious, quoted in Sec. RQ4). It is also the only row with
    |Delta| >= tau = 0.10.
    """
    data = {}
    for model in MODELS:
        for cond in CONDITIONS_ALPHA:
            shares = {}
            for run in (1, 5):
                per_rep = []
                for rep in _reps(ctx, model):
                    rs = _rows(ctx, model, cond, rep, (run,))
                    tot = sum(r["total_tokens"] for r in rs)
                    per_rep.append(Fraction(sum(r["total_tokens"] for r in rs if not r["success"]), tot))
                shares[run] = frac_mean(per_rep)
            data[(model, cond)] = shares
    top = max(data, key=lambda k: data[k][5] - data[k][1])
    lines = []
    for model in MODELS:
        for cond in CONDITIONS_ALPHA:
            r1, r5 = rnd(data[(model, cond)][1], 3), rnd(data[(model, cond)][5], 3)
            delta = Decimal(r5) - Decimal(r1)  # difference of printed values (see docstring)
            on = (model, cond) == top
            lines.append(row([model, cond, r1, bold(r5, on), bold(f"{delta:+.3f}", on)]))
    return "\n".join(lines)


def _amb_table(ctx: Ctx, keys, label_fn, select) -> str:
    lines = []
    for model in MODELS:
        reps = _reps(ctx, model)
        for key in keys:
            cells = [model, label_fn(key)]
            ns = set()
            for cond in CONDITIONS:
                per_rep = []
                n = 0
                for rep in reps:
                    rs = [r for r in _rows(ctx, model, cond, rep) if select(r, key)]
                    per_rep.append(rate(rs, "success"))
                    n += len(rs)
                ns.add(n)
                cells.append(f"{rnd(frac_mean(per_rep) * 100, 1)}\\%")
            if len(ns) != 1:
                raise RuntimeError(f"{model} {key}: N differs across conditions {ns}")
            cells.append(f"{ns.pop():,}")
            lines.append(row(cells))
    return "\n".join(lines)


def amb_dimension(ctx: Ctx) -> str:
    """tab:amb-dimension -- success rate by ambiguity dimension x condition.

    A task counts toward every dimension listed in its ambiguity_dimensions
    (tasks can carry several). Per replicate: success rate over the matching
    tasks of runs 1-5 pooled. Cell: mean of the three replicate rates (equal to
    the pooled rate, since every replicate has the same tasks), x100, 1 decimal,
    half up, '\\%'. N (per condition): number of matching task records per
    condition over 3 replicates x 5 runs, with thousands separators. Rows:
    Goal, Process, Priority, Behavior; columns Bold, Neutral, Cautious.
    """
    return _amb_table(ctx, DIMENSIONS, str, lambda r, k: k in r["dims"])


def amb_level(ctx: Ctx) -> str:
    """tab:amb-level -- success rate by ambiguity level (number of co-occurring
    dimensions, 1-4) x condition. Same aggregation and formatting as
    tab:amb-dimension; rows L1-L4.
    """
    return _amb_table(ctx, LEVELS, lambda k: f"L{k}", lambda r, k: r["level"] == k)


TABLES = {
    "tab:run1-vs-run5": run1_vs_run5,
    "tab:clarif-gptoss": clarif_gptoss,
    "tab:clarif-qwen": clarif_qwen,
    "tab:clarif-gemma": clarif_gemma,
    "tab:L-clarif-correction": clarif_correction,
    "tab:L-tokens-per-success": tokens_per_success,
    "tab:L-failed-share": failed_share,
    "tab:amb-dimension": amb_dimension,
    "tab:amb-level": amb_level,
}
