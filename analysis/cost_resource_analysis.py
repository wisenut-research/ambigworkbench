#!/usr/bin/env python3
"""Cost/resource analysis for cumulative Ambig OfficeBench runs."""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
from collections import Counter, defaultdict
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

RESOURCE_METRICS = [
    "total_tokens",
    "agent_tokens",
    "oracle_tokens",
    "oracle_clarification_tokens",
    "oracle_correction_tokens",
    "input_tokens",
    "output_tokens",
    "first_turn_input_tokens",
    "total_turns",
    "correction_turns",
    "e2e_latency_ms",
]

MAIN_COST_COLUMNS = [
    "n",
    "success_count",
    "failure_count",
    "success_rate",
    "total_tokens_sum",
    "successful_tokens_sum",
    "failed_tokens_sum",
    "failed_token_share",
    "tokens_per_success",
]

APPENDIX_ROBUSTNESS_COLUMNS = [
    "n",
    "total_tokens_mean",
    "total_tokens_median",
    "total_tokens_p95",
    "agent_tokens_sum",
    "oracle_tokens_sum",
    "oracle_clarification_tokens_sum",
    "oracle_correction_tokens_sum",
    "input_tokens_sum",
    "input_tokens_mean",
    "output_tokens_sum",
    "output_tokens_mean",
    "first_turn_input_tokens_mean",
    "first_turn_input_tokens_median",
    "first_turn_input_tokens_p95",
    "oracle_tokens_mean",
    "e2e_latency_ms_mean",
    "e2e_latency_ms_median",
    "e2e_latency_ms_p95",
    "zero_token_runtime_failures",
    "zero_token_runtime_failure_rate",
]

RUNTIME_ERROR_MARKERS = (
    "timed out",
    "exit 137",
    "no transcript",
    "transcript not found",
    "agent run failed",
)


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


def percentile(values: list[float], q: float) -> float:
    values = sorted(float(value) for value in values if finite(value))
    if not values:
        return math.nan
    pos = (len(values) - 1) * q
    lo = math.floor(pos)
    hi = math.ceil(pos)
    if lo == hi:
        return values[int(pos)]
    return values[lo] * (hi - pos) + values[hi] * (pos - lo)


def is_zero_token_runtime_failure(record: dict[str, Any]) -> bool:
    error = str(record.get("error") or "").lower()
    total_tokens = int(record.get("total_tokens") or 0)
    return total_tokens == 0 and any(marker in error for marker in RUNTIME_ERROR_MARKERS)


def first_turn_input(record: dict[str, Any]) -> int:
    turns = record.get("turns") or []
    if not turns:
        return 0
    return int(turns[0].get("input_tokens") or 0)


def first_turn_output(record: dict[str, Any]) -> int:
    turns = record.get("turns") or []
    if not turns:
        return 0
    return int(turns[0].get("output_tokens") or 0)


def per_task_row(record: dict[str, Any]) -> dict[str, Any]:
    eval_data = record.get("eval") or {}
    total_tokens = int(record.get("total_tokens") or 0)
    agent_tokens = int(record.get("agent_tokens") or (int(record.get("total_input_tokens") or 0) + int(record.get("total_output_tokens") or 0)))
    oracle_tokens = int(record.get("oracle_tokens") or 0)
    oracle_clarification_tokens = (
        int(record.get("oracle_clarify_input_tokens") or 0)
        + int(record.get("oracle_clarify_output_tokens") or 0)
    )
    oracle_correction_tokens = (
        int(record.get("oracle_correct_input_tokens") or 0)
        + int(record.get("oracle_correct_output_tokens") or 0)
    )
    success = bool(eval_data.get("e2e_success"))
    return {
        "run": int(record.get("_run") or 0),
        "soul_id": record.get("soul_id"),
        "identity": SOUL_LABELS.get(record.get("soul_id"), record.get("soul_id")),
        "task_id": record.get("task_id"),
        "domain": record.get("domain"),
        "ambiguity_level": record.get("ambiguity_level"),
        "ambiguity_dimensions": "|".join(str(dim) for dim in (record.get("ambiguity_dimensions") or [])),
        "e2e_success": success,
        "completed": bool(record.get("completed")),
        "error": record.get("error") or "",
        "zero_token_runtime_failure": is_zero_token_runtime_failure(record),
        "total_tokens": total_tokens,
        "agent_tokens": agent_tokens,
        "oracle_tokens": oracle_tokens,
        "oracle_clarification_tokens": oracle_clarification_tokens,
        "oracle_correction_tokens": oracle_correction_tokens,
        "input_tokens": int(record.get("total_input_tokens") or 0),
        "output_tokens": int(record.get("total_output_tokens") or 0),
        "first_turn_input_tokens": first_turn_input(record),
        "first_turn_output_tokens": first_turn_output(record),
        "total_turns": int(record.get("total_turns") or 0),
        "clarification_turns": int(record.get("clarification_turns") or 0),
        "correction_turns": int(record.get("correction_turns") or 0),
        "e2e_latency_ms": int(record.get("e2e_latency_ms") or 0),
        "failed_trajectory_tokens": 0 if success else total_tokens,
        "successful_trajectory_tokens": total_tokens if success else 0,
    }


def aggregate(rows: list[dict[str, Any]], group_keys: list[str]) -> list[dict[str, Any]]:
    grouped: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[tuple(row.get(key) for key in group_keys)].append(row)

    out: list[dict[str, Any]] = []
    for key, subset in sorted(grouped.items(), key=lambda item: tuple(str(x) for x in item[0])):
        item = dict(zip(group_keys, key))
        successes = [row for row in subset if row["e2e_success"]]
        failures = [row for row in subset if not row["e2e_success"]]
        total_tokens = sum(row["total_tokens"] for row in subset)
        successful_tokens = sum(row["total_tokens"] for row in successes)
        failed_tokens = sum(row["total_tokens"] for row in failures)
        item.update(
            {
                "n": len(subset),
                "success_count": len(successes),
                "failure_count": len(failures),
                "success_rate": len(successes) / len(subset) if subset else math.nan,
                "zero_token_runtime_failures": sum(1 for row in subset if row["zero_token_runtime_failure"]),
                "zero_token_runtime_failure_rate": sum(1 for row in subset if row["zero_token_runtime_failure"]) / len(subset) if subset else math.nan,
                "total_tokens_sum": total_tokens,
                "successful_tokens_sum": successful_tokens,
                "failed_tokens_sum": failed_tokens,
                "failed_token_share": failed_tokens / total_tokens if total_tokens else math.nan,
                "tokens_per_success": total_tokens / len(successes) if successes else math.nan,
            }
        )
        for metric in RESOURCE_METRICS:
            vals = [row[metric] for row in subset if finite(row.get(metric))]
            success_vals = [row[metric] for row in successes if finite(row.get(metric))]
            failure_vals = [row[metric] for row in failures if finite(row.get(metric))]
            item[f"{metric}_sum"] = sum(vals) if vals else 0
            item[f"{metric}_mean"] = mean(vals)
            item[f"{metric}_median"] = median(vals)
            item[f"{metric}_p95"] = percentile(vals, 0.95)
            item[f"{metric}_success_mean"] = mean(success_vals)
            item[f"{metric}_failure_mean"] = mean(failure_vals)
        out.append(item)
    return out


def select_columns(rows: list[dict[str, Any]], group_keys: list[str], columns: list[str]) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for row in rows:
        selected.append({key: row.get(key) for key in [*group_keys, *columns]})
    return selected


def kruskal_tests(rows: list[dict[str, Any]], group_key: str = "identity") -> list[dict[str, Any]]:
    groups = sorted({row[group_key] for row in rows})
    out: list[dict[str, Any]] = []
    for metric in RESOURCE_METRICS:
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
    for metric in RESOURCE_METRICS:
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


def write_summary(path: Path, rows: list[dict[str, Any]], by_identity: list[dict[str, Any]], by_run_identity: list[dict[str, Any]], tests: list[dict[str, Any]]) -> None:
    lines = [
        "# Cost / Resource Analysis",
        "",
        f"Rows analyzed: {len(rows)}",
        "",
        "## Metric Definitions",
        "",
        "| Metric | Formula / Source | What It Measures | Notes |",
        "|---|---|---|---|",
        "| total_token_expenditure | `sum(total_tokens)` | Total recorded token budget spent by a condition. | Main cost metric. Runtime failures with missing telemetry can make this a lower bound. |",
        "| failed_token_share | `sum(tokens for failed tasks) / sum(total_tokens)` | Fraction of recorded token budget spent on unsuccessful trajectories. | Main cost metric. Separates productive from unproductive computation. |",
        "| tokens_per_success | `sum(total_tokens) / success_count` | Aggregate token cost per successful task. | Undefined when success count is zero. |",
        "| input/output token split | JSONL `total_input_tokens`, `total_output_tokens` | Whether cost comes from context/prompt burden or generation verbosity. | Appendix robustness metric. |",
        "| first_turn_input_tokens | first turn `input_tokens` | Initial prompt/context size for each task. | Appendix robustness metric; useful proxy for memory context pressure. |",
        "| agent/oracle split | JSONL `agent_tokens`, `oracle_tokens` | Separates evaluated-agent inference from clarification/correction oracle inference. | Appendix robustness metric. |",
        "| oracle clarification/correction split | JSONL oracle token subfields | Separates pre-action clarification from post-action correction feedback. | Appendix robustness metric. |",
        "| e2e_latency_ms | JSONL `e2e_latency_ms` | Wall-clock end-to-end trajectory time. | Appendix robustness metric; affected by GPU load, network, vLLM queueing, and context length. |",
        "| zero_token_runtime_failure_rate | `zero-token runtime failures / n` | Share of trajectories with missing token telemetry after runtime failure. | Appendix robustness metric and limitation check. |",
        "",
        "## Main Cost Analysis By Identity",
        "",
        "| Identity | n | Success rate | Total token expenditure | Successful-trajectory tokens | Failed-trajectory tokens | Failed token share | Tokens / success |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in by_identity:
        lines.append(
            "| {identity} | {n} | {succ:.3f} | {total:.0f} | {successful:.0f} | {failed:.0f} | {fts:.3f} | {tps:.1f} |".format(
                identity=row["identity"],
                n=row["n"],
                succ=row["success_rate"],
                total=row["total_tokens_sum"],
                successful=row["successful_tokens_sum"],
                failed=row["failed_tokens_sum"],
                tps=row["tokens_per_success"],
                fts=row["failed_token_share"],
            )
        )

    lines += [
        "",
        "## Main Cost Analysis By Run And Identity",
        "",
        "| Run | Identity | n | Success rate | Total token expenditure | Failed token share | Tokens / success |",
        "|---:|---|---:|---:|---:|---:|---:|",
    ]
    for row in by_run_identity:
        lines.append(
            "| {run} | {identity} | {n} | {succ:.3f} | {total:.0f} | {fts:.3f} | {tps:.1f} |".format(
                run=row["run"],
                identity=row["identity"],
                n=row["n"],
                succ=row["success_rate"],
                total=row["total_tokens_sum"],
                fts=row["failed_token_share"],
                tps=row["tokens_per_success"],
            )
        )

    lines += [
        "",
        "## Appendix Robustness By Identity",
        "",
        "| Condition | Total tokens mean / median / p95 | Agent tokens sum | Oracle tokens sum | Oracle clarify / correct | Input / output tokens | First-turn input mean | Latency mean / p95 ms | Zero-token runtime failure rate |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in by_identity:
        lines.append(
            "| {identity} | {total_mean:.1f} / {total_median:.1f} / {total_p95:.1f} | {agent_sum:.0f} | {oracle_sum:.0f} | {oracle_clarify:.0f} / {oracle_correct:.0f} | {input_sum:.0f} / {output_sum:.0f} | {first:.1f} | {lat:.1f} / {lat_p95:.1f} | {zrate:.3f} |".format(
                identity=row["identity"],
                total_mean=row["total_tokens_mean"],
                total_median=row["total_tokens_median"],
                total_p95=row["total_tokens_p95"],
                agent_sum=row["agent_tokens_sum"],
                input_sum=row["input_tokens_sum"],
                output_sum=row["output_tokens_sum"],
                first=row["first_turn_input_tokens_mean"],
                oracle_sum=row["oracle_tokens_sum"],
                oracle_clarify=row["oracle_clarification_tokens_sum"],
                oracle_correct=row["oracle_correction_tokens_sum"],
                lat=row["e2e_latency_ms_mean"],
                lat_p95=row["e2e_latency_ms_p95"],
                zrate=row["zero_token_runtime_failure_rate"],
            )
        )

    lines += [
        "",
        "## Kruskal-Wallis By Resource Metric",
        "",
        "| Metric | H | p |",
        "|---|---:|---:|",
    ]
    for row in tests:
        lines.append(f"| {row['metric']} | {row['h_statistic']:.6g} | {row['p_value']:.6g} |")
    path.write_text("\n".join(lines) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("rep_dir", type=Path)
    parser.add_argument("--out-dir", type=Path, default=None)
    args = parser.parse_args()

    out_dir = args.out_dir or (args.rep_dir / "cost_resource_analysis")
    records = load_records(args.rep_dir)
    rows = [per_task_row(record) for record in records]
    by_identity = aggregate(rows, ["identity"])
    by_run_identity = aggregate(rows, ["run", "identity"])
    by_domain_identity = aggregate(rows, ["domain", "identity"])
    main_cost_by_identity = select_columns(by_identity, ["identity"], MAIN_COST_COLUMNS)
    main_cost_by_run_identity = select_columns(by_run_identity, ["run", "identity"], MAIN_COST_COLUMNS)
    appendix_robustness_by_identity = select_columns(by_identity, ["identity"], APPENDIX_ROBUSTNESS_COLUMNS)
    appendix_robustness_by_run_identity = select_columns(by_run_identity, ["run", "identity"], APPENDIX_ROBUSTNESS_COLUMNS)
    kruskal_global = kruskal_tests(rows)
    pairwise_global = pairwise_tests(rows)

    sheets = {
        "per_task": rows,
        "main_cost_by_identity": main_cost_by_identity,
        "main_cost_by_run_identity": main_cost_by_run_identity,
        "appendix_robustness_by_identity": appendix_robustness_by_identity,
        "appendix_robustness_by_run_identity": appendix_robustness_by_run_identity,
        "by_identity": by_identity,
        "by_run_identity": by_run_identity,
        "by_domain_identity": by_domain_identity,
        "kruskal_global": kruskal_global,
        "pairwise_global": pairwise_global,
    }

    out_dir.mkdir(parents=True, exist_ok=True)
    for name, sheet_rows in sheets.items():
        write_csv(out_dir / f"{name}.csv", sheet_rows)
    write_xlsx(out_dir / "cost_resource_analysis.xlsx", sheets)
    write_summary(out_dir / "cost_resource_summary.md", rows, by_identity, by_run_identity, kruskal_global)

    print(f"records={len(rows)}")
    print(f"out_dir={out_dir}")
    for row in by_identity:
        print(
            f"{row['identity']}: total_tokens_mean={row['total_tokens_mean']:.1f}, "
            f"tokens_per_success={row['tokens_per_success']:.1f}, "
            f"failed_token_share={row['failed_token_share']:.3f}, "
            f"zero_runtime={row['zero_token_runtime_failures']}"
        )


if __name__ == "__main__":
    main()
