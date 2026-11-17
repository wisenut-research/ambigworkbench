"""Memory-corpus tables: constraint density and sample lines from patterns_run5.md.

  tab:gating-density   lines matching each lexical family per 100 non-empty lines
                       of the Run-5 memory snapshot, mean over replicates 1-3
  tab:gating-samples   hand-picked example lines from replicate 1, with provenance
                       checked against the archived snapshots

Regex families. PROHIBITIVE, CONDITIONAL and ASK_FIRST are imported from
scripts/extract_gating_lines.py, the same objects used for matched-line removal
and by scripts/measure_gating_density.py, so this table and the released
detector cannot drift apart. HEDGE and ACTION_VERB have no released
implementation; they are defined below verbatim from the paper's regex table
(tab:regex) and compiled case-insensitively like the other three.

Run directly to print exact (unrounded) densities and sample provenance:
  python3 scripts/tables/memory.py --results-root results [--extra-results-root ...]
"""
from __future__ import annotations

import argparse
import re
from fractions import Fraction
from pathlib import Path

from common import CONDITION_TO_SOUL, REPS, Ctx, latex_rows, rnd
from extract_gating_lines import ASK_FIRST, CONDITIONAL, PROHIBITIVE, has_gating

# Not in released code: copied verbatim from tab:regex.
HEDGE = re.compile(
    r"\b(might|may|possibly|likely|consider|caution|risk|cautious|careful|carefully)\b",
    re.IGNORECASE,
)
ACTION_VERB = re.compile(
    r"\b(create|update|delete|send|reply|forward|add|plot|run|execute|perform|apply|do)\b",
    re.IGNORECASE,
)

# Families measured as "lines with >= 1 match" (Eq. gating-density) ...
LINE_FAMILIES = {
    "PROHIBITIVE": PROHIBITIVE,
    "CONDITIONAL": CONDITIONAL,
    "ASK_FIRST": ASK_FIRST,
    "HEDGE": HEDGE,
}
# ... versus "every match" (ACTION_VERB can exceed 100 per 100 lines).
MATCH_FAMILIES = {"ACTION_VERB": ACTION_VERB}
CONSTRAINT_FAMILIES = ("PROHIBITIVE", "CONDITIONAL", "ASK_FIRST")

CONDITIONS = ("Neutral", "Cautious", "Bold")
CONDITION_MACRO = {"Neutral": r"\neutral", "Cautious": r"\cautious", "Bold": r"\boldid"}


# ---------------------------------------------------------------------------
# Constraint density
# ---------------------------------------------------------------------------

def nonempty_lines(ctx: Ctx, path: Path) -> list[str]:
    """Non-empty lines of a memory snapshot (the denominator N(M)). Read the same
    way as scripts/measure_gating_density.py (UTF-8, undecodable bytes replaced)."""
    key = ("memlines", str(path))
    if key not in ctx._cache:
        text = path.read_text(encoding="utf-8", errors="replace")
        ctx._cache[key] = [ln for ln in text.splitlines() if ln.strip()]
    return ctx._cache[key]


def corpus_density(ctx: Ctx, path: Path) -> dict[str, Fraction]:
    """Per-100-line densities of one snapshot, as exact fractions.

    Line families: 100 * (#lines with >= 1 match) / N. A line that matches a
    family several times counts once. ANY = lines matching at least one of
    PROHIBITIVE/CONDITIONAL/ASK_FIRST (released `has_gating`).
    ACTION_VERB: 100 * (#matches) / N, so one line can contribute several."""
    lines = nonempty_lines(ctx, path)
    n = len(lines)
    if n == 0:
        raise ValueError(f"empty memory snapshot: {path}")
    out = {name: Fraction(100 * sum(1 for ln in lines if rx.search(ln)), n) for name, rx in LINE_FAMILIES.items()}
    out.update({name: Fraction(100 * sum(len(rx.findall(ln)) for ln in lines), n) for name, rx in MATCH_FAMILIES.items()})
    out["ANY"] = Fraction(100 * sum(1 for ln in lines if has_gating(ln)), n)
    return out


def replicate_mean_density(ctx: Ctx, model: str, condition: str, run: int = 5, reps=REPS) -> dict[str, Fraction]:
    """Mean over replicates of per-replicate densities (each replicate weighs
    equally regardless of corpus length; corpora are not pooled)."""
    soul = CONDITION_TO_SOUL[condition]
    per_rep = [corpus_density(ctx, ctx.memory_snapshot(model, rep, soul, run)) for rep in reps]
    return {k: sum(d[k] for d in per_rep) / len(per_rep) for k in per_rep[0]}


DENSITY_MODELS = (("GPT-OSS", "GPT-OSS-120B"), ("Gemma", "Gemma4-26B-A4B-it"), ("Qwen", "Qwen3.5-27B"))
DENSITY_COLUMNS = ("PROHIBITIVE", "CONDITIONAL", "ASK_FIRST", "ACTION_VERB")

# Bold cells in the printed table are editorial emphasis on cells discussed in
# Sec. 5.3.2-5.3.3 (they follow no max/min rule, e.g. Qwen's highest ASK_FIRST
# and GPT-OSS's highest ACTION_VERB are not bold), so they are listed, not derived.
DENSITY_BOLD = {
    ("GPT-OSS-120B", "Neutral", "ASK_FIRST"),
    ("Gemma4-26B-A4B-it", "Neutral", "ASK_FIRST"),
    ("Gemma4-26B-A4B-it", "Cautious", "ACTION_VERB"),
}


def tab_gating_density(ctx: Ctx) -> str:
    """tab:gating-density. For each model and condition, the replicate-1..3
    `patterns_run5.md` snapshots are scored per Eq. (gating-density):
    PROHIBITIVE/CONDITIONAL/ASK_FIRST = lines with >= 1 match per 100 non-empty
    lines; ACTION_VERB = matches per 100 non-empty lines. Each replicate's
    density is computed first and the three are averaged (camera-ready
    definition; earlier drafts counted total matches for every family). HEDGE
    is computed by `corpus_density` but omitted from the printed table.
    Values are rounded half-up to one decimal."""
    rows = []
    for short, model in DENSITY_MODELS:
        for cond in CONDITIONS:
            dens = replicate_mean_density(ctx, model, cond)
            cells = []
            for col in DENSITY_COLUMNS:
                txt = rnd(dens[col], 1)
                cells.append(rf"\textbf{{{txt}}}" if (model, cond, col) in DENSITY_BOLD else txt)
            rows.append([short, CONDITION_MACRO[cond], *cells])
    # The paper source indents each body row by one space.
    return "\n".join(" " + ln for ln in latex_rows(rows).splitlines())


# ---------------------------------------------------------------------------
# Sample lines
# ---------------------------------------------------------------------------

# Regime labels as printed; they come from the run-level regime rule (Eq. regime),
# which is computed with the performance tables, not here.
REGIME = {"GPT-OSS-120B": "cliff", "Gemma4-26B-A4B-it": "drift", "Qwen3.5-27B": "stable"}

# (model, condition, example as printed in LaTeX). Selected by hand from the
# replicate-1 Run-5 snapshots; the list is data, not the output of a rule.
GATING_SAMPLES = (
    ("GPT-OSS-120B", "Neutral",
     r"\texttt{[action-scope]} When a specific meeting is reported missing, first list calendar events for the relevant date(s) to confirm absence before creating the event with \texttt{wb-calendar.py create}."),
    ("GPT-OSS-120B", "Neutral",
     r"\texttt{[action-scope]} Verify the condition (e.g., metric threshold) before performing bulk deletions of CRM leads for a specific assignee."),
    ("GPT-OSS-120B", "Cautious",
     r"\texttt{[action-scope]} When deleting multiple future events with a specific title, first list matching events, confirm the IDs to delete, then perform deletions one by one."),
    ("GPT-OSS-120B", "Cautious",
     r"\texttt{[action-scope]} When an email address is not provided, ask the user to supply it before sending the email."),
    ("GPT-OSS-120B", "Bold",
     r"\texttt{[action-scope]} Before updating multiple records of the same type, verify the exact number of records that need the change and limit update commands to that count to avoid over-acting."),
    ("Gemma4-26B-A4B-it", "Neutral",
     r"\texttt{[action-scope]} When a user claims a task or event is missing despite tool outputs confirming its existence, provide the specific tool output as evidence before repeating the action."),
    ("Gemma4-26B-A4B-it", "Cautious",
     r"\texttt{[action-scope]} When a user's request for a specific target or person describes them as ``overdue'', verify the system date against the dataset due dates before assuming tasks exist to be reassigned."),
    ("Gemma4-26B-A4B-it", "Cautious",
     r"\texttt{[action-scope]} When a task's requirements are partially clarified, ensure only the newly specified requirements are addressed to avoid redundant actions."),
    ("Gemma4-26B-A4B-it", "Bold",
     r"\texttt{[action-scope]} After executing a command, verify the result with a list/read command to ensure the change is reflected immediately."),
    ("Qwen3.5-27B", "Neutral",
     r"\texttt{[crm-deletion]} When asked to delete ``an old contact'' without specifics, clarify the exact customer name before executing destructive action."),
    ("Qwen3.5-27B", "Neutral",
     r"\texttt{[initial-setup]} Gather all required details (participants, timing, purpose) completely before executing CREATE operations to avoid corrective iterations."),
    ("Qwen3.5-27B", "Cautious",
     r"\texttt{[compound-criteria]} Multi-condition selections require intersection logic---combine ALL filters (e.g., Status $\in$ \{Qualified, Proposal\} AND Industry=X)---rather than union/approximate matching."),
    ("Qwen3.5-27B", "Bold",
     r"\texttt{[surname-ambiguity]} When user references surname-only like ``Anderson'', ask which specific person before acting---CRM often contains multiple records sharing family names."),
)


def detex(latex: str) -> str:
    """Undo the LaTeX markup used in the printed examples (exact inverse for the
    constructs that occur there, nothing more)."""
    s = re.sub(r"^\\texttt\{(\[[^}]*\])\}", r"\1", latex)  # leading [tag]
    s = re.sub(r"\\texttt\{([^}]*)\}", r"`\1`", s)  # inline code was `backticked` in the file
    for tex, plain in (("``", '"'), ("''", '"'), ("---", "\u2014"), (r"$\in$", "\u2208"),
                       (r"\{", "{"), (r"\}", "}"), (r"\_", "_")):
        s = s.replace(tex, plain)
    return s


# Typography the paper applies when printing an archived line. Each step is
# applied to BOTH the archived line and the de-TeXed printed line, so a match
# means the two differ only in these respects. Nothing else (wording,
# punctuation inside the sentence, tag) is normalized.
_TAG_BODY = re.compile(r"^(\[[^\]]*\]\s+)(\S)")
TYPOGRAPHY = (
    # sentence case: first letter of the rule text after the [tag] is capitalized
    ("sentence-case", lambda s: _TAG_BODY.sub(lambda m: m.group(1) + m.group(2).upper(), s)),
    # a terminal period is added when the archived line has none
    ("terminal-period", lambda s: s if s.endswith(".") else s + "."),
    # quoted words are typeset with LaTeX double quotes whatever the source quote
    # mark; only a quote pair delimiting a word span is touched, not apostrophes
    ("quote-style", lambda s: re.sub(r"(?<!\w)'([^'\n]+?)'(?!\w)", r'"\1"', s)),
    # U+2011 non-breaking hyphen is printed as an ASCII hyphen
    ("ascii-hyphen", lambda s: s.replace("\u2011", "-")),
    # set notation is spaced in print: "Status∈{A,B}" -> "Status ∈ {A, B}"
    ("set-spacing", lambda s: re.sub(r",(?=\S)", ", ", re.sub(r"\s*\u2208\s*", " \u2208 ", s))),
)


def _canon(s: str) -> tuple[str, list[str]]:
    """Apply TYPOGRAPHY; return the result and the names of steps that changed `s`."""
    changed = []
    for name, fn in TYPOGRAPHY:
        t = fn(s)
        if t != s:
            changed.append(name)
        s = t
    return s, changed


def _strip_marker(line: str) -> str:
    s = line.strip()
    return s[2:] if s.startswith("- ") else s


def locate_sample(ctx: Ctx, model: str, condition: str, latex: str, rep: int = 1, run: int = 5) -> dict:
    """Find a printed example in the replicate-`rep` Run-`run` snapshot of
    model/condition. Raises LookupError unless an archived line equals the
    printed text up to `detex` and TYPOGRAPHY. Returns the file, every matching
    1-based line number (duplicate rules are kept in memory, so there may be
    several), the archived text, the typography steps that were needed, and
    the regex families the archived line matches."""
    path = ctx.memory_snapshot(model, rep, CONDITION_TO_SOUL[condition], run)
    printed, _ = _canon(detex(latex))
    hits = []
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not raw.strip():
            continue
        canon, steps = _canon(_strip_marker(raw))
        if canon == printed:
            hits.append((lineno, raw, steps))
    if not hits:
        raise LookupError(f"printed sample not found in {path}: {latex[:80]}...")
    # Duplicates may differ in typography; report the closest (then earliest) copy.
    lineno, raw, steps = min(hits, key=lambda h: (len(h[2]), h[0]))
    families = [name for name, rx in {**LINE_FAMILIES, **MATCH_FAMILIES}.items() if rx.search(raw)]
    if not any(f in families for f in CONSTRAINT_FAMILIES):
        raise ValueError(f"sample matches none of {CONSTRAINT_FAMILIES}: {path}:{lineno}")
    root = next((r for r in ctx.roots if path.is_relative_to(r)), None)
    return {
        "model": model,
        "condition": condition,
        "file": str(path.relative_to(root)) if root else str(path),
        "lines": [h[0] for h in hits],
        "archived": raw,
        "typography": steps,
        "families": families,
    }


def sample_provenance(ctx: Ctx) -> list[dict]:
    return [locate_sample(ctx, model, cond, latex) for model, cond, latex in GATING_SAMPLES]


def tab_gating_samples(ctx: Ctx) -> str:
    """tab:gating-samples. The examples were SELECTED MANUALLY for the paper;
    there is no selection rule and this function does not pretend to have one.
    It verifies provenance instead: every printed line must occur in the
    replicate-1 `patterns_run5.md` of the stated model/condition (verbatim up
    to the documented LaTeX markup and TYPOGRAPHY steps) and must match at least
    one of PROHIBITIVE/CONDITIONAL/ASK_FIRST; otherwise it raises. The rows are
    then emitted as printed (one line per row). Use `sample_provenance` or run
    this module directly for file and line numbers."""
    sample_provenance(ctx)  # raises on any unverifiable sample
    rows = [[model, REGIME[model], cond, latex] for model, cond, latex in GATING_SAMPLES]
    return latex_rows(rows)


TABLES = {
    "tab:gating-density": tab_gating_density,
    "tab:gating-samples": tab_gating_samples,
}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--results-root", default="results")
    ap.add_argument("--extra-results-root", action="append", default=[])
    args = ap.parse_args()
    ctx = Ctx(roots=[Path(args.results_root)] + [Path(p) for p in args.extra_results_root])

    cols = (*DENSITY_COLUMNS, "HEDGE", "ANY")
    print("Run-5 density per 100 non-empty lines, mean over replicates " + ",".join(map(str, REPS)))
    print(f"{'model':18s} {'condition':9s} " + " ".join(f"{c:>12s}" for c in cols))
    for _, model in DENSITY_MODELS:
        for cond in CONDITIONS:
            d = replicate_mean_density(ctx, model, cond)
            print(f"{model:18s} {cond:9s} " + " ".join(f"{float(d[c]):12.4f}" for c in cols))
    print("\nSample provenance (replicate 1, patterns_run5.md):")
    for p in sample_provenance(ctx):
        print(f"  {p['model']} / {p['condition']}: {p['file']}:{','.join(map(str, p['lines']))}"
              f"  families={'+'.join(p['families'])}  typography={'+'.join(p['typography']) or 'none'}")


if __name__ == "__main__":
    main()
