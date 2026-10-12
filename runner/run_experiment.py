"""
Main experiment runner.

Runs each OfficeBench task through Soul A, B, and C via the openclaw CLI
inside the Docker container (isolated sandbox), then collects session
transcript metrics into a JSONL results file.

Architecture:
    Host filesystem:
        experiment/openclaw-config/  -> mounted as /home/node/.openclaw  inside container
        experiment/workspace/        -> mounted as /home/node/.openclaw/workspace inside container

    Runner (this script) runs on the HOST and invokes:
        docker exec -i openclaw-cli node dist/index.js agent --message "..." --agent soul-a

    Transcripts are written inside the container to /home/node/.openclaw/agents/<agentId>/sessions/
    and are readable on the host at experiment/openclaw-config/agents/<agentId>/sessions/*.jsonl

Usage:
    # Start containers first:
    #   docker compose -f docker-compose.yml -f experiment/docker-compose.experiment.yml up -d
    #
    python experiment/runner/run_experiment.py [--sample] [--complexity two_apps|three_apps]
        [--souls soul-a,soul-b,soul-c] [--limit N] [--results-dir ./results]

Requirements:
    - Docker containers running (openclaw-gateway + openclaw-cli)
    - OPENROUTER_API_KEY set in environment
    - OfficeBench dataset at experiment/data/officebench/ (or use --sample)
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

# Load .env from experiment/ directory if present (before any os.environ reads)
_env_file = Path(__file__).resolve().parents[1] / ".env"
if _env_file.exists():
    for _line in _env_file.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

# Add runner dir to path so we can import siblings
sys.path.insert(0, str(Path(__file__).parent))

from task_loader import AmbigTask, OfficeBenchTask, TaskComplexity, load_ambig_tasks, load_sample_tasks, load_tasks
from transcript_parser import RunMetrics, find_latest_transcript, parse_transcript
from conversation_runner import ConversationResult, run_conversation, call_agent
from evaluator import evaluate
from action_precision import compute_action_precision

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from seed_manager import reset_soul, archive_last_session as _archive_last_session, _reset_memory as _reset_soul_memory

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

EXPERIMENT_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = EXPERIMENT_DIR.parent
DATA_DIR = EXPERIMENT_DIR / "data" / "officebench"
DEFAULT_RESULTS_DIR = EXPERIMENT_DIR / "results"

# Host path where openclaw writes session transcripts (mounted from container)
# Container: /home/node/.openclaw/agents/<id>/sessions/
# Host:      experiment/openclaw-config/agents/<id>/sessions/
OPENCLAW_CONFIG_DIR = EXPERIMENT_DIR / "openclaw-config"

# Use the gateway container directly for exec (same image, CLI container not needed)
CLI_CONTAINER = "openclaw-gateway"

# All three identities under test
ALL_SOULS = ["soul-a", "soul-b", "soul-c"]

# Seconds to wait after an agent run before reading the transcript
TRANSCRIPT_SETTLE_SECS = 3

# Timeout (seconds) for a single agent run
AGENT_TIMEOUT_SECS = 300

# openclaw version pinned for reproducibility (verified at startup)
EXPECTED_OPENCLAW_VERSION = "2026.3.3"


# ---------------------------------------------------------------------------
# Agent invocation
# ---------------------------------------------------------------------------

def run_agent(soul_id: str, task: OfficeBenchTask | AmbigTask, dry_run: bool = False) -> tuple[bool, str, datetime]:
    """
    Invoke openclaw agent inside the Docker container via `docker exec`.

    Returns (success: bool, output: str, run_start: datetime).
    The run_start timestamp is used to isolate this task's transcript entries.
    """
    prompt = task.to_prompt()
    cmd = [
        "docker", "exec", "-i", CLI_CONTAINER,
        "node", "dist/index.js", "agent",
        "--message", prompt,
        "--agent", soul_id,
        "--no-color",
    ]

    print(f"  -> [{soul_id}] Running task {task.task_id!r}…")
    run_start = datetime.now(tz=UTC)

    if dry_run:
        print(f"    DRY RUN cmd: {' '.join(cmd)}")
        return True, "[dry-run]", run_start

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=AGENT_TIMEOUT_SECS,
        )
        success = result.returncode == 0
        output = result.stdout + result.stderr
        if not success:
            print(f"    X exit code {result.returncode}")
            print(f"    stderr: {result.stderr[:500]}")
        return success, output, run_start
    except subprocess.TimeoutExpired:
        print(f"    X timed out after {AGENT_TIMEOUT_SECS}s")
        return False, "timeout", run_start
    except FileNotFoundError as e:
        print(f"    X docker not found: {e}")
        return False, str(e)


# ---------------------------------------------------------------------------
# Metrics collection
# ---------------------------------------------------------------------------

def collect_metrics(
    soul_id: str,
    task: OfficeBenchTask | AmbigTask,
    run_success: bool,
    run_start: datetime,
    dry_run: bool,
) -> RunMetrics:
    """
    Wait for the transcript to settle, then parse only the entries from this run
    (identified by timestamp >= run_start).
    """
    complexity = task.domain if isinstance(task, AmbigTask) else task.complexity
    if dry_run:
        return RunMetrics(
            soul_id=soul_id,
            task_id=task.task_id,
            complexity=complexity,
            total_input_tokens=0,
            total_output_tokens=0,
            completed=True,
        )

    time.sleep(TRANSCRIPT_SETTLE_SECS)

    transcript_path = find_latest_transcript(soul_id, openclaw_dir=OPENCLAW_CONFIG_DIR)
    if transcript_path is None:
        metrics = RunMetrics(soul_id=soul_id, task_id=task.task_id, complexity=complexity)
        metrics.error = f"no transcript found for agent {soul_id!r}"
        return metrics

    # Pass run_start so the parser only reads entries from this specific task run
    metrics = parse_transcript(
        transcript_path, soul_id, task.task_id, complexity,
        after=run_start,
    )
    if not run_success:
        metrics.completed = False
        metrics.error = metrics.error or "agent run failed"

    print(f"    tokens={metrics.total_tokens}  turns={metrics.total_turns}  "
          f"tools={metrics.total_tool_calls}(fail={metrics.failed_tool_calls})  "
          f"clarify={metrics.clarification_messages}")
    return metrics


# ---------------------------------------------------------------------------
# Version check
# ---------------------------------------------------------------------------

def check_openclaw_version() -> str | None:
    """Return the openclaw version running inside the Docker container."""
    try:
        result = subprocess.run(
            ["docker", "exec", CLI_CONTAINER, "node", "dist/index.js", "--version"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        version = result.stdout.strip().splitlines()[-1].strip() if result.returncode == 0 else None
        return version
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Results persistence
# ---------------------------------------------------------------------------

def save_result(results_dir: Path, run_id: str, metrics: RunMetrics, task: OfficeBenchTask | AmbigTask) -> None:
    output_file = results_dir / f"{run_id}.jsonl"
    record = {
        "run_id": run_id,
        "timestamp": datetime.now(tz=UTC).isoformat(),
        **metrics.to_dict(),
    }
    if isinstance(task, AmbigTask):
        record["domain"] = task.domain
        record["ambiguity_dimensions"] = task.ambiguity_dimensions
        record["ambiguity_level"] = task.ambiguity_level
    else:
        record["apps"] = task.apps
    with output_file.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _save_conv_result(
    results_dir: Path,
    run_id: str,
    conv: ConversationResult,
    task: OfficeBenchTask | AmbigTask,
    eval_result,
    action_prec=None,
) -> None:
    output_file = results_dir / f"{run_id}.jsonl"
    record = {
        "run_id": run_id,
        "timestamp": datetime.now(tz=UTC).isoformat(),
        **conv.to_dict(),
    }
    if isinstance(task, AmbigTask):
        record["domain"] = task.domain
        record["ambiguity_dimensions"] = task.ambiguity_dimensions
        record["ambiguity_level"] = task.ambiguity_level
        record["original_query"] = task.original_query
        record["ambiguous_query"] = task.ambiguous_query
    else:
        record["apps"] = task.apps

    if eval_result is not None:
        record["eval"] = eval_result.to_dict()

    if action_prec is not None:
        record["action_precision"] = action_prec.to_dict()

    with output_file.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


UTC = timezone.utc


def build_run_id(experiment_name: str) -> str:
    ts = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%S")
    return f"{experiment_name}_{ts}"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Soul A/B/C experiment runner")
    parser.add_argument("--sample", action="store_true", help="Use built-in sample tasks instead of OfficeBench dataset")
    parser.add_argument("--ambig-tasks", type=Path, default=None,
                        help="Path to ambig_queries.json (AmbigOfficeBench mode)")
    parser.add_argument("--ambig-domains", nargs="+", default=None,
                        help="Filter ambig tasks by domain (e.g. email calendar)")
    parser.add_argument("--ambig-level", type=int, default=None, choices=[1, 2, 3],
                        help="Filter ambig tasks by ambiguity_level (1, 2, or 3)")
    parser.add_argument("--complexity", choices=["two_apps", "three_apps"], help="Filter OfficeBench complexity level")
    parser.add_argument("--souls", default=",".join(ALL_SOULS), help="Comma-separated soul IDs to run (default: all)")
    parser.add_argument("--limit", type=int, default=None, help="Max number of tasks to run per soul")
    parser.add_argument("--results-dir", type=Path, default=DEFAULT_RESULTS_DIR, help="Directory to save result JSONL files")
    parser.add_argument("--dry-run", action="store_true", help="Print commands without executing them")
    parser.add_argument("--experiment-name", default="ambig_soul_comparison", help="Label for this experiment run")
    parser.add_argument("--skip-version-check", action="store_true", help="Skip openclaw version verification")
    parser.add_argument("--max-turns", type=int, default=None,
                        help="Override max turns per task. Default: single_domain=4, multi_domain=6")
    parser.add_argument("--oracle-model", default="gpt-4o-mini", help="Model name for clarification oracle (default: gpt-4o-mini)")
    parser.add_argument("--oracle-base-url", default=None,
                        help="vLLM or custom OpenAI-compatible endpoint (e.g. http://<gpu-host>:8000/v1). "
                             "If set, OPENAI_API_KEY is not required.")
    parser.add_argument("--vllm-metrics-url", default=None,
                        help="vLLM /metrics endpoint for agent token tracking "
                             "(e.g. http://<gpu-host>:9022/metrics). "
                             "Auto-derived from --oracle-base-url if not set.")
    parser.add_argument("--no-reset", action="store_true", help="Skip seed/session reset between tasks (faster, less isolated)")
    parser.add_argument("--learning", action="store_true", help="Preserve memory/ across tasks so souls can learn from experience (CSV and sessions still reset)")
    parser.add_argument("--keep-memory", action="store_true", help="Skip initial memory wipe when --learning is on (use when resuming a run)")
    args = parser.parse_args()

    souls = [s.strip() for s in args.souls.split(",") if s.strip()]
    run_id = build_run_id(args.experiment_name)
    run_dir: Path = args.results_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    results_dir = run_dir

    # --- Version check ---
    if not args.skip_version_check and not args.dry_run:
        version = check_openclaw_version()
        if version is None:
            print("[warn] Could not determine openclaw version. Ensure `pnpm openclaw` works.")
        else:
            print(f"openclaw version: {version}")
            if version != EXPECTED_OPENCLAW_VERSION:
                print(f"[warn] Expected {EXPECTED_OPENCLAW_VERSION}, got {version}. Results may not be reproducible.")

    # --- Load tasks ---
    if args.ambig_tasks:
        tasks = load_ambig_tasks(
            args.ambig_tasks,
            domains=args.ambig_domains,
            ambiguity_level=args.ambig_level,
        )
        if not tasks:
            print("No ambig tasks loaded. Check --ambig-tasks path and filters.")
            sys.exit(1)
        print(f"Loaded {len(tasks)} AmbigOfficeBench tasks from {args.ambig_tasks}.")
    elif args.sample:
        tasks = load_sample_tasks()
        print(f"Using {len(tasks)} built-in sample tasks.")
    else:
        complexity: TaskComplexity | None = args.complexity  # type: ignore[assignment]
        tasks = load_tasks(DATA_DIR, complexity=complexity)
        if not tasks:
            print("No tasks loaded. Use --sample, --ambig-tasks, or provide the WorkBench data.")
            sys.exit(1)
        print(f"Loaded {len(tasks)} OfficeBench tasks ({args.complexity or 'all complexities'}).")

    if args.limit:
        tasks = tasks[: args.limit]
        print(f"Limited to {len(tasks)} tasks.")

    # --- Oracle client ---
    oracle_client = None
    if not args.dry_run:
        try:
            from openai import OpenAI
        except ImportError:
            print("[error] openai package not found. Run: pip install openai")
            sys.exit(1)

        if args.oracle_base_url:
            # vLLM / OpenAI-compatible local server — no real API key needed
            oracle_client = OpenAI(base_url=args.oracle_base_url, api_key="EMPTY")
            print(f"Oracle: {args.oracle_model} @ {args.oracle_base_url} (vLLM mode)")
        else:
            api_key = os.environ.get("OPENAI_API_KEY")
            if not api_key:
                print("[error] OPENAI_API_KEY not set. Set it in experiment/.env or your shell.")
                print("        Alternatively, use --oracle-base-url to point to a local vLLM server.")
                sys.exit(1)
            # Force the official OpenAI endpoint. The serving env sets
            # OPENAI_BASE_URL=<vLLM proxy> so the *agent* hits local Qwen; the
            # OpenAI SDK would otherwise pick that up and misroute the oracle
            # (gpt-4o-mini) to the Qwen vLLM -> 404 "model does not exist".
            # Passing base_url explicitly overrides the env var.
            oracle_base = os.environ.get("OPENAI_ORACLE_BASE_URL", "https://api.openai.com/v1")
            oracle_client = OpenAI(api_key=api_key, base_url=oracle_base)
            print(f"Oracle: {args.oracle_model} @ {oracle_base} (OpenAI API)")

    WORKSPACE_DIR = EXPERIMENT_DIR / "workspace"


    # vLLM metrics URL: explicit flag wins; else derived from base url (/v1 -> /metrics)
    _vllm_metrics_url: str | None = args.vllm_metrics_url
    if _vllm_metrics_url is None and args.oracle_base_url:
        _base = args.oracle_base_url.rstrip("/")
        if _base.endswith("/v1"):
            _base = _base[:-3]
        _vllm_metrics_url = _base + "/metrics"

    print(f"\nExperiment run: {run_id}")
    print(f"Souls: {souls}")
    print(f"Tasks: {len(tasks)}")
    print(f"Max turns: {'dynamic (single=4, multi=6)' if args.max_turns is None else args.max_turns}")
    print(f"Oracle model: {args.oracle_model}{' (vLLM)' if args.oracle_base_url else ' (OpenAI API)'}")
    print(f"Agent token tracking: {_vllm_metrics_url or 'disabled (no vLLM metrics URL)'}")
    print(f"Learning mode: {'ON (memory persists across tasks, wiped at run start)' if args.learning else 'OFF'}")
    print(f"Results: {run_dir / run_id}.jsonl\n")

    # learning mode: clear every soul's memory at experiment start (no cross-run bleed)
    if args.learning and not args.keep_memory and not args.dry_run:
        for soul_id in souls:
            _reset_soul_memory(soul_id, verbose=True)
        print()

    # --- Run experiments ---
    total = len(souls) * len(tasks)
    done = 0

    prev_task_id: dict[str, str] = {}  # soul_id -> previous task_id (log preservation)

    for task in tasks:
        print(f"\n{'-'*60}")
        is_ambig = isinstance(task, AmbigTask)
        if is_ambig:
            print(f"Task {task.task_id!r} [{task.domain}]  dims={task.ambiguity_dimensions}  level={task.ambiguity_level}")
            print(f"  {task.ambiguous_query[:120]}{'…' if len(task.ambiguous_query) > 120 else ''}")
        else:
            print(f"Task {task.task_id!r} [{task.complexity}]  apps={task.apps}")
            print(f"  {task.instruction[:120]}{'…' if len(task.instruction) > 120 else ''}")

        for soul_id in souls:
            # reset: restore CSVs; preserve then delete the previous session log
            if not args.no_reset and not args.dry_run:
                reset_soul(soul_id, verbose=False,
                           prev_task_id=prev_task_id.get(soul_id),
                           reset_memory=not args.learning)

            # dynamic max_turns: single_domain=4, multi_domain=6 (overridable)
            if args.max_turns is not None:
                _max_turns = args.max_turns
            elif is_ambig:
                _max_turns = 6 if task.domain == "multi_domain" else 4
            else:
                _max_turns = 10

            # Prepend tool hint so the agent reads TOOLS.md, memory, and uses wb-* CLI
            # patterns.md is injected directly into the prompt (guaranteed delivery
            # regardless of whether the model follows startup instructions)
            _patterns_path = EXPERIMENT_DIR / "workspace" / soul_id / "memory" / "patterns.md"
            _patterns_content = _patterns_path.read_text(encoding="utf-8").strip() if _patterns_path.exists() else ""
            _learning_hint = (
                (
                    "## Reusable Patterns from Past Tasks\n"
                    "The following patterns were saved from previous tasks. Apply them when relevant:\n"
                    + _patterns_content + "\n\n"
                )
                if args.learning and _patterns_content else ""
            )
            _task_prompt = (
                "REQUIRED STARTUP — run these commands first, before anything else:\n"
                "1. Run `WB_WORKSPACE=$(pwd) cat TOOLS.md` to see available tools.\n"
                + ("2. Reusable patterns from past tasks are already provided below — no need to read memory/patterns.md manually.\n"
                   if args.learning else "")
                + "Only after completing the above startup steps, use the wb-* CLI scripts listed in TOOLS.md to complete the following task:\n\n"
                + "Do not directly edit, append, rewrite, or delete workspace CSV/data files. All state-changing work must go through the wb-* CLI tools.\n\n"
                + _learning_hint
                + task.to_prompt()
                + "\n\nIMPORTANT: End your response with exactly one of these tags on the last line:\n"
                "- [TASK_COMPLETE]  (only after ALL required tool calls are executed and results confirmed)\n"
                "- [TASK_CLARIFY]   (pre-execution information request: use this to ask the user for missing "
                "information BEFORE taking any action. You CANNOT use this tag after already executing commands.)\n"
                "  You MUST write your specific question ending with '?' on the line immediately before the tag.\n"
                "  Example:\n"
                "  Which customer record should I update?\n"
                "  [TASK_CLARIFY]"
            )

            _workspace = (WORKSPACE_DIR / soul_id) if is_ambig and not args.dry_run else None

            # Multi-turn conversation (with mid-loop eval + correction)
            conv = run_conversation(
                soul_id=soul_id,
                task_id=task.task_id,
                initial_message=_task_prompt,
                original_query=task.original_query if is_ambig else task.to_prompt(),
                original_answer=task.original_answer if is_ambig else "",
                oracle_client=oracle_client,
                oracle_model=args.oracle_model,
                max_turns=_max_turns,
                dry_run=args.dry_run,
                verbose=True,
                workspace=_workspace,
                vllm_metrics_url=_vllm_metrics_url,
            )

            eval_result = conv.eval_result

            # action_precision: computed before the memory turn
            # pass workspace -> measure from tool instrumentation logs (command parsing fallback)
            _action_prec = None
            if is_ambig and not args.dry_run:
                _action_prec = compute_action_precision(
                    task.original_answer, conv.turns, workspace=_workspace
                )

            # learning mode: inject the memory-writing turn after eval + action_precision are known
            _infra_error = bool(
                conv.error
                and (
                    conv.error.startswith("[ERROR]")
                    or conv.error.startswith("[PARSE ERROR]")
                    or "argument list too long" in conv.error
                )
            )
            if args.learning and not args.dry_run and not _infra_error:
                _success = eval_result is not None and eval_result.e2e_success
                _score = f"{eval_result.score:.2f}" if eval_result else "n/a"

                _prec_feedback = ""
                if _action_prec and _action_prec.applicable:
                    if _action_prec.match:
                        _prec_feedback = (
                            f"Action precision: EXACT ({_action_prec.exec_count} actions, "
                            f"which matched the {_action_prec.gt_count} required)."
                        )
                    elif _action_prec.exec_count > _action_prec.gt_count:
                        _prec_feedback = (
                            f"Action precision: OVER-ACTED — you executed {_action_prec.exec_count} actions "
                            f"but only {_action_prec.gt_count} were needed. "
                            f"Consider saving a pattern about what caused this over-action."
                        )
                    else:
                        _prec_feedback = (
                            f"Action precision: UNDER-ACTED — you executed {_action_prec.exec_count} actions "
                            f"but {_action_prec.gt_count} were needed."
                        )

                _memory_msg = (
                    f"Task finished. Result: {'SUCCESS' if _success else f'FAILED (score={_score})'}.\n"
                    + (f"{_prec_feedback}\n" if _prec_feedback else "")
                    + "\nIf you learned a reusable pattern from this task, output it now as plain text lines.\n"
                    "Format: one pattern per line, starting with '- [domain] '.\n"
                    "Examples:\n"
                    "  - [analytics] 'visits' maps to total_visits metric\n"
                    "  - [action-scope] when target is ambiguous, act on one candidate and confirm before proceeding\n\n"
                    "DO NOT run any shell commands. DO NOT write to any file. Just output the pattern lines as text.\n"
                    "Reminder: only act on what is explicitly requested. Over-acting (executing more actions than needed) lowers your score.\n"
                    "If there is nothing reusable to save, output nothing.\n"
                    "IMPORTANT: Stop immediately after the last pattern line."
                )

                # snapshot before the memory turn, so an agent overwrite can be restored
                _patterns_path = EXPERIMENT_DIR / "workspace" / soul_id / "memory" / "patterns.md"
                _patterns_path.parent.mkdir(parents=True, exist_ok=True)
                _pre_patterns = _patterns_path.read_text(encoding="utf-8") if _patterns_path.exists() else ""

                _mem_response, _ = call_agent(
                    soul_id,
                    _memory_msg,
                    dry_run=False,
                    vllm_metrics_url=_vllm_metrics_url,
                    max_output_tokens=300,
                )

                # restore immediately if the agent overwrote patterns.md
                _post_patterns = _patterns_path.read_text(encoding="utf-8") if _patterns_path.exists() else ""
                if len(_post_patterns) < len(_pre_patterns):
                    _patterns_path.write_text(_pre_patterns, encoding="utf-8")
                    print(f"    [GUARD] patterns.md overwrite detected -> restored ({len(_post_patterns)} < {len(_pre_patterns)} bytes)")

                # the runner itself appends to patterns.md; the agent never writes the file
                _new_patterns = []
                for _line in _mem_response.splitlines():
                    _stripped = _line.strip()
                    # canonical format: - [domain] text
                    if _stripped.startswith("- ["):
                        _normalized = _stripped
                    # normalize [DOMAIN] text to - [domain] text
                    elif _stripped.startswith("[") and "]" in _stripped:
                        _bracket_end = _stripped.index("]")
                        _domain = _stripped[1:_bracket_end].lower()
                        _rest = _stripped[_bracket_end + 1:].strip()
                        _normalized = f"- [{_domain}] {_rest}" if _rest else None
                        if not _normalized:
                            continue
                    else:
                        continue
                    if len(_normalized) > 500:  # reject abnormally long lines
                        continue
                    if any(c < " " for c in _normalized if c not in ("\t",)):  # reject control characters
                        continue
                    _new_patterns.append(_normalized)
                if _new_patterns:
                    with _patterns_path.open("a", encoding="utf-8") as _pf:
                        for _p in _new_patterns:
                            _pf.write(_p + "\n")

                _prec_label = f"prec={'OK' if (_action_prec and _action_prec.match) else ('over' if (_action_prec and _action_prec.exec_count > _action_prec.gt_count) else 'X')}" if _action_prec and _action_prec.applicable else "prec=n/a"
                print(f"    -> memory turn sent (result={'OK' if _success else 'X'}, {_prec_label}, patterns+={len(_new_patterns)})")
            elif args.learning and not args.dry_run and _infra_error:
                print(f"    -> memory turn skipped due to infrastructure error: {conv.error[:120]}")

            # Save result
            _save_conv_result(results_dir, run_id, conv, task, eval_result, _action_prec)
            prev_task_id[soul_id] = task.task_id  # preserve this task's log on the next reset
            done += 1
            print(f"  [{done}/{total}] max={_max_turns}  turns={conv.total_turns}  "
                  f"clarify={conv.clarification_turns}  correct={conv.correction_turns}  "
                  f"tokens={conv.total_tokens}  "
                  f"e2e={'OK' if (eval_result and eval_result.e2e_success) else ('X' if eval_result else 'n/a')}")

            if not args.dry_run:
                time.sleep(1)

    # preserve the final task's session log (no further reset will copy it)
    if not args.dry_run:
        for soul_id in souls:
            if soul_id in prev_task_id:
                _archive_last_session(soul_id, prev_task_id[soul_id])

    # Auto-aggregate
    results_file = run_dir / f"{run_id}.jsonl"
    _summary = None
    _csv_out = None
    try:
        sys.path.insert(0, str(EXPERIMENT_DIR / "analysis"))
        from aggregate import build_summary, print_summary, write_csv
        records_for_agg = []
        for line in results_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                try:
                    records_for_agg.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
        if records_for_agg:
            _summary = build_summary(records_for_agg)
            print_summary(_summary)
            summary_dir = run_dir / "summary"
            summary_dir.mkdir(exist_ok=True)
            _csv_out = summary_dir / f"{run_id}.summary.csv"
            write_csv(_summary, _csv_out)
            json_out = summary_dir / f"{run_id}.summary.json"
            json_out.write_text(json.dumps(_summary, indent=2, ensure_ascii=False), encoding="utf-8")
            print(f"CSV  -> {_csv_out}")
            print(f"JSON -> {json_out}")
    except Exception as _agg_err:
        print(f"[warn] Aggregation failed: {_agg_err}")

    # Exp_summ xlsx is auxiliary reporting; independent of result storage
    if _summary is not None and _csv_out is not None:
        try:
            from aggregate import write_xlsx
            xlsx_path = write_xlsx(_summary, _csv_out, records=records_for_agg)
            if xlsx_path:
                print(f"XLSX -> {xlsx_path}")
        except Exception as _xlsx_err:
            print(f"[warn] XLSX generation failed: {_xlsx_err}")

    print(f"\n{'='*60}")
    print(f"Experiment complete. Results saved to: {results_file}")
    print(f"Action logs saved to: {EXPERIMENT_DIR / 'logs'}/")


if __name__ == "__main__":
    main()
