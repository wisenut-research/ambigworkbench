#!/usr/bin/env bash
# run_sharedmem_ablation.sh  (paper section 5.3.3, shared-memory design)
#
# Installs ONE identical corpus (by default the Neutral replicate-1
# patterns_run4.md, staged as seed_01/shared_patterns_run4_neutral.md) as the
# Run-5 starting state for ALL THREE identities and reruns Run 5. If the
# identity ordering of collapse persists, the prompt prior acts at execution
# time; if it disappears, identity acts through what it accumulates.
#
set -euo pipefail

cd "$(dirname "$0")/.."
EXP_DIR="$(pwd)"

SOURCE_REP="${1:-GPT-OSS-120B_rep1}"
SOURCE_MODEL_LABEL="${SOURCE_REP%_rep*}"
ORACLE_MODEL="${ORACLE_MODEL:-gpt-4o-mini}"
VLLM_METRICS="${VLLM_METRICS:?set VLLM_METRICS, e.g. http://<gpu-host>:9022/metrics}"
TASKS_FILE="${TASKS_FILE:-benchmark/tasks/ambig_queries.json}"

SOUL_LIST=(soul-a soul-b soul-c)
CONTROL_LABEL="${SOURCE_REP}_run5_sharedmem_neutral"
CONTROL_DIR="results/_ablation/${CONTROL_LABEL}"
SOURCE_PATTERNS="results/${SOURCE_MODEL_LABEL}/${SOURCE_REP}/${SOURCE_REP}_memory_log/soul-a/patterns_run4.md"

if [ -z "${OPENAI_API_KEY:-}" ] && [ -f .env ]; then
    set -a; . ./.env; set +a
fi
if [ -z "${OPENAI_API_KEY:-}" ]; then
    echo "[ERROR] OPENAI_API_KEY not set"
    exit 1
fi

SEED_DIR="${CONTROL_DIR}/seed_01"
mkdir -p "$SEED_DIR"
if [ ! -f "$SEED_DIR/shared_patterns_run4_neutral.md" ]; then
    [ -f "$SOURCE_PATTERNS" ] || { echo "[ERROR] source corpus not found: $SOURCE_PATTERNS"; exit 1; }
    cp "$SOURCE_PATTERNS" "$SEED_DIR/shared_patterns_run4_neutral.md"
fi

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
                shutil.rmtree(item)
                item.mkdir()
                continue
            if item.name == "memory":
                for m in list(item.iterdir()):
                    if m.is_file():
                        m.unlink()
                    else:
                        shutil.rmtree(m)
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

install_seed_patterns() {
    local seed_dir="$1"
    SEED_DIR="$seed_dir" python3 - <<'PY'
from pathlib import Path
import os

seed_dir = Path(os.environ["SEED_DIR"])
src = seed_dir / "shared_patterns_run4_neutral.md"
if not src.exists():
    raise FileNotFoundError(f"missing shared pattern file: {src}")
text = src.read_text(encoding="utf-8")
for soul in ("soul-a", "soul-b", "soul-c"):
    dst = Path("workspace") / soul / "memory" / "patterns.md"
    dst.write_text(text, encoding="utf-8")
    n = sum(1 for ln in text.splitlines() if ln.strip().startswith("- ["))
    print(f"  [{soul}] installed SHARED (Neutral rep1 run4) patterns.md ({n} pattern lines)")
PY
}

lock_workspace() {
    for soul in "${SOUL_LIST[@]}"; do
        chmod 444 "workspace/${soul}/AGENTS.md" 2>/dev/null || true
        chmod 444 "workspace/${soul}/TOOLS.md" 2>/dev/null || true
        chmod 444 workspace/${soul}/wb-*.py 2>/dev/null || true
    done
}

echo "=== Shared-starting-memory intervention ==="
echo "Source rep:     ${SOURCE_REP}"
echo "Control root:   ${CONTROL_DIR}"
echo "Tasks file:     ${TASKS_FILE}"
echo "Oracle model:   ${ORACLE_MODEL}"
echo "vLLM metrics:   ${VLLM_METRICS}"
echo

for seed in 01; do
    SEED_DIR="${CONTROL_DIR}/seed_${seed}"
    RUN_LABEL="${SOURCE_REP}_run5_sharedmem_neutral_seed_${seed}"

    if [ ! -d "$SEED_DIR" ]; then
        echo "[ERROR] seed dir missing: $SEED_DIR"
        exit 1
    fi
    if find "$SEED_DIR" -maxdepth 1 -type d -name "${RUN_LABEL}_*" | grep -q .; then
        echo "[ERROR] output already exists for seed ${seed} under ${SEED_DIR}"
        exit 1
    fi

    echo "===================================================================="
    echo "Seed ${seed}: preparing workspace"
    cleanup_workspace
    install_seed_patterns "$SEED_DIR"
    lock_workspace

    echo "Seed ${seed}: running souls in parallel"
    RUN_TS=$(date +%Y%m%dT%H%M%S)
    TMP_ROOT="${SEED_DIR}/_parallel_tmp"
    mkdir -p "$TMP_ROOT"

    PIDS=()
    SOULS_ORDERED=()
    for soul in "${SOUL_LIST[@]}"; do
        soul_log="${TMP_ROOT}/${soul}.log"
        echo "  launching ${soul} -> ${soul_log}"
        bash scripts/run_python.sh runner/run_experiment.py \
            --souls "$soul" \
            --ambig-tasks "$TASKS_FILE" \
            --experiment-name "_parallel_${RUN_LABEL}_${soul}" \
            --results-dir "$TMP_ROOT" \
            --oracle-model "$ORACLE_MODEL" \
            --vllm-metrics-url "$VLLM_METRICS" \
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
        echo "[ERROR] seed ${seed} failed (${FAILED} soul process(es))"
        exit 1
    fi

    MERGED_DIR="${SEED_DIR}/${RUN_LABEL}_${RUN_TS}"
    mkdir -p "$MERGED_DIR"
    MERGED_JSONL="${MERGED_DIR}/${RUN_LABEL}_${RUN_TS}.jsonl"
    : > "$MERGED_JSONL"

    for soul in "${SOUL_LIST[@]}"; do
        soul_subdir=$(find "$TMP_ROOT" -name "_parallel_${RUN_LABEL}_${soul}*" -type d | head -1)
        cat "$soul_subdir"/*.jsonl >> "$MERGED_JSONL"
    done
    echo "  merged -> $MERGED_JSONL ($(wc -l < "$MERGED_JSONL") records)"

    MERGED_JSONL="$MERGED_JSONL" MERGED_DIR="$MERGED_DIR" python3 - <<'PY'
import json, os, sys
from pathlib import Path
sys.path.insert(0, "analysis")
from aggregate import build_summary, write_csv, write_xlsx

jsonl = Path(os.environ["MERGED_JSONL"])
merged_dir = Path(os.environ["MERGED_DIR"])
run_id = jsonl.stem
records = [json.loads(l) for l in jsonl.read_text(encoding="utf-8").splitlines() if l.strip()]
if records:
    s = build_summary(records)
    sd = merged_dir / "summary"
    sd.mkdir(exist_ok=True)
    csv_path = sd / f"{run_id}.summary.csv"
    write_csv(s, csv_path)
    (sd / f"{run_id}.summary.json").write_text(json.dumps(s, indent=2, ensure_ascii=False), encoding="utf-8")
    try:
        write_xlsx(s, csv_path, records=records)
    except Exception as e:
        print(f"  XLSX failed: {e}")
    print(f"  summary -> {sd}")
PY

    for soul in "${SOUL_LIST[@]}"; do
        find "$TMP_ROOT" -name "_parallel_${RUN_LABEL}_${soul}*" -type d -exec rm -rf {} +
    done
    mv "$TMP_ROOT"/*.log "$MERGED_DIR/" 2>/dev/null || true
    rmdir "$TMP_ROOT" 2>/dev/null || true

    echo "Seed ${seed}: done"
    echo
done

echo "=== Shared-starting-memory intervention completed ==="
echo "Control root: ${CONTROL_DIR}"
