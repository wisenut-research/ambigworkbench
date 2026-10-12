"""
conversation_runner.py

Multi-turn agent loop + clarification oracle + post-action correction.

Flow:
  1. send the initial ambiguous query
  2. classify the agent response
     a. clarification -> oracle answers from original_answer -> repeat
     b. action (non-clarification) -> verify with the evaluator
        - success -> done
        - failure with turns left -> oracle emits correction feedback -> repeat
        - failure with no turns left -> timed_out
  3. stop at max_turns or on a completion signal

Token accounting:
  per-turn tokens come directly from lastCallUsage of the --json output,
  independent of JSONL transcript parsing.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import tempfile
import time
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

UTC = timezone.utc

PROTECTED_WORKSPACE_FILES = (
    "emails.csv",
    "calendar_events.csv",
    "project_tasks.csv",
    "customer_relationship_manager_data.csv",
)

DIRECT_MUTATION_MARKERS = (
    ">>",
    " > ",
    "sed -i",
    "perl -i",
    "truncate ",
    " rm ",
    " mv ",
    " cp ",
    " tee ",
    "python -",
    "python3 -",
    "python -c",
    "python3 -c",
)


# ---------------------------------------------------------------------------
# vLLM metrics helper (agent token accounting)
# ---------------------------------------------------------------------------

def _fetch_vllm_tokens(metrics_url: str, _retries: int = 5) -> tuple[float, float]:
    """
    Read cumulative token counters from the vLLM /metrics endpoint.
    Returns: (prompt_tokens_total, generation_tokens_total)

    Uses a 10s timeout with 3 retries (timeouts happen under heavy load).
    Returns (0.0, 0.0) if all attempts fail; the caller should log a warning.
    """
    for attempt in range(_retries):
        try:
            with urllib.request.urlopen(metrics_url, timeout=30) as resp:
                text = resp.read().decode("utf-8")
            prompt = generation = 0.0
            for line in text.splitlines():
                if line.startswith("vllm:prompt_tokens_total{"):
                    prompt = float(line.split("} ")[1])
                elif line.startswith("vllm:generation_tokens_total{"):
                    generation = float(line.split("} ")[1])
            if prompt > 0.0 or generation > 0.0:
                return prompt, generation
            # if both are 0 the metrics may not be initialized yet; retry
        except Exception:
            pass
        if attempt < _retries - 1:
            time.sleep(0.5)
    return 0.0, 0.0


def _normalize_command_text(command: Any) -> str:
    if isinstance(command, str):
        return command
    if isinstance(command, (list, tuple)):
        try:
            return shlex.join(str(part) for part in command)
        except Exception:
            return " ".join(str(part) for part in command)
    return str(command)


def _is_wb_command(command: str) -> bool:
    return bool(re.search(r"\bwb-[\w-]+\.py\b", command))


def _direct_csv_mutation_reason(command: Any) -> str | None:
    command_text = _normalize_command_text(command)
    lowered = f" {command_text.lower()} "
    if _is_wb_command(command_text):
        return None
    if not any(name in lowered for name in PROTECTED_WORKSPACE_FILES):
        return None
    if any(marker in lowered for marker in DIRECT_MUTATION_MARKERS):
        return f"direct protected CSV mutation outside wb-* CLI: {command_text[:200]}"
    return None


def _direct_csv_mutation_reasons(turns: list["TurnRecord"]) -> list[str]:
    reasons: list[str] = []
    for turn in turns:
        for command in turn.commands_executed:
            reason = _direct_csv_mutation_reason(command)
            if reason:
                reasons.append(reason)
    return reasons

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None  # type: ignore


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class TurnRecord:
    turn: int
    message_sent: str
    response_text: str
    is_clarification: bool
    is_correction: bool = False   # turn retried after oracle correction feedback
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    duration_ms: int = 0
    error: str | None = None
    commands_executed: list[str] = field(default_factory=list)  # executed wb-*.py commands


@dataclass
class ConversationResult:
    soul_id: str
    task_id: str
    turns: list[TurnRecord] = field(default_factory=list)
    completed: bool = False
    timed_out: bool = False
    run_start: datetime = field(default_factory=lambda: datetime.now(tz=UTC))
    e2e_latency_ms: int = 0
    eval_result: Any = None   # EvalResult | None (final evaluator result)
    error: str | None = None
    # oracle tokens (tracked separately from agent tokens)
    oracle_clarify_input_tokens: int = 0
    oracle_clarify_output_tokens: int = 0
    oracle_correct_input_tokens: int = 0
    oracle_correct_output_tokens: int = 0

    @property
    def total_turns(self) -> int:
        return len(self.turns)

    @property
    def clarification_turns(self) -> int:
        return sum(1 for t in self.turns if t.is_clarification)

    @property
    def correction_turns(self) -> int:
        return sum(1 for t in self.turns if t.is_correction)

    @property
    def total_input_tokens(self) -> int:
        return sum(t.input_tokens for t in self.turns)

    @property
    def total_output_tokens(self) -> int:
        return sum(t.output_tokens for t in self.turns)

    @property
    def total_cache_read_tokens(self) -> int:
        return sum(t.cache_read_tokens for t in self.turns)

    @property
    def agent_tokens(self) -> int:
        """Tokens consumed by the agent (soul) itself."""
        return self.total_input_tokens + self.total_output_tokens

    @property
    def oracle_tokens(self) -> int:
        """Total oracle tokens (clarification + correction)."""
        return (
            self.oracle_clarify_input_tokens + self.oracle_clarify_output_tokens
            + self.oracle_correct_input_tokens + self.oracle_correct_output_tokens
        )

    @property
    def total_tokens(self) -> int:
        """Total cost tokens = agent + oracle."""
        return self.agent_tokens + self.oracle_tokens

    def to_dict(self) -> dict[str, Any]:
        return {
            "soul_id": self.soul_id,
            "task_id": self.task_id,
            "completed": self.completed,
            "timed_out": self.timed_out,
            "total_turns": self.total_turns,
            "clarification_turns": self.clarification_turns,
            "correction_turns": self.correction_turns,
            # agent tokens
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "total_cache_read_tokens": self.total_cache_read_tokens,
            "agent_tokens": self.agent_tokens,
            # oracle tokens
            "oracle_clarify_input_tokens": self.oracle_clarify_input_tokens,
            "oracle_clarify_output_tokens": self.oracle_clarify_output_tokens,
            "oracle_correct_input_tokens": self.oracle_correct_input_tokens,
            "oracle_correct_output_tokens": self.oracle_correct_output_tokens,
            "oracle_tokens": self.oracle_tokens,
            # totals
            "total_tokens": self.total_tokens,
            "e2e_latency_ms": self.e2e_latency_ms,
            "error": self.error,
            "turns": [
                {
                    "turn": t.turn,
                    "is_clarification": t.is_clarification,
                    "is_correction": t.is_correction,
                    "message_sent": t.message_sent,
                    "response_text": t.response_text,
                    "input_tokens": t.input_tokens,
                    "output_tokens": t.output_tokens,
                    "duration_ms": t.duration_ms,
                    "commands_executed": t.commands_executed,
                    **({"error": t.error} if t.error else {}),
                }
                for t in self.turns
            ],
        }


# ---------------------------------------------------------------------------
# Clarification helpers
# ---------------------------------------------------------------------------

def _first_question_only(text: str) -> str:
    """
    If the agent asks several questions at once, only the first is passed to the
    oracle. This standardizes one turn = one question across souls for fair
    clarification comparisons; the full original response is still logged.
    """
    idx = text.find("?")
    if idx == -1:
        return text
    # if there is a second '?', cut after the first question
    if text.find("?", idx + 1) == -1:
        return text  # single question, return as is
    return text[: idx + 1].strip()


# ---------------------------------------------------------------------------
# Clarification detection
# ---------------------------------------------------------------------------

def is_clarification(text: str) -> bool:
    """Return True if the agent is asking for clarification.

    Protocol: the tag is appended at the end of the response (declared after acting).
    Priority:
    1. [TASK_COMPLETE] within the last 5 lines -> False (declared after execution)
    2. [TASK_CLARIFY]  within the last 5 lines -> True  (information request)
    3. neither -> infer from text patterns (fallback for truncated context)
    """
    lines = [l.strip() for l in text.strip().splitlines() if l.strip()] if text.strip() else []
    tail = lines[-5:] if len(lines) >= 5 else lines
    if any("[TASK_COMPLETE]" in line for line in tail):
        return False
    if any("[TASK_CLARIFY]" in line for line in tail):
        return True

    # fallback: treat as ACTION if completion phrasing is present
    if re.search(
        r"is there anything else|anything else (i can|you need)|"
        r"have (successfully|already) (deleted|created|updated|removed|completed)|"
        r"has been (successfully |)(deleted|created|updated|removed|completed)",
        text, re.IGNORECASE,
    ):
        return False

    # fallback: treat as CLARIFICATION if question patterns are present
    return bool(re.search(
        r"\?|could you clarify|please clarify|please specify|can you confirm|"
        r"which .+ (should|do you|would you)|what (format|type|kind|is|are|do|should)|"
        r"do you (want|mean|prefer)|should i|who should|when (should|would|do)|"
        r"how (many|much|would|should)|i('m| am) not sure|"
        r"need (more|clarification|to know)|before i (proceed|continue|do)",
        text, re.IGNORECASE,
    ))


# ---------------------------------------------------------------------------
# Agent caller (--json mode)
# ---------------------------------------------------------------------------

# Container hosting the openclaw agent CLI. Override via env to target a second
# container when running two endpoints in parallel (e.g. a second compose stack
# named openclaw-gateway-b serving a second vLLM endpoint on the other 2 GPUs).
CLI_CONTAINER = os.environ.get("OPENCLAW_CLI_CONTAINER", "openclaw-gateway")
AGENT_TIMEOUT_SECS = 300
AGENT_MESSAGE_ARG_MAX_CHARS = 100_000
AGENT_FILE_HELPER_CONTAINER_PATH = "/home/node/.openclaw/agent-message-file.mjs"


def _clear_agent_session(soul_id: str, container: str = CLI_CONTAINER) -> None:
    """Reset the agent session before a task (prevents history carryover)."""
    subprocess.run(
        ["docker", "exec", container,
         "sh", "-c",
         f"rm -rf /home/node/.openclaw/agents/{soul_id}/sessions/"],
        capture_output=True,
    )


def _read_session_commands(soul_id: str, container: str, since_line: int = 0) -> tuple[list[str], int]:
    """
    Read the newest session JSONL in the container and return bash commands seen
    after since_line. Used to track whether the agent executed wb-*.py.

    Returns:
        (commands, total_line_count)
        commands: list of executed bash commands (all of them, not only wb-*.py)
    """
    try:
        result = subprocess.run(
            ["docker", "exec", container, "sh", "-c",
             f"latest=$(ls -t /home/node/.openclaw/agents/{soul_id}/sessions/*.jsonl 2>/dev/null | head -1); "
             "[ -n \"$latest\" ] && cat \"$latest\" || true"],
            capture_output=True, text=True, timeout=10,
        )
        lines = [l for l in result.stdout.splitlines() if l.strip()]
        new_lines = lines[since_line:]
        commands: list[str] = []
        for raw in new_lines:
            try:
                entry = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if entry.get("type") != "message":
                continue
            msg = entry.get("message") or {}
            if msg.get("role") != "assistant":
                continue
            for block in msg.get("content") or []:
                if not isinstance(block, dict) or block.get("type") != "toolCall":
                    continue
                # exec tool: arguments.command (openclaw vLLM)
                # bash tool fallback: input.command or input.cmd
                tc_input = block.get("arguments") or block.get("input") or {}
                cmd = tc_input.get("command") or tc_input.get("cmd") or ""
                if cmd:
                    commands.append(cmd)
        return commands, len(lines)
    except Exception:
        return [], since_line


def call_agent(
    soul_id: str,
    message: str,
    dry_run: bool = False,
    container: str = CLI_CONTAINER,
    vllm_metrics_url: str | None = None,
    max_output_tokens: int | None = None,
) -> tuple[str, dict]:
    """
    Send one message to the agent and return (response_text, meta).
    meta includes token counts (from vLLM metrics delta if available) and durationMs.
    """
    message_file: str | None = None
    use_gateway_file_body = (
        len(message) > AGENT_MESSAGE_ARG_MAX_CHARS
        or max_output_tokens is not None
    )
    if use_gateway_file_body:
        tmp = tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            delete=False,
            dir="/tmp",
            prefix=f"openclaw-{soul_id}-",
            suffix=".txt",
        )
        with tmp:
            tmp.write(message)
        message_file = tmp.name
        container_message_file = f"/tmp/{Path(message_file).name}"
        cmd = [
            "docker", "exec", "-i", container,
            "node", AGENT_FILE_HELPER_CONTAINER_PATH,
            container_message_file,
            soul_id,
            str(AGENT_TIMEOUT_SECS),
        ]
        if max_output_tokens is not None:
            cmd.append(str(max_output_tokens))
    else:
        cmd = [
            "docker", "exec", "-i", container,
            "node", "dist/index.js", "agent",
            "--message", message,
            "--agent", soul_id,
            "--no-color", "--json",
        ]

    if dry_run:
        return (
            f"[DRY RUN] Received: {message[:80]}",
            {"lastCallUsage": {"input": 10, "output": 5, "cacheRead": 0},
             "durationMs": 0},
        )

    # vLLM metrics snapshot (before the call)
    pre_prompt = pre_gen = 0.0
    if vllm_metrics_url:
        pre_prompt, pre_gen = _fetch_vllm_tokens(vllm_metrics_url)

    try:
        if message_file:
            subprocess.run(
                [
                    "docker", "exec", "-i", container,
                    "sh", "-c", f"cat > /tmp/{Path(message_file).name}",
                ],
                capture_output=True,
                text=True,
                timeout=30,
                input=Path(message_file).read_text(encoding="utf-8"),
                check=True,
            )
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=AGENT_TIMEOUT_SECS,
        )

        # vLLM metrics snapshot (after the call); wait for flush, then take deltas
        input_tokens = output_tokens = 0
        if vllm_metrics_url:
            time.sleep(1.0)  # wait for vLLM's async metrics flush
            post_prompt, post_gen = _fetch_vllm_tokens(vllm_metrics_url)
            if post_prompt == 0.0 and post_gen == 0.0 and pre_prompt == 0.0:
                print("[WARN] vLLM metrics fetch returned 0/0 — agent token counts will be 0", flush=True)
            input_tokens  = max(0, int(post_prompt - pre_prompt))
            output_tokens = max(0, int(post_gen    - pre_gen))

        if result.returncode != 0:
            return f"[ERROR] exit {result.returncode}: {result.stderr[:300]}", {}

        data = json.loads(result.stdout)
        payloads = data.get("result", {}).get("payloads", [])
        text = " ".join(p.get("text", "") for p in payloads if p.get("text"))
        meta = data.get("result", {}).get("meta", {})

        # prefer the vLLM delta; fall back to gateway lastCallUsage
        usage = meta.get("agentMeta", {}).get("lastCallUsage", {})
        if input_tokens == 0 and output_tokens == 0:
            input_tokens  = usage.get("input", 0)
            output_tokens = usage.get("output", 0)

        return text, {
            "lastCallUsage": {"input": input_tokens, "output": output_tokens,
                              "cacheRead": usage.get("cacheRead", 0)},
            "durationMs": meta.get("durationMs", 0),
        }

    except subprocess.CalledProcessError as e:
        return f"[ERROR] message file upload failed: {e.stderr[:300] if e.stderr else str(e)}", {}
    except subprocess.TimeoutExpired:
        return "[TIMEOUT]", {}
    except (json.JSONDecodeError, KeyError) as e:
        return f"[PARSE ERROR] {e}", {}
    finally:
        if message_file:
            Path(message_file).unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Clarification Oracle
# ---------------------------------------------------------------------------

ORACLE_SYSTEM_PROMPT = """You are a simulated user in an AI agent experiment.

An AI agent has been given an ambiguous workplace task and is asking you for clarification.
Your job: answer the agent's question as naturally and concisely as possible,
based ONLY on the ground-truth answer provided below.

Rules:
- Answer in 1-2 sentences max
- Resolve the AMBIGUITY only — clarify intent, scope, or target (e.g. "the last one", "from Nadia", "this week")
- Do NOT provide internal IDs, record numbers, database keys, or raw data values — the agent must look those up itself
- Do NOT reveal the ground-truth answer format (function calls) directly
- NEVER say "use your best judgment" or "use your discretion" — always give a concrete answer
- If the question is directly relevant to resolving the task ambiguity, answer it concretely
- If the question is off-topic or irrelevant to completing the task (e.g. asking about tools, systems, or things not needed to resolve the ambiguity), redirect: "That doesn't matter — just [restate the core task simply]."
- Respond in the same language the agent used"""

ORACLE_USER_TEMPLATE = """Original task given to the agent:
"{original_query}"

Ground-truth expected outcome:
{original_answer}

Agent's clarification question:
"{question}"

Answer the question naturally, as the user who assigned this task would respond."""


def oracle_answer(
    question: str,
    original_query: str,
    original_answer: str,
    client: Any,
    model: str = "gpt-4o-mini",
    dry_run: bool = False,
) -> tuple[str, dict]:
    """Generate a natural language answer to the agent's clarification question.

    Returns:
        (answer_text, token_usage)  where token_usage = {"input": int, "output": int}
    """
    if dry_run:
        return "[DRY RUN ORACLE] Please use your best judgment.", {"input": 0, "output": 0}

    if client is None:
        raise RuntimeError(
            "oracle_client is None — set OPENAI_API_KEY before running the experiment. "
            "Fallback 'best judgment' is disabled to prevent invalid results."
        )

    for attempt in range(3):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": ORACLE_SYSTEM_PROMPT},
                    {"role": "user", "content": ORACLE_USER_TEMPLATE.format(
                        original_query=original_query,
                        original_answer=original_answer,
                        question=question,
                    )},
                ],
                temperature=0.3,
                max_tokens=4096,
            )
            usage = response.usage
            msg = response.choices[0].message
            content = msg.content or getattr(msg, "reasoning_content", None) or ""
            return content.strip(), {
                "input": usage.prompt_tokens if usage else 0,
                "output": usage.completion_tokens if usage else 0,
            }
        except Exception as e:
            if attempt == 2:
                raise RuntimeError(f"Oracle failed after 3 attempts: {e}") from e
            time.sleep(2 ** attempt)


# ---------------------------------------------------------------------------
# Correction Oracle
# ---------------------------------------------------------------------------

CORRECTION_SYSTEM_PROMPT = """You are a simulated user reviewing an AI agent's completed work.

The agent has attempted your task but the result is not correct.
Your job: describe what outcome is missing or wrong, as a user would naturally notice it.

Rules:
- 1-2 sentences max
- Be direct: state that the expected outcome has not happened yet, not that something "seems" wrong
- Describe the OUTCOME that is wrong (e.g. "the chart isn't there", "that event is still on my calendar")
- Do NOT name tools, scripts, commands, or arguments — you are a user, not a developer
- Do NOT reveal function call formats or internal system details
- Do NOT tell the agent how to fix it — only describe what is still not right
- Respond in the same language the agent used"""

CORRECTION_USER_TEMPLATE = """Original task:
"{original_query}"

Expected outcome (use this to describe what is missing or wrong — do NOT mention tools or implementation):
{original_answer}

What the agent did wrong (technical check results):
{eval_failures}

Tell the agent what outcome is still missing or incorrect, as the user who assigned this task would say it.

Remember: use [TASK_COMPLETE] only after the required action has actually been executed and confirmed."""


def oracle_correction(
    eval_failures: list[dict],
    original_query: str,
    original_answer: str,
    client: Any,
    model: str = "gpt-4o-mini",
    dry_run: bool = False,
) -> tuple[str, dict]:
    """Generate natural correction feedback based on evaluator failure details.

    Returns:
        (correction_text, token_usage)  where token_usage = {"input": int, "output": int}
    """
    if dry_run:
        return "[DRY RUN CORRECTION] That's not quite right — please check and try again.", {"input": 0, "output": 0}

    if client is None:
        raise RuntimeError("oracle_client is None — cannot generate correction feedback.")

    failure_lines = [
        f"- {d['func']}: {d.get('detail', 'check failed')}"
        for d in eval_failures
        if not d.get("passed", True) and "func" in d
    ]
    failure_text = "\n".join(failure_lines) if failure_lines else "The task was not completed correctly."

    for attempt in range(3):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": CORRECTION_SYSTEM_PROMPT},
                    {"role": "user", "content": CORRECTION_USER_TEMPLATE.format(
                        original_query=original_query,
                        original_answer=original_answer,
                        eval_failures=failure_text,
                    )},
                ],
                temperature=0.3,
                max_tokens=4096,
            )
            usage = response.usage
            msg = response.choices[0].message
            content = msg.content or getattr(msg, "reasoning_content", None) or ""
            return content.strip(), {
                "input": usage.prompt_tokens if usage else 0,
                "output": usage.completion_tokens if usage else 0,
            }
        except Exception as e:
            if attempt == 2:
                raise RuntimeError(f"Correction oracle failed after 3 attempts: {e}") from e
            time.sleep(2 ** attempt)


# ---------------------------------------------------------------------------
# Main conversation loop
# ---------------------------------------------------------------------------

def run_conversation(
    soul_id: str,
    task_id: str,
    initial_message: str,
    original_query: str,
    original_answer: str,
    oracle_client: Any = None,
    oracle_model: str = "gpt-4o-mini",
    max_turns: int = 10,
    dry_run: bool = False,
    container: str = CLI_CONTAINER,
    verbose: bool = True,
    workspace: Path | None = None,
    vllm_metrics_url: str | None = None,  # e.g. "http://host:port/metrics"
) -> ConversationResult:
    """
    Run a full multi-turn conversation for one task.

    Args:
        soul_id:          Agent identity (soul-a / soul-b / soul-c)
        task_id:          Task identifier for logging
        initial_message:  The ambiguous query to send first
        original_query:   Original WorkBench query (oracle context)
        original_answer:  WorkBench ground-truth answer (oracle context)
        oracle_client:    OpenAI-compatible client for oracle/correction
        max_turns:        Maximum conversation turns (formula: L + 3 + 2*multi_domain)
        workspace:        Soul workspace path — enables mid-loop evaluation & correction
    """
    from evaluator import EvalResult, evaluate as _evaluate  # lazy import to avoid circular dep

    result = ConversationResult(soul_id=soul_id, task_id=task_id)

    # reset the session before the task (prevents history carryover)
    if not dry_run:
        _clear_agent_session(soul_id, container=container)

    message = initial_message
    _wall_start = time.perf_counter()
    _seen_responses: set[str] = set()  # detects identical-response loops
    _next_is_correction = False        # marks the next turn as a correction reply
    _session_line_offset = 0           # session JSONL read offset (per-turn command extraction)

    # Reset action log once per task (not per turn).
    # Accumulating across turns lets us capture write ops even when the final turn
    # is a verification-only turn with no write ops.
    # compute_action_precision() deduplicates anchors via set, so retries don't double-count.
    if workspace is not None and not dry_run:
        (workspace / "memory" / "action_log.jsonl").unlink(missing_ok=True)

    for turn_num in range(1, max_turns + 1):
        if verbose:
            if turn_num == 1:
                label = "initial"
            elif _next_is_correction:
                label = "correction-reply"
            else:
                label = "oracle-reply"
            print(f"    turn {turn_num} [{label}]: {message[:80]}{'…' if len(message) > 80 else ''}")

        response_text, meta = call_agent(soul_id, message, dry_run=dry_run,
                                          container=container, vllm_metrics_url=vllm_metrics_url)
        usage = meta.get("lastCallUsage", {})

        # extract wb-*.py commands executed this turn (session JSONL parsing)
        commands_executed: list[str] = []
        if not dry_run:
            commands_executed, _session_line_offset = _read_session_commands(
                soul_id, container, since_line=_session_line_offset
            )

        clarification = is_clarification(response_text)
        record = TurnRecord(
            turn=turn_num,
            message_sent=message,
            response_text=response_text,
            is_clarification=clarification,
            is_correction=_next_is_correction,
            input_tokens=usage.get("input", 0),
            output_tokens=usage.get("output", 0),
            cache_read_tokens=usage.get("cacheRead", 0),
            duration_ms=meta.get("durationMs", 0),
            commands_executed=commands_executed,
        )
        _next_is_correction = False

        if "[TIMEOUT]" in response_text:
            record.error = "timeout"
            result.turns.append(record)
            result.error = "agent timed out"
            break

        if "[ERROR]" in response_text or "[PARSE ERROR]" in response_text:
            record.error = response_text
            result.turns.append(record)
            result.error = response_text
            break

        result.turns.append(record)

        if verbose:
            cmd_summary = f", cmds={len(commands_executed)}" if commands_executed else ", cmds=0"
            print(f"         -> {'[CLARIFICATION]' if clarification else '[ACTION]'} "
                  f"tokens={record.input_tokens}+{record.output_tokens}{cmd_summary}")
            for cmd in commands_executed:
                print(f"           $ {cmd[:120]}")

        # loop detection (skip the turn right after a correction; a different message was sent)
        if not record.is_correction and response_text in _seen_responses:
            result.error = "loop_detected: identical response repeated"
            if verbose:
                print(f"    WARNING identical response detected at turn {turn_num} — breaking loop")
            break
        _seen_responses.add(response_text)

        # -- clarification case ----------------------------------------------
        if clarification:
            if turn_num == max_turns:
                result.timed_out = True
                result.error = f"max_turns ({max_turns}) reached without completion"
                if verbose:
                    print(f"    WARNING max turns reached")
                break

            try:
                answer, clarify_usage = oracle_answer(
                    question=response_text,
                    original_query=original_query,
                    original_answer=original_answer,
                    client=oracle_client,
                    model=oracle_model,
                    dry_run=dry_run,
                )
            except RuntimeError as e:
                result.error = str(e)
                if verbose:
                    print(f"    X oracle error: {e}")
                break

            result.oracle_clarify_input_tokens  += clarify_usage.get("input", 0)
            result.oracle_clarify_output_tokens += clarify_usage.get("output", 0)
            if verbose:
                print(f"    oracle >> {answer[:100]}{'…' if len(answer) > 100 else ''} "
                      f"[oracle_tok={clarify_usage.get('input',0)}+{clarify_usage.get('output',0)}]")
            message = answer
            if not dry_run:
                time.sleep(0.5)
            continue

        # -- action (non-clarification) case -> evaluator check ---------------
        if workspace is not None:
            policy_violations = _direct_csv_mutation_reasons(result.turns)
            if policy_violations:
                eval_res = EvalResult(
                    e2e_success=False,
                    total_checks=1,
                    passed_checks=0,
                    details=[
                        {
                            "func": "runner.direct_csv_mutation_guard",
                            "passed": False,
                            "detail": reason,
                        }
                        for reason in policy_violations
                    ],
                )
            else:
                eval_res = _evaluate(original_answer, workspace)
            result.eval_result = eval_res

            if eval_res.e2e_success:
                result.completed = True
                if verbose:
                    print(f"    OK eval passed (score={eval_res.score:.2f})")
                break

            # failure: if turns remain, send correction feedback
            if turn_num < max_turns:
                if verbose:
                    print(f"    X eval failed (score={eval_res.score:.2f}) — generating correction")
                try:
                    correction_msg, correct_usage = oracle_correction(
                        eval_failures=eval_res.details,
                        original_query=original_query,
                        original_answer=original_answer,
                        client=oracle_client,
                        model=oracle_model,
                        dry_run=dry_run,
                    )
                except RuntimeError as e:
                    result.error = str(e)
                    if verbose:
                        print(f"    X correction oracle error: {e}")
                    break

                result.oracle_correct_input_tokens  += correct_usage.get("input", 0)
                result.oracle_correct_output_tokens += correct_usage.get("output", 0)
                if verbose:
                    print(f"    correction >> {correction_msg[:100]}{'…' if len(correction_msg) > 100 else ''} "
                          f"[oracle_tok={correct_usage.get('input',0)}+{correct_usage.get('output',0)}]")
                message = correction_msg
                _next_is_correction = True
                if not dry_run:
                    time.sleep(0.5)
                continue
            else:
                result.timed_out = True
                result.error = f"max_turns ({max_turns}) reached without eval success"
                if verbose:
                    print(f"    WARNING max turns reached — eval score={eval_res.score:.2f}")
                break

        else:
            # without a workspace, keep legacy behavior (non-clarification = complete)
            result.completed = True
            break

    result.e2e_latency_ms = int((time.perf_counter() - _wall_start) * 1000)
    return result
