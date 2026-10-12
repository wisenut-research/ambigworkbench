#!/usr/bin/env bash
# run_seeding_control_ablation.sh  (paper section 5.3.6, volume-matched control)
#
# Control arm for the seeding ablation: overlays the SAME token budget of the
# source model's NON-gating lines onto the target's own patterns_run4.md
# (token-matched per identity via extract_nongating_lines.py), then reruns
# Run 5 under the identical protocol. Comparing seeding vs. this control
# separates gating content from added memory volume within one model.
#
# Usage:
#   SEEDS=1 bash scripts/run_seeding_control_ablation.sh <SOURCE_REP> <BASELINE_REP>
#
set -euo pipefail

cd "$(dirname "$0")/.."
EXP_DIR="$(pwd)"

# ---- Configuration ----
SOURCE_REP="${1:-GPT-OSS-120B_rep1}"
BASELINE_REP="${2:-Qwen3.5-27B_rep2}"
SOURCE_MODEL_LABEL="${SOURCE_REP%_rep*}"
TARGET_MODEL_LABEL="${BASELINE_REP%_rep*}"
ORACLE_MODEL="${ORACLE_MODEL:-gpt-4o-mini}"
VLLM_METRICS="${VLLM_METRICS:?set VLLM_METRICS, e.g. http://<gpu-host>:9022/metrics}"
TASKS_FILE="${TASKS_FILE:-benchmark/tasks/ambig_queries.json}"
SEEDS="${SEEDS:-3}"
TOKENIZER="${TOKENIZER:-o200k_base}"
# TASK_LIMIT: cap tasks per soul (pilot only; unset = full 314). Limited runs use
# a different task set than the 314-task baseline -> directional, not comparable.
TASK_LIMIT="${TASK_LIMIT:-}"

SOUL_LIST=(soul-a soul-b soul-c)
SOURCE_MEMORY_LOG="results/${SOURCE_MODEL_LABEL}/${SOURCE_REP}/${SOURCE_REP}_memory_log"
QWEN_MEMORY_LOG="results/${TARGET_MODEL_LABEL}/${BASELINE_REP}/${BASELINE_REP}_memory_log"

# Results root matching run_seeding_ablation.sh.
RESULTS_ROOT="${RESULTS_ROOT:-results/interventions/seeding}"
# Label includes BASELINE_REP so each Qwen rep gets its own dir (no rep1/2/3 collision).
CONTROL_LABEL="${BASELINE_REP}_run5_injected_control_nongating_from_${SOURCE_REP}"
CONTROL_DIR="${RESULTS_ROOT}/${CONTROL_LABEL}"
PREP_DIR="${CONTROL_DIR}/_control_patterns"

# ---- Sanity checks ----
if [ -z "${OPENAI_API_KEY:-}" ] && [ -f .env ]; then
    set -a; . ./.env; set +a
fi
if [ -z "${OPENAI_API_KEY:-}" ]; then
    echo "[ERROR] OPENAI_API_KEY not set"; exit 1
fi
if [ ! -d "$SOURCE_MEMORY_LOG" ]; then
    echo "[ERROR] source memory_log not found: $SOURCE_MEMORY_LOG"; exit 1
fi
if [ ! -d "$QWEN_MEMORY_LOG" ]; then
    echo "[ERROR] Qwen baseline memory_log not found: $QWEN_MEMORY_LOG"; exit 1
fi
for soul in "${SOUL_LIST[@]}"; do
    [ -f "${SOURCE_MEMORY_LOG}/${soul}/patterns_run4.md" ] || { echo "[ERROR] missing source patterns_run4 for ${soul}"; exit 1; }
    [ -f "${QWEN_MEMORY_LOG}/${soul}/patterns_run4.md" ]   || { echo "[ERROR] missing Qwen base patterns_run4 for ${soul}"; exit 1; }
done

CONFIGURED_MODEL=$(python3 -c "
import json
cfg = json.load(open('openclaw-config/agents/soul-a/agent/models.json'))
print(cfg['providers']['openai']['models'][0]['id'])
" 2>/dev/null || echo "unknown")

echo "=== Gate-Injection NON-GATING control ==="
echo "  Source (overlay):  ${SOURCE_REP} non-gating lines, token-matched to gating arm"
echo "  Target model:      ${TARGET_MODEL_LABEL} (agent config: ${CONFIGURED_MODEL})"
echo "  Qwen base:         ${BASELINE_REP} patterns_run4.md"
echo "  Seeds:             ${SEEDS}"
echo "  Tokenizer:         ${TOKENIZER}"
echo "  Endpoint:          ${VLLM_METRICS}"
echo "  WARNING  confirm vLLM is serving ${TARGET_MODEL_LABEL}, not GPT-OSS/Gemma"
echo

# SEED_LIST lets two endpoints split the control seeds (e.g. endpoint A runs
# SEED_LIST="1", endpoint B runs SEED_LIST="2 3") into a shared CONTROL_DIR
# without colliding. Defaults to 1..SEEDS.
SEED_LIST="${SEED_LIST:-$(seq 1 "$SEEDS")}"
# Do NOT error if CONTROL_DIR exists (the other endpoint may have created it);
# collisions are checked per-seed inside the loop instead.
mkdir -p "$PREP_DIR"

# ---- Step 1: per-soul gating-overlay token target (matches the injection arm) ----
# Targets are written to per-soul files (not an associative array) so this runs
# on macOS's default bash 3.2 (no `declare -A`).
echo "=== Step 1: compute per-soul gating-overlay token targets ==="
for soul in "${SOUL_LIST[@]}"; do
    gptoss_src="${SOURCE_MEMORY_LOG}/${soul}/patterns_run4.md"
    gating_only="${PREP_DIR}/${soul}_gating_only.md"
    python3 scripts/extract_gating_lines.py --input "$gptoss_src" --output "$gating_only" >/dev/null
    tgt=$(SRC="$gating_only" TOK="$TOKENIZER" python3 - <<'PY'
import os, tiktoken
enc = tiktoken.get_encoding(os.environ["TOK"])
txt = open(os.environ["SRC"], encoding="utf-8").read()
print(sum(len(enc.encode(l)) for l in txt.splitlines(keepends=True) if l.strip().startswith("- [")))
PY
)
    echo "$tgt" > "${PREP_DIR}/${soul}.target"
    echo "  [${soul}] gating-overlay target = ${tgt} tokens"
done
echo

# ---- Helpers ----
cleanup_workspace() {
    python3 - <<'PY'
from pathlib import Path
import shutil
souls = ("soul-a", "soul-b", "soul-c")
allowed_files = {
    "AGENTS.md", "SOUL.md", "TOOLS.md", "IDENTITY.md", "USER.md",
    "HEARTBEAT.md", "BOOTSTRAP.md",
    "wb-analytics.py", "wb-calendar.py", "wb-crm.py", "wb-email.py", "wb-project.py",
    "emails.csv", "calendar_events.csv", "project_tasks.csv",
    "analytics_data.csv", "customer_relationship_manager_data.csv",
}
allowed_dirs = {"memory", "plots"}
for soul in souls:
    root = Path("workspace") / soul
    if not root.exists():
        continue
    for item in root.iterdir():
        if item.is_dir():
            if item.name == "plots":
                shutil.rmtree(item); item.mkdir(); continue
            if item.name == "memory":
                for m in list(item.iterdir()):
                    m.unlink() if m.is_file() else shutil.rmtree(m)
                continue
            if item.name not in allowed_dirs:
                shutil.rmtree(item)
            continue
        if item.name not in allowed_files:
            item.unlink()
    (root / "plots").mkdir(exist_ok=True)
    (root / "memory").mkdir(exist_ok=True)
PY
}

# ---- Step 2: per-seed build overlay, install, run ----
for seed in $SEED_LIST; do
    seed_tag=$(printf "seed_%02d" "$seed")
    seed_dir="${CONTROL_DIR}/${seed_tag}"
    if [ -d "$seed_dir" ] && find "$seed_dir" -name '*.summary.csv' | grep -q .; then
        echo "=== ${seed_tag}: already has results, skipping ==="
        continue
    fi
    mkdir -p "$seed_dir"
    echo "=== ${seed_tag}: build token-matched non-gating overlay + install ==="

    for soul in "${SOUL_LIST[@]}"; do
        qwen_base="${QWEN_MEMORY_LOG}/${soul}/patterns_run4.md"
        gptoss_src="${SOURCE_MEMORY_LOG}/${soul}/patterns_run4.md"
        ng_overlay="${seed_dir}/${soul}_nongating_matched.md"
        merged="${seed_dir}/${soul}_patterns_to_inject.md"
        tgt=$(cat "${PREP_DIR}/${soul}.target")

        python3 scripts/extract_nongating_lines.py \
            --input "$gptoss_src" \
            --output "$ng_overlay" \
            --target-tokens "$tgt" \
            --tokenizer "$TOKENIZER" \
            --seed "$seed" \
            --stats-json "${seed_dir}/${soul}_match_stats.json"

        {
            cat "$qwen_base"
            echo ""
            echo "# --- INJECTED CONTROL OVERLAY: token-matched NON-gating lines from ${SOURCE_REP} same-soul patterns_run4.md (seed ${seed}) ---"
            cat "$ng_overlay"
        } > "$merged"
    done

    # Record gating density of each control corpus (should be DILUTED vs the
    # injection arm, and close to the Qwen baseline, since we add non-gating lines).
    python3 scripts/measure_gating_density.py --label "control_${seed_tag}" \
        --inputs "$seed_dir"/*_patterns_to_inject.md \
        --output "${seed_dir}/gating_density.json" || true

    # Reset workspace + install merged corpus as starting memory
    cleanup_workspace
    SEED_DIR="$seed_dir" python3 - <<'PY'
from pathlib import Path
import os
seed_dir = Path(os.environ["SEED_DIR"])
for soul in ("soul-a", "soul-b", "soul-c"):
    src = seed_dir / f"{soul}_patterns_to_inject.md"
    dst = Path("workspace") / soul / "memory" / "patterns.md"
    dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    n = sum(1 for ln in dst.read_text().splitlines() if ln.strip().startswith("- ["))
    print(f"  [{soul}] installed control patterns.md ({n} pattern lines)")
PY

    # Run Run 5' — SINGLE process, souls interleaved per task (matches how the
    # Qwen baseline was generated; do NOT parallelize the souls or the vLLM load
    # profile diverges from the baseline). run_experiment.py writes its own run
    # dir + summary under --results-dir, exactly like the baseline pipeline.
    echo "=== ${seed_tag}: execute Run 5' (single process, souls interleaved) ==="
    seed_log="${seed_dir}/${seed_tag}_run.log"
    bash scripts/run_python.sh runner/run_experiment.py \
        --souls "soul-a,soul-b,soul-c" \
        --ambig-tasks "$TASKS_FILE" \
        --experiment-name "${CONTROL_LABEL}_${seed_tag}" \
        --results-dir "$seed_dir" \
        --oracle-model "$ORACLE_MODEL" \
        --vllm-metrics-url "$VLLM_METRICS" \
        ${TASK_LIMIT:+--limit "$TASK_LIMIT"} \
        --learning --keep-memory \
        2>&1 | tee "$seed_log"
    echo "  ${seed_tag} done -> $seed_dir"
    echo
done

echo "=== Done ==="
echo "Control results:  $CONTROL_DIR"
echo "Prep patterns:    $PREP_DIR"
echo
echo "Next: compare three arms against the Qwen baseline Run 5"
echo "  baseline:   ${BASELINE_REP} Run 5            (Qwen base, no overlay)"
echo "  injection:  ${BASELINE_REP}_run5_injected_from_${SOURCE_REP}     (Qwen base + gating overlay)"
echo "  control:    ${CONTROL_LABEL}  (Qwen base + token-matched non-gating overlay)"
