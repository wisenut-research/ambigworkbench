"""
action_precision.py

Auxiliary metric: did the agent execute exactly the intended number of unique actions?

Division of labor with state eval (CSV state check):
  state eval       -> did it touch the right targets (correctness)
  action_precision -> did it touch only as many as intended (precision / over-action)

Anchor types:
  entity_id  : delete / update / reply  ->  --id value
  recipient  : send / forward           ->  --to value
  name       : create / add             ->  --name value (event_name / task_name / customer_name)
  metric     : analytics plot           ->  --metric value (ground truth: value_to_plot)
"""

from __future__ import annotations

import ast
import json
import re
from dataclasses import dataclass, field
from pathlib import Path


# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------

@dataclass
class ActionPrecisionResult:
    applicable: bool          # False = ground truth has no anchors, not measurable (N/A)
    gt_count: int             # number of unique ground-truth anchors
    exec_count: int           # number of unique anchors in agent write ops
    match: bool               # gt_count == exec_count
    anchor_type: str          # entity_id / recipient / name / metric / mixed / none
    gt_anchors: list[str] = field(default_factory=list)
    exec_anchors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "applicable": self.applicable,
            "gt_count": self.gt_count,
            "exec_count": self.exec_count,
            "match": self.match,
            "anchor_type": self.anchor_type,
            "gt_anchors": self.gt_anchors,
            "exec_anchors": self.exec_anchors,
        }


# ---------------------------------------------------------------------------
# Ground-truth anchor extraction
# ---------------------------------------------------------------------------

# function name -> (anchor_type, param_name)
_GT_ANCHOR_MAP: dict[str, tuple[str, str]] = {
    "email.delete_email":                          ("entity_id", "email_id"),
    "email.reply_email":                           ("entity_id", "email_id"),
    "email.forward_email":                         ("recipient", "recipient"),
    "email.send_email":                            ("recipient", "recipient"),
    "calendar.delete_event":                       ("entity_id", "event_id"),
    "calendar.update_event":                       ("entity_id", "event_id"),
    "calendar.create_event":                       ("name",      "event_name"),
    "customer_relationship_manager.delete_customer": ("entity_id", "customer_id"),
    "customer_relationship_manager.update_customer": ("entity_id", "customer_id"),
    "customer_relationship_manager.add_customer":    ("name",      "customer_name"),
    "project_management.update_task":              ("entity_id", "task_id"),
    "project_management.create_task":              ("name",      "task_name"),
    "analytics.create_plot":                       ("metric",    "value_to_plot"),
}


def _extract_gt_anchors(original_answer: str) -> tuple[set[str], str]:
    """
    Extract the unique anchor set and anchor type from the ground-truth answer string.
    Returns: (anchors, anchor_type)
    """
    try:
        funcs: list[str] = ast.literal_eval(original_answer)
    except (ValueError, SyntaxError):
        return set(), "none"

    anchors: set[str] = set()
    anchor_types: set[str] = set()

    for func_str in funcs:
        # extract the function name from "some.func_name.func(param=...)"
        m = re.match(r"([\w.]+)\.func\(", func_str)
        if not m:
            continue
        func_name = m.group(1)

        if func_name not in _GT_ANCHOR_MAP:
            continue
        anchor_type, param_name = _GT_ANCHOR_MAP[func_name]

        # extract values via param_name="value" patterns
        vm = re.search(rf'{param_name}="([^"]+)"', func_str)
        if vm:
            anchors.add(vm.group(1).lower())
            anchor_types.add(anchor_type)

    if not anchor_types:
        return set(), "none"

    anchor_type_str = list(anchor_types)[0] if len(anchor_types) == 1 else "mixed"
    return anchors, anchor_type_str


# ---------------------------------------------------------------------------
# Executed-command anchor extraction
# ---------------------------------------------------------------------------

# Read ops are excluded from anchor extraction
_READ_SUBCOMMANDS = {"list", "read", "get", "query", "metrics"}


def _normalize_cmd(cmd: str) -> str:
    """Normalize by dropping WB_WORKSPACE=... prefix, cd ... &&, and python3 prefix."""
    # for `cd /path && ...`, keep only the part after &&
    if "&&" in cmd:
        cmd = cmd[cmd.index("&&") + 2:]
    cmd = re.sub(r"WB_WORKSPACE=\S+\s*", "", cmd)
    cmd = re.sub(r"python3?\s+", "", cmd)
    return cmd.strip()


_SHELL_META = re.compile(r"[$`<>|{}\[\]\\]")


def _is_valid_anchor(value: str) -> bool:
    """Check the anchor value is valid (no shell metacharacters or placeholders)."""
    return not _SHELL_META.search(value)


def _extract_flag(cmd: str, flag: str) -> str | None:
    """Extract the value from '--flag value' or '--flag "quoted value"'."""
    m = re.search(rf'{flag}\s+"([^"]+)"', cmd)
    if m:
        return m.group(1).lower()
    m = re.search(rf"{flag}\s+'([^']+)'", cmd)
    if m:
        return m.group(1).lower()
    m = re.search(rf"{flag}\s+(\S+)", cmd)
    if m:
        return m.group(1).lower()
    return None


def _extract_exec_anchor(script: str, subcommand: str, cmd: str) -> str | None:
    """Extract the anchor value for a script + subcommand combination."""

    # entity_id family: delete / update / reply / delete-many
    if subcommand in ("delete", "update"):
        if subcommand == "delete" and "--ids" in cmd:
            # wb-crm.py delete-many --ids id1,id2,id3 -> caller handles each id
            return None  # handled by the delete-many handler below
        return _extract_flag(cmd, "--id")

    if subcommand == "reply" and "wb-email.py" in script:
        return _extract_flag(cmd, "--id")

    # recipient family: send / forward
    if subcommand in ("send", "forward") and "wb-email.py" in script:
        return _extract_flag(cmd, "--to")

    # name family: create / add
    if subcommand == "create":
        return _extract_flag(cmd, "--name")
    if subcommand == "add" and "wb-crm.py" in script:
        return _extract_flag(cmd, "--name")

    # metric family: analytics plot
    if subcommand == "plot" and "wb-analytics.py" in script:
        return _extract_flag(cmd, "--metric")

    return None


def _extract_bash_loop_anchors(raw_cmd: str) -> set[str]:
    """
    Extract anchors from bash -c '...' loop commands.

    Supported patterns:
      ids=('id1' 'id2' ...) ... wb-*.py update/delete --id $id ...
      ids=(id1 id2 ...) ... wb-*.py update/delete --id $id ...

    temp-file-driven loops (done < /tmp/file) cannot be extracted without runtime info -> return empty set.
    """
    anchors: set[str] = set()

    # extract the body of bash -c '...' or bash -c "..."
    inner = None
    m = re.search(r'bash\s+-c\s+\'(.*?)\'', raw_cmd, re.DOTALL)
    if m:
        inner = m.group(1)
    else:
        m = re.search(r'bash\s+-c\s+"(.*?)"', raw_cmd, re.DOTALL)
        if m:
            inner = m.group(1)

    if not inner:
        return anchors

    # temp-file-driven loops cannot be parsed
    if "< /tmp/" in inner or "done <" in inner:
        return anchors

    # check whether a wb-*.py write subcommand is present
    if not re.search(r'wb-\S+\.py\s+(update|delete|create|send|forward|add|reply|plot)', inner):
        return anchors

    # extract IDs from an ids=(...) array
    array_m = re.search(r'ids=\(([^)]+)\)', inner)
    if array_m:
        raw_ids = array_m.group(1)
        for token in re.findall(r"'([^']+)'|\"([^\"]+)\"|(\S+)", raw_ids):
            val = (token[0] or token[1] or token[2]).strip().lower()
            if val and _is_valid_anchor(val):
                anchors.add(val)

    return anchors


def _extract_exec_anchors(commands: list[str]) -> set[str]:
    """
    Extract the unique anchor set from the list of write-op commands.
    Read ops excluded; delete-many treats each ID as its own anchor.
    Also attempts to parse bash loop/array patterns.
    """
    anchors: set[str] = set()

    for raw_cmd in commands:
        if not isinstance(raw_cmd, str):
            continue

        # try bash -c '...' loop patterns first
        if re.search(r'bash\s+-c', raw_cmd):
            loop_anchors = _extract_bash_loop_anchors(raw_cmd)
            anchors.update(loop_anchors)
            if loop_anchors:
                continue  # avoid double-counting wb-*.py inside the loop

        cmd = _normalize_cmd(raw_cmd)
        parts = cmd.split()
        if len(parts) < 2:
            continue

        script = parts[0]       # e.g. wb-email.py
        subcommand = parts[1]   # e.g. delete, send, create

        # skip read ops
        if subcommand in _READ_SUBCOMMANDS:
            continue

        # special-case delete-many (wb-crm.py delete-many --ids a,b,c)
        if subcommand == "delete-many":
            m = re.search(r"--ids\s+(\S+)", cmd)
            if m:
                for id_val in m.group(1).split(","):
                    v = id_val.strip().lower()
                    if v and _is_valid_anchor(v):
                        anchors.add(v)
            continue

        anchor = _extract_exec_anchor(script, subcommand, cmd)
        if anchor and _is_valid_anchor(anchor):
            # split comma-joined values as in --to "a@x.com, b@x.com"
            for part in anchor.split(","):
                part = part.strip()
                if part:
                    anchors.add(part)

    return anchors


# ---------------------------------------------------------------------------
# Log-based anchor extraction (tool instrumentation)
# ---------------------------------------------------------------------------

def _read_action_log(workspace: Path) -> set[str] | None:
    """
    Read memory/action_log.jsonl written by instrumented wb-*.py tools.

    Returns:
        set of unique anchor values  — if log file exists (even if empty)
        None                         — if log file does not exist (use fallback)

    An empty set means the log exists but no write ops were recorded.
    """
    log_path = workspace / "memory" / "action_log.jsonl"
    if not log_path.exists():
        return None
    anchors: set[str] = set()
    for line in log_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
            anchor = entry.get("anchor", "").strip().lower()
            if anchor:
                anchors.add(anchor)
        except json.JSONDecodeError:
            continue
    return anchors


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def compute_action_precision(
    original_answer: str,
    turns: list,   # list[TurnRecord]; typed loosely to avoid a circular import
    workspace: Path | None = None,  # soul workspace path — enables log-based measurement
) -> ActionPrecisionResult:
    """
    Compute action_precision from the commands_executed of the last
    non-clarification ([TASK_COMPLETE]) turn.

    Args:
        original_answer: ground-truth answer string
        turns: ConversationResult.turns (list of TurnRecord)
    """
    # 1. ground truth anchors
    gt_anchors, anchor_type = _extract_gt_anchors(original_answer)

    if not gt_anchors:
        return ActionPrecisionResult(
            applicable=False,
            gt_count=0,
            exec_count=0,
            match=True,
            anchor_type=anchor_type,
        )

    # 2. exec anchors
    # priority: tool instrumentation logs -> command-text parsing fallback
    if workspace is not None:
        log_anchors = _read_action_log(workspace)
        if log_anchors is not None:
            # log-based measurement (covers dynamic shell pipelines, bash loops, etc.)
            return ActionPrecisionResult(
                applicable=True,
                gt_count=len(gt_anchors),
                exec_count=len(log_anchors),
                match=len(gt_anchors) == len(log_anchors),
                anchor_type=anchor_type,
                gt_anchors=sorted(gt_anchors),
                exec_anchors=sorted(log_anchors),
            )

    # fallback: command-text parsing (for runs without instrumentation logs)
    # use only the last non-clarification turn's commands_executed, so earlier
    # failed attempts in a correction cycle are not double counted.
    last_action_turn = None
    for t in reversed(turns):
        if not t.is_clarification:
            last_action_turn = t
            break

    if last_action_turn is None:
        return ActionPrecisionResult(
            applicable=True,
            gt_count=len(gt_anchors),
            exec_count=0,
            match=False,
            anchor_type=anchor_type,
            gt_anchors=sorted(gt_anchors),
            exec_anchors=[],
        )

    exec_anchors = _extract_exec_anchors(last_action_turn.commands_executed)

    return ActionPrecisionResult(
        applicable=True,
        gt_count=len(gt_anchors),
        exec_count=len(exec_anchors),
        match=len(gt_anchors) == len(exec_anchors),
        anchor_type=anchor_type,
        gt_anchors=sorted(gt_anchors),
        exec_anchors=sorted(exec_anchors),
    )
