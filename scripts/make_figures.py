#!/usr/bin/env python3
"""Generate the four externally rendered figures in the submitted paper.

Usage:
    python3 scripts/make_figures.py

Output:
    figures/fig2_success_trajectories.pdf
    figures/fig3_pca_projection.pdf
    figures/fig4_cost_trajectories.pdf
    figures/fig5_gate_stripping.pdf

Figure 1 is the protocol schematic drawn directly in LaTeX. This script reads
the regenerated JSONL trajectories under results/. The gate-stripping panel
uses the three-replicate aggregates reported in the paper.
"""
import json
import re
import statistics
from pathlib import Path
from collections import defaultdict

import matplotlib.pyplot as plt
import matplotlib as mpl
import numpy as np
from sklearn.decomposition import PCA

# ---- Paths ----
SCRIPT_DIR = Path(__file__).parent
EXP_DIR = SCRIPT_DIR.parent
ROOT = EXP_DIR / "results"
FIG_DIR = EXP_DIR / "figures"
FIG_DIR.mkdir(exist_ok=True)

# ---- Constants ----
SOUL_TO_ID = {"soul-a": "Neutral", "soul-b": "Cautious", "soul-c": "Bold"}
IDENTITIES = ["Bold", "Neutral", "Cautious"]
MODELS_SHORT = {
    "GPT-OSS-120B": "GPT-OSS-120B",
    "Qwen3.5-27B": "Qwen3.5-27B",
    "Gemma4-26B-A4B-it": "Gemma4-26B-A4B-it",
}

READ_SUBCOMMANDS = {"list", "read", "get", "query", "metrics", "contacts"}

# Color palette (user-specified hex codes)
COLORS = {
    "Bold": "#C4A03E",     # darker gold
    "Neutral": "#A0A0A0",  # lighter gray (less visually heavy for "no bias" identity)
    "Cautious": "#A85F8A", # mauve
}
ALPHAS = {
    "Bold": 0.55,
    "Neutral": 0.45,
    "Cautious": 0.55,
}
CENTROID_ALPHA = 1.0
BAND_ALPHA = 0.25  # SE band fill (raised for print visibility)
LINE_STYLES = {"Bold": "-", "Neutral": "--", "Cautious": ":"}
ABLATION_COLOR_ORIG = "#999999"     # gray for original Run 5
ABLATION_COLOR_STRIP = "#4E79A7"    # steel blue for stripped Run 5'

REGIME_COLORS = {
    "GPT-OSS-120B": "#e41a1c",       # cliff
    "Gemma4-26B-A4B-it": "#377eb8",  # drift
    "Qwen3.5-27B": "#4daf4a",        # stable
}

# ---- matplotlib style ----
mpl.rcParams.update({
    "font.size": 9,
    "axes.titlesize": 10,
    "axes.labelsize": 9,
    "xtick.labelsize": 8,
    "ytick.labelsize": 8,
    "legend.fontsize": 8,
    "figure.dpi": 150,
    "pdf.fonttype": 42,  # editable text in PDF
    "ps.fonttype": 42,
    "axes.spines.top": False,
    "axes.spines.right": False,
})


# ============================================================
# Data loading
# ============================================================

def has_write_op(commands_executed):
    for raw in commands_executed:
        if not isinstance(raw, str): continue
        cmd = raw
        if "&&" in cmd:
            cmd = cmd[cmd.index("&&")+2:]
        cmd = re.sub(r"WB_WORKSPACE=\S+\s*", "", cmd)
        cmd = re.sub(r"python3?\s+", "", cmd).strip()
        parts = cmd.split()
        if len(parts) < 2: continue
        if "bash" in parts[0]:
            if re.search(r'wb-\S+\.py\s+(update|delete|create|send|forward|add|reply|plot|delete-many)', raw):
                return True
            continue
        if parts[1] in READ_SUBCOMMANDS: continue
        return True
    return False


def parse_dir(name):
    m = re.search(r"_rep(\d+)_run(\d+)_", name)
    if m: return f"rep{m.group(1)}", int(m.group(2))
    m = re.search(r"_run(\d+)_", name)
    if m: return "rep1", int(m.group(1))
    return None, None


def collect(model_dir, exclude_rep4=False):
    for rep_dir in sorted(model_dir.iterdir()):
        if not rep_dir.is_dir(): continue
        if any(s in rep_dir.name for s in ("memory_log","analysis","_smoke")): continue
        for rd in sorted(rep_dir.iterdir()):
            if not rd.is_dir() or "_run" not in rd.name: continue
            rep, run = parse_dir(rd.name)
            if rep is None: continue
            if exclude_rep4 and rep == "rep4": continue
            for jp in rd.glob("*.jsonl"):
                with open(jp) as f:
                    for line in f:
                        try: d = json.loads(line.strip())
                        except: continue
                        soul = d.get("soul_id","")
                        if soul not in SOUL_TO_ID: continue
                        yield d, rep, run, SOUL_TO_ID[soul]


def compute_trajectory(model_label, model_dir, exclude_rep4=False):
    """Per-(rep, run, ident) means for success rate and tokens-per-success."""
    by_rep_run_id = defaultdict(lambda: defaultdict(lambda: defaultdict(lambda: {"n":0, "succ":0, "tot":0})))
    for d, rep, run, ident in collect(model_dir, exclude_rep4):
        b = by_rep_run_id[rep][run][ident]
        b["n"] += 1
        if d.get("completed"): b["succ"] += 1
        b["tot"] += d.get("total_tokens",0) or 0

    # Aggregate per-run mean ± SE across reps
    success = {ident: {"runs": [], "mean": [], "se": []} for ident in IDENTITIES}
    cost_per_succ = {ident: {"runs": [], "mean": [], "se": []} for ident in IDENTITIES}
    for ident in IDENTITIES:
        for run in (1,2,3,4,5):
            sr_vals, cps_vals = [], []
            for rep in by_rep_run_id:
                b = by_rep_run_id[rep][run][ident]
                if b["n"]:
                    sr_vals.append(b["succ"]/b["n"]*100)
                    if b["succ"] > 0:
                        cps_vals.append(b["tot"]/b["succ"])
            if sr_vals:
                success[ident]["runs"].append(run)
                success[ident]["mean"].append(np.mean(sr_vals))
                success[ident]["se"].append(np.std(sr_vals, ddof=1)/np.sqrt(len(sr_vals)) if len(sr_vals)>1 else 0)
            if cps_vals:
                cost_per_succ[ident]["runs"].append(run)
                cost_per_succ[ident]["mean"].append(np.mean(cps_vals))
                cost_per_succ[ident]["se"].append(np.std(cps_vals, ddof=1)/np.sqrt(len(cps_vals)) if len(cps_vals)>1 else 0)
    return success, cost_per_succ


def compute_pca(model_dir, exclude_rep4=False):
    """5-dim behavior vector per (rep, run, ident), z-normalize, PCA."""
    cells = defaultdict(lambda: {"clarif":[], "fal":[], "ratio":[], "oa":[], "ua":[]})
    for d, rep, run, ident in collect(model_dir, exclude_rep4):
        ct = d.get("clarification_turns",0) or 0
        tt = d.get("total_turns",0) or 0
        if tt: cells[(rep,run,ident)]["clarif"].append(ct/tt)
        for i,t in enumerate(d.get("turns",[])):
            if has_write_op(t.get("commands_executed",[])):
                cells[(rep,run,ident)]["fal"].append(i+1); break
        ap = d.get("action_precision",{})
        if isinstance(ap,dict) and ap.get("applicable"):
            gt, ex = ap.get("gt_count",0), ap.get("exec_count",0)
            cells[(rep,run,ident)]["ratio"].append(ex/gt if gt else 0)
            cells[(rep,run,ident)]["oa"].append(1 if ex > gt else 0)
            cells[(rep,run,ident)]["ua"].append(1 if ex < gt else 0)

    keys, X = [], []
    for k, v in cells.items():
        if all(v[m] for m in ("clarif","fal","ratio","oa","ua")):
            keys.append(k)
            X.append([np.mean(v[m]) for m in ("clarif","fal","ratio","oa","ua")])
    X = np.array(X)
    if len(X) < 5:
        return None
    Z = (X - X.mean(axis=0)) / (X.std(axis=0) + 1e-12)
    pca = PCA(n_components=2)
    Y = pca.fit_transform(Z)
    return keys, Y, pca.explained_variance_ratio_


# ============================================================
# Figure 2: Success trajectories
# ============================================================

def fig2_success_trajectories():
    print("Generating Figure 2: Success trajectories...")
    fig, axes = plt.subplots(1, 3, figsize=(7.0, 2.4), sharey=True)

    model_data = {}
    for label, mdir, ex_rep4 in [
        ("GPT-OSS-120B", ROOT/"GPT-OSS-120B", True),
        ("Gemma4-26B-A4B-it", ROOT/"Gemma4-26B-A4B-it", False),
        ("Qwen3.5-27B", ROOT/"Qwen3.5-27B", False),
    ]:
        success, _ = compute_trajectory(label, mdir, ex_rep4)
        model_data[label] = success

    regime_titles = {
        "GPT-OSS-120B": "GPT-OSS-120B (cliff)",
        "Gemma4-26B-A4B-it": "Gemma4-26B-A4B-it (drift)",
        "Qwen3.5-27B": "Qwen3.5-27B (stable)",
    }
    model_order = ["GPT-OSS-120B", "Gemma4-26B-A4B-it", "Qwen3.5-27B"]

    for ax, label in zip(axes, model_order):
        success = model_data[label]
        for ident in IDENTITIES:
            d = success[ident]
            ax.plot(d["runs"], d["mean"],
                    color=COLORS[ident],
                    linestyle=LINE_STYLES[ident],
                    marker="o", markersize=4,
                    linewidth=1.5,
                    label=ident)
            # SE shaded region
            mean = np.array(d["mean"])
            se = np.array(d["se"])
            ax.fill_between(d["runs"], mean-se, mean+se, color=COLORS[ident], alpha=BAND_ALPHA)
        ax.set_title(regime_titles[label])
        ax.set_xlabel("Run")
        ax.set_xticks([1,2,3,4,5])
        ax.grid(alpha=0.3, linestyle=":")

    axes[0].set_ylabel("Success rate (%)")
    axes[0].legend(loc="lower left", framealpha=0.9)

    plt.tight_layout()
    out = FIG_DIR / "fig2_success_trajectories.pdf"
    plt.savefig(out, bbox_inches="tight")
    plt.savefig(out.with_suffix(".png"), bbox_inches="tight", dpi=200)
    print(f"  -> {out}")
    plt.close()


# ============================================================
# Figure 4: Cost trajectories (tokens per success)
# ============================================================

def fig4_cost_trajectories():
    print("Generating Figure 4: Cost trajectories...")
    fig, axes = plt.subplots(1, 3, figsize=(7.0, 2.4), sharey=False)

    model_data = {}
    for label, mdir, ex_rep4 in [
        ("GPT-OSS-120B", ROOT/"GPT-OSS-120B", True),
        ("Gemma4-26B-A4B-it", ROOT/"Gemma4-26B-A4B-it", False),
        ("Qwen3.5-27B", ROOT/"Qwen3.5-27B", False),
    ]:
        _, cps = compute_trajectory(label, mdir, ex_rep4)
        model_data[label] = cps

    regime_titles = {
        "GPT-OSS-120B": "GPT-OSS-120B (cliff)",
        "Gemma4-26B-A4B-it": "Gemma4-26B-A4B-it (drift)",
        "Qwen3.5-27B": "Qwen3.5-27B (stable)",
    }
    model_order = ["GPT-OSS-120B", "Gemma4-26B-A4B-it", "Qwen3.5-27B"]

    for ax, label in zip(axes, model_order):
        cps = model_data[label]
        for ident in IDENTITIES:
            d = cps[ident]
            mean = np.array(d["mean"]) / 1e6  # millions
            se = np.array(d["se"]) / 1e6
            ax.plot(d["runs"], mean,
                    color=COLORS[ident],
                    linestyle=LINE_STYLES[ident],
                    marker="o", markersize=4,
                    linewidth=1.5,
                    label=ident)
            ax.fill_between(d["runs"], mean-se, mean+se, color=COLORS[ident], alpha=BAND_ALPHA)
        # Mark r5/r1 ratio for max identity
        max_ratio = max((d["mean"][-1]/d["mean"][0] if d["mean"][0] else 0) for d in cps.values())
        ax.set_title(f"{regime_titles[label]}\nmax r5/r1 = {max_ratio:.2f}×", fontsize=9)
        ax.set_xlabel("Run")
        ax.set_xticks([1,2,3,4,5])
        ax.grid(alpha=0.3, linestyle=":")

    axes[0].set_ylabel("Tokens per success (millions)")
    axes[0].legend(loc="upper left", framealpha=0.9)

    plt.tight_layout()
    out = FIG_DIR / "fig4_cost_trajectories.pdf"
    plt.savefig(out, bbox_inches="tight")
    plt.savefig(out.with_suffix(".png"), bbox_inches="tight", dpi=200)
    print(f"  -> {out}")
    plt.close()


# ============================================================
# Figure 5: Gate-stripping (original Run 5 vs. stripped Run 5)
# ============================================================

def fig5_gate_stripping():
    print("Generating Figure 5: Gate-stripping...")

    # 3-replicate aggregate (mean +/- SE across rep1/rep2/rep3), computed from the
    # runs by the same code that builds tab:ablation (scripts/tables/interventions.py).
    # The annotated delta is the mean of per-replicate differences, as in the table.
    import sys
    sys.path.insert(0, str(SCRIPT_DIR / "tables"))
    from common import Ctx
    from interventions import ablation_summary
    summary = ablation_summary(Ctx(roots=[ROOT]))
    data = {}
    for ident in IDENTITIES:
        s_, u_ = summary[ident]["succ"], summary[ident]["under"]
        data[ident] = {
            "orig_succ": 100 * s_[0], "orig_succ_se": 100 * s_[1],
            "strip_succ": 100 * s_[2], "strip_succ_se": 100 * s_[3], "succ_delta": 100 * s_[4],
            "orig_ua": 100 * u_[0], "orig_ua_se": 100 * u_[1],
            "strip_ua": 100 * u_[2], "strip_ua_se": 100 * u_[3], "ua_delta": 100 * u_[4],
        }

    fig, axes = plt.subplots(1, 2, figsize=(7.0, 2.8))

    x = np.arange(len(IDENTITIES))
    width = 0.35

    # Panel A: Success rate (recovery — deltas positive, place above higher bar = strip)
    ax = axes[0]
    orig_succ = [data[i]["orig_succ"] for i in IDENTITIES]
    strip_succ = [data[i]["strip_succ"] for i in IDENTITIES]
    orig_succ_se = [data[i]["orig_succ_se"] for i in IDENTITIES]
    strip_succ_se = [data[i]["strip_succ_se"] for i in IDENTITIES]
    ax.bar(x - width/2, orig_succ, width, yerr=orig_succ_se, label="Original Run 5",
           color=ABLATION_COLOR_ORIG, edgecolor="black", linewidth=0.5,
           error_kw={"ecolor": "black", "capsize": 3, "elinewidth": 0.7})
    ax.bar(x + width/2, strip_succ, width, yerr=strip_succ_se, label="Stripped Run 5'",
           color=ABLATION_COLOR_STRIP, edgecolor="black", linewidth=0.5,
           error_kw={"ecolor": "black", "capsize": 3, "elinewidth": 0.7})

    # Annotate Δ above the higher bar in each pair
    for i, ident in enumerate(IDENTITIES):
        delta = data[ident]["succ_delta"]
        higher = max(data[ident]["strip_succ"] + data[ident]["strip_succ_se"],
                     data[ident]["orig_succ"] + data[ident]["orig_succ_se"])
        ax.annotate(f"+{delta:.1f}pp",
                    xy=(i, higher),
                    xytext=(0, 6), textcoords="offset points",
                    ha="center", fontsize=8, fontweight="bold",
                    color=ABLATION_COLOR_STRIP)

    ax.set_ylabel("Success rate (%)")
    ax.set_title("(a) Success rate recovery")
    ax.set_xticks(x)
    ax.set_xticklabels(IDENTITIES)
    ax.set_ylim(0, 100)
    ax.grid(alpha=0.3, axis="y", linestyle=":")

    # Panel B: Under-action rate (attenuation — deltas negative, place above higher bar = orig)
    ax = axes[1]
    orig_ua = [data[i]["orig_ua"] for i in IDENTITIES]
    strip_ua = [data[i]["strip_ua"] for i in IDENTITIES]
    orig_ua_se = [data[i]["orig_ua_se"] for i in IDENTITIES]
    strip_ua_se = [data[i]["strip_ua_se"] for i in IDENTITIES]
    ax.bar(x - width/2, orig_ua, width, yerr=orig_ua_se, label="Original Run 5",
           color=ABLATION_COLOR_ORIG, edgecolor="black", linewidth=0.5,
           error_kw={"ecolor": "black", "capsize": 3, "elinewidth": 0.7})
    ax.bar(x + width/2, strip_ua, width, yerr=strip_ua_se, label="Stripped Run 5'",
           color=ABLATION_COLOR_STRIP, edgecolor="black", linewidth=0.5,
           error_kw={"ecolor": "black", "capsize": 3, "elinewidth": 0.7})
    for i, ident in enumerate(IDENTITIES):
        delta = data[ident]["ua_delta"]
        higher = max(data[ident]["strip_ua"] + data[ident]["strip_ua_se"],
                     data[ident]["orig_ua"] + data[ident]["orig_ua_se"])
        ax.annotate(f"{delta:+.1f}pp",
                    xy=(i, higher),
                    xytext=(0, 6), textcoords="offset points",
                    ha="center", fontsize=8, fontweight="bold",
                    color=ABLATION_COLOR_STRIP)

    ax.set_ylabel("Under-action rate (%)")
    ax.set_title("(b) Under-action attenuation")
    ax.set_xticks(x)
    ax.set_xticklabels(IDENTITIES)
    ax.set_ylim(0, 55)
    ax.grid(alpha=0.3, axis="y", linestyle=":")

    # Shared legend below both panels (avoids overlapping bars + error bars)
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center", ncol=2,
               bbox_to_anchor=(0.5, -0.02), framealpha=0.9, fontsize=9)

    plt.tight_layout(rect=[0, 0.04, 1, 1])
    out = FIG_DIR / "fig5_gate_stripping.pdf"
    plt.savefig(out, bbox_inches="tight")
    plt.savefig(out.with_suffix(".png"), bbox_inches="tight", dpi=200)
    print(f"  -> {out}")
    plt.close()


# ============================================================
# Figure 3: PCA projection (3 panels)
# ============================================================

def fig3_pca_projection():
    print("Generating Figure 3: PCA projection...")
    fig, axes = plt.subplots(1, 3, figsize=(7.0, 2.8))

    model_order = [
        ("GPT-OSS-120B", ROOT/"GPT-OSS-120B", True),
        ("Gemma4-26B-A4B-it", ROOT/"Gemma4-26B-A4B-it", False),
        ("Qwen3.5-27B", ROOT/"Qwen3.5-27B", False),
    ]
    regime_titles = {
        "GPT-OSS-120B": "GPT-OSS-120B (cliff)",
        "Gemma4-26B-A4B-it": "Gemma4-26B-A4B-it (drift)",
        "Qwen3.5-27B": "Qwen3.5-27B (stable)",
    }

    for ax, (label, mdir, ex_rep4) in zip(axes, model_order):
        result = compute_pca(mdir, ex_rep4)
        if result is None: continue
        keys, Y, var = result

        # Plot each identity
        for ident in IDENTITIES:
            idx = [i for i, k in enumerate(keys) if k[2] == ident]
            if not idx: continue
            ax.scatter(Y[idx,0], Y[idx,1],
                        color=COLORS[ident], alpha=ALPHAS[ident], s=20,
                        label=ident, edgecolor="white", linewidth=0.3)
            # Centroid (alpha=1.0, thinner edge)
            cx = Y[idx,0].mean()
            cy = Y[idx,1].mean()
            ax.scatter(cx, cy, color=COLORS[ident], s=120,
                        marker="X", alpha=CENTROID_ALPHA,
                        edgecolor="black", linewidth=0.5, zorder=5)

        ax.set_xlabel(f"PC1 ({var[0]*100:.0f}%)")
        ax.set_ylabel(f"PC2 ({var[1]*100:.0f}%)")
        ax.set_title(regime_titles[label])
        ax.grid(alpha=0.3, linestyle=":")
        ax.axhline(0, color="black", linewidth=0.3, alpha=0.5)
        ax.axvline(0, color="black", linewidth=0.3, alpha=0.5)

    # Legend OUTSIDE plot area (below all panels) — never covers data points
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center",
                bbox_to_anchor=(0.5, -0.02), ncol=3,
                framealpha=0.9, markerscale=0.8, fontsize=8.5)
    plt.tight_layout(rect=[0, 0.07, 1, 1])  # leave 7% bottom margin for legend
    out = FIG_DIR / "fig3_pca_projection.pdf"
    plt.savefig(out, bbox_inches="tight")
    plt.savefig(out.with_suffix(".png"), bbox_inches="tight", dpi=200)
    print(f"  -> {out}")
    plt.close()


# ============================================================
# Main
# ============================================================

if __name__ == "__main__":
    fig2_success_trajectories()
    fig3_pca_projection()
    fig4_cost_trajectories()
    fig5_gate_stripping()
    print(f"\nAll figures saved to {FIG_DIR}")
