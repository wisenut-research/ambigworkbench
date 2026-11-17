#!/usr/bin/env bash
# run_full_cumul_parallel.sh
# Same semantics as run_full_cumul.sh but launches 3 souls concurrently
# against a shared vLLM endpoint to amortize decode-time bottlenecks.
# The reported Gemma4-26B-A4B-it baselines were produced with this runner
# (via scripts/run_gemma4_reps.sh); the GPT-OSS-120B, Qwen3.5-27B, and
# GPT-OSS-20B baselines used the single-process runner run_full_cumul.sh.
#
# Per-run flow:
#   1. cleanup workspace extras
#   2. launch 3 parallel run_experiment.py (one per soul) into per-soul subdirs
#   3. wait for all 3, abort if any failed
#   4. merge per-soul JSONLs into the standard RUN_PREFIX_runN_TIMESTAMP/ dir
#   5. snapshot patterns.md per soul
#
# Usage:
#   export OPENAI_API_KEY="<oracle-key>"
#   bash scripts/run_full_cumul_parallel.sh
#
# Env vars (same as run_full_cumul.sh):
#   ORACLE_MODEL, VLLM_METRICS, TASKS_FILE, RUN_PREFIX, RESULTS_DIR

set -euo pipefail

ORACLE_MODEL="${ORACLE_MODEL:-gpt-4o-mini}"
VLLM_METRICS="${VLLM_METRICS:?set VLLM_METRICS, e.g. http://<gpu-host>:9022/metrics}"
TASKS_FILE="${TASKS_FILE:-benchmark/tasks/ambig_queries.json}"
RESULTS_DIR="${RESULTS_DIR:-results}"

if [ -z "${RUN_PREFIX:-}" ]; then
    RUN_PREFIX=$(python3 -c "
import json, sys
try:
    cfg = json.load(open('openclaw-config/agents/soul-a/agent/models.json'))
    model_id = cfg['providers']['openai']['models'][0]['id']
    print(model_id.split('/')[-1])
except Exception as e:
    print('unknown-model', file=sys.stderr)
    sys.exit(1)
")
fi
SOULS=(soul-a soul-b soul-c)

cleanup_workspace_extras() {
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
    removed = 0
    if not root.exists():
        continue
    for item in root.iterdir():
        if item.is_dir():
            if item.name == "plots":
                shutil.rmtree(item)
                item.mkdir()
                removed += 1
                continue
            if item.name not in allowed_dirs:
                shutil.rmtree(item)
                removed += 1
            continue
        if item.name not in allowed_files:
            item.unlink()
            removed += 1
    (root / "plots").mkdir(exist_ok=True)
    print(f"  [{soul}] workspace extras cleaned ({removed} removed)")
PY
}

snapshot_patterns() {
    local run_n="$1"
    local archive_dir="${RESULTS_DIR}/${RUN_PREFIX}_memory_log"
    for soul in "${SOULS[@]}"; do
        if [ -f "workspace/${soul}/memory/patterns.md" ]; then
            cp "workspace/${soul}/memory/patterns.md" \
               "workspace/${soul}/memory/patterns_run${run_n}.md"
            echo "  -> snapshot: workspace/${soul}/memory/patterns_run${run_n}.md"
            mkdir -p "${archive_dir}/${soul}"
            cp "workspace/${soul}/memory/patterns.md" \
               "${archive_dir}/${soul}/patterns_run${run_n}.md"
            echo "  -> archive:  ${archive_dir}/${soul}/patterns_run${run_n}.md"
        else
            echo "  -> [warn] workspace/${soul}/memory/patterns.md not found, skipping snapshot"
        fi
    done
}

run_one_run_parallel() {
    local run_n="$1"
    local extra_args="$2"  # "--keep-memory" for runs 2-5, empty for run 1

    cleanup_workspace_extras

    # Per-soul tmp dirs (will be merged after all 3 done)
    local tmp_root="${RESULTS_DIR}/_parallel_tmp_run${run_n}"
    rm -rf "$tmp_root"
    mkdir -p "$tmp_root"

    # bash 3.2 compatible: parallel arrays instead of associative array
    PIDS=()
    SOULS_ORDERED=()

    for soul in "${SOULS[@]}"; do
        local soul_log="${tmp_root}/${soul}.log"
        echo "[$(date '+%F %T %Z')] launching ${RUN_PREFIX}_run${run_n}/${soul} -> log: ${soul_log}"

        bash scripts/run_python.sh runner/run_experiment.py \
            --souls "$soul" \
            --ambig-tasks "$TASKS_FILE" \
            --experiment-name "_parallel_${RUN_PREFIX}_run${run_n}_${soul}" \
            --results-dir "$tmp_root" \
            --oracle-model "$ORACLE_MODEL" \
            --vllm-metrics-url "$VLLM_METRICS" \
            --learning $extra_args \
            > "$soul_log" 2>&1 &
        PIDS+=("$!")
        SOULS_ORDERED+=("$soul")
    done

    # Wait for all and check exit codes (parallel-array iteration)
    local FAILED=0
    local i
    for i in "${!PIDS[@]}"; do
        local pid="${PIDS[$i]}"
        local soul="${SOULS_ORDERED[$i]}"
        if wait "$pid"; then
            echo "[$(date '+%F %T %Z')]   ok ${soul} (pid=$pid) finished OK"
        else
            local rc=$?
            echo "[$(date '+%F %T %Z')]   FAILED: ${soul} (pid=$pid) FAILED with exit code $rc"
            echo "      log tail:"
            tail -n 20 "${tmp_root}/${soul}.log" | sed 's/^/        /'
            FAILED=$((FAILED + 1))
        fi
    done

    if [ "$FAILED" -gt 0 ]; then
        echo "[ERROR] $FAILED soul process(es) failed in run $run_n. Aborting."
        echo "        Per-soul logs preserved in: $tmp_root"
        exit 1
    fi

    # Merge per-soul JSONLs into the standard run dir naming
    local run_ts
    run_ts=$(date +%Y%m%dT%H%M%SKST)
    local merged_dir="${RESULTS_DIR}/${RUN_PREFIX}_run${run_n}_${run_ts}"
    mkdir -p "$merged_dir"

    local merged_jsonl="${merged_dir}/${RUN_PREFIX}_run${run_n}_${run_ts}.jsonl"
    : > "$merged_jsonl"
    for soul in "${SOULS[@]}"; do
        # Each soul's tmp dir contains a single subdir (the runner's run_id)
        # which contains the JSONL file
        local soul_jsonls
        soul_jsonls=$(find "$tmp_root" -name "_parallel_${RUN_PREFIX}_run${run_n}_${soul}*" -type d | head -1)
        if [ -z "$soul_jsonls" ] || [ ! -d "$soul_jsonls" ]; then
            echo "[ERROR] missing per-soul output dir for ${soul}: ${tmp_root}/_parallel_${RUN_PREFIX}_run${run_n}_${soul}*"
            exit 1
        fi
        local jsonl_files
        jsonl_files=$(find "$soul_jsonls" -name "*.jsonl" -type f)
        if [ -z "$jsonl_files" ]; then
            echo "[ERROR] no JSONL produced for ${soul} in ${soul_jsonls}"
            exit 1
        fi
        cat $jsonl_files >> "$merged_jsonl"
    done

    local n_records
    n_records=$(wc -l < "$merged_jsonl")
    echo "[$(date '+%F %T %Z')] merged -> ${merged_jsonl} (${n_records} records)"

    # Regenerate run-level summary (csv/json/xlsx) from the merged JSONL.
    # This is the SAME aggregate function the sequential runner calls at end of run,
    # ensuring the parallel run dir has identical artifacts to a sequential run dir.
    echo "[$(date '+%F %T %Z')] regenerating run-level summary from merged JSONL ..."
    MERGED_JSONL="$merged_jsonl" MERGED_DIR="$merged_dir" python3 - <<'PY'
import json, os, sys
from pathlib import Path

sys.path.insert(0, "analysis")
from aggregate import build_summary, write_csv, write_xlsx

jsonl = Path(os.environ["MERGED_JSONL"])
merged_dir = Path(os.environ["MERGED_DIR"])
run_id = jsonl.stem

records = []
for line in jsonl.read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if not line:
        continue
    try:
        records.append(json.loads(line))
    except json.JSONDecodeError:
        pass

if not records:
    print("    [warn] no records parsed; skipping summary")
    sys.exit(0)

summary = build_summary(records)
summary_dir = merged_dir / "summary"
summary_dir.mkdir(exist_ok=True)

csv_out = summary_dir / f"{run_id}.summary.csv"
write_csv(summary, csv_out)
print(f"    CSV  -> {csv_out}")

json_out = summary_dir / f"{run_id}.summary.json"
json_out.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
print(f"    JSON -> {json_out}")

try:
    xlsx_path = write_xlsx(summary, csv_out, records=records)
    if xlsx_path:
        print(f"    XLSX -> {xlsx_path}")
except Exception as e:
    print(f"    [warn] XLSX generation failed: {e}")
PY

    # Cleanup tmp dirs (logs preserved for debugging traceability)
    for soul in "${SOULS[@]}"; do
        find "$tmp_root" -name "_parallel_${RUN_PREFIX}_run${run_n}_${soul}*" -type d -exec rm -rf {} +
    done
    # Move per-soul logs into merged dir so post-mortem is co-located with results
    mv "$tmp_root"/*.log "$merged_dir/" 2>/dev/null || true
    rmdir "$tmp_root" 2>/dev/null || true
}

echo "Tasks file : $TASKS_FILE"
echo "Run prefix : $RUN_PREFIX"
echo "Results dir: $RESULTS_DIR"
echo "Oracle     : $ORACLE_MODEL"
echo "vLLM       : $VLLM_METRICS"
echo "Mode       : PARALLEL (3 souls concurrent)"
echo ""

echo "=== Run 1 (fresh memory) ==="
run_one_run_parallel 1 ""
snapshot_patterns 1

for run_n in 2 3 4 5; do
    echo ""
    echo "=== Run ${run_n} (keep-memory) ==="
    run_one_run_parallel "$run_n" "--keep-memory"
    snapshot_patterns "$run_n"
done

echo ""
echo "=== Cumulative aggregation ==="
python analysis/aggregate_cumul.py \
    --run-prefix "${RUN_PREFIX}" \
    --runs 5 \
    --results-dir "$RESULTS_DIR" \
    --out "${RESULTS_DIR}/${RUN_PREFIX}_analysis.xlsx"

echo ""
echo "Done. Pattern snapshots saved to workspace/soul-*/memory/patterns_run{1..5}.md"
