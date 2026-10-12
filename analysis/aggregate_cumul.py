"""
aggregate_cumul.py — Cumulative run analysis (run1->runN)

Usage:
    python analysis/aggregate_cumul.py \
        --run-prefix GPT-OSS-120B_full_cumul \
        --runs 5 \
        [--results-dir results/] \
        [--out results/GPT-OSS-120B_full_cumul_analysis.xlsx]

Sheets:
  rankings  — domain block x (Highest/Lowest) x (SR / AP / Token), runs as columns
  detail    — domain block x soul x 4 metrics, runs as columns + Δ(runN−run1)
"""

import argparse
import glob
import json
import sys
from collections import defaultdict
from pathlib import Path

try:
    import openpyxl
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter
except ImportError:
    sys.exit("openpyxl required: pip install openpyxl")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
SOULS = ["soul-a", "soul-b", "soul-c"]
SOUL_LABEL = {
    "soul-a": "Soul A (Neutral)",
    "soul-b": "Soul B (Cautious)",
    "soul-c": "Soul C (Bold)",
}
SOUL_SHORT = {"soul-a": "A", "soul-b": "B", "soul-c": "C"}

DOMAINS_ORDER = [
    "analytics", "calendar", "customer_relationship_manager",
    "email", "multi_domain", "project_management",
]
DOMAIN_LABEL = {
    "analytics":                        "Analytics",
    "calendar":                         "Calendar",
    "customer_relationship_manager":    "Customer Relationship Manager",
    "email":                            "Email",
    "multi_domain":                     "Multi Domain",
    "project_management":               "Project Management",
}

RANK_METRICS = [
    ("success_rate",          "Success Rate"),
    ("action_precision_rate", "Action Precision Rate"),
    ("token_per_success",     "Total Tokens / e2e Success"),
]
DETAIL_METRICS = [
    ("success_rate",          "Success Rate"),
    ("action_precision_rate", "Action Precision Rate"),
    ("over_action_rate",      "Over-Action Rate"),
    ("token_per_success",     "Total Tokens / e2e Success"),
]

# ---------------------------------------------------------------------------
# Styles
# ---------------------------------------------------------------------------
FILL_DOMAIN     = PatternFill("solid", fgColor="2E4057")
FILL_COL_HDR    = PatternFill("solid", fgColor="1F497D")
FILL_SOUL_HDR   = {
    "soul-a": PatternFill("solid", fgColor="70AD47"),
    "soul-b": PatternFill("solid", fgColor="2E75B6"),
    "soul-c": PatternFill("solid", fgColor="C65911"),
}
FILL_SOUL_ROW   = {
    "soul-a": PatternFill("solid", fgColor="E2EFDA"),
    "soul-b": PatternFill("solid", fgColor="DDEEFF"),
    "soul-c": PatternFill("solid", fgColor="FCE4D6"),
}
FILL_SOUL_RANK  = {
    "soul-a": PatternFill("solid", fgColor="C6EFCE"),
    "soul-b": PatternFill("solid", fgColor="BDD7EE"),
    "soul-c": PatternFill("solid", fgColor="FCE4D6"),
}
FILL_NONE       = PatternFill("solid", fgColor="FFFFFF")

thin  = Side(style="thin",   color="BBBBBB")
BORDER = Border(left=thin, right=thin, top=thin, bottom=thin)
CENTER = Alignment(horizontal="center", vertical="center", wrap_text=False)
LEFT   = Alignment(horizontal="left",   vertical="center")


def _sc(cell, value=None, font=None, fill=None, align=None, border=BORDER, nfmt=None):
    if value is not None:
        cell.value = value
    if font:   cell.font   = font
    if fill:   cell.fill   = fill
    if align:  cell.alignment = align
    if border: cell.border  = border
    if nfmt:   cell.number_format = nfmt


# ---------------------------------------------------------------------------
# Data loading & aggregation
# ---------------------------------------------------------------------------
def load_records(results_dir: Path, run_prefix: str, n_runs: int) -> dict:
    data = {}
    for run_n in range(1, n_runs + 1):
        pattern = str(
            results_dir / f"{run_prefix}_run{run_n}_*"
                        / f"{run_prefix}_run{run_n}_*.jsonl"
        )
        files = sorted(glob.glob(pattern))
        if not files:
            print(f"[warn] no JSONL for run{run_n}: {pattern}", file=sys.stderr)
            data[run_n] = []
        else:
            records = []
            with open(files[-1]) as f:
                for line in f:
                    line = line.strip()
                    if line:
                        records.append(json.loads(line))
            data[run_n] = records
            print(f"  run{run_n}: {len(records)} records  ({Path(files[-1]).name})")
    return data


def compute_stats(records: list) -> dict:
    """Returns {domain: {soul_id: {metric: value}}}"""
    groups = defaultdict(list)
    for r in records:
        groups[(r["domain"], r["soul_id"])].append(r)

    result = {}
    for domain in set(k[0] for k in groups):
        result[domain] = {}
        for soul in SOULS:
            recs = groups.get((domain, soul), [])
            if not recs:
                result[domain][soul] = None
                continue
            n = len(recs)
            success_n = sum(1 for r in recs if r.get("eval", {}).get("e2e_success", False))
            ap_recs   = [r for r in recs if r.get("action_precision", {}).get("applicable", False)]
            ap_success_recs = [r for r in ap_recs if r.get("eval", {}).get("e2e_success", False)]
            ap_match  = sum(1 for r in ap_success_recs if r.get("action_precision", {}).get("match", False))
            over_act  = sum(
                1 for r in ap_recs
                if r.get("action_precision", {}).get("exec_count", 0) >
                   r.get("action_precision", {}).get("gt_count", 0)
            )
            total_tok = sum(r.get("total_tokens", 0) for r in recs)
            result[domain][soul] = {
                "success_rate":          round(success_n / n * 100, 1),
                "action_precision_rate": round(ap_match / len(ap_success_recs) * 100, 1) if ap_success_recs else None,
                "over_action_rate":      round(over_act / len(ap_recs) * 100, 1) if ap_recs else None,
                "token_per_success":     int(total_tok / success_n) if success_n > 0 else None,
            }
    return result


# ---------------------------------------------------------------------------
# Sheet: rankings
# ---------------------------------------------------------------------------
def write_rankings(wb, all_stats: dict, n_runs: int):
    ws = wb.create_sheet("rankings")

    # Col widths: A=25, B=28, C..G=14
    ws.column_dimensions["A"].width = 25
    ws.column_dimensions["B"].width = 28
    for i in range(3, 3 + n_runs):
        ws.column_dimensions[get_column_letter(i)].width = 14

    total_cols = 2 + n_runs  # Tier + Metric + run1..runN

    row = 1
    for domain in DOMAINS_ORDER:
        if not any(domain in all_stats.get(r, {}) for r in range(1, n_runs + 1)):
            continue

        # -- Domain header (merged full width) ------------------------------
        ws.merge_cells(start_row=row, start_column=1,
                       end_row=row, end_column=total_cols)
        c = ws.cell(row, 1, DOMAIN_LABEL.get(domain, domain))
        c.font  = Font(bold=True, color="FFFFFF", size=11)
        c.fill  = FILL_DOMAIN
        c.alignment = CENTER
        c.border = BORDER
        row += 1

        # -- Column headers -------------------------------------------------
        for col, label in enumerate(["Tier", "Metric"] + [f"run{r}" for r in range(1, n_runs+1)], 1):
            c = ws.cell(row, col, label)
            c.font  = Font(bold=True, color="FFFFFF", size=10)
            c.fill  = FILL_COL_HDR
            c.alignment = CENTER
            c.border = BORDER
        row += 1

        # -- Highest block --------------------------------------------------
        tier_start = row
        for m_idx, (mkey, mlabel) in enumerate(RANK_METRICS):
            c_tier = ws.cell(row, 1, "Highest" if m_idx == 0 else None)
            c_tier.font   = Font(bold=True, size=10)
            c_tier.alignment = CENTER
            c_tier.border = BORDER

            c_met = ws.cell(row, 2, mlabel)
            c_met.font    = Font(size=10)
            c_met.alignment = LEFT
            c_met.border  = BORDER

            for run_n in range(1, n_runs + 1):
                stats = all_stats.get(run_n, {}).get(domain, {})
                vals = {s: stats[s][mkey] for s in SOULS
                        if stats.get(s) and stats[s].get(mkey) is not None}
                if vals:
                    # Highest = highest raw value for all metrics
                    best = max(vals, key=lambda s: vals[s])
                    letter = SOUL_SHORT[best]
                    fill   = FILL_SOUL_RANK[best]
                else:
                    letter, fill = "—", FILL_NONE
                c = ws.cell(row, 2 + run_n, letter)
                c.font  = Font(bold=True, size=10)
                c.fill  = fill
                c.alignment = CENTER
                c.border = BORDER
            row += 1

        ws.merge_cells(start_row=tier_start, start_column=1,
                       end_row=row - 1,      end_column=1)
        merged = ws.cell(tier_start, 1)
        merged.font      = Font(bold=True, size=10)
        merged.alignment = CENTER

        # -- Lowest block ---------------------------------------------------
        tier_start = row
        for m_idx, (mkey, mlabel) in enumerate(RANK_METRICS):
            c_tier = ws.cell(row, 1, "Lowest" if m_idx == 0 else None)
            c_tier.font   = Font(bold=True, size=10)
            c_tier.alignment = CENTER
            c_tier.border = BORDER

            c_met = ws.cell(row, 2, mlabel)
            c_met.font    = Font(size=10)
            c_met.alignment = LEFT
            c_met.border  = BORDER

            for run_n in range(1, n_runs + 1):
                stats = all_stats.get(run_n, {}).get(domain, {})
                vals = {s: stats[s][mkey] for s in SOULS
                        if stats.get(s) and stats[s].get(mkey) is not None}
                if vals:
                    worst  = min(vals, key=lambda s: vals[s])
                    letter = SOUL_SHORT[worst]
                    fill   = FILL_SOUL_RANK[worst]
                else:
                    letter, fill = "—", FILL_NONE
                c = ws.cell(row, 2 + run_n, letter)
                c.font  = Font(bold=True, size=10)
                c.fill  = fill
                c.alignment = CENTER
                c.border = BORDER
            row += 1

        ws.merge_cells(start_row=tier_start, start_column=1,
                       end_row=row - 1,      end_column=1)
        merged = ws.cell(tier_start, 1)
        merged.font      = Font(bold=True, size=10)
        merged.alignment = CENTER

        # blank row between domains
        row += 1



# ---------------------------------------------------------------------------
# Sheet: detail
# ---------------------------------------------------------------------------
def write_detail(wb, all_stats: dict, n_runs: int):
    ws = wb.create_sheet("detail")

    total_cols = 2 + n_runs + 1  # Soul + Metric + run1..N + Delta

    ws.column_dimensions["A"].width = 22
    ws.column_dimensions["B"].width = 28
    for i in range(3, 3 + n_runs):
        ws.column_dimensions[get_column_letter(i)].width = 12
    ws.column_dimensions[get_column_letter(2 + n_runs + 1)].width = 16

    row = 1
    for domain in DOMAINS_ORDER:
        if not any(domain in all_stats.get(r, {}) for r in range(1, n_runs + 1)):
            continue

        # -- Domain header --------------------------------------------------
        ws.merge_cells(start_row=row, start_column=1,
                       end_row=row, end_column=total_cols)
        c = ws.cell(row, 1, DOMAIN_LABEL.get(domain, domain))
        c.font  = Font(bold=True, color="FFFFFF", size=11)
        c.fill  = FILL_DOMAIN
        c.alignment = CENTER
        c.border = BORDER
        row += 1

        # -- Column headers -------------------------------------------------
        hdrs = ["Soul", "Metric"] + [f"run{r}" for r in range(1, n_runs+1)] + [f"Δ (run{n_runs}−run1)"]
        for col, label in enumerate(hdrs, 1):
            c = ws.cell(row, col, label)
            c.font  = Font(bold=True, color="FFFFFF", size=10)
            c.fill  = FILL_COL_HDR
            c.alignment = CENTER
            c.border = BORDER
        row += 1

        # -- Soul blocks ----------------------------------------------------
        for soul in SOULS:
            soul_start = row
            row_fill   = FILL_SOUL_ROW[soul]

            for m_idx, (mkey, mlabel) in enumerate(DETAIL_METRICS):
                # Soul label (first row only; others left None, merged later)
                c_soul = ws.cell(row, 1, SOUL_LABEL[soul] if m_idx == 0 else None)
                c_soul.font      = Font(bold=True, color="FFFFFF" if m_idx == 0 else "000000", size=10)
                c_soul.fill      = FILL_SOUL_HDR[soul] if m_idx == 0 else row_fill
                c_soul.alignment = CENTER
                c_soul.border    = BORDER

                # Metric label
                c_met = ws.cell(row, 2, mlabel)
                c_met.font      = Font(size=10)
                c_met.fill      = row_fill
                c_met.alignment = LEFT
                c_met.border    = BORDER

                # Values per run
                run_vals = []
                for run_n in range(1, n_runs + 1):
                    stats = all_stats.get(run_n, {}).get(domain, {}).get(soul)
                    val   = stats[mkey] if stats else None
                    run_vals.append(val)
                    col   = 2 + run_n
                    cell  = ws.cell(row, col)
                    cell.fill      = row_fill
                    cell.alignment = CENTER
                    cell.border    = BORDER
                    if val is None:
                        cell.value = "—"
                        cell.font  = Font(size=10, color="888888")
                    elif mkey == "token_per_success":
                        cell.value         = val
                        cell.font          = Font(size=10)
                        cell.number_format = "#,##0"
                    else:
                        cell.value         = val   # already a rounded percentage
                        cell.font          = Font(size=10)
                        cell.number_format = '0.0'

                # Delta column
                delta_col  = 2 + n_runs + 1
                delta_cell = ws.cell(row, delta_col)
                delta_cell.fill      = row_fill
                delta_cell.alignment = CENTER
                delta_cell.border    = BORDER
                v1, vn = run_vals[0], run_vals[-1]
                if v1 is not None and vn is not None:
                    delta = vn - v1 if mkey != "token_per_success" else int(vn) - int(v1)
                    delta_cell.value = round(delta, 1) if mkey != "token_per_success" else delta
                    # color: green = improvement, red = degradation
                    lower_better = mkey in ("over_action_rate", "token_per_success")
                    good  = (delta < 0) if lower_better else (delta > 0)
                    bad   = (delta > 0) if lower_better else (delta < 0)
                    color = "00AA00" if good else ("FF0000" if bad else "000000")
                    delta_cell.font = Font(size=10, bold=True, color=color)
                    if mkey == "token_per_success":
                        delta_cell.number_format = '+#,##0;-#,##0;0'
                    else:
                        delta_cell.number_format = '+0.0;-0.0;0.0'
                else:
                    delta_cell.value = "—"
                    delta_cell.font  = Font(size=10, color="888888")

                row += 1

            # Merge soul label vertically
            ws.merge_cells(start_row=soul_start, start_column=1,
                           end_row=row - 1,      end_column=1)
            merged = ws.cell(soul_start, 1)
            merged.font      = Font(bold=True, color="FFFFFF", size=10)
            merged.fill      = FILL_SOUL_HDR[soul]
            merged.alignment = CENTER

        # blank row between domains
        row += 1


# ---------------------------------------------------------------------------
# Sheet: memory_tokens  (turn-1 input tokens per soul x run)
# ---------------------------------------------------------------------------
def compute_memory_tokens(raw: dict, n_runs: int) -> dict:
    """Returns {soul: {run_n: {avg, min, max, n}}}"""
    result = {soul: {} for soul in SOULS}
    for run_n in range(1, n_runs + 1):
        records = raw.get(run_n, [])
        by_soul: dict[str, list[int]] = {s: [] for s in SOULS}
        for r in records:
            soul = r.get("soul_id")
            if soul not in by_soul:
                continue
            turns = r.get("turns", [])
            if turns:
                by_soul[soul].append(turns[0].get("input_tokens", 0))
        for soul in SOULS:
            vals = by_soul[soul]
            result[soul][run_n] = {
                "avg": int(sum(vals) / len(vals)) if vals else 0,
                "min": min(vals) if vals else 0,
                "max": max(vals) if vals else 0,
                "n":   len(vals),
            }
    return result


def write_memory_tokens(wb, raw: dict, n_runs: int):
    ws = wb.create_sheet("memory_tokens")

    FILL_HDR   = PatternFill("solid", fgColor="1F497D")
    FILL_SUBHDR = PatternFill("solid", fgColor="4472C4")

    ws.column_dimensions["A"].width = 22
    ws.column_dimensions["B"].width = 14
    for i in range(3, 3 + n_runs + 1):
        ws.column_dimensions[get_column_letter(i)].width = 14

    mem = compute_memory_tokens(raw, n_runs)

    # -- Title --------------------------------------------------------------
    total_cols = 2 + n_runs + 1
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=total_cols)
    c = ws.cell(1, 1, "Memory Context Size — Turn 1 Input Tokens per Soul x Run")
    c.font      = Font(bold=True, color="FFFFFF", size=11)
    c.fill      = PatternFill("solid", fgColor="2E4057")
    c.alignment = CENTER
    c.border    = BORDER

    ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=total_cols)
    c = ws.cell(2, 1, "Turn 1 = startup turn (TOOLS.md + patterns.md read). "
                      "Higher values across runs indicate patterns.md context growth.")
    c.font      = Font(italic=True, size=9, color="444444")
    c.alignment = LEFT
    c.border    = BORDER

    # -- Column headers -----------------------------------------------------
    row = 3
    hdrs = ["Soul", "Stat"] + [f"run{r}" for r in range(1, n_runs + 1)] + [f"Δ (run{n_runs}−run1)"]
    for col, label in enumerate(hdrs, 1):
        c = ws.cell(row, col, label)
        c.font      = Font(bold=True, color="FFFFFF", size=10)
        c.fill      = FILL_HDR
        c.alignment = CENTER
        c.border    = BORDER
    row += 1

    # -- Soul blocks --------------------------------------------------------
    for soul in SOULS:
        soul_start = row
        row_fill   = FILL_SOUL_ROW[soul]

        for s_idx, stat_key in enumerate(["avg", "min", "max"]):
            stat_label = {"avg": "Avg", "min": "Min", "max": "Max"}[stat_key]

            c_soul = ws.cell(row, 1, SOUL_LABEL[soul] if s_idx == 0 else None)
            c_soul.font      = Font(bold=True, color="FFFFFF" if s_idx == 0 else "000000", size=10)
            c_soul.fill      = FILL_SOUL_HDR[soul] if s_idx == 0 else row_fill
            c_soul.alignment = CENTER
            c_soul.border    = BORDER

            c_stat = ws.cell(row, 2, stat_label)
            c_stat.font      = Font(size=10)
            c_stat.fill      = row_fill
            c_stat.alignment = CENTER
            c_stat.border    = BORDER

            run_vals = []
            for run_n in range(1, n_runs + 1):
                val = mem[soul][run_n][stat_key]
                run_vals.append(val)
                cell = ws.cell(row, 2 + run_n)
                cell.value         = val
                cell.font          = Font(size=10)
                cell.fill          = row_fill
                cell.alignment     = CENTER
                cell.border        = BORDER
                cell.number_format = "#,##0"

            # Delta (avg only)
            delta_cell = ws.cell(row, 2 + n_runs + 1)
            delta_cell.fill      = row_fill
            delta_cell.alignment = CENTER
            delta_cell.border    = BORDER
            if stat_key == "avg":
                delta = run_vals[-1] - run_vals[0]
                delta_cell.value         = delta
                delta_cell.number_format = '+#,##0;-#,##0;0'
                color = "FF0000" if delta > 0 else ("00AA00" if delta < 0 else "000000")
                delta_cell.font = Font(size=10, bold=True, color=color)
            else:
                delta_cell.value = "—"
                delta_cell.font  = Font(size=10, color="888888")

            row += 1

        ws.merge_cells(start_row=soul_start, start_column=1,
                       end_row=row - 1,      end_column=1)
        merged = ws.cell(soul_start, 1)
        merged.font      = Font(bold=True, color="FFFFFF", size=10)
        merged.fill      = FILL_SOUL_HDR[soul]
        merged.alignment = CENTER

        row += 1  # blank row between souls


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-prefix",   default="GPT-OSS-120B")
    parser.add_argument("--runs",         type=int, default=5)
    parser.add_argument("--results-dir",  default="results")
    parser.add_argument("--out",          default=None)
    args = parser.parse_args()

    results_dir = Path(args.results_dir)
    out_path    = Path(args.out) if args.out else \
                  results_dir / f"{args.run_prefix}_analysis.xlsx"

    print(f"Prefix : {args.run_prefix}")
    print(f"Runs   : 1..{args.runs}")
    print(f"Dir    : {results_dir}")
    raw = load_records(results_dir, args.run_prefix, args.runs)

    all_stats = {rn: compute_stats(recs) if recs else {}
                 for rn, recs in raw.items()}

    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    write_rankings(wb, all_stats, args.runs)
    write_detail(wb, all_stats, args.runs)
    write_memory_tokens(wb, raw, args.runs)
    wb.save(out_path)
    print(f"\nSaved -> {out_path}")


if __name__ == "__main__":
    main()
