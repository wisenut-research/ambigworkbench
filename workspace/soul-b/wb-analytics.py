"""
wb-analytics.py — WorkBench Analytics Tool

Commands:
  metrics                          List available metrics
  query  --metric M [--from F] [--to T]   Query metric data (aggregated by date)
  plot   --metric M --type T [--from F] [--to T]  Generate and save a chart

Output file: {WB_WORKSPACE}/plots/{time_min}_{time_max}_{metric}_{plot_type}.png
"""

import argparse
import csv
import json
import os
import sys
from collections import defaultdict
from pathlib import Path

WORKSPACE = Path(os.environ.get("WB_WORKSPACE", "."))
DATA_FILE = WORKSPACE / "analytics_data.csv"
PLOTS_DIR = WORKSPACE / "plots"

# Metric names match CSV columns / eval expected filenames exactly
VALID_METRICS = [
    "total_visits",           # count of rows per date
    "user_engaged",           # count of user_engaged=True rows per date
    "session_duration_seconds",  # average session_duration_seconds per date
    "visits_social_media",    # count rows where traffic_source=social_media
    "visits_search_engine",   # count rows where traffic_source=search_engine
    "visits_referral",        # count rows where traffic_source=referral
    "visits_direct",          # count rows where traffic_source=direct
]

VALID_PLOT_TYPES = ["bar", "line", "scatter", "histogram"]


def _log_action(anchor_type: str, anchor: str) -> None:
    """Append a write-op anchor to memory/action_log.jsonl for action precision measurement."""
    log_path = WORKSPACE / "memory" / "action_log.jsonl"
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"anchor_type": anchor_type, "anchor": anchor.lower()}) + "\n")
    except Exception:
        pass


def load_raw_rows(time_min: str | None, time_max: str | None) -> list[dict]:
    """Load raw CSV rows filtered by date range."""
    if not DATA_FILE.exists():
        print(f"[error] analytics_data.csv not found at {DATA_FILE}", file=sys.stderr)
        sys.exit(1)

    rows = []
    with DATA_FILE.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            date_str = row.get("date_of_visit", row.get("date", ""))
            if time_min and date_str < time_min:
                continue
            if time_max and date_str > time_max:
                continue
            rows.append(row)
    return rows


def aggregate_by_date(rows: list[dict], metric: str) -> list[tuple[str, float]]:
    """
    Aggregate raw rows by date for the given metric.
    Returns sorted list of (date, value) tuples.
    """
    daily: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        date = row.get("date_of_visit", row.get("date", ""))
        if date:
            daily[date].append(row)

    result = []
    for date in sorted(daily.keys()):
        group = daily[date]
        if metric == "total_visits":
            val = float(len(group))
        elif metric == "user_engaged":
            val = float(sum(
                1 for r in group
                if str(r.get("user_engaged", "")).strip().lower() in ("true", "1", "yes")
            ))
        elif metric == "session_duration_seconds":
            vals = []
            for r in group:
                raw = r.get("session_duration_seconds", "")
                try:
                    vals.append(float(raw))
                except (ValueError, TypeError):
                    pass
            val = sum(vals) / len(vals) if vals else 0.0
        elif metric == "visits_social_media":
            val = float(sum(1 for r in group if r.get("traffic_source", "").lower() == "social_media"))
        elif metric == "visits_search_engine":
            val = float(sum(1 for r in group if r.get("traffic_source", "").lower() == "search_engine"))
        elif metric == "visits_referral":
            val = float(sum(1 for r in group if r.get("traffic_source", "").lower() == "referral"))
        elif metric == "visits_direct":
            val = float(sum(1 for r in group if r.get("traffic_source", "").lower() == "direct"))
        else:
            val = 0.0
        result.append((date, val))
    return result


def cmd_metrics() -> None:
    print("Available metrics:")
    for m in VALID_METRICS:
        print(f"  {m}")


def cmd_query(metric: str, time_min: str | None, time_max: str | None) -> None:
    if metric not in VALID_METRICS:
        print(f"[error] Unknown metric '{metric}'. Valid: {', '.join(VALID_METRICS)}", file=sys.stderr)
        sys.exit(1)

    rows = load_raw_rows(time_min, time_max)
    if not rows:
        print("No data found for given filters.")
        return

    daily = aggregate_by_date(rows, metric)
    print(f"date,{metric}")
    for date, val in daily:
        print(f"{date},{val:.2f}" if val != int(val) else f"{date},{int(val)}")


def cmd_plot(metric: str, plot_type: str, time_min: str | None, time_max: str | None) -> None:
    if metric not in VALID_METRICS:
        print(f"[error] Unknown metric '{metric}'. Valid: {', '.join(VALID_METRICS)}", file=sys.stderr)
        sys.exit(1)
    if plot_type not in VALID_PLOT_TYPES:
        print(f"[error] Unknown plot type '{plot_type}'. Valid: {', '.join(VALID_PLOT_TYPES)}", file=sys.stderr)
        sys.exit(1)

    rows = load_raw_rows(time_min, time_max)
    if not rows:
        print("[error] No data found for given filters.", file=sys.stderr)
        sys.exit(1)

    daily = aggregate_by_date(rows, metric)
    plot_dates = [d for d, _ in daily]
    values = [v for _, v in daily]

    # Effective date range for filename
    eff_min = time_min or (plot_dates[0] if plot_dates else "unknown")
    eff_max = time_max or (plot_dates[-1] if plot_dates else "unknown")

    PLOTS_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"{eff_min}_{eff_max}_{metric}_{plot_type}.png"
    out_path = PLOTS_DIR / filename

    try:
        import matplotlib
        matplotlib.use("Agg")  # headless — no display required
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots(figsize=(10, 5))
        if plot_type == "bar":
            ax.bar(plot_dates, values)
        elif plot_type == "line":
            ax.plot(plot_dates, values)
        elif plot_type == "scatter":
            ax.scatter(plot_dates, values)
        elif plot_type == "histogram":
            ax.hist(values, bins=20)

        ax.set_title(f"{metric} ({eff_min} to {eff_max})")
        ax.set_xlabel("Date")
        ax.set_ylabel(metric)
        plt.xticks(rotation=45, ha="right")
        plt.tight_layout()
        plt.savefig(out_path)
        plt.close()
        print(f"Plot saved: {out_path}")

    except ImportError:
        # matplotlib not available — create a marker file so evaluator can verify
        out_path.write_text(
            f"plot_params: metric={metric} type={plot_type} from={eff_min} to={eff_max}\n",
            encoding="utf-8",
        )
        print(f"Plot marker saved: {out_path}")

    _log_action("metric", metric)


def main() -> None:
    parser = argparse.ArgumentParser(prog="wb-analytics")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("metrics", help="List available metrics")

    q = sub.add_parser("query", help="Query metric data (aggregated by date)")
    q.add_argument("--metric", required=True)
    q.add_argument("--from", dest="time_min", default=None)
    q.add_argument("--to", dest="time_max", default=None)

    p = sub.add_parser("plot", help="Generate a chart")
    p.add_argument("--metric", required=True)
    p.add_argument("--type", dest="plot_type", required=True)
    p.add_argument("--from", dest="time_min", default=None)
    p.add_argument("--to", dest="time_max", default=None)

    args = parser.parse_args()

    if args.command == "metrics":
        cmd_metrics()
    elif args.command == "query":
        cmd_query(args.metric, args.time_min, args.time_max)
    elif args.command == "plot":
        cmd_plot(args.metric, args.plot_type, args.time_min, args.time_max)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
