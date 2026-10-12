#!/usr/bin/env python3
"""
wb-project: WorkBench simulated project management CLI.
Reads/writes experiment/workspace/<soul>/project_tasks.csv

Commands:
  list   [--assignee <email>] [--board <board>] [--status <list_name>]
  create --name <name> --board <board> --assignee <email> --due <date> --status <list_name>
  update --id <task_id> --field <field> --value <value>
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
    return Path(workspace) / "project_tasks.csv"


def load_tasks(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def save_tasks(path: Path, rows: list[dict]) -> None:
    if not rows:
        path.write_text("task_id,task_name,assigned_to_email,list_name,due_date,board\n", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)


def cmd_list(args) -> None:
    path = get_csv_path()
    rows = load_tasks(path)
    if args.assignee:
        rows = [r for r in rows if args.assignee.lower() in r.get("assigned_to_email", "").lower()]
    if args.board:
        rows = [r for r in rows if args.board.lower() in r.get("board", "").lower()]
    if args.status:
        rows = [r for r in rows if args.status.lower() in r.get("list_name", "").lower()]
    if not rows:
        print("No tasks found.")
        return
    for r in rows:
        print(f"[{r['task_id']}] {r['task_name']}  |  {r['list_name']}  |  {r['board']}  |  {r['assigned_to_email']}  |  due:{r['due_date']}")


def cmd_create(args) -> None:
    path = get_csv_path()
    rows = load_tasks(path)
    new_id = f"{int(uuid.uuid4().int % 100000):08d}"
    rows.append({
        "task_id": new_id,
        "task_name": args.name,
        "assigned_to_email": args.assignee,
        "list_name": args.status,
        "due_date": args.due,
        "board": args.board,
    })
    save_tasks(path, rows)
    print(f"Created. task_id={new_id}")
    _log_action("name", args.name)


def cmd_update(args) -> None:
    path = get_csv_path()
    rows = load_tasks(path)
    match = [r for r in rows if r["task_id"] == args.id]
    if not match:
        print(f"Error: task_id={args.id} not found", file=sys.stderr)
        sys.exit(1)
    valid_fields = {"task_name", "assigned_to_email", "list_name", "due_date", "board"}
    if args.field not in valid_fields:
        print(f"Error: field must be one of {valid_fields}", file=sys.stderr)
        sys.exit(1)
    match[0][args.field] = args.value
    save_tasks(path, rows)
    print(f"Updated task_id={args.id}: {args.field}={args.value}")
    _log_action("entity_id", args.id)


def main() -> None:
    parser = argparse.ArgumentParser(prog="wb-project")
    sub = parser.add_subparsers(dest="command", required=True)

    p_list = sub.add_parser("list")
    p_list.add_argument("--assignee", default=None)
    p_list.add_argument("--board", default=None)
    p_list.add_argument("--status", default=None)

    p_create = sub.add_parser("create")
    p_create.add_argument("--name", required=True)
    p_create.add_argument("--board", required=True)
    p_create.add_argument("--assignee", required=True)
    p_create.add_argument("--due", required=True)
    p_create.add_argument("--status", required=True)

    p_update = sub.add_parser("update")
    p_update.add_argument("--id", required=True)
    p_update.add_argument("--field", required=True)
    p_update.add_argument("--value", required=True)

    args = parser.parse_args()
    {"list": cmd_list, "create": cmd_create, "update": cmd_update}[args.command](args)


if __name__ == "__main__":
    main()
