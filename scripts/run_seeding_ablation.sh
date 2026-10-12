#!/usr/bin/env bash
# run_seeding_ablation.sh  (paper section 5.3.6, memory-injection variant)
#
# Seeds a target model with the source model's gating-matched memory lines:
#   merged corpus = target's own patterns_run4.md + gating lines extracted from
#   the source model's same-identity patterns_run4.md, installed as the Run-5
#   starting state; Run 5 is then rerun unchanged (--learning, souls
#   interleaved in a single process, as in the baselines).
#
# Usage:
#   export OPENAI_API_KEY=...   (clarification/correction oracle)
#   export VLLM_METRICS=http://<gpu-host>:9022/metrics
#   bash scripts/run_seeding_ablation.sh <SOURCE_REP> <BASELINE_REP>
#   e.g. bash scripts/run_seeding_ablation.sh GPT-OSS-120B_rep1 Qwen3.5-27B_rep1
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
# TASK_LIMIT: cap tasks per soul (pilot/direction-check only; leave unset for the
# full 314-task run used for submission). With a limit the task SET differs from
# the 314-task baseline, so treat limited runs as directional, not comparable.
TASK_LIMIT="${TASK_LIMIT:-}"
# Default 0 (single-process, souls interleaved per task) to MATCH how the
# GPT-OSS/Qwen baselines were generated. Gemma used parallel; do NOT use
# parallel here or the vLLM load profile diverges from the Qwen baseline and
# breaks comparability. Set PARALLEL=1 only if the baseline you compare against
# was itself produced in parallel.
PARALLEL="${PARALLEL:-0}"

SOUL_LIST=(soul-a soul-b soul-c)
SOURCE_MEMORY_LOG="results/${SOURCE_MODEL_LABEL}/${SOURCE_REP}/${SOURCE_REP}_memory_log"

# Dedicated results root for the seeding experiments (kept separate from the
# main per-model result trees). Override with RESULTS_ROOT=... if needed.
RESULTS_ROOT="${RESULTS_ROOT:-results/interventions/seeding}"
# Label includes BASELINE_REP so each Qwen rep gets its own dir (rep1/2/3 must
# not collide under one label).
ABLATION_LABEL="${BASELINE_REP}_run5_injected_from_${SOURCE_REP}"
ABLATION_DIR="${RESULTS_ROOT}/${ABLATION_LABEL}"
INJECTED_DIR="${ABLATION_DIR}/_injected_patterns"

# ---- Sanity checks ----
if [ -z "${OPENAI_API_KEY:-}" ] && [ -f .env ]; then
    set -a; . ./.env; set +a
fi
if [ -z "${OPENAI_API_KEY:-}" ]; then
    echo "[ERROR] OPENAI_API_KEY not set"
    exit 1
fi

if [ ! -d "$SOURCE_MEMORY_LOG" ]; then
    echo "[ERROR] source memory_log not found: $SOURCE_MEMORY_LOG"
    exit 1
fi

for soul in "${SOUL_LIST[@]}"; do
    src="${SOURCE_MEMORY_LOG}/${soul}/patterns_run4.md"
    if [ ! -f "$src" ]; then
        echo "[ERROR] source patterns_run4.md missing for ${soul}: $src"
        exit 1
    fi
done

baseline_dir="results/${TARGET_MODEL_LABEL}/${BASELINE_REP}"
if [ ! -d "$baseline_dir" ]; then
    echo "[ERROR] baseline rep dir not found: $baseline_dir"
    exit 1
fi

echo "=== Gate-Injection Ablation Setup ==="
echo "  Source memory:  ${SOURCE_REP} patterns_run4.md (gating-heavy)"
echo "  Target model:   ${TARGET_MODEL_LABEL} (currently served by vLLM)"
echo "  Baseline rep:   ${BASELINE_REP} Run 5 (comparison)"
echo "  Endpoint:       ${VLLM_METRICS}"
echo

CONFIGURED_MODEL=$(python3 -c "
import json
cfg = json.load(open('openclaw-config/agents/soul-a/agent/models.json'))
print(cfg['providers']['openai']['models'][0]['id'])
" 2>/dev/null || echo "unknown")
echo "  Agent config model: ${CONFIGURED_MODEL}"
echo "  WARNING  manual confirmation required — proceeding with configured model"
echo

if [ -e "$ABLATION_DIR" ]; then
    echo "[ERROR] ablation dir already exists: $ABLATION_DIR"
    exit 1
fi
mkdir -p "$INJECTED_DIR"

# ---- Step 1: Build OVERLAY corpus per soul ----
# Final corpus per soul = Qwen base patterns + extracted GPT-OSS gating lines
echo "=== Step 1: Building overlay corpus (Qwen base + GPT-OSS gating overlay) ==="

QWEN_MEMORY_LOG="results/${TARGET_MODEL_LABEL}/${BASELINE_REP}/${BASELINE_REP}_memory_log"

for soul in "${SOUL_LIST[@]}"; do
    qwen_base="${QWEN_MEMORY_LOG}/${soul}/patterns_run4.md"
    gptoss_src="${SOURCE_MEMORY_LOG}/${soul}/patterns_run4.md"

    if [ ! -f "$qwen_base" ]; then
        echo "[ERROR] Qwen base patterns_run4.md not found: $qwen_base"
        echo "        (Qwen baseline rep ${BASELINE_REP} must have completed runs 1-4)"
        exit 1
    fi

    qwen_copy="${INJECTED_DIR}/${soul}_step1_qwen_base.md"
    gpt_gates="${INJECTED_DIR}/${soul}_step2_gptoss_gating_only.md"
    merged="${INJECTED_DIR}/${soul}_patterns_to_inject.md"

    # Step 1a: copy the target model's own patterns as-is (preserve its natural style)
    cp "$qwen_base" "$qwen_copy"

    # Step 1b: extract only the source model's gating-bearing lines
    python3 scripts/extract_gating_lines.py \
        --input "$gptoss_src" \
        --output "$gpt_gates"

    # Step 1c: merge (target base + source gating overlay)
    {
        cat "$qwen_copy"
        echo ""
        echo "# --- INJECTED OVERLAY: gating-bearing lines extracted from ${SOURCE_REP} same-soul patterns_run4.md ---"
        cat "$gpt_gates"
    } > "$merged"

    n_qwen=$(grep -c '^- \[' "$qwen_copy" || echo 0)
    n_gates=$(grep -c '^- \[' "$gpt_gates" || echo 0)
    n_merged=$(grep -c '^- \[' "$merged" || echo 0)
    echo "  [${soul}] Qwen base: ${n_qwen} lines, GPT-OSS gating overlay: ${n_gates} lines, merged: ${n_merged} lines"
done
echo

# Record gating density of each injected corpus (should be RAISED vs Qwen base).
echo "=== Gating density of injected (gating-overlay) corpora ==="
python3 scripts/measure_gating_density.py --label injection \
    --inputs "$INJECTED_DIR"/*_patterns_to_inject.md \
    --output "${ABLATION_DIR}/gating_density.json" || true
echo

# ---- Step 2: Reset workspace + install injected patterns ----
echo "=== Step 2: Reset workspace + inject GPT-OSS patterns into target model ==="
ABLATION_DIR="$ABLATION_DIR" INJECTED_DIR="$INJECTED_DIR" python3 - <<'PY'
from pathlib import Path
import shutil, os

souls = ("soul-a", "soul-b", "soul-c")
allowed_files = {
    "AGENTS.md", "SOUL.md", "TOOLS.md", "IDENTITY.md", "USER.md",
    "HEARTBEAT.md", "BOOTSTRAP.md",
    "wb-analytics.py", "wb-calendar.py", "wb-crm.py", "wb-email.py", "wb-project.py",
    "emails.csv", "calendar_events.csv", "project_tasks.csv",
    "analytics_data.csv", "customer_relationship_manager_data.csv",
}
allowed_dirs = {"memory", "plots"}

inj_dir = os.environ["INJECTED_DIR"]

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
                    if m.is_file(): m.unlink()
                    else: shutil.rmtree(m)
                continue
            if item.name not in allowed_dirs:
                shutil.rmtree(item)
            continue
        if item.name not in allowed_files:
            item.unlink()
    (root / "plots").mkdir(exist_ok=True)
    (root / "memory").mkdir(exist_ok=True)

    # Inject GPT-OSS gating-heavy patterns
    inj_src = Path(inj_dir) / f"{soul}_patterns_to_inject.md"
    target = root / "memory" / "patterns.md"
    target.write_text(inj_src.read_text(encoding="utf-8"), encoding="utf-8")
    n = sum(1 for ln in target.read_text().splitlines() if ln.strip().startswith("- ["))
    print(f"  [{soul}] workspace cleaned, GPT-OSS patterns injected ({n} pattern lines)")
PY
echo

# ---- Step 3: Execute Run 5' ----
echo "=== Step 3: Execute Run 5' on target model with injected memory ==="
RUN_TS=$(date +%Y%m%dT%H%M%S)

if [ "$PARALLEL" = "1" ]; then
    echo "  Mode: PARALLEL (3 souls concurrent)"
    PIDS=()
    SOULS_ORDERED=()
    TMP_ROOT="${ABLATION_DIR}/_parallel_tmp"
    mkdir -p "$TMP_ROOT"

    for soul in "${SOUL_LIST[@]}"; do
        soul_log="${TMP_ROOT}/${soul}.log"
        echo "  launching ${soul} -> ${soul_log}"
        bash scripts/run_python.sh runner/run_experiment.py \
            --souls "$soul" \
            --ambig-tasks "$TASKS_FILE" \
            --experiment-name "_parallel_${ABLATION_LABEL}_${soul}" \
            --results-dir "$TMP_ROOT" \
            --oracle-model "$ORACLE_MODEL" \
            --vllm-metrics-url "$VLLM_METRICS" \
            ${TASK_LIMIT:+--limit "$TASK_LIMIT"} \
            --learning --keep-memory \
            > "$soul_log" 2>&1 &
        PIDS+=("$!")
        SOULS_ORDERED+=("$soul")
    done

    FAILED=0
    for i in "${!PIDS[@]}"; do
        pid="${PIDS[$i]}"
        soul="${SOULS_ORDERED[$i]}"
        if wait "$pid"; then
            echo "  OK ${soul} (pid=$pid) OK"
        else
            rc=$?
            echo "  X ${soul} (pid=$pid) FAILED (rc=$rc)"
            tail -n 20 "${TMP_ROOT}/${soul}.log" | sed 's/^/      /'
            FAILED=$((FAILED + 1))
        fi
    done

    if [ "$FAILED" -gt 0 ]; then
        echo "[ERROR] $FAILED soul process(es) failed"
        exit 1
    fi

    MERGED_DIR="${ABLATION_DIR}/${ABLATION_LABEL}_${RUN_TS}"
    mkdir -p "$MERGED_DIR"
    MERGED_JSONL="${MERGED_DIR}/${ABLATION_LABEL}_${RUN_TS}.jsonl"
    : > "$MERGED_JSONL"
    for soul in "${SOUL_LIST[@]}"; do
        soul_subdir=$(find "$TMP_ROOT" -name "_parallel_${ABLATION_LABEL}_${soul}*" -type d | head -1)
        cat "$soul_subdir"/*.jsonl >> "$MERGED_JSONL"
    done
    echo "  merged -> $MERGED_JSONL ($(wc -l < $MERGED_JSONL) records)"

    MERGED_JSONL="$MERGED_JSONL" MERGED_DIR="$MERGED_DIR" python3 - <<'PY'
import json, os, sys
from pathlib import Path
sys.path.insert(0, "analysis")
from aggregate import build_summary, write_csv, write_xlsx
jsonl = Path(os.environ["MERGED_JSONL"])
merged_dir = Path(os.environ["MERGED_DIR"])
run_id = jsonl.stem
records = [json.loads(l) for l in jsonl.read_text().splitlines() if l.strip()]
if records:
    s = build_summary(records)
    sd = merged_dir / "summary"; sd.mkdir(exist_ok=True)
    write_csv(s, sd / f"{run_id}.summary.csv")
    (sd / f"{run_id}.summary.json").write_text(json.dumps(s, indent=2, ensure_ascii=False))
    try:
        write_xlsx(s, sd / f"{run_id}.summary.csv", records=records)
    except Exception as e:
        print(f"  XLSX failed: {e}")
    print(f"  summary -> {sd}")
PY

    for soul in "${SOUL_LIST[@]}"; do
        find "$TMP_ROOT" -name "_parallel_${ABLATION_LABEL}_${soul}*" -type d -exec rm -rf {} +
    done
    mv "$TMP_ROOT"/*.log "$MERGED_DIR/" 2>/dev/null || true
    rmdir "$TMP_ROOT" 2>/dev/null || true
else
    bash scripts/run_python.sh runner/run_experiment.py \
        --souls "soul-a,soul-b,soul-c" \
        --ambig-tasks "$TASKS_FILE" \
        --experiment-name "${ABLATION_LABEL}" \
        --results-dir "$ABLATION_DIR" \
        --oracle-model "$ORACLE_MODEL" \
        --vllm-metrics-url "$VLLM_METRICS" \
        ${TASK_LIMIT:+--limit "$TASK_LIMIT"} \
        --learning --keep-memory
fi

echo
echo "=== Done ==="
echo "Ablation results:    $ABLATION_DIR"
echo "Injected patterns:   $INJECTED_DIR"
echo
echo "Next: run the token-matched non-constraint control"
echo "  bash scripts/run_seeding_control_ablation.sh ${SOURCE_REP} ${BASELINE_REP}"
echo
echo "After all Qwen and Gemma replicates and controls are complete, run the"
echo "task-paired analysis reported in the paper:"
echo "  python3 scripts/paired_intervention_analysis.py --results-root results"
