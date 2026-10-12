"""
evaluator.py

Parse the WorkBench original_answer and decide end-to-end success by
comparing the post-task CSV state against it.

Decision rules:
  - email.delete_email     -> email_id must be absent from emails.csv
  - email.send_email       -> outbox row matching recipient + subject exists
  - email.reply_email      -> outbox row with "Re:" prefix + recipient exists
  - email.forward_email    -> outbox row with "Fwd:" prefix + recipient exists
  - calendar.create_event  -> row matching event_name + participant_email exists
  - calendar.delete_event  -> event_id must be absent from calendar_events.csv
  - calendar.update_event  -> event_id row has field == new_value
  - project_management.create_task  -> row matching task_name + board exists
  - project_management.update_task  -> task_id row has field == new_value
  - crm.add_customer       -> row matching customer_name exists
  - crm.delete_customer    -> customer_id must be absent from the csv
  - crm.update_customer    -> customer_id row has field == new_value
  - analytics.create_plot  -> read-only; always True (output judged separately)
"""

from __future__ import annotations

import ast
import csv
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class FuncCall:
    domain: str      # e.g. "email"
    action: str      # e.g. "delete_email"
    args: dict[str, Any]


@dataclass
class EvalResult:
    e2e_success: bool
    total_checks: int
    passed_checks: int
    details: list[dict] = field(default_factory=list)

    @property
    def score(self) -> float:
        return self.passed_checks / self.total_checks if self.total_checks else 0.0

    def to_dict(self) -> dict:
        return {
            "e2e_success": self.e2e_success,
            "total_checks": self.total_checks,
            "passed_checks": self.passed_checks,
            "score": round(self.score, 3),
            "details": self.details,
        }


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

def parse_original_answer(answer_str: str) -> list[FuncCall]:
    """
    Parse WorkBench answer string into FuncCall list.

    Input:  "['email.delete_email.func(email_id=\"00000479\")', ...]"
    Output: [FuncCall(domain='email', action='delete_email', args={'email_id': '00000479'})]
    """
    if not answer_str or answer_str.strip() in ("", "[]", "['']"):
        return []

    try:
        raw_list: list[str] = ast.literal_eval(answer_str)
    except Exception:
        return []

    calls = []
    for raw in raw_list:
        match = re.match(r'(\w+)\.(\w+)\.func\((.*)\)$', raw.strip(), re.DOTALL)
        if not match:
            continue
        domain, action, args_str = match.groups()

        # Parse kwargs: key="value" or key='value' or key=number
        args: dict[str, Any] = {}
        for kv in re.finditer(r'(\w+)=("(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\'|\S+?)(?:,\s*|$)', args_str):
            key = kv.group(1)
            val = kv.group(2).strip()
            # Strip surrounding quotes
            if (val.startswith('"') and val.endswith('"')) or \
               (val.startswith("'") and val.endswith("'")):
                val = val[1:-1]
            args[key] = val

        calls.append(FuncCall(domain=domain, action=action, args=args))

    return calls


# ---------------------------------------------------------------------------
# CSV loaders
# ---------------------------------------------------------------------------

def _load_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _s(value: Any) -> str:
    """Return a safe string for possibly malformed CSV cells."""
    return "" if value is None else str(value)


def _lower(value: Any) -> str:
    return _s(value).lower()


# ---------------------------------------------------------------------------
# Per-function evaluators
# ---------------------------------------------------------------------------

def _check_email_delete(args: dict, workspace: Path) -> tuple[bool, str]:
    email_id = args.get("email_id", "")
    rows = _load_csv(workspace / "emails.csv")
    exists = any(_s(r.get("email_id")) == email_id for r in rows)
    ok = not exists
    return ok, f"email_id={email_id} {'not found (deleted OK)' if ok else 'still exists (not deleted X)'}"


def _check_email_send(args: dict, workspace: Path) -> tuple[bool, str]:
    recipient = _lower(args.get("recipient"))
    subject = _lower(args.get("subject"))
    rows = _load_csv(workspace / "emails.csv")
    outbox = [r for r in rows if _lower(r.get("inbox/outbox")) == "outbox"]
    ok = any(
        recipient in _lower(r.get("sender/recipient")) and
        subject in _lower(r.get("subject"))
        for r in outbox
    )
    return ok, f"send to {recipient!r} subject={subject!r}: {'found OK' if ok else 'not found X'}"


def _check_email_reply(args: dict, workspace: Path) -> tuple[bool, str]:
    email_id = args.get("email_id", "")
    rows = _load_csv(workspace / "emails.csv")
    # Find original email to get recipient
    orig = next((r for r in rows if _s(r.get("email_id")) == email_id), None)
    outbox = [r for r in rows if _lower(r.get("inbox/outbox")) == "outbox"]
    if orig:
        sender = _lower(orig.get("sender/recipient"))
        ok = any(
            "re:" in _lower(r.get("subject")) and
            sender in _lower(r.get("sender/recipient"))
            for r in outbox
        )
    else:
        # Original deleted; check any Re: reply exists
        ok = any("re:" in _lower(r.get("subject")) for r in outbox)
    return ok, f"reply to email_id={email_id}: {'found OK' if ok else 'not found X'}"


def _check_email_forward(args: dict, workspace: Path) -> tuple[bool, str]:
    recipient = _lower(args.get("recipient"))
    rows = _load_csv(workspace / "emails.csv")
    outbox = [r for r in rows if _lower(r.get("inbox/outbox")) == "outbox"]
    ok = any(
        "fwd:" in _lower(r.get("subject")) and
        recipient in _lower(r.get("sender/recipient"))
        for r in outbox
    )
    return ok, f"forward to {recipient!r}: {'found OK' if ok else 'not found X'}"


def _check_calendar_create(args: dict, workspace: Path) -> tuple[bool, str]:
    name = _lower(args.get("event_name"))
    participant = _lower(args.get("participant_email"))
    rows = _load_csv(workspace / "calendar_events.csv")
    ok = any(
        name in _lower(r.get("event_name")) and
        participant in _lower(r.get("participant_email"))
        for r in rows
    )
    return ok, f"event {name!r} with {participant!r}: {'found OK' if ok else 'not found X'}"


def _check_calendar_delete(args: dict, workspace: Path) -> tuple[bool, str]:
    event_id = args.get("event_id", "")
    rows = _load_csv(workspace / "calendar_events.csv")
    exists = any(_s(r.get("event_id")) == event_id for r in rows)
    ok = not exists
    return ok, f"event_id={event_id} {'not found (deleted OK)' if ok else 'still exists X'}"


def _check_calendar_update(args: dict, workspace: Path) -> tuple[bool, str]:
    event_id = args.get("event_id", "")
    field = args.get("field", "")
    new_value = _lower(args.get("new_value"))
    rows = _load_csv(workspace / "calendar_events.csv")
    row = next((r for r in rows if _s(r.get("event_id")) == event_id), None)
    if not row:
        return False, f"event_id={event_id} not found X"
    actual = _lower(row.get(field))
    ok = new_value in actual
    return ok, f"event_id={event_id} {field}={actual!r} (expected {new_value!r}): {'OK' if ok else 'X'}"


def _check_project_create(args: dict, workspace: Path) -> tuple[bool, str]:
    name = _lower(args.get("task_name"))
    board = _lower(args.get("board"))
    rows = _load_csv(workspace / "project_tasks.csv")
    ok = any(
        name in _lower(r.get("task_name")) and
        board in _lower(r.get("board"))
        for r in rows
    )
    return ok, f"task {name!r} on {board!r}: {'found OK' if ok else 'not found X'}"


def _check_project_update(args: dict, workspace: Path) -> tuple[bool, str]:
    task_id = args.get("task_id", "")
    field = args.get("field", "")
    new_value = _lower(args.get("new_value"))
    rows = _load_csv(workspace / "project_tasks.csv")
    row = next((r for r in rows if _s(r.get("task_id")) == task_id), None)
    if not row:
        return False, f"task_id={task_id} not found X"
    actual = _lower(row.get(field))
    ok = new_value in actual
    return ok, f"task_id={task_id} {field}={actual!r} (expected {new_value!r}): {'OK' if ok else 'X'}"


def _check_crm_add(args: dict, workspace: Path) -> tuple[bool, str]:
    name = _lower(args.get("customer_name"))
    rows = _load_csv(workspace / "customer_relationship_manager_data.csv")
    ok = any(name in _lower(r.get("customer_name")) for r in rows)
    return ok, f"customer {name!r}: {'found OK' if ok else 'not found X'}"


def _check_crm_delete(args: dict, workspace: Path) -> tuple[bool, str]:
    customer_id = args.get("customer_id", "")
    rows = _load_csv(workspace / "customer_relationship_manager_data.csv")
    exists = any(_s(r.get("customer_id")) == customer_id for r in rows)
    ok = not exists
    return ok, f"customer_id={customer_id} {'not found (deleted OK)' if ok else 'still exists X'}"


def _check_crm_update(args: dict, workspace: Path) -> tuple[bool, str]:
    customer_id = args.get("customer_id", "")
    field = args.get("field", "")
    new_value = _lower(args.get("new_value"))
    rows = _load_csv(workspace / "customer_relationship_manager_data.csv")
    row = next((r for r in rows if _s(r.get("customer_id")) == customer_id), None)
    if not row:
        return False, f"customer_id={customer_id} not found X"
    actual = _lower(row.get(field))
    ok = new_value in actual
    return ok, f"customer_id={customer_id} {field}={actual!r} (expected {new_value!r}): {'OK' if ok else 'X'}"


def _check_analytics_plot(args: dict, workspace: Path) -> tuple[bool, str]:
    time_min   = args.get("time_min", "")
    time_max   = args.get("time_max", "")
    metric     = args.get("value_to_plot", "")
    plot_type  = args.get("plot_type", "")
    # filename convention: {time_min}_{time_max}_{value_to_plot}_{plot_type}.png
    expected_name = f"{time_min}_{time_max}_{metric}_{plot_type}.png"
    plots_dir = workspace / "plots"
    ok = (plots_dir / expected_name).exists()
    return ok, f"plot file {expected_name}: {'found OK' if ok else 'not found X'}"


# ---------------------------------------------------------------------------
# Dispatch table
# ---------------------------------------------------------------------------

_CHECKERS = {
    ("email", "delete_email"):                          _check_email_delete,
    ("email", "send_email"):                            _check_email_send,
    ("email", "reply_email"):                           _check_email_reply,
    ("email", "forward_email"):                         _check_email_forward,
    ("calendar", "create_event"):                       _check_calendar_create,
    ("calendar", "delete_event"):                       _check_calendar_delete,
    ("calendar", "update_event"):                       _check_calendar_update,
    ("project_management", "create_task"):              _check_project_create,
    ("project_management", "update_task"):              _check_project_update,
    ("customer_relationship_manager", "add_customer"):  _check_crm_add,
    ("customer_relationship_manager", "delete_customer"): _check_crm_delete,
    ("customer_relationship_manager", "update_customer"): _check_crm_update,
    ("analytics", "create_plot"):                         _check_analytics_plot,
}


# ---------------------------------------------------------------------------
# Main evaluate function
# ---------------------------------------------------------------------------

def evaluate(original_answer: str, workspace: Path) -> EvalResult:
    """
    Parse original_answer and check each expected operation against the
    current CSV state in workspace.

    Returns EvalResult with e2e_success=True only if ALL checks pass.
    """
    calls = parse_original_answer(original_answer)

    if not calls:
        # No checkable operations (e.g. analytics-only)
        return EvalResult(e2e_success=True, total_checks=0, passed_checks=0,
                          details=[{"note": "no checkable operations (analytics/read-only)"}])

    details = []
    passed = 0

    for call in calls:
        key = (call.domain, call.action)
        checker = _CHECKERS.get(key)

        if checker is None:
            # analytics.create_plot or unknown -> skip, count as pass
            details.append({"func": f"{call.domain}.{call.action}", "result": "skipped (read-only)", "passed": True})
            passed += 1
            continue

        ok, msg = checker(call.args, workspace)
        details.append({
            "func": f"{call.domain}.{call.action}",
            "args": call.args,
            "passed": ok,
            "detail": msg,
        })
        if ok:
            passed += 1

    total = len(calls)
    return EvalResult(
        e2e_success=(passed == total),
        total_checks=total,
        passed_checks=passed,
        details=details,
    )


# ---------------------------------------------------------------------------
# CLI for manual testing
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse
    import json
    import sys

    EXPERIMENT_DIR = Path(__file__).resolve().parents[1]
    WORKSPACE_DIR = EXPERIMENT_DIR / "workspace"

    parser = argparse.ArgumentParser(description="Evaluate E2E task success")
    parser.add_argument("--answer", required=True, help="original_answer string from WorkBench")
    parser.add_argument("--soul", required=True, choices=["soul-a", "soul-b", "soul-c"])
    args = parser.parse_args()

    workspace = WORKSPACE_DIR / args.soul
    result = evaluate(args.answer, workspace)
    print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
    sys.exit(0 if result.e2e_success else 1)
