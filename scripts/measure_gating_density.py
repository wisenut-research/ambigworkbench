#!/usr/bin/env python3
"""
measure_gating_density.py — Record per-100-line gating-clause density of one or
more patterns.md corpora.

Used to verify that the gate-injection manipulation worked: the injection arm
should RAISE gating density vs the Qwen baseline, while the token-matched
non-gating control should LOWER (dilute) it. Densities use the same regex
families as §4 / Appendix I and extract_gating_lines.py so they line up with
the paper.

Density_c = 100 * (#lines matching family c) / (#non-empty pattern lines)

Usage:
  python3 scripts/measure_gating_density.py \\
    --inputs a.md b.md ... --label some_arm --output dens.json
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from extract_gating_lines import ASK_FIRST, CONDITIONAL, PROHIBITIVE  # noqa: E402


def density(path: Path) -> dict:
    lines = [
        l for l in path.read_text(encoding="utf-8", errors="replace").splitlines()
        if l.strip().startswith("- [")
    ]
    n = len(lines)
    if not n:
        return {"file": str(path), "pattern_lines": 0}
    proh = sum(1 for l in lines if PROHIBITIVE.search(l))
    cond = sum(1 for l in lines if CONDITIONAL.search(l))
    ask = sum(1 for l in lines if ASK_FIRST.search(l))
    any_gate = sum(
        1 for l in lines
        if PROHIBITIVE.search(l) or CONDITIONAL.search(l) or ASK_FIRST.search(l)
    )
    return {
        "file": str(path),
        "pattern_lines": n,
        "PROHIBITIVE_per100": round(100 * proh / n, 2),
        "CONDITIONAL_per100": round(100 * cond / n, 2),
        "ASK_FIRST_per100": round(100 * ask / n, 2),
        "ANY_GATING_per100": round(100 * any_gate / n, 2),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--inputs", "-i", nargs="+", required=True, type=Path)
    ap.add_argument("--label", default="")
    ap.add_argument("--output", "-o", type=Path, default=None)
    args = ap.parse_args()

    rows = [density(p) for p in args.inputs if p.exists()]
    payload = {"label": args.label, "corpora": rows}
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    for r in rows:
        if r.get("pattern_lines"):
            print(
                f"  [{args.label}] {Path(r['file']).name}: "
                f"PROH={r['PROHIBITIVE_per100']} COND={r['CONDITIONAL_per100']} "
                f"ASK_FIRST={r['ASK_FIRST_per100']} ANY={r['ANY_GATING_per100']} "
                f"(n={r['pattern_lines']})"
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
