"""
analyze_learning.py

Analysis for learning experiments.
Analyzes JSONL results produced against ambig_queries_evolving.json:
  1. summary CSVs per variant stage (v1-v4) x soul (learning_curve, cost_efficiency, behavior_change)
  2. three chart PNGs

Usage:
    python3 experiment/runner/analyze_learning.py <results.jsonl> [--out-dir ./analysis]
"""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np

try:
    import pandas as pd
    HAS_PANDAS = True
except ImportError:
    HAS_PANDAS = False

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SOULS = ["soul-a", "soul-b", "soul-c"]
SOUL_LABELS = {"soul-a": "Soul A (Neutral)", "soul-b": "Soul B (Cautious)", "soul-c": "Soul C (Bold)"}
SOUL_COLORS = {"soul-a": "#4C72B0", "soul-b": "#DD8452", "soul-c": "#55A868"}
VARIANTS = [1, 2, 3, 4]


def variant_of(task_id: str) -> int | None:
    m = re.search(r"_v(\d+)$", task_id)
    return int(m.group(1)) if m else None


def base_of(task_id: str) -> str:
    return re.sub(r"_v\d+$", "", task_id)


def load_records(path: Path) -> list[dict]:
    records = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------

def aggregate(records: list[dict]) -> dict:
    """
    Returns nested dict: stats[variant][soul] = {metric: value, ...}
    Also returns full_progression stats (44 tasks with v1~v4 all present).
    """
    # variant x soul buckets
    buckets: dict[int, dict[str, list]] = {v: {s: [] for s in SOULS} for v in VARIANTS}

    for r in records:
        v = variant_of(r.get("task_id", ""))
        soul = r.get("soul_id", "")
        if v not in VARIANTS or soul not in SOULS:
            continue
        buckets[v][soul].append(r)

    stats: dict[int, dict[str, dict]] = {}
    for v in VARIANTS:
        stats[v] = {}
        for soul in SOULS:
            recs = buckets[v][soul]
            if not recs:
                stats[v][soul] = None
                continue
            n = len(recs)

            scores = [r.get("eval", {}).get("score", 0) if r.get("eval") else 0 for r in recs]
            clarify = [r.get("clarification_turns", 0) for r in recs]
            tokens = [r.get("agent_tokens", 0) for r in recs]
            latency = [r.get("e2e_latency_ms", 0) / 1000 for r in recs]
            timeouts = [1 if r.get("timed_out") else 0 for r in recs]

            ap_recs = [r.get("action_precision") for r in recs if r.get("action_precision")]
            ap_applicable = [a for a in ap_recs if a and a.get("applicable")]
            over_act = sum(1 for a in ap_applicable if a.get("exec_count", 0) > a.get("gt_count", 0))

            turns_all = []
            for r in recs:
                for t in r.get("turns", []):
                    turns_all.append(len(t.get("commands_executed", [])))
            avg_cmds = sum(turns_all) / len(turns_all) if turns_all else 0

            stats[v][soul] = {
                "n": n,
                "avg_score": round(sum(scores) / n, 3),
                "clarify_rate": round(sum(1 for c in clarify if c > 0) / n, 3),
                "avg_clarify_turns": round(sum(clarify) / n, 3),
                "avg_agent_tokens": int(sum(tokens) / n),
                "avg_latency_s": round(sum(latency) / n, 1),
                "timeout_rate": round(sum(timeouts) / n, 3),
                "over_action_rate": round(over_act / len(ap_applicable), 3) if ap_applicable else None,
                "avg_commands": round(avg_cmds, 2),
            }

    return stats


def full_progression_stats(records: list[dict]) -> dict:
    """Aggregate only the 44 full-progression tasks (having all of v1-v4)."""
    # check which variants exist per base task
    base_variants: dict[str, set[int]] = defaultdict(set)
    for r in records:
        v = variant_of(r.get("task_id", ""))
        base = base_of(r.get("task_id", ""))
        if v:
            base_variants[base].add(v)

    full_bases = {b for b, vs in base_variants.items() if {1, 2, 3, 4}.issubset(vs)}

    filtered = [r for r in records if base_of(r.get("task_id", "")) in full_bases]
    return aggregate(filtered)


# ---------------------------------------------------------------------------
# CSV / Excel output
# ---------------------------------------------------------------------------

def build_rows(stats: dict, label_prefix: str = "") -> list[dict]:
    rows = []
    for v in VARIANTS:
        for soul in SOULS:
            s = stats[v].get(soul)
            if s is None:
                continue
            row = {"variant": f"v{v}", "soul": soul, **s}
            if label_prefix:
                row = {"group": label_prefix, **row}
            rows.append(row)
    return rows


def save_summary(stats_all: dict, stats_fp: dict, out_dir: Path, run_id: str) -> None:
    sheets = {
        "learning_curve": ["variant", "soul", "n", "avg_score", "clarify_rate", "avg_clarify_turns", "timeout_rate"],
        "cost_efficiency": ["variant", "soul", "n", "avg_agent_tokens", "avg_latency_s", "avg_commands"],
        "behavior_change": ["variant", "soul", "n", "clarify_rate", "over_action_rate", "avg_commands", "timeout_rate"],
        "full_progression": ["variant", "soul", "n", "avg_score", "clarify_rate", "avg_agent_tokens", "over_action_rate"],
    }

    all_rows = build_rows(stats_all)
    fp_rows = build_rows(stats_fp)

    sheet_data = {
        "learning_curve": all_rows,
        "cost_efficiency": all_rows,
        "behavior_change": all_rows,
        "full_progression": fp_rows,
    }

    if HAS_PANDAS:
        xlsx_path = out_dir / f"{run_id}_summary.xlsx"
        with pd.ExcelWriter(xlsx_path, engine="openpyxl") as writer:
            for sheet, rows in sheet_data.items():
                cols = sheets[sheet]
                df = pd.DataFrame(rows)[[c for c in cols if c in pd.DataFrame(rows).columns]]
                df.to_excel(writer, sheet_name=sheet, index=False)
        print(f"  Summary: {xlsx_path}")
    else:
        # without pandas, write one CSV per sheet
        import csv
        for sheet, rows in sheet_data.items():
            cols = sheets[sheet]
            csv_path = out_dir / f"{run_id}_{sheet}.csv"
            with open(csv_path, "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=[c for c in cols if rows and c in rows[0]])
                writer.writeheader()
                writer.writerows([{k: r.get(k) for k in cols if k in r} for r in rows])
            print(f"  {sheet}: {csv_path}")


# ---------------------------------------------------------------------------
# Charts
# ---------------------------------------------------------------------------

def chart_learning_curve(stats: dict, fp_stats: dict, out_dir: Path, run_id: str) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(13, 5))
    fig.suptitle("Learning Curve: Score by Variant Window", fontsize=13, fontweight="bold")

    for ax, (s, title) in zip(axes, [(stats, "All Tasks"), (fp_stats, "Full-Progression Tasks (v1–v4)")]):
        for soul in SOULS:
            xs, ys = [], []
            for v in VARIANTS:
                st = s[v].get(soul)
                if st:
                    xs.append(f"v{v}\n(n={st['n']})")
                    ys.append(st["avg_score"])
            if xs:
                ax.plot(xs, ys, marker="o", label=SOUL_LABELS[soul],
                        color=SOUL_COLORS[soul], linewidth=2, markersize=7)
        ax.set_title(title, fontsize=11)
        ax.set_ylabel("Avg Score")
        ax.set_ylim(0, 1.05)
        ax.yaxis.set_major_formatter(mticker.PercentFormatter(xmax=1))
        ax.legend(fontsize=9)
        ax.grid(axis="y", alpha=0.3)

    plt.tight_layout()
    path = out_dir / f"{run_id}_learning_curve.png"
    plt.savefig(path, dpi=150)
    plt.close()
    print(f"  Chart: {path}")


def chart_cost_efficiency(stats: dict, out_dir: Path, run_id: str) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(13, 5))
    fig.suptitle("Cost Efficiency: Token Usage & Latency by Variant Window", fontsize=13, fontweight="bold")

    metrics = [("avg_agent_tokens", "Avg Agent Tokens"), ("avg_latency_s", "Avg Latency (s)")]
    for ax, (metric, ylabel) in zip(axes, metrics):
        for soul in SOULS:
            xs, ys = [], []
            for v in VARIANTS:
                st = stats[v].get(soul)
                if st:
                    xs.append(f"v{v}\n(n={st['n']})")
                    ys.append(st.get(metric, 0))
            if xs:
                ax.plot(xs, ys, marker="o", label=SOUL_LABELS[soul],
                        color=SOUL_COLORS[soul], linewidth=2, markersize=7)
        ax.set_title(ylabel, fontsize=11)
        ax.set_ylabel(ylabel)
        ax.legend(fontsize=9)
        ax.grid(axis="y", alpha=0.3)
        if metric == "avg_agent_tokens":
            ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{x/1000:.0f}K"))

    plt.tight_layout()
    path = out_dir / f"{run_id}_cost_efficiency.png"
    plt.savefig(path, dpi=150)
    plt.close()
    print(f"  Chart: {path}")


def chart_behavior_change(stats: dict, out_dir: Path, run_id: str) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(13, 5))
    fig.suptitle("Behavior Change: Clarification & Over-Action Rates", fontsize=13, fontweight="bold")

    metrics = [
        ("clarify_rate", "Clarification Rate (turn ≥1 clarify)"),
        ("over_action_rate", "Over-Action Rate (exec > gt)"),
    ]
    for ax, (metric, ylabel) in zip(axes, metrics):
        for soul in SOULS:
            xs, ys = [], []
            for v in VARIANTS:
                st = stats[v].get(soul)
                if st and st.get(metric) is not None:
                    xs.append(f"v{v}\n(n={st['n']})")
                    ys.append(st[metric])
            if xs:
                ax.plot(xs, ys, marker="o", label=SOUL_LABELS[soul],
                        color=SOUL_COLORS[soul], linewidth=2, markersize=7)
        ax.set_title(ylabel, fontsize=11)
        ax.set_ylabel("Rate")
        ax.set_ylim(-0.05, 1.05)
        ax.yaxis.set_major_formatter(mticker.PercentFormatter(xmax=1))
        ax.legend(fontsize=9)
        ax.grid(axis="y", alpha=0.3)

    plt.tight_layout()
    path = out_dir / f"{run_id}_behavior_change.png"
    plt.savefig(path, dpi=150)
    plt.close()
    print(f"  Chart: {path}")


# ---------------------------------------------------------------------------
# Memory snapshot
# ---------------------------------------------------------------------------

def snapshot_memory(workspace_dir: Path, out_dir: Path, run_id: str) -> None:
    snap = {}
    for soul in SOULS:
        p = workspace_dir / soul / "memory" / "patterns.md"
        if p.exists():
            snap[soul] = p.read_text()
        else:
            snap[soul] = "(empty)"

    snap_path = out_dir / f"{run_id}_memory_snapshot.md"
    with open(snap_path, "w") as f:
        f.write(f"# Memory Snapshot — {run_id}\n\n")
        for soul, content in snap.items():
            f.write(f"## {SOUL_LABELS[soul]}\n\n```\n{content}\n```\n\n")
    print(f"  Memory snapshot: {snap_path}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze learning experiment results")
    parser.add_argument("results_jsonl", type=Path, help="JSONL results file from run_experiment.py")
    parser.add_argument("--out-dir", type=Path, default=None, help="Output directory (default: same as results file)")
    parser.add_argument("--workspace", type=Path,
                        default=Path(__file__).resolve().parents[1] / "workspace",
                        help="Path to experiment/workspace/ for memory snapshot")
    args = parser.parse_args()

    out_dir = args.out_dir or args.results_jsonl.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    run_id = args.results_jsonl.stem

    print(f"\nAnalyzing: {args.results_jsonl}")
    records = load_records(args.results_jsonl)
    print(f"Records loaded: {len(records)}")

    stats_all = aggregate(records)
    stats_fp = full_progression_stats(records)

    print("\nGenerating outputs...")
    save_summary(stats_all, stats_fp, out_dir, run_id)
    chart_learning_curve(stats_all, stats_fp, out_dir, run_id)
    chart_cost_efficiency(stats_all, out_dir, run_id)
    chart_behavior_change(stats_all, out_dir, run_id)
    snapshot_memory(args.workspace, out_dir, run_id)

    print("\nDone.")


if __name__ == "__main__":
    main()
