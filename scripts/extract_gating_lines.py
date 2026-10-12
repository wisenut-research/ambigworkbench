#!/usr/bin/env python3
"""
extract_gating_lines.py — Extract ONLY the gating-clause-bearing pattern lines
from a patterns.md corpus. The gate-strip runner retains the complementary set.

Used by gate-injection ablation: we take a strong-IF model's gating-bearing
lines and overlay them onto a weak-IF model's own corpus.

Usage:
  python3 scripts/extract_gating_lines.py \\
    --input  results/<MODEL>/<MODEL>_<rep>_memory_log/<soul>/patterns_run4.md \\
    --output results/_ablation/<...>/<soul>_gating_lines_only.md
"""

import argparse
import re
import sys
from pathlib import Path

# Same regex as §4 / Appendix I
PROHIBITIVE = re.compile(
    r"\b(do not|don't|never|must not|mustn't|avoid|refrain|forbid|prohibit|disallow|cannot|can't)\b",
    re.IGNORECASE,
)
CONDITIONAL = re.compile(
    r"\b(only if|only when|unless|before [a-z]+ing|until|provided that|require[ds]?|need[s]? to confirm|require[sd]? confirm)\b",
    re.IGNORECASE,
)
ASK_FIRST = re.compile(
    r"\b(ask|clarify|confirm|verify|check (?:with|the user)|request (?:more )?(?:clarification|info(?:rmation)?))\b",
    re.IGNORECASE,
)


def has_gating(line: str) -> bool:
    return bool(PROHIBITIVE.search(line) or CONDITIONAL.search(line) or ASK_FIRST.search(line))


def extract(input_path: Path, output_path: Path) -> dict:
    src_lines = input_path.read_text(encoding="utf-8").splitlines(keepends=True)
    extracted: list[str] = []
    for line in src_lines:
        if line.strip().startswith("- [") and has_gating(line):
            extracted.append(line)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("".join(extracted), encoding="utf-8")
    return {
        "total_pattern_lines_in_source": sum(1 for l in src_lines if l.strip().startswith("- [")),
        "extracted_gating_lines": len(extracted),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--input", "-i", required=True, type=Path)
    ap.add_argument("--output", "-o", required=True, type=Path)
    args = ap.parse_args()

    if not args.input.exists():
        print(f"[ERROR] input not found: {args.input}", file=sys.stderr)
        return 1

    stats = extract(args.input, args.output)
    rate = 100.0 * stats["extracted_gating_lines"] / max(stats["total_pattern_lines_in_source"], 1)
    print(f"Source:  {args.input}")
    print(f"Output:  {args.output}")
    print(f"Source pattern lines:    {stats['total_pattern_lines_in_source']}")
    print(f"Extracted gating lines:  {stats['extracted_gating_lines']} ({rate:.1f}%)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
