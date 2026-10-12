#!/usr/bin/env python3
"""Performance analysis for cumulative Ambig OfficeBench runs."""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
from collections import defaultdict
from itertools import combinations
from pathlib import Path
from typing import Any

import openpyxl
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from scipy import stats


SOUL_LABELS = {
    "soul-a": "Neutral",
    "soul-b": "Cautious",
    "soul-c": "Bold",
}

PERFORMANCE_METRICS = [
    "e2e_success",
    "score",
    "action_precision_match",
    "over_action",
    "under_action",
    "correction_recovery",
]


def parse_run_number(path: Path) -> int:
    match = re.search(r"_run(\d+)_", str(path))
    if not match:
        raise ValueError(f"cannot parse run number from {path}")
    return int(match.group(1))


def jsonl_files(rep_dir: Path) -> list[Path]:
    return sorted(rep_dir.glob("*_run*/*.jsonl"), key=parse_run_number)


def iter_json_objects(path: Path) -> list[tuple[int, dict[str, Any]]]:
    objects: list[tuple[int, dict[str, Any]]] = []
    current_start: int | None = None
    current_parts: list[str] = []

    def flush() -> None:
        nonlocal current_start, current_parts
        if not current_parts or current_start is None:
            return
        raw = current_parts[0] + "".join(r"\n" + part for part in current_parts[1:])
        record = json.loads(raw)
        objects.append((current_start, record))
        current_start = None
        current_parts = []

    for line_no, line in enumerate(path.read_text(errors="ignore").splitlines(), 1):
        if not line.strip():
            continue
        if line.startswith("{"):
            flush()
            current_start = line_no
            current_parts = [line]
        else:
            if current_start is None:
                raise ValueError(f"orphan JSON continuation at {path}:{line_no}")
            current_parts.append(line)

    flush()
    return objects


def load_records(rep_dir: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in jsonl_files(rep_dir):
        run = parse_run_number(path)
        for line_no, record in iter_json_objects(path):
            record["_run"] = run
            record["_line_no"] = line_no
            record["_jsonl"] = str(path)
            records.append(record)
    return records


def finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and not math.isnan(float(value)) and not math.isinf(float(value))


def mean(values: list[float]) -> float:
    values = [float(value) for value in values if finite(value)]
    return sum(values) / len(values) if values else math.nan


def median(values: list[float]) -> float:
    values = sorted(float(value) for value in values if finite(value))
    if not values:
        return math.nan
    mid = len(values) // 2
    return values[mid] if len(values) % 2 else (values[mid - 1] + values[mid]) / 2


def per_task_row(record: dict[str, Any]) -> dict[str, Any]:
    eval_data = record.get("eval") or {}
    ap = record.get("action_precision") or {}
    gt_count = int(ap.get("gt_count") or 0)
    exec_count = int(ap.get("exec_count") or 0)
    has_correction = int(record.get("correction_turns") or 0) > 0
    success = bool(eval_data.get("e2e_success"))
    dimensions = record.get("ambiguity_dimensions") or []
    if not isinstance(dimensions, list):
        dimensions = [dimensions]
    return {
        "run": int(record.get("_run") or 0),
        "soul_id": record.get("soul_id"),
        "identity": SOUL_LABELS.get(record.get("soul_id"), record.get("soul_id")),
        "task_id": record.get("task_id"),
        "domain": record.get("domain"),
        "ambiguity_level": record.get("ambiguity_level"),
        "ambiguity_dimensions": "|".join(str(dim) for dim in dimensions),
        "completed": bool(record.get("completed")),
        "error": record.get("error") or "",
        "e2e_success": 1.0 if success else 0.0,
        "score": float(eval_data.get("score") or 0.0),
        "passed_checks": int(eval_data.get("passed_checks") or 0),
        "total_checks": int(eval_data.get("total_checks") or 0),
        "check_pass_rate": (int(eval_data.get("passed_checks") or 0) / int(eval_data.get("total_checks") or 0)) if int(eval_data.get("total_checks") or 0) else math.nan,
        "action_precision_applicable": bool(ap.get("applicable")),
        "action_precision_match": 1.0 if ap.get("match") else 0.0,
        "gt_action_count": gt_count,
        "exec_action_count": exec_count,
        "over_action": 1.0 if gt_count and exec_count > gt_count else 0.0,
        "under_action": 1.0 if gt_count and exec_count < gt_count else 0.0,
        "has_correction": 1.0 if has_correction else 0.0,
        "correction_recovery": (1.0 if success else 0.0) if has_correction else math.nan,
        "total_turns": int(record.get("total_turns") or 0),
        "correction_turns": int(record.get("correction_turns") or 0),
    }


def explode_dimensions(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        dims = [dim for dim in str(row.get("ambiguity_dimensions") or "").split("|") if dim]
        for dim in dims:
            copy = dict(row)
            copy["ambiguity_dimension"] = dim
            out.append(copy)
    return out


def aggregate(rows: list[dict[str, Any]], group_keys: list[str]) -> list[dict[str, Any]]:
    grouped: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[tuple(row.get(key) for key in group_keys)].append(row)

    out: list[dict[str, Any]] = []
    for key, subset in sorted(grouped.items(), key=lambda item: tuple(str(x) for x in item[0])):
        item = dict(zip(group_keys, key))
        item["n"] = len(subset)
        for metric in PERFORMANCE_METRICS:
            vals = [row[metric] for row in subset if finite(row.get(metric))]
            item[f"{metric}_mean"] = mean(vals)
            item[f"{metric}_median"] = median(vals)
            item[f"{metric}_n"] = len(vals)
        item["check_pass_rate_mean"] = mean([row["check_pass_rate"] for row in subset])
        item["completed_rate"] = mean([1.0 if row["completed"] else 0.0 for row in subset])
        item["correction_required_rate"] = mean([row["has_correction"] for row in subset])
        out.append(item)
    return out


def kruskal_tests(rows: list[dict[str, Any]], group_key: str = "identity") -> list[dict[str, Any]]:
    groups = sorted({row[group_key] for row in rows})
    out: list[dict[str, Any]] = []
    for metric in PERFORMANCE_METRICS:
        arrays = [[float(row[metric]) for row in rows if row[group_key] == group and finite(row.get(metric))] for group in groups]
        valid = [array for array in arrays if array]
        if len(valid) < 2:
            stat = p = math.nan
        else:
            stat, p = stats.kruskal(*valid)
        out.append({"metric": metric, "groups": "|".join(groups), "h_statistic": stat, "p_value": p})
    return out


def cliff_delta(xs: list[float], ys: list[float]) -> float:
    xs = [x for x in xs if finite(x)]
    ys = [y for y in ys if finite(y)]
    if not xs or not ys:
        return math.nan
    gt = lt = 0
    for x in xs:
        for y in ys:
            if x > y:
                gt += 1
            elif x < y:
                lt += 1
    return (gt - lt) / (len(xs) * len(ys))


def pairwise_tests(rows: list[dict[str, Any]], group_key: str = "identity") -> list[dict[str, Any]]:
    groups = sorted({row[group_key] for row in rows})
    out: list[dict[str, Any]] = []
    for metric in PERFORMANCE_METRICS:
        for left, right in combinations(groups, 2):
            xs = [float(row[metric]) for row in rows if row[group_key] == left and finite(row.get(metric))]
            ys = [float(row[metric]) for row in rows if row[group_key] == right and finite(row.get(metric))]
            if xs and ys:
                stat, p = stats.mannwhitneyu(xs, ys, alternative="two-sided")
                delta = cliff_delta(xs, ys)
            else:
                stat = p = delta = math.nan
            out.append(
                {
                    "metric": metric,
                    "group_a": left,
                    "group_b": right,
                    "n_a": len(xs),
                    "n_b": len(ys),
                    "mean_a": mean(xs),
                    "mean_b": mean(ys),
                    "u_statistic": stat,
                    "p_value": p,
                    "p_bonferroni": min(p * 3, 1.0) if finite(p) else math.nan,
                    "cliffs_delta_a_minus_b": delta,
                }
            )
    return out


def tests_by_dimension(dim_rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    kruskal_out: list[dict[str, Any]] = []
    pairwise_out: list[dict[str, Any]] = []
    for dim in sorted({row["ambiguity_dimension"] for row in dim_rows}):
        subset = [row for row in dim_rows if row["ambiguity_dimension"] == dim]
        for item in kruskal_tests(subset):
            item["ambiguity_dimension"] = dim
            kruskal_out.append(item)
        for item in pairwise_tests(subset):
            item["ambiguity_dimension"] = dim
            pairwise_out.append(item)
    return kruskal_out, pairwise_out


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("")
        return
    with path.open("w", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def write_xlsx(path: Path, sheets: dict[str, list[dict[str, Any]]]) -> None:
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for name, rows in sheets.items():
        ws = wb.create_sheet(name[:31])
        if not rows:
            continue
        headers = list(rows[0].keys())
        ws.append(headers)
        for row in rows:
            values = [row.get(header) for header in headers]
            ws.append([
                ILLEGAL_CHARACTERS_RE.sub("", value)
                if isinstance(value, str) else value
                for value in values
            ])
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)


def write_summary(path: Path, rows: list[dict[str, Any]], by_identity: list[dict[str, Any]], by_run_identity: list[dict[str, Any]], by_dim_identity: list[dict[str, Any]], kruskal_global: list[dict[str, Any]], kruskal_dim: list[dict[str, Any]]) -> None:
    lines = [
        "# Performance Analysis",
        "",
        f"Rows analyzed: {len(rows)}",
        "",
        "## Metric Definitions",
        "",
        "| Metric | Formula / Source | What It Measures | Notes |",
        "|---|---|---|---|",
        "| e2e_success | `1[eval.e2e_success]` | Whether all evaluator checks passed. | Primary task-performance outcome. |",
        "| score | JSONL `eval.score` | Fractional evaluator score. | Usually passed_checks / total_checks. |",
        "| check_pass_rate | `passed_checks / total_checks` | Check-level pass fraction. | Useful when tasks contain multiple checks. |",
        "| action_precision_match | `1[action_precision.match]` | Whether executed action count/anchors match expected action count/anchors. | Only action precision, not full task success. |",
        "| over_action | `1[exec_count > gt_count]` | Whether the agent executed too many action anchors. | Same definition as behavior analysis. |",
        "| under_action | `1[exec_count < gt_count]` | Whether the agent executed too few action anchors. | Same definition as behavior analysis. |",
        "| correction_recovery | `1[final e2e_success after correction]` | Whether a trajectory that received correction ultimately succeeded. | Undefined for tasks with no correction turn. |",
        "| correction_required_rate | `1[correction_turns > 0]` | How often the trajectory needed oracle correction. | Operational/performance hybrid indicator. |",
        "",
        "## By Identity",
        "",
        "| Identity | n | Success | Score | Action precision | Over-action | Under-action | Correction required | Correction recovery |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in by_identity:
        lines.append(
            "| {identity} | {n} | {success:.3f} | {score:.3f} | {ap:.3f} | {over:.3f} | {under:.3f} | {corr_req:.3f} | {corr_rec:.3f} |".format(
                identity=row["identity"],
                n=row["n"],
                success=row["e2e_success_mean"],
                score=row["score_mean"],
                ap=row["action_precision_match_mean"],
                over=row["over_action_mean"],
                under=row["under_action_mean"],
                corr_req=row["correction_required_rate"],
                corr_rec=row["correction_recovery_mean"],
            )
        )

    lines += [
        "",
        "## By Run And Identity",
        "",
        "| Run | Identity | n | Success | Score | Action precision | Correction required | Correction recovery |",
        "|---:|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in by_run_identity:
        lines.append(
            "| {run} | {identity} | {n} | {success:.3f} | {score:.3f} | {ap:.3f} | {corr_req:.3f} | {corr_rec:.3f} |".format(
                run=row["run"],
                identity=row["identity"],
                n=row["n"],
                success=row["e2e_success_mean"],
                score=row["score_mean"],
                ap=row["action_precision_match_mean"],
                corr_req=row["correction_required_rate"],
                corr_rec=row["correction_recovery_mean"],
            )
        )

    lines += [
        "",
        "## By Ambiguity Dimension And Identity",
        "",
        "| Dimension | Identity | n | Success | Score | Action precision | Over-action | Under-action | Correction recovery |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in by_dim_identity:
        lines.append(
            "| {dim} | {identity} | {n} | {success:.3f} | {score:.3f} | {ap:.3f} | {over:.3f} | {under:.3f} | {corr_rec:.3f} |".format(
                dim=row["ambiguity_dimension"],
                identity=row["identity"],
                n=row["n"],
                success=row["e2e_success_mean"],
                score=row["score_mean"],
                ap=row["action_precision_match_mean"],
                over=row["over_action_mean"],
                under=row["under_action_mean"],
                corr_rec=row["correction_recovery_mean"],
            )
        )

    lines += [
        "",
        "## Kruskal-Wallis By Performance Metric",
        "",
        "| Metric | H | p |",
        "|---|---:|---:|",
    ]
    for row in kruskal_global:
        lines.append(f"| {row['metric']} | {row['h_statistic']:.6g} | {row['p_value']:.6g} |")

    sig_dim = [row for row in kruskal_dim if finite(row.get("p_value")) and row["p_value"] < 0.05]
    lines += [
        "",
        "## Dimension-Level Significant Kruskal Results (p < .05)",
        "",
        "| Dimension | Metric | H | p |",
        "|---|---|---:|---:|",
    ]
    for row in sig_dim:
        lines.append(f"| {row['ambiguity_dimension']} | {row['metric']} | {row['h_statistic']:.6g} | {row['p_value']:.6g} |")

    path.write_text("\n".join(lines) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("rep_dir", type=Path)
    parser.add_argument("--out-dir", type=Path, default=None)
    args = parser.parse_args()

    out_dir = args.out_dir or (args.rep_dir / "performance_analysis")
    records = load_records(args.rep_dir)
    rows = [per_task_row(record) for record in records]
    dim_rows = explode_dimensions(rows)

    by_identity = aggregate(rows, ["identity"])
    by_run_identity = aggregate(rows, ["run", "identity"])
    by_domain_identity = aggregate(rows, ["domain", "identity"])
    by_dim_identity = aggregate(dim_rows, ["ambiguity_dimension", "identity"])
    kruskal_global = kruskal_tests(rows)
    pairwise_global = pairwise_tests(rows)
    kruskal_dim, pairwise_dim = tests_by_dimension(dim_rows)

    sheets = {
        "per_task": rows,
        "by_identity": by_identity,
        "by_run_identity": by_run_identity,
        "by_domain_identity": by_domain_identity,
        "by_dimension_identity": by_dim_identity,
        "kruskal_global": kruskal_global,
        "pairwise_global": pairwise_global,
        "kruskal_by_dimension": kruskal_dim,
        "pairwise_by_dimension": pairwise_dim,
    }

    out_dir.mkdir(parents=True, exist_ok=True)
    for name, sheet_rows in sheets.items():
        write_csv(out_dir / f"{name}.csv", sheet_rows)
    write_xlsx(out_dir / "performance_analysis.xlsx", sheets)
    write_summary(out_dir / "performance_summary.md", rows, by_identity, by_run_identity, by_dim_identity, kruskal_global, kruskal_dim)

    print(f"records={len(rows)}")
    print(f"out_dir={out_dir}")
    for row in by_identity:
        print(
            f"{row['identity']}: success={row['e2e_success_mean']:.3f}, "
            f"score={row['score_mean']:.3f}, "
            f"action_precision={row['action_precision_match_mean']:.3f}, "
            f"correction_recovery={row['correction_recovery_mean']:.3f}"
        )


if __name__ == "__main__":
    main()
