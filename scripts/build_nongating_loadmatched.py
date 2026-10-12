#!/usr/bin/env python3
"""Build the high-load corpus containing no constraint-matched lines.

The corpus starts with all unmatched lines from GPT-OSS replicate 1 and is
padded with seeded, shuffled unmatched lines from replicates 2 and 3 of the
same condition until it matches the full replicate-1 Run-4 token count.

Usage:
  python3 scripts/build_nongating_loadmatched.py \
      --rep GPT-OSS-120B_rep1 --seed 1
"""

import argparse
import glob
import json
import random
import sys
from pathlib import Path

import tiktoken

sys.path.insert(0, str(Path(__file__).parent))
from extract_gating_lines import has_gating

SOULS = ("soul-a", "soul-b", "soul-c")
PAD_REPS = ("rep2", "rep3")


def run4_path(results_root, model, rep, soul):
    pattern = f"{results_root}/{model}/{model}_{rep}/**/{soul}/patterns_run4.md"
    matches = glob.glob(pattern, recursive=True)
    if len(matches) != 1:
        raise FileNotFoundError(f"{pattern} -> {len(matches)} matches")
    return Path(matches[0])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--rep", default="GPT-OSS-120B_rep1")
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--tokenizer", default="o200k_base")
    parser.add_argument("--results-root", default="results")
    args = parser.parse_args()

    model, rep_number = args.rep.rsplit("_rep", 1)
    base_rep = f"rep{rep_number}"
    encoder = tiktoken.get_encoding(args.tokenizer)
    tokens = lambda text: len(encoder.encode(text))
    output_root = Path(args.results_root) / "interventions" / (
        f"{args.rep}_run5_nongating_loadmatched"
    ) / f"seed_{args.seed:02d}"
    output_root.mkdir(parents=True, exist_ok=True)

    for soul in SOULS:
        base_file = run4_path(args.results_root, model, base_rep, soul)
        base_text = base_file.read_text(encoding="utf-8", errors="replace")
        target = tokens(base_text)
        base_lines = [line for line in base_text.splitlines() if line.strip()]
        kept = [line for line in base_lines if not has_gating(line)]

        pool = []
        for pad_rep in PAD_REPS:
            text = run4_path(args.results_root, model, pad_rep, soul).read_text(
                encoding="utf-8", errors="replace")
            pool.extend(line for line in text.splitlines()
                        if line.strip() and not has_gating(line))
        rng = random.Random(args.seed)
        rng.shuffle(pool)

        output_lines = list(kept)
        current = sum(tokens(line + "\n") for line in output_lines)
        pad_used = 0
        for line in pool:
            if current >= target:
                break
            output_lines.append(line)
            current += tokens(line + "\n")
            pad_used += 1

        matched_count = sum(has_gating(line) for line in output_lines)
        if matched_count:
            raise AssertionError(f"{soul}: {matched_count} matched lines leaked")
        if current < target:
            raise RuntimeError(f"{soul}: padding pool exhausted at {current}/{target}")

        metadata = {
            "soul": soul,
            "seed": args.seed,
            "base_rep": args.rep,
            "target_tokens": target,
            "final_tokens": current,
            "delta_tokens_vs_target": current - target,
            "base_nongating_lines": len(kept),
            "pad_lines_used": pad_used,
            "final_lines": len(output_lines),
            "constraint_lines_in_output": matched_count,
            "base_full_lines": len(base_lines),
        }
        (output_root / f"{soul}_patterns_run4_nongating_loadmatched.md").write_text(
            "\n".join(output_lines) + "\n", encoding="utf-8")
        (output_root / f"{soul}_metadata.json").write_text(
            json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
        print(f"{soul}: target={target}, final={current}, "
              f"lines={len(output_lines)}, matched=0")


if __name__ == "__main__":
    main()
