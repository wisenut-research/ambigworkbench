"""
Results analyzer for the Soul A/B/C experiment.

Reads the JSONL results file produced by run_experiment.py and prints
summary statistics + efficiency comparisons.

Usage:
    python experiment/analysis/analyze.py --results experiment/results/<run_id>.jsonl
    python experiment/analysis/analyze.py --results-dir experiment/results/  # merge all files
"""

from __future__ import annotations

import argparse
import json
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any


SOUL_LABELS = {
    "soul-a": "Soul A (Neutral)",
    "soul-b": "Soul B (Cautious)",
    "soul-c": "Soul C (Bold)",
}

METRIC_DEFS = [
    ("total_tokens",            "Total tokens"),
    ("total_input_tokens",      "Input tokens"),
    ("total_output_tokens",     "Output tokens"),
    ("total_turns",             "Turns (steps)"),
    ("total_tool_calls",        "Tool calls"),
    ("failed_tool_calls",       "Failed tool calls"),
    ("failed_tool_token_waste", "Wasted tokens (failed tools)"),
    ("clarification_messages",  "Clarification messages"),
]


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_results(paths: list[Path]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in paths:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


# ---------------------------------------------------------------------------
# Statistics helpers
# ---------------------------------------------------------------------------

def group_by_soul(records: list[dict]) -> dict[str, list[dict]]:
    groups: dict[str, list[dict]] = defaultdict(list)
    for r in records:
        groups[r["soul_id"]].append(r)
    return dict(groups)


def describe(values: list[float]) -> dict[str, float]:
    if not values:
        return {"n": 0, "mean": 0, "median": 0, "stdev": 0, "min": 0, "max": 0}
    return {
        "n": len(values),
        "mean": statistics.mean(values),
        "median": statistics.median(values),
        "stdev": statistics.stdev(values) if len(values) > 1 else 0.0,
        "min": min(values),
        "max": max(values),
    }


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def fmt(v: float, decimals: int = 1) -> str:
    return f"{v:,.{decimals}f}"


def print_table(headers: list[str], rows: list[list[str]]) -> None:
    col_widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            col_widths[i] = max(col_widths[i], len(cell))

    sep = "  "
    header_line = sep.join(h.ljust(col_widths[i]) for i, h in enumerate(headers))
    print(header_line)
    print("-" * len(header_line))
    for row in rows:
        print(sep.join(cell.ljust(col_widths[i]) for i, cell in enumerate(row)))


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------

def analyze(records: list[dict]) -> None:
    if not records:
        print("No records found.")
        return

    by_soul = group_by_soul(records)
    souls = sorted(by_soul.keys())

    total_tasks = len({r["task_id"] for r in records})
    print(f"\n{'='*70}")
    print(f"  Soul A/B/C Experiment Analysis")
    print(f"  Tasks: {total_tasks}  |  Souls: {len(souls)}  |  Total runs: {len(records)}")
    print(f"{'='*70}\n")

    # --- Per-metric summary table ---
    print("-- Mean values per soul ----------------------------------------------")
    soul_labels = [SOUL_LABELS.get(s, s) for s in souls]
    headers = ["Metric"] + soul_labels + ["Winner (lower=better)"]
    rows = []

    for metric_key, metric_label in METRIC_DEFS:
        soul_means: dict[str, float] = {}
        for soul in souls:
            vals = [r.get(metric_key, 0) or 0 for r in by_soul[soul]]
            soul_means[soul] = statistics.mean(vals) if vals else 0.0

        min_val = min(soul_means.values()) if soul_means else 0
        winner_souls = [s for s, v in soul_means.items() if v == min_val]
        winner = " & ".join(SOUL_LABELS.get(s, s) for s in winner_souls)

        row = [metric_label]
        for soul in souls:
            row.append(fmt(soul_means[soul]))
        row.append(winner)
        rows.append(row)

    print_table(headers, rows)

    # --- Completion rate ---
    print("\n-- Task completion rate ----------------------------------------------")
    for soul in souls:
        soul_records = by_soul[soul]
        n = len(soul_records)
        completed = sum(1 for r in soul_records if r.get("completed"))
        rate = 100 * completed / n if n else 0
        print(f"  {SOUL_LABELS.get(soul, soul):<25}  {completed}/{n}  ({rate:.1f}%)")

    # --- Efficiency ratios ---
    print("\n-- Efficiency ratios (relative to Soul A baseline) ------------------")
    if "soul-a" in by_soul:
        baseline_vals: dict[str, float] = {}
        for metric_key, _ in METRIC_DEFS:
            vals = [r.get(metric_key, 0) or 0 for r in by_soul["soul-a"]]
            baseline_vals[metric_key] = statistics.mean(vals) if vals else 1.0

        ratio_headers = ["Metric"] + [SOUL_LABELS.get(s, s) for s in souls if s != "soul-a"]
        ratio_rows = []
        for metric_key, metric_label in METRIC_DEFS:
            base = baseline_vals.get(metric_key, 1) or 1
            row = [metric_label]
            for soul in souls:
                if soul == "soul-a":
                    continue
                vals = [r.get(metric_key, 0) or 0 for r in by_soul[soul]]
                mean_val = statistics.mean(vals) if vals else 0
                ratio = mean_val / base
                arrow = "+" if ratio > 1.05 else ("-" if ratio < 0.95 else "≈")
                row.append(f"{arrow} {ratio:.2f}x")
            ratio_rows.append(row)
        print_table(ratio_headers, ratio_rows)
    else:
        print("  (Soul A baseline not present in results)")

    # --- Per-complexity breakdown ---
    complexities = sorted({r.get("complexity", "unknown") for r in records})
    if len(complexities) > 1:
        print("\n-- Total tokens by complexity ----------------------------------------")
        cplx_headers = ["Complexity"] + [SOUL_LABELS.get(s, s) for s in souls]
        cplx_rows = []
        for cplx in complexities:
            row = [cplx]
            for soul in souls:
                vals = [r.get("total_tokens", 0) or 0 for r in by_soul.get(soul, []) if r.get("complexity") == cplx]
                row.append(fmt(statistics.mean(vals)) if vals else "n/a")
            cplx_rows.append(row)
        print_table(cplx_headers, cplx_rows)

    # --- Research interpretation hints ---
    print("\n-- Interpretation guide ----------------------------------------------")
    print("  Soul B higher 'Clarification messages' -> risk-avoidance overhead")
    print("  Soul C higher 'Failed tool calls' -> execution-risk materialized")
    print("  Soul C lower 'Turns' with similar 'Total tokens' -> efficient when succeeding")
    print("  Compare 'Failed tool token waste' vs 'Clarification' cost for trade-off insight")
    print()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze Soul A/B/C experiment results")
    parser.add_argument("--results", type=Path, help="Single JSONL results file")
    parser.add_argument("--results-dir", type=Path, help="Directory of JSONL results files (merged)")
    args = parser.parse_args()

    paths: list[Path] = []
    if args.results:
        paths.append(args.results)
    if args.results_dir:
        paths.extend(sorted(args.results_dir.glob("*.jsonl")))

    if not paths:
        print("Specify --results <file> or --results-dir <dir>")
        raise SystemExit(1)

    records = load_results(paths)
    analyze(records)


if __name__ == "__main__":
    main()
