#!/usr/bin/env python3
"""
wb-email: WorkBench simulated email CLI.
Reads/writes experiment/workspace/<soul>/emails.csv

Commands:
  list                          List inbox emails (most recent first)
  read    --id <email_id>       Show full email body
  contacts                      List all known senders/recipients with names
  send    --to <email> --subject <subject> --body <body>
  reply   --id <email_id> --body <body>
  forward --id <email_id> --to <email>
  delete  --id <email_id>
  delete-many --ids <id1,id2,...>
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import uuid
from datetime import datetime, timezone
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
    return Path(workspace) / "emails.csv"


def load_emails(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def save_emails(path: Path, rows: list[dict]) -> None:
    if not rows:
        path.write_text("email_id,inbox/outbox,sender/recipient,subject,sent_datetime,body\n", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)


def cmd_list(args) -> None:
    path = get_csv_path()
    rows = load_emails(path)
    inbox = [r for r in rows if r.get("inbox/outbox", "").lower() == "inbox"]
    inbox.sort(key=lambda r: r.get("sent_datetime", ""), reverse=True)
    if not inbox:
        print("No emails in inbox.")
        return
    for r in inbox:
        print(f"[{r['email_id']}] From: {r['sender/recipient']}  |  {r['subject']}  |  {r['sent_datetime']}")


def cmd_read(args) -> None:
    path = get_csv_path()
    rows = load_emails(path)
    match = [r for r in rows if r["email_id"] == args.id]
    if not match:
        print(f"Error: email_id={args.id} not found", file=sys.stderr)
        sys.exit(1)
    r = match[0]
    print(f"ID:       {r['email_id']}")
    print(f"Type:     {r['inbox/outbox']}")
    print(f"From/To:  {r['sender/recipient']}")
    print(f"Subject:  {r['subject']}")
    print(f"Date:     {r['sent_datetime']}")
    print(f"Body:\n{r['body']}")


def cmd_contacts(args) -> None:
    path = get_csv_path()
    rows = load_emails(path)
    seen: dict[str, str] = {}
    for r in rows:
        email = r.get("sender/recipient", "").strip()
        if email and email not in seen:
            # Derive name from email local part (e.g. kofi.boateng@atlas.com -> Kofi Boateng)
            local = email.split("@")[0].replace(".", " ").title()
            seen[email] = local
    for email, name in sorted(seen.items(), key=lambda x: x[1]):
        print(f"{name:<25} {email}")


def cmd_send(args) -> None:
    path = get_csv_path()
    rows = load_emails(path)
    new_id = f"{int(uuid.uuid4().int % 100000):08d}"
    ts = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    rows.append({
        "email_id": new_id,
        "inbox/outbox": "outbox",
        "sender/recipient": args.to,
        "subject": args.subject,
        "sent_datetime": ts,
        "body": args.body,
    })
    save_emails(path, rows)
    print(f"Sent. email_id={new_id}")
    _log_action("recipient", args.to)


def cmd_reply(args) -> None:
    path = get_csv_path()
    rows = load_emails(path)
    orig = next((r for r in rows if r["email_id"] == args.id), None)
    if not orig:
        print(f"Error: email_id={args.id} not found", file=sys.stderr)
        sys.exit(1)
    new_id = f"{int(uuid.uuid4().int % 100000):08d}"
    ts = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    rows.append({
        "email_id": new_id,
        "inbox/outbox": "outbox",
        "sender/recipient": orig["sender/recipient"],
        "subject": f"Re: {orig['subject']}",
        "sent_datetime": ts,
        "body": args.body,
    })
    save_emails(path, rows)
    print(f"Replied. email_id={new_id}")
    _log_action("entity_id", args.id)


def cmd_forward(args) -> None:
    path = get_csv_path()
    rows = load_emails(path)
    orig = next((r for r in rows if r["email_id"] == args.id), None)
    if not orig:
        print(f"Error: email_id={args.id} not found", file=sys.stderr)
        sys.exit(1)
    new_id = f"{int(uuid.uuid4().int % 100000):08d}"
    ts = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    rows.append({
        "email_id": new_id,
        "inbox/outbox": "outbox",
        "sender/recipient": args.to,
        "subject": f"Fwd: {orig['subject']}",
        "sent_datetime": ts,
        "body": orig["body"],
    })
    save_emails(path, rows)
    print(f"Forwarded. email_id={new_id}")
    _log_action("recipient", args.to)


def cmd_delete(args) -> None:
    path = get_csv_path()
    rows = load_emails(path)
    before = len(rows)
    rows = [r for r in rows if r["email_id"] != args.id]
    if len(rows) == before:
        print(f"Error: email_id={args.id} not found", file=sys.stderr)
        sys.exit(1)
    save_emails(path, rows)
    print(f"Deleted email_id={args.id}")
    _log_action("entity_id", args.id)


def cmd_delete_many(args) -> None:
    path = get_csv_path()
    rows = load_emails(path)
    ids = set(i.strip() for i in args.ids.split(","))
    before = len(rows)
    rows = [r for r in rows if r["email_id"] not in ids]
    deleted = before - len(rows)
    save_emails(path, rows)
    print(f"Deleted {deleted} email(s).")
    for _id in ids:
        _log_action("entity_id", _id)


def main() -> None:
    parser = argparse.ArgumentParser(prog="wb-email")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list")
    sub.add_parser("contacts")

    p_read = sub.add_parser("read")
    p_read.add_argument("--id", required=True)

    p_send = sub.add_parser("send")
    p_send.add_argument("--to", required=True)
    p_send.add_argument("--subject", required=True)
    p_send.add_argument("--body", required=True)

    p_reply = sub.add_parser("reply")
    p_reply.add_argument("--id", required=True)
    p_reply.add_argument("--body", required=True)

    p_fwd = sub.add_parser("forward")
    p_fwd.add_argument("--id", required=True)
    p_fwd.add_argument("--to", required=True)

    p_del = sub.add_parser("delete")
    p_del.add_argument("--id", required=True)

    p_delm = sub.add_parser("delete-many")
    p_delm.add_argument("--ids", required=True, help="Comma-separated email_ids")

    args = parser.parse_args()
    {
        "list": cmd_list,
        "contacts": cmd_contacts,
        "read": cmd_read,
        "send": cmd_send,
        "reply": cmd_reply,
        "forward": cmd_forward,
        "delete": cmd_delete,
        "delete-many": cmd_delete_many,
    }[args.command](args)


if __name__ == "__main__":
    main()
