#!/usr/bin/env python3
"""Regenerate the paper's data tables from raw run JSONL and memory snapshots.

Usage (from the repository root):
  python3 scripts/tables/make_tables.py --results-root results \
      [--extra-results-root <second results tree> ...] \
      [--out derived_results/tables] [--only tab:L-spread tab:pca-centroids]

Each table is written to <out>/<label>.tex as the LaTeX body rows printed in
the paper (one line per row), so a diff against the paper source is direct.
Tables that are not computed from data (terminology, regex families, IFEval,
serving configuration) are not generated here.
"""
from __future__ import annotations

import argparse
import importlib
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import Ctx  # noqa: E402

MODULES = ("behavior", "performance", "memory", "interventions")


def collect_tables() -> dict:
    tables = {}
    for name in MODULES:
        mod = importlib.import_module(name)
        for label, fn in mod.TABLES.items():
            if label in tables:
                raise RuntimeError(f"duplicate table label {label}")
            tables[label] = fn
    return tables


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--results-root", default="results")
    ap.add_argument("--extra-results-root", action="append", default=[])
    ap.add_argument("--out", default="derived_results/tables")
    ap.add_argument("--only", nargs="*", default=None, help="table labels to generate (default: all)")
    args = ap.parse_args()

    ctx = Ctx(roots=[Path(args.results_root)] + [Path(p) for p in args.extra_results_root])
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    tables = collect_tables()
    labels = args.only or list(tables)
    failed = []
    for label in labels:
        t0 = time.time()
        try:
            text = tables[label](ctx)
        except Exception as exc:  # keep going so one missing run does not block the rest
            failed.append(label)
            print(f"[FAIL] {label}: {type(exc).__name__}: {exc}")
            continue
        (out / f"{label.replace(':', '_')}.tex").write_text(text.rstrip() + "\n", encoding="utf-8")
        print(f"[ok]   {label} ({time.time() - t0:.1f}s)")
    print(f"\n{len(labels) - len(failed)}/{len(labels)} tables written to {out}")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
