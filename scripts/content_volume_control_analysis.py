#!/usr/bin/env python3
"""Summarize the targeted GPT-OSS content-volume controls.

The script reports success and under-action for the original replicate-1
Run 5, gate-stripping, three random-strip subsets, and the high-load corpus
with zero constraint-matched lines.
"""

import argparse
import glob
import json
from pathlib import Path

SOULS = (("soul-b", "Cautious"), ("soul-a", "Neutral"), ("soul-c", "Bold"))


def read_jsonls(patterns):
    matches = []
    for pattern in patterns:
        matches.extend(glob.glob(pattern, recursive=True))
    matches = sorted({path for path in matches
                      if "_parallel_tmp" not in path and ".bak" not in path})
    if not matches:
        raise FileNotFoundError(" | ".join(patterns))
    records = []
    for path in matches:
        records.extend(json.loads(line) for line in Path(path).read_text(
            encoding="utf-8").splitlines() if line.strip())
    # A merged file and per-condition files may coexist.  Keep one record per
    # condition/task pair rather than double counting regenerated outputs.
    unique = {}
    for record in records:
        unique[(record["soul_id"], record["task_id"])] = record
    return list(unique.values())


def rates(records):
    output = {}
    for soul, name in SOULS:
        subset = [record for record in records if record["soul_id"] == soul]
        success = sum(bool((record.get("eval") or {}).get("e2e_success"))
                      for record in subset) / len(subset)
        precision = [record.get("action_precision") or {} for record in subset]
        precision = [item for item in precision if item.get("applicable")]
        under = sum(item.get("exec_count", 0) < item.get("gt_count", 0)
                    for item in precision) / len(precision)
        output[name] = (success, under)
    return output


def print_arm(label, records):
    values = rates(records)
    print(label)
    for _, name in SOULS:
        success, under = values[name]
        print(f"  {name:9s} success={success:.3f} under={under:.3f}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--results-root", default="results")
    parser.add_argument("--extra-results-root", default=None)
    args = parser.parse_args()
    roots = [args.results_root]
    if args.extra_results_root:
        roots.append(args.extra_results_root)

    base_patterns = [
        f"{args.results_root}/GPT-OSS-120B/GPT-OSS-120B_rep1/*run5*/**/*.jsonl"
    ]
    gate_patterns = []
    random_patterns = {seed: [] for seed in (1, 2, 3)}
    high_patterns = []
    for root in roots:
        for parent in ("interventions", "_ablation"):
            gate_patterns.append(
                f"{root}/{parent}/GPT-OSS-120B_rep1_run5_stripped/**/*.jsonl")
            for seed in (1, 2, 3):
                random_patterns[seed].append(
                    f"{root}/{parent}/GPT-OSS-120B_rep1_run5_random_stripped_size_matched/seed_{seed:02d}/**/*.jsonl")
            high_patterns.append(
                f"{root}/{parent}/GPT-OSS-120B_rep1_run5_nongating_loadmatched/seed_01/**/*.jsonl")

    print_arm("Original high-load corpus", read_jsonls(base_patterns))
    print_arm("Gate-strip: low load, no matched lines", read_jsonls(gate_patterns))
    for seed in (1, 2, 3):
        print_arm(f"Random-strip seed {seed}: low load, matched lines retained",
                  read_jsonls(random_patterns[seed]))
    print_arm("Non-gating load-matched: high load, zero matched lines",
              read_jsonls(high_patterns))


if __name__ == "__main__":
    main()
