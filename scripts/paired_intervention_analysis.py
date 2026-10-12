#!/usr/bin/env python3
"""Paired statistical analysis for the intervention experiments.

Reproduces the numbers reported in Sections 5.3.3-5.3.6 and the Interventions
appendix of the paper:
  A. Gate-stripping: task-paired per replicate with percentile bootstrap CIs
     clustered by the 80 source WorkBench tasks.
  B. Seeding (Qwen / Gemma x injection / control): task-paired mean differences
     with pointwise percentile bootstrap 95% CIs; largest upper bounds across
     cells are the equivalence-style bounds quoted in the text.
  C. Shared-starting-memory: execution-order quartiles per condition; condition
     spread per quartile with bootstrap CIs; own-memory replicate-1 Run 5
     restricted to the same tasks per quartile.
  D. Manipulation check: ANY-gating line prevalence of injected / control
     corpora vs the receiving model's own Run-4 corpora.

Procedure constants (documented in the appendix): resampling unit = source
WorkBench task (the 314 variants form 80 clusters), B = 10,000 percentile
bootstrap resamples, fixed seed = 4214.

Directory defaults follow the runner scripts in this artifact; pass
--results-root / --sharedmem-glob to match customized output locations.

Usage: python3 scripts/paired_intervention_analysis.py --results-root results
"""
import argparse, glob, json, os, random, sys
from pathlib import Path

SOULS = [("soul-b", "Cautious"), ("soul-a", "Neutral"), ("soul-c", "Bold")]
B = 10000
SEED = 4214


def load_one(pattern):
    fs = glob.glob(pattern, recursive=True)
    if len(fs) != 1:
        raise FileNotFoundError(f"{pattern} -> {len(fs)} matches")
    return [json.loads(l) for l in open(fs[0])]


def by_task(recs, soul):
    out = {}
    for r in recs:
        if r["soul_id"] != soul:
            continue
        succ = 1 if (r.get("eval") or {}).get("e2e_success") else 0
        ap = r.get("action_precision") or {}
        under = None
        if ap.get("applicable"):
            under = 1 if ap.get("exec_count", 0) < ap.get("gt_count", 0) else 0
        out[r["task_id"]] = (succ, under)
    return out


def load_task_clusters(path):
    """Map each ambiguous variant to its source WorkBench task cluster."""
    tasks = json.loads(Path(path).read_text(encoding="utf-8"))
    return {task["task_id"]: task["original_query"] for task in tasks}


def boot_ci(diffs, task_ids, task_clusters):
    """Cluster bootstrap over source tasks while retaining their variants."""
    grouped = {}
    for diff, task_id in zip(diffs, task_ids):
        cluster = task_clusters[task_id]
        grouped.setdefault(cluster, []).append(diff)
    clusters = sorted(grouped)
    n_clusters = len(clusters)
    means = []
    for _ in range(B):
        sampled = [clusters[random.randrange(n_clusters)]
                   for _ in range(n_clusters)]
        values = [value for cluster in sampled for value in grouped[cluster]]
        means.append(sum(values) / len(values))
    means.sort()
    return means[int(0.025 * B)], means[int(0.975 * B)]


def paired_cell(base, arm, soul, task_clusters):
    tb, ta = by_task(base, soul), by_task(arm, soul)
    keys = sorted(set(tb) & set(ta))
    ds = [ta[k][0] - tb[k][0] for k in keys]
    du = [ta[k][1] - tb[k][1] for k in keys
          if tb[k][1] is not None and ta[k][1] is not None]
    under_keys = [k for k in keys
                  if tb[k][1] is not None and ta[k][1] is not None]
    return dict(n=len(keys), n_clusters=len({task_clusters[k] for k in keys}),
                mean_ds=sum(ds) / len(ds),
                ci_ds=boot_ci(ds, keys, task_clusters),
                mean_du=sum(du) / len(du),
                ci_du=boot_ci(du, under_keys, task_clusters))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--results-root", default="results")
    ap.add_argument("--extra-results-root", default=None,
                    help="second results tree searched for intervention arms")
    ap.add_argument("--sharedmem-glob", default=None,
                    help="override glob for the shared-starting-memory run jsonl")
    ap.add_argument("--tasks-file", default="benchmark/tasks/ambig_queries.json",
                    help="task JSON used to map 314 variants to 80 source tasks")
    args = ap.parse_args()
    random.seed(SEED)
    R = args.results_root
    roots = [R] + ([args.extra_results_root] if args.extra_results_root else [])
    task_clusters = load_task_clusters(args.tasks_file)

    def arm_pattern(model, rep, arm):
        suffix = ("injected_from" if arm == "inj"
                  else "injected_control_nongating_from")
        name = f"{model}_rep{rep}_run5_{suffix}_GPT-OSS-120B_rep1"
        for root in roots:
            for parent in ("interventions/seeding", "gate_inject_rebuttal"):
                d = os.path.join(root, parent, name)
                if os.path.isdir(d):
                    return os.path.join(d, "**", "*.jsonl")
        raise FileNotFoundError(name)

    print("A. GATE-STRIPPING (paired; source-seed-cluster bootstrap)")
    cells = []
    for rep in (1, 2, 3):
        base = load_one(f"{R}/GPT-OSS-120B/GPT-OSS-120B_rep{rep}/*run5*/**/*.jsonl")
        strip = None
        for root in roots:
            for parent in ("interventions", "_ablation"):
                fs = glob.glob(
                    f"{root}/{parent}/GPT-OSS-120B_rep{rep}_run5_stripped/**/*.jsonl",
                    recursive=True,
                )
                if fs:
                    strip = [json.loads(line) for line in open(fs[0])]
                    break
            if strip is not None:
                break
        for soul, name in SOULS:
            r = paired_cell(base, strip, soul, task_clusters)
            cells.append((rep, name, r))
    for rep, name, r in cells:
        print(f"  rep{rep} {name:9s} d_succ={r['mean_ds']:+.3f} CI{r['ci_ds']} "
              f"d_under={r['mean_du']:+.3f} CI{r['ci_du']} "
              f"clusters={r['n_clusters']}")

    print("B. SEEDING (pointwise bootstrap bounds)")
    worst = {}
    for model in ("Qwen3.5-27B", "Gemma4-26B-A4B-it"):
        drop_hi = under_hi = -9
        for rep in (1, 2, 3):
            base = load_one(f"{R}/{model}/{model}_rep{rep}/*run5*/**/*.jsonl")
            for arm in ("inj", "ctl"):
                arm_recs = load_one(arm_pattern(model, rep, arm))
                for soul, name in SOULS:
                    r = paired_cell(base, arm_recs, soul, task_clusters)
                    if arm == "inj":
                        drop_hi = max(drop_hi, -r["ci_ds"][0])
                        under_hi = max(under_hi, r["ci_du"][1])
        worst[model] = (drop_hi, under_hi)
        print(f"  {model}: largest pointwise 95% upper bounds: "
              f"success drop {drop_hi:.3f}, under-action rise {under_hi:.3f}")

    print("C. SHARED-STARTING-MEMORY quartiles")
    if args.sharedmem_glob:
        shared = load_one(args.sharedmem_glob)
    else:
        shared = None
        for root in roots:
            for pattern in (
                f"{root}/interventions/sharedmem/**/*.jsonl",
                f"{root}/_ablation/*sharedmem*/**/*.jsonl",
            ):
                fs = glob.glob(pattern, recursive=True)
                if len(fs) == 1:
                    shared = [json.loads(line) for line in open(fs[0])]
                    break
            if shared is not None:
                break
        if shared is None:
            raise FileNotFoundError("shared-starting-memory JSONL")
    own = load_one(f"{R}/GPT-OSS-120B/GPT-OSS-120B_rep1/*run5*/**/*.jsonl")
    own_lu = {s: by_task(own, s) for s, _ in SOULS}
    for q in range(4):
        sh, ow = {}, {}
        for soul, name in SOULS:
            rs = sorted((r for r in shared if r["soul_id"] == soul),
                        key=lambda r: r["timestamp"])
            n = len(rs); chunk = rs[int(q * n / 4):int((q + 1) * n / 4)]
            sh[name] = sum(1 for r in chunk
                           if (r.get("eval") or {}).get("e2e_success")) / len(chunk)
            ov = [own_lu[soul].get(r["task_id"]) for r in chunk]
            ov = [v for v in ov if v is not None]
            ow[name] = sum(v[0] for v in ov) / len(ov)
        # Joint cluster bootstrap on the shared-run spread: identities share
        # each quartile's task set, so resample source tasks jointly.
        rs0 = sorted((r for r in shared if r["soul_id"] == SOULS[0][0]),
                     key=lambda r: r["timestamp"])
        n0 = len(rs0)
        pool = [r["task_id"] for r in rs0[int(q * n0 / 4):int((q + 1) * n0 / 4)]]
        succ_by = {s: {r["task_id"]: (1 if (r.get("eval") or {}).get("e2e_success") else 0)
                       for r in shared if r["soul_id"] == s} for s, _ in SOULS}
        grouped_pool = {}
        for task_id in pool:
            grouped_pool.setdefault(task_clusters[task_id], []).append(task_id)
        source_clusters = sorted(grouped_pool)
        spreads = []
        for _ in range(B):
            sampled = [source_clusters[random.randrange(len(source_clusters))]
                       for _ in range(len(source_clusters))]
            idx = [task_id for cluster in sampled
                   for task_id in grouped_pool[cluster]]
            ms = []
            for s, _ in SOULS:
                vals = [succ_by[s][tid] for tid in idx if tid in succ_by[s]]
                ms.append(sum(vals) / len(vals))
            spreads.append(max(ms) - min(ms))
        spreads.sort()
        ci = (spreads[int(0.025 * B)], spreads[int(0.975 * B)])
        print(f"  Q{q+1} shared: " + " ".join(f"{k}={v:.3f}" for k, v in sh.items())
              + f" spread={max(sh.values())-min(sh.values()):.3f}"
              + f" jointCI=[{ci[0]:.3f},{ci[1]:.3f}]")
        print(f"      own   : " + " ".join(f"{k}={v:.3f}" for k, v in ow.items())
              + f" spread={max(ow.values())-min(ow.values()):.3f}")

    print("D. MANIPULATION CHECK (ANY-gating line prevalence per 100 lines)")
    sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
    from measure_gating_density import density
    for model in ("Qwen3.5-27B", "Gemma4-26B-A4B-it"):
        vals = {"base": [], "seeded": [], "control": []}
        for rep in (1, 2, 3):
            for soul, _ in SOULS:
                for f in glob.glob(f"{R}/{model}/{model}_rep{rep}/*memory_log/{soul}/patterns_run4.md"):
                    vals["base"].append(density(Path(f))["ANY_GATING_per100"])
            for arm, key in (("inj", "seeded"), ("ctl", "control")):
                d = os.path.dirname(arm_pattern(model, rep, arm).split("**")[0])
                for f in glob.glob(f"{d}/**/*patterns_to_inject*.md", recursive=True):
                    vals[key].append(density(Path(f))["ANY_GATING_per100"])
        for k in ("base", "seeded", "control"):
            v = vals[k]
            if v:
                print(f"  {model} {k:8s}: n={len(v)} min={min(v):.1f} max={max(v):.1f}")


if __name__ == "__main__":
    main()
