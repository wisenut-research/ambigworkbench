#!/usr/bin/env python3
"""
wb-crm: WorkBench simulated CRM CLI.
Reads/writes experiment/workspace/<soul>/customer_relationship_manager_data.csv

Commands:
  list   [--assignee <email>] [--status <status>] [--product <product>]
  add    --name <name> --assignee <email> --status <status>
  update --id <customer_id> --field <field> --value <value>
  delete --id <customer_id>
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
        pass  # never fail the main operation due to logging


def get_csv_path() -> Path:
    workspace = os.environ.get("WB_WORKSPACE")
    if not workspace:
        print("Error: WB_WORKSPACE environment variable not set", file=sys.stderr)
        sys.exit(1)
    return Path(workspace) / "customer_relationship_manager_data.csv"


def load_customers(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def save_customers(path: Path, rows: list[dict]) -> None:
    if not rows:
        path.write_text(
            "customer_id,assigned_to_email,customer_name,customer_email,"
            "customer_phone,last_contact_date,product_interest,status,follow_up_by,notes\n",
            encoding="utf-8",
        )
        return
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)


def cmd_list(args) -> None:
    path = get_csv_path()
    rows = load_customers(path)
    if args.assignee:
        rows = [r for r in rows if args.assignee.lower() in r.get("assigned_to_email", "").lower()]
    if args.status:
        rows = [r for r in rows if args.status.lower() == r.get("status", "").lower()]
    if args.product:
        rows = [r for r in rows if args.product.lower() in r.get("product_interest", "").lower()]
    if not rows:
        print("No customers found.")
        return
    for r in rows:
        print(f"[{r['customer_id']}] {r['customer_name']}  |  {r['status']}  |  {r['product_interest']}  |  assigned:{r['assigned_to_email']}")


def cmd_add(args) -> None:
    path = get_csv_path()
    rows = load_customers(path)
    new_id = f"{int(uuid.uuid4().int % 100000):08d}"
    fieldnames = ["customer_id", "assigned_to_email", "customer_name", "customer_email",
                  "customer_phone", "last_contact_date", "product_interest", "status", "follow_up_by", "notes"]
    rows.append({k: "" for k in fieldnames} | {
        "customer_id": new_id,
        "assigned_to_email": args.assignee,
        "customer_name": args.name,
        "status": args.status,
    })
    save_customers(path, rows)
    print(f"Added. customer_id={new_id}")
    _log_action("name", args.name)


def cmd_update(args) -> None:
    path = get_csv_path()
    rows = load_customers(path)
    match = [r for r in rows if r["customer_id"] == args.id]
    if not match:
        print(f"Error: customer_id={args.id} not found", file=sys.stderr)
        sys.exit(1)
    valid_fields = {"assigned_to_email", "customer_name", "customer_email", "status",
                    "product_interest", "last_contact_date", "follow_up_by", "notes"}
    if args.field not in valid_fields:
        print(f"Error: field must be one of {valid_fields}", file=sys.stderr)
        sys.exit(1)
    match[0][args.field] = args.value
    save_customers(path, rows)
    print(f"Updated customer_id={args.id}: {args.field}={args.value}")
    _log_action("entity_id", args.id)


def cmd_delete(args) -> None:
    path = get_csv_path()
    rows = load_customers(path)
    before = len(rows)
    rows = [r for r in rows if r["customer_id"] != args.id]
    if len(rows) == before:
        print(f"Error: customer_id={args.id} not found", file=sys.stderr)
        sys.exit(1)
    save_customers(path, rows)
    print(f"Deleted customer_id={args.id}")
    _log_action("entity_id", args.id)


def cmd_delete_many(args) -> None:
    path = get_csv_path()
    rows = load_customers(path)
    ids = set(i.strip() for i in args.ids.split(","))
    before = len(rows)
    rows = [r for r in rows if r["customer_id"] not in ids]
    deleted = before - len(rows)
    save_customers(path, rows)
    print(f"Deleted {deleted} customer(s).")
    for _id in ids:
        _log_action("entity_id", _id)


def main() -> None:
    parser = argparse.ArgumentParser(prog="wb-crm")
    sub = parser.add_subparsers(dest="command", required=True)

    p_list = sub.add_parser("list")
    p_list.add_argument("--assignee", default=None)
    p_list.add_argument("--status", default=None)
    p_list.add_argument("--product", default=None)

    p_add = sub.add_parser("add")
    p_add.add_argument("--name", required=True)
    p_add.add_argument("--assignee", required=True)
    p_add.add_argument("--status", required=True)

    p_update = sub.add_parser("update")
    p_update.add_argument("--id", required=True)
    p_update.add_argument("--field", required=True)
    p_update.add_argument("--value", required=True)

    p_del = sub.add_parser("delete")
    p_del.add_argument("--id", required=True)

    p_delm = sub.add_parser("delete-many")
    p_delm.add_argument("--ids", required=True)

    args = parser.parse_args()
    {"list": cmd_list, "add": cmd_add, "update": cmd_update,
     "delete": cmd_delete, "delete-many": cmd_delete_many}[args.command](args)


if __name__ == "__main__":
    main()
