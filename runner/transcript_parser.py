"""
Parses openclaw session transcripts (JSONL) to extract per-run token/cost metrics.

Transcript path: experiment/openclaw-config/agents/<agentId>/sessions/<session-id>.jsonl

Entry format (type="message"):
  {
    "type": "message",
    "timestamp": "2026-03-20T02:23:20.347Z",
    "message": {
      "role": "assistant" | "user",
      "content": [ {"type": "text", "text": "..."} | {"type": "toolCall", ...} ],
      "usage": { "input": N, "output": N, "cacheRead": N, "cacheWrite": N, "totalTokens": N },
      "stopReason": "stop" | "toolUse" | "error"
    }
  }
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass
class ToolCallRecord:
    name: str
    success: bool
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class RunMetrics:
    soul_id: str
    task_id: str
    complexity: str

    total_input_tokens: int = 0
    total_output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0

    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    clarification_messages: int = 0
    total_turns: int = 0

    completed: bool = False
    error: str | None = None

    @property
    def total_tokens(self) -> int:
        return self.total_input_tokens + self.total_output_tokens

    @property
    def total_tool_calls(self) -> int:
        return len(self.tool_calls)

    @property
    def failed_tool_calls(self) -> int:
        return sum(1 for t in self.tool_calls if not t.success)

    @property
    def failed_tool_token_waste(self) -> int:
        return sum(t.input_tokens + t.output_tokens for t in self.tool_calls if not t.success)

    def to_dict(self) -> dict[str, Any]:
        return {
            "soul_id": self.soul_id,
            "task_id": self.task_id,
            "complexity": self.complexity,
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "cache_read_tokens": self.cache_read_tokens,
            "cache_write_tokens": self.cache_write_tokens,
            "total_tokens": self.total_tokens,
            "total_turns": self.total_turns,
            "total_tool_calls": self.total_tool_calls,
            "failed_tool_calls": self.failed_tool_calls,
            "failed_tool_token_waste": self.failed_tool_token_waste,
            "clarification_messages": self.clarification_messages,
            "completed": self.completed,
            "error": self.error,
        }


_QUESTION_PATTERN = re.compile(
    r"\?|could you clarify|please clarify|please specify|which .+ (should|do you|would you)|"
    r"what (format|type|kind|is|are)|do you want|should i",
    re.IGNORECASE,
)


def _parse_iso(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def parse_transcript(
    path: Path,
    soul_id: str,
    task_id: str,
    complexity: str,
    after: datetime | None = None,
    before: datetime | None = None,
) -> RunMetrics:
    """
    Parse openclaw session JSONL for a single agent run.

    Use `after` and `before` to isolate a specific task's entries within
    a continuous session file (all tasks share the same session file).
    """
    metrics = RunMetrics(soul_id=soul_id, task_id=task_id, complexity=complexity)

    if not path.exists():
        metrics.error = f"transcript not found: {path}"
        return metrics

    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as e:
        metrics.error = str(e)
        return metrics

    pending_tool_name: str | None = None
    pending_tool_input_tokens: int = 0

    for raw_line in lines:
        raw_line = raw_line.strip()
        if not raw_line:
            continue

        try:
            entry = json.loads(raw_line)
        except json.JSONDecodeError:
            continue

        # Timestamp-based filtering to isolate this task's run
        entry_ts_raw = entry.get("timestamp")
        if entry_ts_raw:
            try:
                entry_ts = _parse_iso(entry_ts_raw)
                if after and entry_ts <= after:
                    continue
                if before and entry_ts >= before:
                    continue
            except ValueError:
                pass

        if entry.get("type") != "message":
            continue

        msg = entry.get("message") or {}
        role = msg.get("role", "")
        content = msg.get("content") or []
        stop_reason = msg.get("stopReason", "")

        # --- Token usage (lives inside message.usage) ---
        usage = msg.get("usage") or {}
        inp = usage.get("input", 0) or 0
        out = usage.get("output", 0) or 0
        cr = usage.get("cacheRead", 0) or 0
        cw = usage.get("cacheWrite", 0) or 0

        if role == "assistant" and (inp or out):
            metrics.total_input_tokens += inp
            metrics.total_output_tokens += out
            metrics.cache_read_tokens += cr
            metrics.cache_write_tokens += cw
            metrics.total_turns += 1

            # --- Tool calls inside content blocks ---
            tool_calls_in_turn = [b for b in content if isinstance(b, dict) and b.get("type") == "toolCall"]
            for tc in tool_calls_in_turn:
                pending_tool_name = tc.get("name", "unknown")
                pending_tool_input_tokens = inp

            # If this turn had tool results (stop_reason != toolUse but prior had toolCall)
            if stop_reason == "error":
                if pending_tool_name:
                    metrics.tool_calls.append(ToolCallRecord(
                        name=pending_tool_name,
                        success=False,
                        input_tokens=pending_tool_input_tokens,
                        output_tokens=out,
                    ))
                    pending_tool_name = None
            elif tool_calls_in_turn:
                # Record the tool call; success determined by next turn
                pass
            else:
                # Text response turn — flush any pending tool as failed if no result came
                if pending_tool_name:
                    metrics.tool_calls.append(ToolCallRecord(
                        name=pending_tool_name,
                        success=False,
                        input_tokens=pending_tool_input_tokens,
                        output_tokens=out,
                    ))
                    pending_tool_name = None

            # --- Clarification detection ---
            text_blocks = [b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"]
            text = " ".join(text_blocks)
            if text and _QUESTION_PATTERN.search(text):
                metrics.clarification_messages += 1

        elif role == "tool" or role == "tool_result":
            # Tool result — mark pending tool as succeeded or failed
            is_error = msg.get("is_error") or stop_reason == "error"
            if pending_tool_name:
                metrics.tool_calls.append(ToolCallRecord(
                    name=pending_tool_name,
                    success=not is_error,
                    input_tokens=pending_tool_input_tokens,
                    output_tokens=0,
                ))
                pending_tool_name = None

    if metrics.total_turns > 0 and not metrics.error:
        metrics.completed = True

    return metrics


def find_latest_transcript(agent_id: str, openclaw_dir: Path | None = None) -> Path | None:
    base = openclaw_dir or Path.home() / ".openclaw"
    sessions_dir = base / "agents" / agent_id / "sessions"
    if not sessions_dir.exists():
        return None
    jsonl_files = sorted(
        [p for p in sessions_dir.glob("*.jsonl") if p.name != "sessions.json"],
        key=lambda p: p.stat().st_mtime,
    )
    return jsonl_files[-1] if jsonl_files else None
