#!/usr/bin/env python3
"""
wb-calendar: WorkBench simulated calendar CLI.
Reads/writes experiment/workspace/<soul>/calendar_events.csv

Commands:
  list                                          List upcoming events
  create --name <name> --participant <email> --start <datetime> --duration <mins>
  update --id <event_id> --field <field> --value <value>
  delete --id <event_id>
  delete-many --ids <id1,id2,...>
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import uuid
from pathlib import Path


def _log_action(anchor_type: str, anchor: str) -> None:
    """Append a write-op anchor to memory/action_log.jsonl for action precision measurement."""
    workspace = os.environ.get("WB_WORKSPACE", ".")
    log_path = Path(workspace) / "memory" / "action_log.jsonl"
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"anchor_type": anchor_type, "anchor": anchor.lower()}) + "\n")
    except Exception:
        pass


def get_csv_path() -> Path:
    workspace = os.environ.get("WB_WORKSPACE")
    if not workspace:
        print("Error: WB_WORKSPACE environment variable not set", file=sys.stderr)
        sys.exit(1)
    return Path(workspace) / "calendar_events.csv"


def load_events(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def save_events(path: Path, rows: list[dict]) -> None:
    if not rows:
        path.write_text("event_id,event_name,participant_email,event_start,duration\n", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)


def cmd_list(args) -> None:
    path = get_csv_path()
    rows = load_events(path)
    rows.sort(key=lambda r: r.get("event_start", ""))
    if hasattr(args, "date") and args.date:
        rows = [r for r in rows if r.get("event_start", "").startswith(args.date)]
    if hasattr(args, "start") and args.start:
        rows = [r for r in rows if r.get("event_start", "") >= args.start]
    if hasattr(args, "end") and args.end:
        end_val = args.end if " " in args.end else args.end + " 23:59:59"
        rows = [r for r in rows if r.get("event_start", "") <= end_val]
    if not rows:
        print("No events.")
        return
    for r in rows:
        print(f"[{r['event_id']}] {r['event_name']}  |  {r['event_start']}  |  {r['duration']}min  |  {r['participant_email']}")


def cmd_create(args) -> None:
    path = get_csv_path()
    rows = load_events(path)
    new_id = f"{int(uuid.uuid4().int % 100000):08d}"
    rows.append({
        "event_id": new_id,
        "event_name": args.name,
        "participant_email": args.participant,
        "event_start": args.start,
        "duration": args.duration,
    })
    save_events(path, rows)
    print(f"Created. event_id={new_id}")
    _log_action("name", args.name)


def cmd_update(args) -> None:
    path = get_csv_path()
    rows = load_events(path)
    match = [r for r in rows if r["event_id"] == args.id]
    if not match:
        print(f"Error: event_id={args.id} not found", file=sys.stderr)
        sys.exit(1)
    valid_fields = {"event_name", "participant_email", "event_start", "duration"}
    if args.field not in valid_fields:
        print(f"Error: field must be one of {valid_fields}", file=sys.stderr)
        sys.exit(1)
    match[0][args.field] = args.value
    save_events(path, rows)
    print(f"Updated event_id={args.id}: {args.field}={args.value}")
    _log_action("entity_id", args.id)


def cmd_delete(args) -> None:
    path = get_csv_path()
    rows = load_events(path)
    before = len(rows)
    rows = [r for r in rows if r["event_id"] != args.id]
    if len(rows) == before:
        print(f"Error: event_id={args.id} not found", file=sys.stderr)
        sys.exit(1)
    save_events(path, rows)
    print(f"Deleted event_id={args.id}")
    _log_action("entity_id", args.id)


def cmd_delete_many(args) -> None:
    path = get_csv_path()
    rows = load_events(path)
    ids = set(i.strip() for i in args.ids.split(","))
    before = len(rows)
    rows = [r for r in rows if r["event_id"] not in ids]
    deleted = before - len(rows)
    save_events(path, rows)
    print(f"Deleted {deleted} event(s).")
    for _id in ids:
        _log_action("entity_id", _id)


def main() -> None:
    parser = argparse.ArgumentParser(prog="wb-calendar")
    sub = parser.add_subparsers(dest="command", required=True)

    p_list = sub.add_parser("list")
    p_list.add_argument("--date", default=None,
                        help="Filter by date prefix e.g. 2026-12-13 or 2026-12")
    p_list.add_argument("--start", default=None,
                        help="Filter events on or after this datetime e.g. '2026-12-13 00:00:00'")
    p_list.add_argument("--end", default=None,
                        help="Filter events on or before this datetime e.g. '2026-12-13 23:59:59'")

    p_create = sub.add_parser("create")
    p_create.add_argument("--name", required=True)
    p_create.add_argument("--participant", required=True)
    p_create.add_argument("--start", required=True)
    p_create.add_argument("--duration", required=True)

    p_update = sub.add_parser("update")
    p_update.add_argument("--id", required=True)
    p_update.add_argument("--field", required=True)
    p_update.add_argument("--value", required=True)

    p_del = sub.add_parser("delete")
    p_del.add_argument("--id", required=True)

    p_delm = sub.add_parser("delete-many")
    p_delm.add_argument("--ids", required=True)

    args = parser.parse_args()
    {
        "list": cmd_list,
        "create": cmd_create,
        "update": cmd_update,
        "delete": cmd_delete,
        "delete-many": cmd_delete_many,
    }[args.command](args)


if __name__ == "__main__":
    main()
