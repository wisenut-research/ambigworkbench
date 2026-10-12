"""
Task loaders for OfficeBench and AmbigOfficeBench (ambig_queries.json).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal


TaskComplexity = Literal["two_apps", "three_apps"]


@dataclass
class OfficeBenchTask:
    task_id: str
    complexity: TaskComplexity
    instruction: str
    apps: list[str]
    # Optional fields present in some OfficeBench entries
    expected_output: str | None = None
    metadata: dict = field(default_factory=dict)

    def to_prompt(self) -> str:
        """Return the task as a plain-text message for the agent."""
        return self.instruction


def load_tasks(data_dir: Path, complexity: TaskComplexity | None = None) -> list[OfficeBenchTask]:
    """
    Load OfficeBench tasks from the local dataset directory.

    Expected directory layout (downloaded via setup.sh):
        data/officebench/
            two_apps/
                2-1/subtasks/0.json
                2-2/subtasks/0.json
                ...
            three_apps/
                3-1/subtasks/0.json
                ...

    Each subtask JSON contains: username, date, weekday, time, task, evaluation
    """
    tasks: list[OfficeBenchTask] = []
    complexities: list[TaskComplexity] = ["two_apps", "three_apps"] if complexity is None else [complexity]

    for cplx in complexities:
        subdir = data_dir / cplx
        if not subdir.exists():
            print(f"[warn] {subdir} not found; skipping {cplx}. Provide the WorkBench data first.")
            continue

        # tasks/2-{id}/subtasks/*.json
        for json_file in sorted(subdir.glob("*/subtasks/*.json")):
            task_dir = json_file.parent.parent.name  # e.g. "2-1"
            subtask_id = json_file.stem               # e.g. "0"
            try:
                entry = json.loads(json_file.read_text(encoding="utf-8"))
                tasks.append(_parse_entry(entry, cplx, f"{task_dir}_{subtask_id}"))
            except (json.JSONDecodeError, OSError) as e:
                print(f"[warn] Could not load {json_file}: {e}")

    return tasks


def _parse_entry(entry: dict, complexity: TaskComplexity, file_stem: str) -> OfficeBenchTask:
    task_id = entry.get("task_id") or file_stem
    # OfficeBench uses "task" field for the instruction
    instruction = (
        entry.get("task")
        or entry.get("instruction")
        or entry.get("description")
        or ""
    )
    apps = entry.get("apps") or entry.get("applications") or []

    # Add context from OfficeBench metadata to make the task more realistic
    context_parts = []
    if entry.get("username"):
        context_parts.append(f"You are {entry['username']}.")
    if entry.get("date") and entry.get("weekday"):
        context_parts.append(f"Today is {entry['weekday']}, {entry['date']}.")
    if entry.get("time"):
        context_parts.append(f"Current time: {entry['time']}.")

    if context_parts:
        instruction = " ".join(context_parts) + " " + instruction

    return OfficeBenchTask(
        task_id=str(task_id),
        complexity=complexity,
        instruction=instruction,
        apps=apps,
        expected_output=entry.get("expected_output") or entry.get("answer"),
        metadata={k: v for k, v in entry.items() if k not in {"task_id", "task", "instruction", "apps", "applications"}},
    )


# ---------------------------------------------------------------------------
# AmbigOfficeBench task loader
# ---------------------------------------------------------------------------

@dataclass
class AmbigTask:
    task_id: str
    domain: str
    original_query: str
    original_answer: str
    ambiguous_query: str
    ambiguity_dimensions: list[str]
    ambiguity_level: int

    def to_prompt(self) -> str:
        return self.ambiguous_query


def load_ambig_tasks(
    json_path: Path,
    domains: list[str] | None = None,
    ambiguity_level: int | None = None,
) -> list[AmbigTask]:
    """
    Load AmbigOfficeBench tasks from ambig_queries.json.

    Args:
        json_path: Path to ambig_queries.json
        domains: Optional filter by domain (e.g. ["email", "calendar"])
        ambiguity_level: Optional filter by number of injected dimensions (1, 2, or 3)
    """
    raw = json.loads(json_path.read_text(encoding="utf-8"))
    tasks = []
    skipped_noop = 0
    for entry in raw:
        if entry.get("error"):
            continue
        if domains and entry["domain"] not in domains:
            continue
        level = entry.get("ambiguity_level", len(entry.get("ambiguity_dimensions", [])))
        if ambiguity_level is not None and level != ambiguity_level:
            continue
        # exclude no-op tasks: an empty original_answer means the condition is
        # unmet or the data is structurally broken -> not evaluable
        ans = entry.get("original_answer", "").strip()
        if ans in ("[]", "['']", ""):
            skipped_noop += 1
            continue
        tasks.append(AmbigTask(
            task_id=entry["task_id"],
            domain=entry["domain"],
            original_query=entry["original_query"],
            original_answer=entry.get("original_answer", ""),
            ambiguous_query=entry["ambiguous_query"],
            ambiguity_dimensions=entry.get("ambiguity_dimensions", []),
            ambiguity_level=level,
        ))
    if skipped_noop:
        print(f"  [task_loader] skipped {skipped_noop} no-op tasks (original_answer=[])")
    return tasks


def load_sample_tasks() -> list[OfficeBenchTask]:
    """
    Built-in sample tasks for quick pipeline validation without the full dataset.
    These replicate the ambiguity profile of real OfficeBench two/three-app tasks.
    """
    return [
        OfficeBenchTask(
            task_id="sample_two_001",
            complexity="two_apps",
            instruction=(
                "There is a data file with our quarterly sales numbers. "
                "Please summarize it and send the summary to the manager."
            ),
            apps=["spreadsheet", "email"],
        ),
        OfficeBenchTask(
            task_id="sample_two_002",
            complexity="two_apps",
            instruction=(
                "Look up the contact details for John Smith and add them to the address book."
            ),
            apps=["browser", "contacts"],
        ),
        OfficeBenchTask(
            task_id="sample_three_001",
            complexity="three_apps",
            instruction=(
                "Find the latest project status update, create a presentation slide deck from it, "
                "and share it with the team."
            ),
            apps=["email", "presentation", "calendar"],
        ),
        OfficeBenchTask(
            task_id="sample_three_002",
            complexity="three_apps",
            instruction=(
                "Pull the customer feedback from last month, analyze the sentiment, "
                "write a brief report, and schedule a review meeting."
            ),
            apps=["spreadsheet", "document", "calendar"],
        ),
    ]
