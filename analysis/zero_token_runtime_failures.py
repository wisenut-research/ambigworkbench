#!/usr/bin/env python3
"""Summarize zero-token runtime/telemetry failures in experiment JSONL files."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


RUNTIME_ERROR_MARKERS = (
    "timed out",
    "exit 137",
    "no transcript",
    "transcript not found",
    "agent run failed",
)


def jsonl_for(run_dir: Path) -> Path:
    files = sorted(run_dir.glob("*.jsonl"))
    if len(files) != 1:
        raise SystemExit(f"expected exactly one JSONL in {run_dir}, found {len(files)}")
    return files[0]


def is_zero_token_runtime_failure(record: dict[str, Any]) -> bool:
    error = str(record.get("error") or "").lower()
    total_tokens = int(record.get("total_tokens") or 0)
    return total_tokens == 0 and any(marker in error for marker in RUNTIME_ERROR_MARKERS)


def runtime_cause(record: dict[str, Any]) -> str:
    error = str(record.get("error") or "").lower()
    if "exit 137" in error:
        return "exit 137"
    if "timed out" in error:
        return "timeout"
    if "no transcript" in error or "transcript not found" in error:
        return "missing transcript"
    if "agent run failed" in error:
        return "agent run failed"
    return "other runtime"


def domain_of(record: dict[str, Any]) -> str:
    return str(record.get("domain") or record.get("complexity") or "?")


def load_records(run_dirs: list[Path]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for run_dir in run_dirs:
        jsonl = jsonl_for(run_dir)
        run_name = run_dir.name
        for line_no, line in enumerate(jsonl.read_text(errors="ignore").splitlines(), 1):
            if not line.strip():
                continue
            record = json.loads(line)
            record["_run_name"] = run_name
            record["_line_no"] = line_no
            records.append(record)
    return records


def avg_tokens(records: list[dict[str, Any]]) -> float:
    if not records:
        return 0.0
    return sum(int(record.get("total_tokens") or 0) for record in records) / len(records)


def summarize(records: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    by_agent: list[dict[str, Any]] = []
    by_run_agent: list[dict[str, Any]] = []
    by_domain_agent: list[dict[str, Any]] = []

    agents = sorted({str(record.get("soul_id") or "?") for record in records})
    runs = sorted({str(record.get("_run_name") or "?") for record in records})
    domains = sorted({domain_of(record) for record in records})

    for agent in agents:
        agent_records = [record for record in records if record.get("soul_id") == agent]
        zero_records = [record for record in agent_records if is_zero_token_runtime_failure(record)]
        filtered = [record for record in agent_records if not is_zero_token_runtime_failure(record)]
        failures = [record for record in agent_records if not (record.get("eval") or {}).get("e2e_success")]
        filtered_failures = [record for record in failures if not is_zero_token_runtime_failure(record)]
        successes = [record for record in agent_records if (record.get("eval") or {}).get("e2e_success")]
        causes = Counter(runtime_cause(record) for record in zero_records)
        by_agent.append(
            {
                "agent": agent,
                "total_rows": len(agent_records),
                "zero_token_runtime_failures": len(zero_records),
                "zero_token_runtime_failure_rate": len(zero_records) / len(agent_records) if agent_records else 0.0,
                "causes": "; ".join(f"{key}:{causes[key]}" for key in sorted(causes)) or "-",
                "raw_avg_total_tokens": avg_tokens(agent_records),
                "filtered_avg_total_tokens": avg_tokens(filtered),
                "raw_failed_avg_total_tokens": avg_tokens(failures),
                "filtered_failed_avg_total_tokens": avg_tokens(filtered_failures),
                "success_avg_total_tokens": avg_tokens(successes),
            }
        )

    for run in runs:
        for agent in agents:
            subset = [
                record
                for record in records
                if record.get("_run_name") == run and record.get("soul_id") == agent
            ]
            zero_records = [record for record in subset if is_zero_token_runtime_failure(record)]
            causes = Counter(runtime_cause(record) for record in zero_records)
            by_run_agent.append(
                {
                    "run": run,
                    "agent": agent,
                    "total_rows": len(subset),
                    "zero_token_runtime_failures": len(zero_records),
                    "zero_token_runtime_failure_rate": len(zero_records) / len(subset) if subset else 0.0,
                    "causes": "; ".join(f"{key}:{causes[key]}" for key in sorted(causes)) or "-",
                }
            )

    for domain in domains:
        for agent in agents:
            subset = [
                record
                for record in records
                if domain_of(record) == domain and record.get("soul_id") == agent
            ]
            zero_records = [record for record in subset if is_zero_token_runtime_failure(record)]
            if zero_records:
                by_domain_agent.append(
                    {
                        "domain": domain,
                        "agent": agent,
                        "total_rows": len(subset),
                        "zero_token_runtime_failures": len(zero_records),
                        "zero_token_runtime_failure_rate": len(zero_records) / len(subset) if subset else 0.0,
                    }
                )

    return by_agent, by_run_agent, by_domain_agent


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0].keys()) if rows else []
    with path.open("w", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def fmt_pct(value: float) -> str:
    return f"{value * 100:.3f}%"


def write_markdown(path: Path, by_agent: list[dict[str, Any]], by_run_agent: list[dict[str, Any]], by_domain_agent: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Zero-Token Runtime/Telemetry Failures",
        "",
        "Rows counted here satisfy `total_tokens == 0` and have a runtime-style error such as timeout, exit 137, or missing transcript telemetry.",
        "",
        "## By Agent",
        "",
        "| Agent | Rows | Zero-token runtime failures | Rate | Causes | Raw avg tokens | Filtered avg tokens | Raw failed avg | Filtered failed avg | Success avg |",
        "|---|---:|---:|---:|---|---:|---:|---:|---:|---:|",
    ]
    for row in by_agent:
        lines.append(
            "| {agent} | {total_rows} | {zero_token_runtime_failures} | {rate} | {causes} | {raw:.1f} | {filtered:.1f} | {raw_fail:.1f} | {filtered_fail:.1f} | {succ:.1f} |".format(
                agent=row["agent"],
                total_rows=row["total_rows"],
                zero_token_runtime_failures=row["zero_token_runtime_failures"],
                rate=fmt_pct(row["zero_token_runtime_failure_rate"]),
                causes=row["causes"],
                raw=row["raw_avg_total_tokens"],
                filtered=row["filtered_avg_total_tokens"],
                raw_fail=row["raw_failed_avg_total_tokens"],
                filtered_fail=row["filtered_failed_avg_total_tokens"],
                succ=row["success_avg_total_tokens"],
            )
        )
    lines += [
        "",
        "## By Run And Agent",
        "",
        "| Run | Agent | Rows | Zero-token runtime failures | Rate | Causes |",
        "|---|---|---:|---:|---:|---|",
    ]
    for row in by_run_agent:
        lines.append(
            f"| {row['run']} | {row['agent']} | {row['total_rows']} | {row['zero_token_runtime_failures']} | {fmt_pct(row['zero_token_runtime_failure_rate'])} | {row['causes']} |"
        )
    lines += [
        "",
        "## Nonzero Domain Cells",
        "",
        "| Domain | Agent | Rows | Zero-token runtime failures | Rate |",
        "|---|---|---:|---:|---:|",
    ]
    for row in by_domain_agent:
        lines.append(
            f"| {row['domain']} | {row['agent']} | {row['total_rows']} | {row['zero_token_runtime_failures']} | {fmt_pct(row['zero_token_runtime_failure_rate'])} |"
        )
    path.write_text("\n".join(lines) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dirs", nargs="+", type=Path)
    parser.add_argument("--out-dir", type=Path, default=None)
    args = parser.parse_args()

    records = load_records(args.run_dirs)
    by_agent, by_run_agent, by_domain_agent = summarize(records)

    total_zero = sum(is_zero_token_runtime_failure(record) for record in records)
    print(f"total_rows={len(records)}")
    print(f"zero_token_runtime_failures={total_zero}")
    print(f"zero_token_runtime_failure_rate={fmt_pct(total_zero / len(records) if records else 0.0)}")
    print()
    for row in by_agent:
        print(
            f"{row['agent']}: {row['zero_token_runtime_failures']}/{row['total_rows']} "
            f"({fmt_pct(row['zero_token_runtime_failure_rate'])}), causes={row['causes']}"
        )

    if args.out_dir:
        write_csv(args.out_dir / "zero_token_runtime_failures_by_agent.csv", by_agent)
        write_csv(args.out_dir / "zero_token_runtime_failures_by_run_agent.csv", by_run_agent)
        write_csv(args.out_dir / "zero_token_runtime_failures_by_domain_agent.csv", by_domain_agent)
        write_markdown(args.out_dir / "zero_token_runtime_failures_summary.md", by_agent, by_run_agent, by_domain_agent)


if __name__ == "__main__":
    main()
