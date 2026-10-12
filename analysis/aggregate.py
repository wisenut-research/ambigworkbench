"""
aggregate.py

Aggregate experiment JSONL results into domain x ambiguity_level x soul reports.

Outputs:
  - console tables (pretty-print)
  - {results_file}.summary.json  (detailed aggregates)
  - {results_file}.summary.csv   (spreadsheet)
  - {results_file}.summary.xlsx  (Excel incl. Exp_summ sheet)

Usage:
    python experiment/analysis/aggregate.py --results experiment/results/<run_id>.jsonl
    python analysis/aggregate.py --results-dir results/  # merge all
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Load & group
# ---------------------------------------------------------------------------

def load_records(paths: list[Path]) -> list[dict]:
    records = []
    for p in paths:
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return records


def group_key(r: dict) -> tuple:
    """Group by (domain, ambiguity_level, soul_id)."""
    return (
        r.get("domain", "unknown"),
        r.get("ambiguity_level", 0),
        r.get("soul_id", "unknown"),
    )


# ---------------------------------------------------------------------------
# Aggregate one group of records
# ---------------------------------------------------------------------------

def aggregate_group(records: list[dict]) -> dict[str, Any]:
    n = len(records)

    total_input   = sum(r.get("total_input_tokens", 0) for r in records)
    total_output  = sum(r.get("total_output_tokens", 0) for r in records)
    total_cache   = sum(r.get("total_cache_read_tokens", 0) for r in records)
    agent_tokens  = sum(
        r.get("agent_tokens", r.get("total_input_tokens", 0) + r.get("total_output_tokens", 0))
        for r in records
    )

    oracle_clarify_tokens = sum(
        r.get("oracle_clarify_input_tokens", 0) + r.get("oracle_clarify_output_tokens", 0)
        for r in records
    )
    oracle_correct_tokens = sum(
        r.get("oracle_correct_input_tokens", 0) + r.get("oracle_correct_output_tokens", 0)
        for r in records
    )
    oracle_tokens = oracle_clarify_tokens + oracle_correct_tokens
    total_tokens  = sum(r.get("total_tokens", 0) for r in records)

    eval_scores   = [r["eval"]["score"] if r.get("eval") and r["eval"].get("total_checks", 0) > 0 else 0.0 for r in records]
    e2e_successes = sum(1 for r in records if r.get("eval") and r["eval"].get("e2e_success"))

    ap_applicable = [r for r in records if r.get("action_precision", {}).get("applicable", False)]
    ap_applicable_count = len(ap_applicable)
    over_action_count = sum(
        1 for r in ap_applicable
        if r["action_precision"].get("exec_count", 0) > r["action_precision"].get("gt_count", 0)
    )
    # action_precision_rate: share of successful tasks with exact action precision
    ap_success = [r for r in ap_applicable if r.get("eval") and r["eval"].get("e2e_success")]
    ap_match_count = sum(1 for r in ap_success if r.get("action_precision", {}).get("match", False))
    ap_success_count = len(ap_success)

    clarify_tasks    = sum(1 for r in records if r.get("clarification_turns", 0) > 0)
    correction_tasks = sum(1 for r in records if r.get("correction_turns", 0) > 0)

    all_turns              = [r.get("total_turns", 0) for r in records]
    all_clarify_turns      = [r.get("clarification_turns", 0) for r in records]
    all_correct_turns      = [r.get("correction_turns", 0) for r in records]
    all_agent_tok_per      = [
        r.get("agent_tokens", r.get("total_input_tokens", 0) + r.get("total_output_tokens", 0))
        for r in records
    ]
    all_oracle_tok_per     = [r.get("oracle_tokens", 0) for r in records]
    all_total_tok_per      = [r.get("total_tokens", 0) for r in records]
    all_latency            = [r.get("e2e_latency_ms", 0) for r in records if r.get("e2e_latency_ms", 0) > 0]

    def _avg(lst):
        return round(statistics.mean(lst), 2) if lst else 0.0

    def _std(lst):
        return round(statistics.stdev(lst), 2) if len(lst) >= 2 else 0.0

    def _iqr_outlier_n(lst) -> int:
        if len(lst) < 4:
            return 0
        sorted_lst = sorted(lst)
        q1 = statistics.median(sorted_lst[:len(sorted_lst)//2])
        q3 = statistics.median(sorted_lst[(len(sorted_lst)+1)//2:])
        fence = q3 + 1.5 * (q3 - q1)
        return sum(1 for v in lst if v > fence)

    return {
        "tasks":                      n,
        # agent tokens
        "input_tokens":               total_input,
        "output_tokens":              total_output,
        "cache_read_tokens":          total_cache,
        "agent_tokens":               agent_tokens,
        # oracle tokens (clarification vs. correction split)
        "oracle_clarify_tokens":      oracle_clarify_tokens,
        "oracle_correct_tokens":      oracle_correct_tokens,
        "oracle_tokens":              oracle_tokens,
        # total cost
        "total_tokens":               total_tokens,
        # evaluation metrics
        "avg_eval_score":             round(sum(eval_scores) / n, 3) if n else 0.0,
        "e2e_success_count":          e2e_successes,
        "success_rate":               round(e2e_successes / n, 3) if n else 0.0,
        "action_precision_applicable": ap_applicable_count,
        "action_precision_match_count": ap_match_count,
        "action_precision_rate":      round(ap_match_count / ap_success_count, 3) if ap_success_count else 0.0,
        "over_action_count":          over_action_count,
        "over_action_rate":           round(over_action_count / ap_applicable_count, 3) if ap_applicable_count else 0.0,
        "clarify_tasks":              clarify_tasks,
        "clarify_rate":               round(clarify_tasks / n, 3) if n else 0.0,
        "correction_tasks":           correction_tasks,
        "correction_rate":            round(correction_tasks / n, 3) if n else 0.0,
        "avg_turns":                  _avg(all_turns),
        "avg_clarification_turns":    _avg(all_clarify_turns),
        "avg_correction_turns":       _avg(all_correct_turns),
        "avg_agent_tokens_per_task":  _avg(all_agent_tok_per),
        "avg_oracle_tokens_per_task": _avg(all_oracle_tok_per),
        "avg_total_tokens_per_task":  _avg(all_total_tok_per),
        "avg_e2e_latency_ms":         _avg(all_latency),
        # total_tokens distribution
        "total_tokens_median":        round(statistics.median(all_total_tok_per), 2) if all_total_tok_per else 0.0,
        "total_tokens_std":           _std(all_total_tok_per),
        "total_tokens_max":           max(all_total_tok_per) if all_total_tok_per else 0,
        "total_tokens_iqr_outlier_n": _iqr_outlier_n(all_total_tok_per),
    }


# ---------------------------------------------------------------------------
# Build full summary dict
# ---------------------------------------------------------------------------

SOUL_ORDER = ["soul-a", "soul-b", "soul-c"]

def build_summary(records: list[dict]) -> dict:
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for r in records:
        groups[group_key(r)].append(r)

    rows = []
    for (domain, level, soul), grp in sorted(groups.items()):
        row = {"domain": domain, "ambiguity_level": level, "soul_id": soul}
        row.update(aggregate_group(grp))
        rows.append(row)

    return {"total_records": len(records), "groups": rows}


# ---------------------------------------------------------------------------
# Pretty-print
# ---------------------------------------------------------------------------

_COL_WIDTHS = {
    "domain":                      22,
    "ambiguity_level":              5,
    "soul_id":                     10,
    "tasks":                        6,
    "input_tokens":                12,
    "output_tokens":               12,
    "cache_read_tokens":           12,
    "agent_tokens":                12,
    "oracle_clarify_tokens":       14,
    "oracle_correct_tokens":       14,
    "oracle_tokens":               12,
    "total_tokens":                12,
    "avg_eval_score":               9,
    "e2e_success_count":            8,
    "success_rate":                 8,
    "action_precision_applicable":  14,
    "action_precision_match_count": 14,
    "action_precision_rate":        12,
    "over_action_count":            14,
    "over_action_rate":             14,
    "clarify_tasks":                9,
    "clarify_rate":                 9,
    "correction_tasks":            10,
    "correction_rate":             10,
    "avg_turns":                    9,
    "avg_clarification_turns":     12,
    "avg_correction_turns":        12,
    "avg_agent_tokens_per_task":   16,
    "avg_oracle_tokens_per_task":  17,
    "avg_total_tokens_per_task":   16,
    "avg_e2e_latency_ms":          16,
    "total_tokens_median":         18,
    "total_tokens_std":            16,
    "total_tokens_max":            16,
    "total_tokens_iqr_outlier_n":  22,
}

_HEADERS = {
    "domain":                      "Domain",
    "ambiguity_level":             "Lvl",
    "soul_id":                     "Soul",
    "tasks":                       "Tasks",
    "input_tokens":                "In Tokens",
    "output_tokens":               "Out Tokens",
    "cache_read_tokens":           "Cache Tokens",
    "agent_tokens":                "AgentTokens",
    "oracle_clarify_tokens":       "OracleClarTok",
    "oracle_correct_tokens":       "OracleCorTok",
    "oracle_tokens":               "OracleTok",
    "total_tokens":                "TotalTokens",
    "avg_eval_score":              "AvgScore",
    "e2e_success_count":           "E2E OK",
    "success_rate":                "Succ%",
    "action_precision_applicable": "AP Applicable",
    "action_precision_match_count": "AP Match",
    "action_precision_rate":       "ActPrec%",
    "over_action_count":           "OverAct N",
    "over_action_rate":            "OverAct%",
    "clarify_tasks":               "ClarTasks",
    "clarify_rate":                "Clar%",
    "correction_tasks":            "CorrTasks",
    "correction_rate":             "Corr%",
    "avg_turns":                   "AvgTurns",
    "avg_clarification_turns":     "AvgClarTurns",
    "avg_correction_turns":        "AvgCorrTurns",
    "avg_agent_tokens_per_task":   "AvgAgentTok/T",
    "avg_oracle_tokens_per_task":  "AvgOracleTok/T",
    "avg_total_tokens_per_task":   "AvgTotalTok/T",
    "avg_e2e_latency_ms":          "AvgLatency(ms)",
    "total_tokens_median":         "TotalTok Median",
    "total_tokens_std":            "TotalTok Std",
    "total_tokens_max":            "TotalTok Max",
    "total_tokens_iqr_outlier_n":  "TotalTok IQR Outlier N",
}

COLUMNS = list(_COL_WIDTHS.keys())


def _fmt(val, col) -> str:
    if isinstance(val, float):
        if col in ("success_rate", "clarify_rate", "action_precision_rate", "over_action_rate", "avg_eval_score"):
            return f"{val:.1%}" if col != "avg_eval_score" else f"{val:.3f}"
        return f"{val:.1f}"
    return str(val)


def print_summary(summary: dict) -> None:
    rows = summary["groups"]
    if not rows:
        print("No data.")
        return

    # Header
    header = "  ".join(_HEADERS[c].ljust(_COL_WIDTHS[c]) for c in COLUMNS)
    sep = "  ".join("-" * _COL_WIDTHS[c] for c in COLUMNS)
    print(f"\n{'=' * len(sep)}")
    print(f"  Experiment Summary  ({summary['total_records']} records)")
    print(f"{'=' * len(sep)}")
    print(header)
    print(sep)

    prev_domain_level = None
    for row in rows:
        key = (row["domain"], row["ambiguity_level"])
        if prev_domain_level and prev_domain_level != key:
            print(sep)
        prev_domain_level = key

        line = "  ".join(_fmt(row[c], c).ljust(_COL_WIDTHS[c]) for c in COLUMNS)
        print(line)

    print(f"{'=' * len(sep)}\n")


# ---------------------------------------------------------------------------
# Export CSV
# ---------------------------------------------------------------------------

def write_csv(summary: dict, out_path: Path) -> None:
    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        for row in summary["groups"]:
            writer.writerow({c: row[c] for c in COLUMNS})


# ---------------------------------------------------------------------------
# Export XLSX (Exp_summ sheet)
# ---------------------------------------------------------------------------

_SOUL_LABELS = {"soul-a": "A", "soul-b": "B", "soul-c": "C"}
_SOUL_ORDER   = ["soul-a", "soul-b", "soul-c"]


def _write_tokens_std_sheet(wb, records: list[dict]) -> None:
    """Total_Tokens_STD sheet: total_tokens boxplot per domain x soul."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from io import BytesIO
        from openpyxl.drawing.image import Image as XLImage
        from openpyxl.styles import Font
        from openpyxl.utils import get_column_letter
    except ImportError:
        print("[WARN] matplotlib not installed — skipping Total_Tokens_STD sheet", flush=True)
        return

    ws = wb.create_sheet("Total_Tokens_STD")

    from collections import defaultdict
    data: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    for r in records:
        data[r["domain"]][r["soul_id"]].append(r.get("total_tokens", 0))

    domains = sorted(data.keys())
    souls = ["soul-a", "soul-b", "soul-c"]
    soul_labels = {"soul-a": "Soul A", "soul-b": "Soul B", "soul-c": "Soul C"}
    colors = {"soul-a": "#C6EFCE", "soul-b": "#D9E1F2", "soul-c": "#FCE4D6"}

    IMG_W, IMG_H = 280, 240     # pixels
    ROWS_PER_BLOCK = 13
    ROW_SPACER = 1
    COL_ANCHORS = [1, 5, 9]

    # global y-axis range over all data (log scale)
    all_tokens = [t for soul_data in data.values() for tokens in soul_data.values() for t in tokens if t > 0]
    y_min = min(all_tokens) * 0.5 if all_tokens else 1e3
    y_max = max(all_tokens) * 2.0 if all_tokens else 1e7

    def _fmt_tok(v: float) -> str:
        return f"{v/1e6:.1f}M" if v >= 1e6 else f"{int(v/1e3)}K"

    import statistics as _stats

    for d_idx, domain in enumerate(domains):
        row_anchor = d_idx * (ROWS_PER_BLOCK + ROW_SPACER) + 1

        cell = ws.cell(row=row_anchor, column=1, value=domain)
        cell.font = Font(bold=True, size=11)

        for s_idx, soul in enumerate(souls):
            tokens = data[domain][soul]
            col_anchor = COL_ANCHORS[s_idx]

            fig, ax = plt.subplots(figsize=(2.8, 2.4))
            if tokens:
                pos_tokens = [t for t in tokens if t > 0]
                ax.boxplot(
                    pos_tokens, vert=True, patch_artist=True,
                    boxprops=dict(facecolor=colors[soul], linewidth=1.2),
                    medianprops=dict(color="#333333", linewidth=2),
                    whiskerprops=dict(linewidth=1),
                    capprops=dict(linewidth=1),
                    flierprops=dict(marker="o", markersize=3, alpha=0.5),
                )
                ax.set_yscale("log")
                ax.set_ylim(y_min, y_max)
                ax.set_title(soul_labels[soul], fontsize=9, fontweight="bold")
                ax.set_ylabel("Total Tokens (log)", fontsize=7)
                ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: _fmt_tok(x)))
                ax.tick_params(axis="y", labelsize=7)
                ax.set_xticks([])

                med = _stats.median(pos_tokens)
                mean = _stats.mean(pos_tokens)
                n = len(pos_tokens)
                ax.set_xlabel(
                    f"n={n}  |  med={_fmt_tok(med)}  |  mean={_fmt_tok(mean)}",
                    fontsize=6.5, labelpad=4,
                )
            else:
                ax.text(0.5, 0.5, "No data", ha="center", va="center", transform=ax.transAxes)
                ax.set_title(soul_labels[soul], fontsize=9)

            plt.tight_layout(pad=0.5)
            buf = BytesIO()
            fig.savefig(buf, format="png", dpi=100, bbox_inches="tight")
            plt.close(fig)
            buf.seek(0)

            img = XLImage(buf)
            img.width = IMG_W
            img.height = IMG_H
            cell_addr = f"{get_column_letter(col_anchor)}{row_anchor + 1}"
            ws.add_image(img, cell_addr)

    # adjust column widths
    for col in range(1, 13):
        ws.column_dimensions[get_column_letter(col)].width = 11


# ---------------------------------------------------------------------------
# Learning-curve aggregation (variant x soul)
# ---------------------------------------------------------------------------

_VARIANTS = [1, 2, 3, 4]
_LEARNING_SOULS = ["soul-a", "soul-b", "soul-c"]


def _variant_of(task_id: str) -> int | None:
    m = re.search(r"_v(\d+)$", task_id)
    return int(m.group(1)) if m else None


def _base_of(task_id: str) -> str:
    return re.sub(r"_v\d+$", "", task_id)


def _aggregate_variant_soul(recs: list[dict]) -> dict | None:
    if not recs:
        return None
    n = len(recs)
    eval_recs = [r for r in recs if r.get("eval") and r["eval"].get("total_checks", 0) > 0]
    scores   = [r["eval"]["score"] if r.get("eval") and r["eval"].get("total_checks", 0) > 0 else 0.0 for r in recs]
    clarify  = [r.get("clarification_turns", 0) for r in recs]
    tokens   = [r.get("agent_tokens", 0) for r in recs]
    latency  = [r.get("e2e_latency_ms", 0) / 1000 for r in recs]
    timeouts = [1 if r.get("timed_out") else 0 for r in recs]

    ap_recs      = [r.get("action_precision") for r in recs if r.get("action_precision")]
    ap_applicable = [a for a in ap_recs if a and a.get("applicable")]
    over_act     = sum(1 for a in ap_applicable if a.get("exec_count", 0) > a.get("gt_count", 0))

    cmds_all = []
    for r in recs:
        for t in r.get("turns", []):
            cmds_all.append(len(t.get("commands_executed", [])))

    n_eval = len(eval_recs)
    return {
        "n":                   n,
        "n_eval":              n_eval,
        "avg_score":           round(sum(scores) / n, 3) if n else None,
        "clarify_rate":        round(sum(1 for c in clarify if c > 0) / n, 3),
        "avg_clarify_turns":   round(sum(clarify) / n, 3),
        "avg_agent_tokens":    int(sum(tokens) / n),
        "avg_latency_s":       round(sum(latency) / n, 1),
        "timeout_rate":        round(sum(timeouts) / n, 3),
        "over_action_rate":    round(over_act / len(ap_applicable), 3) if ap_applicable else None,
        "avg_commands":        round(sum(cmds_all) / len(cmds_all), 2) if cmds_all else 0,
    }


def aggregate_learning(records: list[dict]) -> dict:
    """
    Returns:
      all_stats[variant][soul]  = metric dict  (all tasks)
      fp_stats[variant][soul]   = metric dict  (full-progression: tasks with v1-v4 all present)
    """
    buckets: dict[int, dict[str, list]] = {v: {s: [] for s in _LEARNING_SOULS} for v in _VARIANTS}
    for r in records:
        v    = _variant_of(r.get("task_id", ""))
        soul = r.get("soul_id", "")
        if v in _VARIANTS and soul in _LEARNING_SOULS:
            buckets[v][soul].append(r)

    all_stats: dict[int, dict[str, dict | None]] = {}
    for v in _VARIANTS:
        all_stats[v] = {s: _aggregate_variant_soul(buckets[v][s]) for s in _LEARNING_SOULS}

    # Full-progression cohort: bases that have all 4 variants
    base_variants: dict[str, set[int]] = defaultdict(set)
    for r in records:
        v    = _variant_of(r.get("task_id", ""))
        base = _base_of(r.get("task_id", ""))
        if v:
            base_variants[base].add(v)
    full_bases = {b for b, vs in base_variants.items() if {1, 2, 3, 4}.issubset(vs)}
    fp_records = [r for r in records if _base_of(r.get("task_id", "")) in full_bases]

    fp_buckets: dict[int, dict[str, list]] = {v: {s: [] for s in _LEARNING_SOULS} for v in _VARIANTS}
    for r in fp_records:
        v    = _variant_of(r.get("task_id", ""))
        soul = r.get("soul_id", "")
        if v in _VARIANTS and soul in _LEARNING_SOULS:
            fp_buckets[v][soul].append(r)

    fp_stats: dict[int, dict[str, dict | None]] = {}
    for v in _VARIANTS:
        fp_stats[v] = {s: _aggregate_variant_soul(fp_buckets[v][s]) for s in _LEARNING_SOULS}

    return {"all": all_stats, "full_progression": fp_stats, "fp_task_count": len(full_bases)}


def _has_variants(records: list[dict]) -> bool:
    return any(_variant_of(r.get("task_id", "")) for r in records)


def _write_learning_sheets(wb, records: list[dict]) -> None:
    """Add learning_curve / cost_efficiency / behavior_change / full_progression sheets."""
    try:
        from openpyxl.styles import Alignment, Font, PatternFill
        from openpyxl.utils import get_column_letter
    except ImportError:
        return

    ldata = aggregate_learning(records)
    all_stats = ldata["all"]
    fp_stats  = ldata["full_progression"]
    fp_count  = ldata["fp_task_count"]

    HEADER_FILL  = PatternFill("solid", fgColor="1F497D")
    HEADER_FONT  = Font(bold=True, color="FFFFFF")
    ALT_FILL     = PatternFill("solid", fgColor="EEF2F7")
    SOUL_COLORS  = {"soul-a": "C6EFCE", "soul-b": "D9E1F2", "soul-c": "FCE4D6"}
    CENTER       = Alignment(horizontal="center")
    BOLD         = Font(bold=True)

    SOUL_LABELS = {"soul-a": "Soul A (Neutral)", "soul-b": "Soul B (Cautious)", "soul-c": "Soul C (Bold)"}

    def _write_sheet(ws, headers: list[str], field_keys: list[str],
                     stats: dict, title: str) -> None:
        ws.append([title])
        ws.cell(row=1, column=1).font = Font(bold=True, size=12)
        ws.append([])  # blank

        # header row
        ws.append(["variant", "soul"] + headers)
        hdr_row = ws.max_row
        for col_idx in range(1, len(headers) + 3):
            cell = ws.cell(row=hdr_row, column=col_idx)
            cell.fill  = HEADER_FILL
            cell.font  = HEADER_FONT
            cell.alignment = CENTER

        PCT_FKS = {"avg_score", "clarify_rate", "timeout_rate", "over_action_rate"}
        row_num = hdr_row + 1
        for v in _VARIANTS:
            for s_idx, soul in enumerate(_LEARNING_SOULS):
                st = stats[v].get(soul)
                if st is None:
                    continue
                values = [f"v{v}", SOUL_LABELS[soul]]
                for fk in field_keys:
                    val = st.get(fk)
                    values.append("N/A" if val is None else val)
                ws.append(values)
                if row_num % 2 == 0:
                    fill = ALT_FILL
                else:
                    fill = PatternFill("solid", fgColor=SOUL_COLORS[soul])
                for col_idx in range(1, len(values) + 1):
                    ws.cell(row=row_num, column=col_idx).fill = fill
                # apply number formats
                for col_offset, fk in enumerate(field_keys, 3):
                    cell = ws.cell(row=row_num, column=col_offset)
                    if fk in PCT_FKS and isinstance(cell.value, float):
                        cell.number_format = "0.0%"
                    elif fk in ("avg_agent_tokens", "n", "n_eval") and isinstance(cell.value, int):
                        cell.number_format = "#,##0"
                row_num += 1

        # column widths
        ws.column_dimensions["A"].width = 8
        ws.column_dimensions["B"].width = 22
        _col_w = {"n": 8, "n_eval": 10, "avg_score": 12, "avg_agent_tokens": 18,
                  "clarify_rate": 14, "over_action_rate": 16, "timeout_rate": 14,
                  "avg_clarify_turns": 18, "avg_commands": 14, "avg_latency_s": 14}
        for i, hdr in enumerate(headers, 3):
            ws.column_dimensions[get_column_letter(i)].width = _col_w.get(hdr, max(len(hdr) + 2, 14))

    # -- Sheet: learning_curve ------------------------------------------------
    ws_lc = wb.create_sheet("learning_curve")
    _write_sheet(
        ws_lc,
        headers=["n", "n_eval", "avg_score", "clarify_rate", "avg_clarify_turns", "timeout_rate"],
        field_keys=["n", "n_eval", "avg_score", "clarify_rate", "avg_clarify_turns", "timeout_rate"],
        stats=all_stats,
        title="Learning Curve — Score by Variant Window (All Tasks)",
    )

    # -- Sheet: cost_efficiency -----------------------------------------------
    ws_ce = wb.create_sheet("cost_efficiency")
    _write_sheet(
        ws_ce,
        headers=["n", "avg_agent_tokens", "avg_latency_s", "avg_commands"],
        field_keys=["n", "avg_agent_tokens", "avg_latency_s", "avg_commands"],
        stats=all_stats,
        title="Cost Efficiency — Token & Latency by Variant Window",
    )

    # -- Sheet: behavior_change -----------------------------------------------
    ws_bc = wb.create_sheet("behavior_change")
    _write_sheet(
        ws_bc,
        headers=["n", "clarify_rate", "over_action_rate", "avg_commands", "timeout_rate"],
        field_keys=["n", "clarify_rate", "over_action_rate", "avg_commands", "timeout_rate"],
        stats=all_stats,
        title="Behavior Change — Clarification & Over-Action Rates",
    )

    # -- Sheet: full_progression ----------------------------------------------
    ws_fp = wb.create_sheet("full_progression")
    ws_fp.append([f"Full-Progression Cohort  ({fp_count} base tasks with v1–v4)"])
    ws_fp.cell(row=1, column=1).font = Font(bold=True, size=12)
    ws_fp.append([])
    _write_sheet(
        ws_fp,
        headers=["n", "n_eval", "avg_score", "clarify_rate", "avg_agent_tokens", "over_action_rate"],
        field_keys=["n", "n_eval", "avg_score", "clarify_rate", "avg_agent_tokens", "over_action_rate"],
        stats=fp_stats,
        title="",
    )
    # remove duplicate title row that _write_sheet added
    ws_fp.delete_rows(3, 2)

    # -- Sheet: soul_progression -----------------------------------------------
    ws_sp = wb.create_sheet("soul_progression")
    ws_sp.append([f"Soul Progression — v1->v4 per Soul  (Full-Progression Cohort, {fp_count} base tasks)"])
    ws_sp.cell(row=1, column=1).font = Font(bold=True, size=12)
    ws_sp.append([])

    TREND_THRESHOLD = 0.03
    PCT_KEYS = {"avg_score", "clarify_rate", "over_action_rate", "timeout_rate"}
    SECTION_METRICS = [
        ("avg_score",        "Avg Score"),
        ("clarify_rate",     "Clarify Rate"),
        ("over_action_rate", "Over-Action Rate"),
        ("avg_agent_tokens", "Avg Agent Tokens"),
    ]

    for metric_key, metric_label in SECTION_METRICS:
        # section title
        ws_sp.append([metric_label])
        ws_sp.cell(row=ws_sp.max_row, column=1).font = Font(bold=True, size=11)

        # header
        hdr = ["Soul", "v1", "v2", "v3", "v4", "Δ (v4−v1)", "trend"]
        ws_sp.append(hdr)
        hdr_row = ws_sp.max_row
        for col_idx in range(1, len(hdr) + 1):
            cell = ws_sp.cell(row=hdr_row, column=col_idx)
            cell.fill = HEADER_FILL
            cell.font = HEADER_FONT
            cell.alignment = CENTER

        for soul in _LEARNING_SOULS:
            row_vals = [SOUL_LABELS[soul]]
            raw = []
            for v in _VARIANTS:
                st = fp_stats[v].get(soul)
                val = st.get(metric_key) if st else None
                raw.append(val)
                row_vals.append("N/A" if val is None else (val if metric_key in PCT_KEYS else int(val)))

            v1, v4 = raw[0], raw[3]
            if v1 is not None and v4 is not None:
                delta = v4 - v1
                row_vals.append(delta if metric_key in PCT_KEYS else int(delta))
                row_vals.append("+" if delta > TREND_THRESHOLD else ("-" if delta < -TREND_THRESHOLD else "->"))
            else:
                row_vals.extend(["N/A", "—"])

            ws_sp.append(row_vals)
            data_row = ws_sp.max_row
            soul_fill = PatternFill("solid", fgColor=SOUL_COLORS[soul])
            for col_idx in range(1, len(row_vals) + 1):
                cell = ws_sp.cell(row=data_row, column=col_idx)
                cell.fill = soul_fill
                cell.alignment = CENTER
            # percentage format for v1~v4 cols (2~5) and delta col (6)
            if metric_key in PCT_KEYS:
                for col_idx in range(2, 7):
                    cell = ws_sp.cell(row=data_row, column=col_idx)
                    if isinstance(cell.value, float):
                        cell.number_format = "+0.0%;-0.0%;0.0%" if col_idx == 6 else "0.0%"

        ws_sp.append([])  # blank between sections

    # column widths
    ws_sp.column_dimensions["A"].width = 24
    for col_letter in ["B", "C", "D", "E", "F", "G"]:
        ws_sp.column_dimensions[col_letter].width = 14

    # -- Shared index for partial_cohort + token_cost_by_outcome --------------
    from collections import defaultdict
    vt_soul: dict[tuple[int, str], dict[str, dict]] = defaultdict(dict)
    vt_domain: dict[tuple[int, str], str] = {}
    for r in records:
        v = _variant_of(r.get("task_id", ""))
        if v not in _VARIANTS:
            continue
        tid  = _base_of(r.get("task_id", ""))
        soul = r.get("soul_id", "")
        if soul in _LEARNING_SOULS:
            vt_soul[(v, tid)][soul] = r
            vt_domain[(v, tid)] = r.get("domain", "unknown")

    OUTCOME_FILL = {"all-pass": PatternFill("solid", fgColor="C6EFCE"),
                    "all-fail": PatternFill("solid", fgColor="FFC7CE")}
    DOMAIN_FILL  = PatternFill("solid", fgColor="FFF2CC")
    SOUL_ORDER   = ["soul-a", "soul-b", "soul-c"]
    SOUL_SHORT   = {"soul-a": "Soul A", "soul-b": "Soul B", "soul-c": "Soul C"}

    def _total_tokens(r: dict) -> int:
        return r.get("agent_tokens", 0) + r.get("oracle_tokens", 0)

    def _write_token_section(ws, scope_label: str, filter_fn) -> None:
        """scope_label: '(All Domains)' or domain name. filter_fn: (v,tid)->bool"""
        ws.append([scope_label])
        ws.cell(row=ws.max_row, column=1).font = Font(bold=True, size=11)

        hdr = ["variant", "outcome", "n_tasks",
               "Soul A tokens", "Soul B tokens", "Soul C tokens",
               "lowest-cost soul"]
        ws.append(hdr)
        hdr_row = ws.max_row
        for col_idx in range(1, len(hdr) + 1):
            cell = ws.cell(row=hdr_row, column=col_idx)
            cell.fill = HEADER_FILL
            cell.font = HEADER_FONT
            cell.alignment = CENTER

        any_row = False
        for v in _VARIANTS:
            for outcome_label, success_val in [("all-pass", True), ("all-fail", False)]:
                matched = []
                for (rv, tid), soul_map in vt_soul.items():
                    if rv != v or not filter_fn(rv, tid):
                        continue
                    if set(soul_map.keys()) != set(_LEARNING_SOULS):
                        continue
                    outcomes = {s: bool(soul_map[s].get("eval", {}).get("e2e_success"))
                                for s in _LEARNING_SOULS}
                    if all(o == success_val for o in outcomes.values()):
                        matched.append(soul_map)

                if not matched:
                    continue

                soul_avg: dict[str, float] = {}
                for soul in SOUL_ORDER:
                    tokens = [_total_tokens(sm[soul]) for sm in matched]
                    soul_avg[soul] = sum(tokens) / len(tokens) if tokens else 0

                cheapest = min(soul_avg, key=lambda s: soul_avg[s])
                row_vals = [
                    f"v{v}", outcome_label, len(matched),
                    int(soul_avg["soul-a"]),
                    int(soul_avg["soul-b"]),
                    int(soul_avg["soul-c"]),
                    SOUL_SHORT[cheapest],  # lowest-cost soul
                ]
                ws.append(row_vals)
                fill = OUTCOME_FILL[outcome_label]
                for col_idx in range(1, len(row_vals) + 1):
                    ws.cell(row=ws.max_row, column=col_idx).fill = fill
                    ws.cell(row=ws.max_row, column=col_idx).alignment = CENTER
                any_row = True

        if not any_row:
            ws.append(["  (no data)"])
        ws.append([])

    domains = sorted({d for d in vt_domain.values()})

    # -- Sheet: partial_cohort (created first so it precedes token_cost_by_outcome) --
    # tasks where souls disagree on success (partial)
    # -> compare per-soul survival rate and cost on genuinely hard tasks
    ws_pc = wb.create_sheet("partial_cohort")
    ws_pc.append(["Partial Cohort — Tasks where souls diverge (some pass, some fail)"])
    ws_pc.cell(row=1, column=1).font = Font(bold=True, size=12)
    ws_pc.append(["Only tasks where at least one soul passes AND at least one fails are included."])
    ws_pc.cell(row=2, column=1).font = Font(italic=True, color="595959")
    ws_pc.append([])

    pc_hdr = [
        "variant", "domain", "n_tasks",
        "Soul A pass%", "Soul A tokens",
        "Soul B pass%", "Soul B tokens",
        "Soul C pass%", "Soul C tokens",
        "highest pass%", "lowest cost (pass only)",
    ]
    ws_pc.append(pc_hdr)
    hdr_row = ws_pc.max_row
    for col_idx in range(1, len(pc_hdr) + 1):
        cell = ws_pc.cell(row=hdr_row, column=col_idx)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = CENTER

    # -- Sheet: token_cost_by_outcome -----------------------------------------
    ws_tc = wb.create_sheet("token_cost_by_outcome")
    ws_tc.append(["Token Cost by Outcome — All-pass vs All-fail cohorts, per soul"])
    ws_tc.cell(row=1, column=1).font = Font(bold=True, size=12)
    ws_tc.append([])

    # all domains combined
    _write_token_section(ws_tc, ">> All Domains", lambda v, tid: True)

    # per domain
    for domain in domains:
        _write_token_section(
            ws_tc,
            f">> {domain}",
            lambda v, tid, d=domain: vt_domain.get((v, tid)) == d,
        )

    ws_tc.column_dimensions["A"].width = 10
    ws_tc.column_dimensions["B"].width = 12
    ws_tc.column_dimensions["C"].width = 10
    for col_letter in ["D", "E", "F", "G"]:
        ws_tc.column_dimensions[col_letter].width = 16

    def _write_partial_section(ws, scope_label: str, filter_fn) -> None:
        ws.append([scope_label])
        ws.cell(row=ws.max_row, column=1).font = Font(bold=True, size=11)

        any_row = False
        for v in _VARIANTS:
            partial_tasks: list[dict[str, dict]] = []
            for (rv, tid), soul_map in vt_soul.items():
                if rv != v or not filter_fn(rv, tid):
                    continue
                if set(soul_map.keys()) != set(_LEARNING_SOULS):
                    continue
                outcomes = {s: bool(soul_map[s].get("eval", {}).get("e2e_success"))
                            for s in _LEARNING_SOULS}
                # partial: not all pass, not all fail
                if any(outcomes.values()) and not all(outcomes.values()):
                    partial_tasks.append(soul_map)

            if not partial_tasks:
                continue

            n = len(partial_tasks)
            soul_pass: dict[str, int] = {s: 0 for s in SOUL_ORDER}
            soul_tokens_pass: dict[str, list] = {s: [] for s in SOUL_ORDER}

            for sm in partial_tasks:
                for soul in SOUL_ORDER:
                    success = bool(sm[soul].get("eval", {}).get("e2e_success"))
                    if success:
                        soul_pass[soul] += 1
                        soul_tokens_pass[soul].append(_total_tokens(sm[soul]))

            pass_rates = {s: soul_pass[s] / n for s in SOUL_ORDER}
            avg_tokens_pass = {
                s: int(sum(soul_tokens_pass[s]) / len(soul_tokens_pass[s]))
                if soul_tokens_pass[s] else None
                for s in SOUL_ORDER
            }

            highest_pass = max(pass_rates, key=pass_rates.get)
            valid_costs = {s: v for s, v in avg_tokens_pass.items() if v is not None}
            lowest_cost = min(valid_costs, key=valid_costs.get) if valid_costs else "N/A"

            domain_label = scope_label.replace(">> ", "") if ">>" in scope_label else "all"
            lc_str = SOUL_SHORT[lowest_cost] if lowest_cost != "N/A" else "N/A"
            row_vals = [
                f"v{v}", domain_label, n,
                pass_rates["soul-a"], avg_tokens_pass["soul-a"] or "N/A",
                pass_rates["soul-b"], avg_tokens_pass["soul-b"] or "N/A",
                pass_rates["soul-c"], avg_tokens_pass["soul-c"] or "N/A",
                SOUL_SHORT[highest_pass],
                lc_str,
            ]
            ws.append(row_vals)
            data_row = ws.max_row
            row_fill = PatternFill("solid", fgColor=SOUL_COLORS[highest_pass])
            for col_idx in range(1, len(row_vals) + 1):
                ws.cell(row=data_row, column=col_idx).fill = row_fill
                ws.cell(row=data_row, column=col_idx).alignment = CENTER
            # percentage format for pass% columns (4, 6, 8)
            for col_idx in [4, 6, 8]:
                cell = ws.cell(row=data_row, column=col_idx)
                if isinstance(cell.value, float):
                    cell.number_format = "0%"
            any_row = True

        if not any_row:
            ws.append(["  (no partial tasks)"])
        ws.append([])

    _write_partial_section(ws_pc, ">> All Domains", lambda v, tid: True)
    for domain in domains:
        _write_partial_section(
            ws_pc,
            f">> {domain}",
            lambda v, tid, d=domain: vt_domain.get((v, tid)) == d,
        )

    ws_pc.column_dimensions["A"].width = 10
    ws_pc.column_dimensions["B"].width = 22
    ws_pc.column_dimensions["C"].width = 10
    for col_letter in ["D", "E", "F", "G", "H", "I", "J", "K"]:
        ws_pc.column_dimensions[col_letter].width = 16


def write_xlsx(summary: dict, out_path: Path, records: list[dict] | None = None) -> Path | None:
    """Write summary + Exp_summ + Total_Tokens_STD sheet to an .xlsx file."""
    try:
        import openpyxl
        from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
        from openpyxl.utils import get_column_letter
    except ImportError:
        print("[WARN] openpyxl not installed — skipping .xlsx output", flush=True)
        return None

    wb = openpyxl.Workbook()

    # -- Sheet 1: Raw data ----------------------------------------------------
    ws_raw = wb.active
    ws_raw.title = "Raw"
    ws_raw.append(COLUMNS)
    header_font = Font(bold=True)
    for cell in ws_raw[1]:
        cell.font = header_font
    for row in summary["groups"]:
        ws_raw.append([row[c] for c in COLUMNS])
    for col_idx, col_name in enumerate(COLUMNS, 1):
        ws_raw.column_dimensions[get_column_letter(col_idx)].width = max(
            len(col_name) + 2, 10
        )

    # -- Sheet 2: Exp_summ ----------------------------------------------------
    ws = wb.create_sheet("Exp_summ")

    # Aggregate (domain, soul_id) across all ambiguity levels
    domain_soul: dict[tuple, dict] = defaultdict(
        lambda: {"total_tokens": 0, "e2e_success_count": 0, "tasks": 0,
                 "action_precision_match_count": 0, "action_precision_applicable": 0,
                 "over_action_count": 0}
    )
    for row in summary["groups"]:
        key = (row["domain"], row["soul_id"])
        domain_soul[key]["total_tokens"]               += row["total_tokens"]
        domain_soul[key]["e2e_success_count"]          += row["e2e_success_count"]
        domain_soul[key]["tasks"]                      += row["tasks"]
        domain_soul[key]["action_precision_match_count"] += row.get("action_precision_match_count", 0)
        domain_soul[key]["action_precision_applicable"]  += row.get("action_precision_applicable", 0)
        domain_soul[key]["over_action_count"]            += row.get("over_action_count", 0)

    domains = sorted({k[0] for k in domain_soul})

    # Styles
    TITLE_FILL   = PatternFill("solid", fgColor="4472C4")
    HEADER_FILL  = PatternFill("solid", fgColor="D9E1F2")
    SUMMARY_HDR  = PatternFill("solid", fgColor="E2EFDA")
    BEST_FILL    = PatternFill("solid", fgColor="C6EFCE")
    TITLE_FONT   = Font(bold=True, color="FFFFFF")
    BOLD         = Font(bold=True)
    CENTER       = Alignment(horizontal="center")
    RIGHT        = Alignment(horizontal="right")

    def _tok_per_success(agg: dict) -> float | None:
        return agg["total_tokens"] / agg["e2e_success_count"] if agg["e2e_success_count"] > 0 else None

    _thin = Side(style="thin")
    _border = Border(left=_thin, right=_thin, top=_thin, bottom=_thin)

    def _apply_border(ws, min_row, max_row, min_col, max_col):
        for r in range(min_row, max_row + 1):
            for c in range(min_col, max_col + 1):
                ws.cell(row=r, column=c).border = _border

    # -- Left area: domain blocks ---------------------------------------------
    LEFT_COLS = 5   # A B C D E
    row_idx = 1

    for domain in domains:
        block_start = row_idx

        # Title (merged A:D)
        ws.merge_cells(
            start_row=row_idx, start_column=1,
            end_row=row_idx,   end_column=LEFT_COLS,
        )
        tc = ws.cell(row=row_idx, column=1, value=domain)
        tc.font = TITLE_FONT
        tc.fill = TITLE_FILL
        tc.alignment = CENTER
        row_idx += 1

        # Header
        for col, hdr in enumerate(
            ["soul", "success_rate", "action_precision_rate", "over_action_rate", "total_tokens / e2e_success_count"], 1
        ):
            cell = ws.cell(row=row_idx, column=col, value=hdr)
            cell.font = BOLD
            cell.fill = HEADER_FILL
        row_idx += 1

        # Find best (lowest) cost for highlight
        costs = {}
        for soul_id in _SOUL_ORDER:
            agg = domain_soul.get((domain, soul_id))
            if agg:
                c = _tok_per_success(agg)
                if c is not None:
                    costs[soul_id] = c
        best_soul = min(costs, key=costs.get) if costs else None

        # Data rows
        for soul_id in _SOUL_ORDER:
            agg = domain_soul.get((domain, soul_id))
            label = _SOUL_LABELS[soul_id]
            ws.cell(row=row_idx, column=1, value=label)
            if agg:
                sr = agg["e2e_success_count"] / agg["tasks"] if agg["tasks"] else 0.0
                sr_cell = ws.cell(row=row_idx, column=2, value=sr)
                sr_cell.number_format = "0.00%"

                ap_applicable = agg.get("action_precision_applicable", 0)
                ap_match = agg.get("action_precision_match_count", 0)
                ap_rate = ap_match / ap_applicable if ap_applicable > 0 else None
                if ap_rate is not None:
                    ap_cell = ws.cell(row=row_idx, column=3, value=ap_rate)
                    ap_cell.number_format = "0.00%"
                else:
                    ws.cell(row=row_idx, column=3, value="N/A")

                oa_applicable = agg.get("action_precision_applicable", 0)
                oa_count = agg.get("over_action_count", 0)
                oa_rate = oa_count / oa_applicable if oa_applicable > 0 else None
                if oa_rate is not None:
                    oa_cell = ws.cell(row=row_idx, column=4, value=oa_rate)
                    oa_cell.number_format = "0.00%"
                else:
                    ws.cell(row=row_idx, column=4, value="N/A")

                tps = _tok_per_success(agg)
                if tps is not None:
                    tok_cell = ws.cell(row=row_idx, column=5, value=int(tps))
                    tok_cell.number_format = "#,##0"
                    tok_cell.alignment = RIGHT
                else:
                    ws.cell(row=row_idx, column=5, value="N/A")

                if soul_id == best_soul:
                    for col in range(1, LEFT_COLS + 1):
                        ws.cell(row=row_idx, column=col).fill = BEST_FILL
            row_idx += 1

        _apply_border(ws, block_start, row_idx - 1, 1, LEFT_COLS)
        row_idx += 1  # blank separator row

    # -- Right area: summary table ---------------------------------------------
    RC = LEFT_COLS + 2   # col F (skip col E as spacer)

    RIGHT_HEADERS = [
        "domain",
        "highest success rate soul",
        "lowest success rate soul",
        "highest action precision rate soul",
        "lowest action precision rate soul",
        "highest cost soul",
        "lowest cost soul",
    ]
    for offset, hdr in enumerate(RIGHT_HEADERS):
        cell = ws.cell(row=1, column=RC + offset, value=hdr)
        cell.font = BOLD
        cell.fill = SUMMARY_HDR

    for i, domain in enumerate(domains, 2):
        success_rates = {}
        ap_rates = {}
        costs = {}
        for soul_id in _SOUL_ORDER:
            agg = domain_soul.get((domain, soul_id))
            if not agg:
                continue
            if agg["tasks"]:
                success_rates[soul_id] = agg["e2e_success_count"] / agg["tasks"]
            ap_app = agg.get("action_precision_applicable", 0)
            if ap_app:
                ap_rates[soul_id] = agg.get("action_precision_match_count", 0) / ap_app
            c = _tok_per_success(agg)
            if c is not None:
                costs[soul_id] = c

        def _label(d: dict, fn) -> str:
            return _SOUL_LABELS[fn(d, key=d.get)] if d else "N/A"

        ws.cell(row=i, column=RC, value=domain)

        for offset, (d, fn) in enumerate([
            (success_rates, max),
            (success_rates, min),
            (ap_rates,      max),
            (ap_rates,      min),
            (costs,         max),
            (costs,         min),
        ], 1):
            label = _SOUL_LABELS[fn(d, key=d.get)] if d else "N/A"
            cell = ws.cell(row=i, column=RC + offset, value=label)
            cell.alignment = CENTER
            if fn is min and offset in (2, 4):   # lowest success/AP -> no highlight (bad)
                pass
            elif fn is max and offset in (5,):   # highest cost -> no highlight (bad)
                pass
            else:
                cell.fill = BEST_FILL

    _apply_border(ws, 1, 1 + len(domains), RC, RC + len(RIGHT_HEADERS) - 1)

    # -- Column widths --------------------------------------------------------
    ws.column_dimensions[get_column_letter(1)].width = 8    # Soul
    ws.column_dimensions[get_column_letter(2)].width = 14   # Success Rate
    ws.column_dimensions[get_column_letter(3)].width = 18   # Action Precision Rate
    ws.column_dimensions[get_column_letter(4)].width = 16   # Over-Action Rate
    ws.column_dimensions[get_column_letter(5)].width = 30   # Tokens/Success
    ws.column_dimensions[get_column_letter(6)].width = 4    # spacer
    ws.column_dimensions[get_column_letter(RC)].width = 32      # Domain
    ws.column_dimensions[get_column_letter(RC + 1)].width = 30  # highest success rate soul
    ws.column_dimensions[get_column_letter(RC + 2)].width = 30  # lowest success rate soul
    ws.column_dimensions[get_column_letter(RC + 3)].width = 30  # highest action precision rate soul
    ws.column_dimensions[get_column_letter(RC + 4)].width = 30  # lowest action precision rate soul
    ws.column_dimensions[get_column_letter(RC + 5)].width = 17.17  # highest cost soul
    ws.column_dimensions[get_column_letter(RC + 6)].width = 30  # lowest cost soul

    if records:
        _write_tokens_std_sheet(wb, records)
        if _has_variants(records):
            _write_learning_sheets(wb, records)

    xlsx_path = out_path.with_suffix(".xlsx")
    wb.save(xlsx_path)
    return xlsx_path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Aggregate experiment results by domain x level x soul")
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument("--results", type=Path, help="Single JSONL results file")
    src.add_argument("--results-dir", type=Path, help="Directory of JSONL files (merged)")
    parser.add_argument("--no-csv", action="store_true", help="Skip CSV output")
    parser.add_argument("--no-json", action="store_true", help="Skip JSON output")
    args = parser.parse_args()

    if args.results:
        paths = [args.results]
        summary_dir = args.results.parent.parent / "summary"
        summary_dir.mkdir(exist_ok=True)
        base = summary_dir / args.results.stem
    else:
        paths = sorted(args.results_dir.glob("*.jsonl"))
        summary_dir = args.results_dir / "summary"
        summary_dir.mkdir(exist_ok=True)
        base = summary_dir / args.results_dir.name

    records = load_records(paths)
    if not records:
        print("No records found.")
        return

    summary = build_summary(records)
    print_summary(summary)

    if not args.no_json:
        json_out = base.with_suffix(".summary.json")
        json_out.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"JSON -> {json_out}")

    if not args.no_csv:
        csv_out = base.with_suffix(".summary.csv")
        write_csv(summary, csv_out)
        xlsx_path = write_xlsx(summary, csv_out, records=records)
        if xlsx_path:
            print(f"XLSX -> {xlsx_path}")


if __name__ == "__main__":
    main()
