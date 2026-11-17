"""Shared helpers for regenerating the paper's tables from raw run JSONL.

Every table module in this package reads results through `Ctx`, so all tables
use the same run discovery, replicate filter (replicates 1-3), condition
names, and rounding.

Results layout (as written by the runners in scripts/):
  <root>/<MODEL>/<MODEL>_repN/<MODEL>_repN_runK_<timestamp>/<...>.jsonl
  <root>/<MODEL>/<MODEL>_repN/<MODEL>_repN_memory_log/<soul>/patterns_runK.md
Qwen replicate 1 omits the "_rep1" infix (Qwen3.5-27B_runK_<timestamp>,
Qwen3.5-27B_memory_log). Interventions live under <root>/_ablation,
<root>/interventions, and <root>/gate_inject_rebuttal; GPT-OSS-20B lives under
<root>/GPT-OSS-20B. When several roots are given, the first root that contains
a run wins, so duplicated copies are never double-counted.
"""
from __future__ import annotations

import glob
import json
import math
import re
import sys
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from fractions import Fraction
from pathlib import Path
from typing import Iterator

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
REPO_DIR = SCRIPTS_DIR.parent
sys.path.insert(0, str(SCRIPTS_DIR))
sys.path.insert(0, str(REPO_DIR / "analysis"))

MODELS = ("GPT-OSS-120B", "Qwen3.5-27B", "Gemma4-26B-A4B-it")
SOUL_TO_CONDITION = {"soul-a": "Neutral", "soul-b": "Cautious", "soul-c": "Bold"}
CONDITION_TO_SOUL = {v: k for k, v in SOUL_TO_CONDITION.items()}
REPS = (1, 2, 3)  # GPT-OSS-120B has an extra replicate 4 that the paper does not use
RUNS = (1, 2, 3, 4, 5)

_RUN_DIR_RE = (re.compile(r"_rep(\d+)_run(\d+)_"), re.compile(r"_run(\d+)_"))


def parse_run_dir(name: str) -> tuple[int | None, int | None]:
    """(replicate, run) from a run directory name; same rule as make_figures.parse_dir."""
    m = _RUN_DIR_RE[0].search(name)
    if m:
        return int(m.group(1)), int(m.group(2))
    m = _RUN_DIR_RE[1].search(name)
    if m:
        return 1, int(m.group(1))
    return None, None


def iter_jsonl(path: Path) -> Iterator[dict]:
    """Stream records from a JSONL file (run files hold full transcripts and
    can be several hundred MB, so they are never held in memory whole)."""
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def load_jsonl(path: Path) -> list[dict]:
    return list(iter_jsonl(path))


@dataclass
class Ctx:
    roots: list[Path]
    _cache: dict = field(default_factory=dict)

    # ---- discovery -------------------------------------------------------
    def glob(self, pattern: str) -> list[Path]:
        """Matches of `pattern` (relative to a root) across all roots. A relative
        path present in several roots is taken from the first root only, so a
        partial copy in one tree and the full set in another combine correctly."""
        seen: dict[str, Path] = {}
        for root in self.roots:
            for p in glob.glob(str(root / pattern), recursive=True):
                if "_parallel_tmp" in p:
                    continue
                rel = str(Path(p).relative_to(root))
                seen.setdefault(rel, Path(p))
        return [seen[k] for k in sorted(seen)]

    def baseline_run_files(self, model: str, reps=REPS) -> dict[tuple[int, int], Path]:
        """{(rep, run): jsonl} for the five cumulative baseline runs of `model`."""
        key = ("baseline", model, tuple(reps))
        if key in self._cache:
            return self._cache[key]
        found: dict[tuple[int, int], Path] = {}
        for root in self.roots:
            model_dir = root / model
            if not model_dir.is_dir():
                continue
            for rep_dir in sorted(model_dir.iterdir()):
                if not rep_dir.is_dir() or any(s in rep_dir.name for s in ("memory_log", "analysis", "_smoke")):
                    continue
                for run_dir in sorted(rep_dir.iterdir()):
                    if not run_dir.is_dir() or "_run" not in run_dir.name or "memory_log" in run_dir.name:
                        continue
                    rep, run = parse_run_dir(run_dir.name)
                    if rep not in reps or run not in RUNS or (rep, run) in found:
                        continue
                    files = [p for p in run_dir.glob("*.jsonl")]
                    if len(files) != 1:
                        raise RuntimeError(f"expected one JSONL in {run_dir}, found {len(files)}")
                    found[(rep, run)] = files[0]
        self._cache[key] = found
        return found

    def memory_snapshot(self, model: str, rep: int, soul: str, run: int) -> Path:
        """patterns_runK.md archived after run K (the memory the next run starts from)."""
        infix = "" if (model.startswith("Qwen") and rep == 1) else f"_rep{rep}"
        rel = f"{model}/{model}_rep{rep}/{model}{infix}_memory_log/{soul}/patterns_run{run}.md"
        for root in self.roots:
            p = root / rel
            if p.exists():
                return p
        raise FileNotFoundError(rel)

    # ---- records ---------------------------------------------------------
    def records(self, model: str, reps=REPS, runs=RUNS) -> Iterator[tuple[int, int, str, dict]]:
        """Yield (rep, run, condition, record) for baseline runs."""
        for (rep, run), path in sorted(self.baseline_run_files(model, reps).items()):
            if run not in runs:
                continue
            for rec in iter_jsonl(path):
                cond = SOUL_TO_CONDITION.get(rec.get("soul_id", ""))
                if cond:
                    yield rep, run, cond, rec

    def load(self, path: Path) -> list[dict]:
        """Full records of one JSONL file (not cached; table modules cache the
        few per-task fields they need in `_cache` instead)."""
        return load_jsonl(path)


# ---- statistics and formatting -------------------------------------------

def mean(xs) -> float:
    xs = list(xs)
    return sum(xs) / len(xs) if xs else math.nan


def se(xs) -> float:
    """Standard error of the mean (sample SD with ddof=1 / sqrt(n))."""
    xs = [float(x) for x in xs]
    n = len(xs)
    if n < 2:
        return 0.0
    m = sum(xs) / n
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1)) / math.sqrt(n)


def rnd(x, nd: int) -> str:
    """Round half up (as printed in the paper). Accepts float, int, or Fraction."""
    if isinstance(x, Fraction):
        d = Decimal(x.numerator) / Decimal(x.denominator)
    else:
        if x is None or (isinstance(x, float) and math.isnan(x)):
            return "--"
        d = Decimal(repr(float(x)))
    q = Decimal(1).scaleb(-nd)
    return str(d.quantize(q, rounding=ROUND_HALF_UP))


def pm(m, s, nd: int = 3) -> str:
    return f"{rnd(m, nd)} $\\pm$ {rnd(s, nd)}"


def latex_rows(rows: list[list[str]]) -> str:
    return "\n".join(" & ".join(r) + r" \\" for r in rows)


def has_write_op(commands_executed) -> bool:
    """First-action detector used for first-action latency (FAL); imported from
    scripts/make_figures.py so tables and figures share one definition."""
    from make_figures import has_write_op as _h  # noqa: WPS433 (lazy: matplotlib import)
    return _h(commands_executed)
