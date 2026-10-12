"""
seed_manager.py

Reset each agent workspace before and after task execution.

Responsibilities:
  1. Copy seed CSV files into each workspace.
  2. Remove session history between tasks.
  3. Archive the previous session JSONL before removal.
  4. Reset workspace memory unless cumulative learning is enabled.

Usage:
    from seed_manager import reset_soul, reset_all_souls
    reset_soul("soul-a", prev_task_id="AOB_email_0001_v1")
    reset_all_souls()
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

EXPERIMENT_DIR = Path(__file__).resolve().parent
SEED_DIR = EXPERIMENT_DIR / "benchmark" / "seed"
WORKSPACE_DIR = EXPERIMENT_DIR / "workspace"
OPENCLAW_CONFIG_DIR = EXPERIMENT_DIR / "openclaw-config"

SOUL_IDS = ["soul-a", "soul-b", "soul-c"]
LOGS_DIR = EXPERIMENT_DIR / "logs"

# CSV files that need to be seeded into each soul's workspace
SEED_FILES = [
    "emails.csv",
    "calendar_events.csv",
    "project_tasks.csv",
    "analytics_data.csv",
    "customer_relationship_manager_data.csv",
]


def reset_soul(soul_id: str, verbose: bool = True, prev_task_id: str | None = None, reset_memory: bool = True) -> None:
    """
    Reset a single soul's workspace CSV files, session history, and memory.
    prev_task_id: if provided, the previous session JSONL is archived to
                  logs/{prev_task_id}/{soul_id}.jsonl before deletion.
    reset_memory: if False, memory/ is preserved across tasks (enables learning).
    """
    _reset_csv(soul_id, verbose)
    _reset_session(soul_id, verbose, prev_task_id=prev_task_id)
    if reset_memory:
        _reset_memory(soul_id, verbose)


def reset_all_souls(verbose: bool = True) -> None:
    for soul_id in SOUL_IDS:
        reset_soul(soul_id, verbose=verbose)


def archive_last_session(soul_id: str, task_id: str) -> bool:
    """
    Archive the final task session when no subsequent reset will do so.
    Returns True if archived successfully.
    """
    sessions_dir = OPENCLAW_CONFIG_DIR / "agents" / soul_id / "sessions"
    sessions_json = sessions_dir / "sessions.json"
    session_key = f"agent:{soul_id}:main"

    if not sessions_json.exists():
        return False
    try:
        registry = json.loads(sessions_json.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return False

    session_id = registry.get(session_key, {}).get("sessionId")
    if not session_id:
        return False

    jsonl_path = sessions_dir / f"{session_id}.jsonl"
    if not jsonl_path.exists():
        return False

    log_dir = LOGS_DIR / task_id
    log_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(jsonl_path, log_dir / f"{soul_id}.jsonl")
    return True


# ---------------------------------------------------------------------------
# CSV reset
# ---------------------------------------------------------------------------

def _reset_csv(soul_id: str, verbose: bool) -> None:
    workspace = WORKSPACE_DIR / soul_id
    workspace.mkdir(parents=True, exist_ok=True)

    for fname in SEED_FILES:
        src = SEED_DIR / fname
        dst = workspace / fname
        if not src.exists():
            print(f"  [warn] seed file missing: {src}")
            continue
        shutil.copy2(src, dst)

    # Remove generated files so a prior task cannot affect evaluation.
    plots_dir = workspace / "plots"
    if plots_dir.exists():
        shutil.rmtree(plots_dir)
        plots_dir.mkdir()

    for fname in ("crm_list.txt", "temp_ids.txt"):
        f = workspace / fname
        if f.exists():
            f.unlink()

    for png in workspace.glob("*.png"):
        png.unlink()

    if verbose:
        print(f"  [{soul_id}] CSV reset from seed ({len(SEED_FILES)} files), generated files cleared")


# ---------------------------------------------------------------------------
# Session reset
# ---------------------------------------------------------------------------

def _reset_session(soul_id: str, verbose: bool, prev_task_id: str | None = None) -> None:
    sessions_dir = OPENCLAW_CONFIG_DIR / "agents" / soul_id / "sessions"
    if not sessions_dir.exists():
        return

    sessions_json = sessions_dir / "sessions.json"
    session_key = f"agent:{soul_id}:main"

    archived = False
    deleted_jsonl = 0
    if sessions_json.exists():
        try:
            registry = json.loads(sessions_json.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            registry = {}

        if session_key in registry:
            session_id = registry[session_key].get("sessionId")
            if session_id:
                jsonl_path = sessions_dir / f"{session_id}.jsonl"
                if jsonl_path.exists():
                    # Archive the session before deleting it.
                    if prev_task_id:
                        log_dir = LOGS_DIR / prev_task_id
                        log_dir.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(jsonl_path, log_dir / f"{soul_id}.jsonl")
                        archived = True

                    jsonl_path.unlink()
                    deleted_jsonl += 1

            del registry[session_key]
            sessions_json.write_text(json.dumps(registry, indent=2), encoding="utf-8")

    if verbose:
        msg = f"archived to logs/{prev_task_id}/{soul_id}.jsonl" if archived else "no archive"
        print(f"  [{soul_id}] Session reset ({msg})")


# ---------------------------------------------------------------------------
# Memory reset
# ---------------------------------------------------------------------------

def _reset_memory(soul_id: str, verbose: bool) -> None:
    memory_dir = WORKSPACE_DIR / soul_id / "memory"
    if not memory_dir.exists():
        if verbose:
            print(f"  [{soul_id}] Memory reset (no memory dir)")
        return

    deleted = 0
    for f in memory_dir.iterdir():
        if f.is_file():
            f.unlink()
            deleted += 1

    if verbose:
        print(f"  [{soul_id}] Memory reset ({deleted} files deleted)")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="Reset soul workspace CSV and session history")
    parser.add_argument("--soul", choices=SOUL_IDS + ["all"], default="all",
                        help="Soul to reset (default: all)")
    parser.add_argument("--csv-only", action="store_true", help="Reset CSV only, keep session")
    parser.add_argument("--session-only", action="store_true", help="Reset session only, keep CSV")
    args = parser.parse_args()

    souls = SOUL_IDS if args.soul == "all" else [args.soul]
    print(f"Resetting: {souls}")

    for soul_id in souls:
        if args.session_only:
            _reset_session(soul_id, verbose=True)
        elif args.csv_only:
            _reset_csv(soul_id, verbose=True)
        else:
            reset_soul(soul_id, verbose=True)

    print("Done.")
