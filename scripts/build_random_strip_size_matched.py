#!/usr/bin/env python3
"""Build the low-load, constraint-retaining control used in the paper.

For each prompt condition, randomly remove only lines that do *not* match the
constraint-bearing regexes.  The requested removal count equals the number of
lines removed by gate-stripping, so the resulting line count matches the
gate-stripped corpus whenever the unmatched-line pool is large enough.  All
matched lines are retained.  Bold exhausts its unmatched pool before reaching
the gate-stripped line count; the metadata records this explicitly.

Usage:
  python3 scripts/build_random_strip_size_matched.py \
      --rep GPT-OSS-120B_rep1 --seeds 1 2 3
"""

import argparse
import glob
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from extract_gating_lines import has_gating

SOULS = ("soul-a", "soul-b", "soul-c")


def run4_path(results_root, model, rep, soul):
    pattern = f"{results_root}/{model}/{model}_{rep}/**/{soul}/patterns_run4.md"
    matches = glob.glob(pattern, recursive=True)
    if len(matches) != 1:
        raise FileNotFoundError(f"{pattern} -> {len(matches)} matches")
    return Path(matches[0])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--rep", default="GPT-OSS-120B_rep1")
    parser.add_argument("--seeds", nargs="+", type=int, default=[1, 2, 3])
    parser.add_argument("--results-root", default="results")
    args = parser.parse_args()

    model, rep_number = args.rep.rsplit("_rep", 1)
    rep = f"rep{rep_number}"
    control_root = Path(args.results_root) / "interventions" / (
        f"{args.rep}_run5_random_stripped_size_matched"
    )

    for seed in args.seeds:
        seed_root = control_root / f"seed_{seed:02d}"
        seed_root.mkdir(parents=True, exist_ok=True)
        for soul in SOULS:
            source = run4_path(args.results_root, model, rep, soul)
            lines = [line for line in source.read_text(
                encoding="utf-8", errors="replace").splitlines() if line.strip()]
            matched = [i for i, line in enumerate(lines) if has_gating(line)]
            unmatched = [i for i, line in enumerate(lines) if not has_gating(line)]

            requested = len(matched)
            feasible = min(requested, len(unmatched))
            rng = random.Random(seed)
            removed = set(rng.sample(unmatched, feasible))
            kept_lines = [line for i, line in enumerate(lines) if i not in removed]
            removed_lines = [line for i, line in enumerate(lines) if i in removed]

            target_lines = len(lines) - requested
            output = seed_root / f"{soul}_patterns_run4_random_stripped.md"
            output.write_text("\n".join(kept_lines) + "\n", encoding="utf-8")
            (seed_root / f"{soul}_random_removed_lines.md").write_text(
                "\n".join(removed_lines) + "\n", encoding="utf-8")
            metadata = {
                "soul": soul,
                "seed": seed,
                "original_lines": len(lines),
                "constraint_lines_retained": len(matched),
                "requested_removed_unmatched_lines": requested,
                "removed_unmatched_lines": feasible,
                "target_gate_stripped_lines": target_lines,
                "final_lines": len(kept_lines),
                "delta_lines_vs_gate_stripped": len(kept_lines) - target_lines,
                "exact_line_match_feasible": feasible == requested,
            }
            (seed_root / f"{soul}_metadata.json").write_text(
                json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
            print(f"seed={seed:02d} {soul}: retained {len(matched)} matched lines; "
                  f"final={len(kept_lines)}, target={target_lines}")


if __name__ == "__main__":
    main()
