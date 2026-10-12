#!/usr/bin/env python3
"""
extract_nongating_lines.py — Token-matched NON-gating overlay builder.

Companion control to extract_gating_lines.py for the gate-injection ablation.

Motivation
----------
The gate-injection arm overlays a strong-IF model's *gating* pattern lines onto
a weak-IF model's corpus. But that overlay also ADDS volume (extra tokens). If
the receiving model then collapses, the effect is confounded: it could be the
gating *content* OR simply the added token burden.

This script builds the matched control overlay: a token-matched set of the same
source model's NON-gating lines. Injecting it adds the SAME token budget of
foreign (same-author) content, differing only in the gating vs non-gating
dimension. Comparing the two injection arms isolates gating content from volume
WITHIN a single receiving model / tokenizer — the only confound-robust test.

Gating membership uses the exact regexes from extract_gating_lines.py so the
two scripts partition the corpus consistently.

Selection is deterministic given --seed: non-gating lines are shuffled with a
seeded RNG, then accumulated in order until cumulative tokens >= target. If the
non-gating pool is exhausted before reaching the target (can happen for souls
whose corpus is gating-dominated, e.g. Bold), the script stops and reports the
shortfall rather than duplicating lines (duplication would inject artificial
redundancy — itself a confound). Pass --allow-duplicate to cycle the pool to
hit the target exactly when an exact match matters more than redundancy.

Usage:
  python3 scripts/extract_nongating_lines.py \\
    --input  results/<SRC>/<SRC>_<rep>_memory_log/<soul>/patterns_run4.md \\
    --output results/_ablation/<...>/<soul>_nongating_matched.md \\
    --target-tokens 1234 [--tokenizer o200k_base] [--seed 1] [--allow-duplicate]
"""

import argparse
import json
import random
import sys
from pathlib import Path

# Reuse the exact gating regexes so gating/non-gating partition matches the
# rest of the pipeline (extract_gating_lines.py and the paper definitions).
sys.path.insert(0, str(Path(__file__).resolve().parent))
from extract_gating_lines import has_gating  # noqa: E402


def get_token_counter(tokenizer_name: str):
    """Return a fn(str)->int. Prefer tiktoken; fall back to char/4 proxy."""
    try:
        import tiktoken

        enc = tiktoken.get_encoding(tokenizer_name)
        return lambda s: len(enc.encode(s)), f"tiktoken:{tokenizer_name}"
    except Exception as e:  # pragma: no cover - environment dependent
        print(
            f"[WARN] tiktoken unavailable ({e}); falling back to char/4 token proxy",
            file=sys.stderr,
        )
        return lambda s: max(1, len(s) // 4), "char_div4_proxy"


def extract(
    input_path: Path,
    output_path: Path,
    target_tokens: int,
    tokenizer_name: str,
    seed: int,
    allow_duplicate: bool,
) -> dict:
    src_lines = input_path.read_text(encoding="utf-8").splitlines(keepends=True)
    pattern_lines = [l for l in src_lines if l.strip().startswith("- [")]
    nongating = [l for l in pattern_lines if not has_gating(l)]

    count_tokens, tok_label = get_token_counter(tokenizer_name)

    # Deterministic shuffle by seed.
    rng = random.Random(seed)
    order = list(range(len(nongating)))
    rng.shuffle(order)
    shuffled = [nongating[i] for i in order]

    pool_tokens = sum(count_tokens(l) for l in nongating)

    selected: list[str] = []
    cum = 0
    idx = 0
    n_pool = len(shuffled)
    exhausted = False
    while cum < target_tokens:
        if idx >= n_pool:
            if not allow_duplicate:
                exhausted = True
                break
            idx = 0  # cycle the pool to keep filling toward the target
        line = shuffled[idx]
        selected.append(line)
        cum += count_tokens(line)
        idx += 1

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("".join(selected), encoding="utf-8")

    return {
        "tokenizer": tok_label,
        "target_tokens": target_tokens,
        "achieved_tokens": cum,
        "shortfall_tokens": max(0, target_tokens - cum),
        "match_ratio": round(cum / target_tokens, 4) if target_tokens else None,
        "selected_lines": len(selected),
        "nongating_pool_lines": len(nongating),
        "nongating_pool_tokens": pool_tokens,
        "pool_exhausted": exhausted,
        "allow_duplicate": allow_duplicate,
        "seed": seed,
        "total_pattern_lines_in_source": len(pattern_lines),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--input", "-i", required=True, type=Path)
    ap.add_argument("--output", "-o", required=True, type=Path)
    ap.add_argument(
        "--target-tokens",
        type=int,
        required=True,
        help="Token budget to match (typically the gating overlay's token count).",
    )
    ap.add_argument("--tokenizer", default="o200k_base", help="tiktoken encoding name.")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument(
        "--allow-duplicate",
        action="store_true",
        help="Cycle the non-gating pool to hit the target exactly (adds redundancy).",
    )
    ap.add_argument("--stats-json", type=Path, default=None)
    args = ap.parse_args()

    if not args.input.exists():
        print(f"[ERROR] input not found: {args.input}", file=sys.stderr)
        return 1

    stats = extract(
        args.input,
        args.output,
        args.target_tokens,
        args.tokenizer,
        args.seed,
        args.allow_duplicate,
    )
    if args.stats_json:
        args.stats_json.parent.mkdir(parents=True, exist_ok=True)
        args.stats_json.write_text(json.dumps(stats, indent=2), encoding="utf-8")

    print(f"Source:   {args.input}")
    print(f"Output:   {args.output}")
    print(f"Tokenizer:        {stats['tokenizer']}")
    print(f"Target tokens:    {stats['target_tokens']}")
    print(
        f"Achieved tokens:  {stats['achieved_tokens']} "
        f"({stats['match_ratio']:.3f} of target, "
        f"{stats['selected_lines']} lines)"
    )
    if stats["pool_exhausted"]:
        print(
            f"[WARN] non-gating pool exhausted: shortfall "
            f"{stats['shortfall_tokens']} tokens "
            f"(pool had {stats['nongating_pool_tokens']} tokens / "
            f"{stats['nongating_pool_lines']} lines). "
            f"Reporting partial match (no duplication)."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
