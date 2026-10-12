#!/usr/bin/env bash
# run_full_cumul.sh
# Run ambig_queries.json (314 tasks) 5 times with cumulative memory.
# Run 1: fresh memory. Run 2-5: --keep-memory (patterns.md accumulates across runs).
# Snapshots patterns.md after each run into patterns_run{N}.md per soul.
#
# Usage:
#   export OPENAI_API_KEY="<oracle-key>"
#   bash scripts/run_full_cumul.sh
#
# Optional overrides (env vars):
#   ORACLE_MODEL   (default: gpt-4o-mini)
#   VLLM_METRICS   (default: http://<gpu-host>:9022/metrics)
#   TASKS_FILE     (default: benchmark/tasks/ambig_queries.json)
#   RUN_PREFIX     (default: model name from openclaw-config/agents/soul-a/agent/models.json)
#   RESULTS_DIR    (default: results)

set -euo pipefail

ORACLE_MODEL="${ORACLE_MODEL:-gpt-4o-mini}"
VLLM_METRICS="${VLLM_METRICS:?set VLLM_METRICS, e.g. http://<gpu-host>:9022/metrics}"
TASKS_FILE="${TASKS_FILE:-benchmark/tasks/ambig_queries.json}"
RESULTS_DIR="${RESULTS_DIR:-results}"

# RUN_PREFIX: env override wins; otherwise derived from the model id in models.json
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
    "AGENTS.md",
    "SOUL.md",
    "TOOLS.md",
    "IDENTITY.md",
    "USER.md",
    "HEARTBEAT.md",
    "BOOTSTRAP.md",
    "wb-analytics.py",
    "wb-calendar.py",
    "wb-crm.py",
    "wb-email.py",
    "wb-project.py",
    "emails.csv",
    "calendar_events.csv",
    "project_tasks.csv",
    "analytics_data.csv",
    "customer_relationship_manager_data.csv",
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

echo "Tasks file : $TASKS_FILE"
echo "Run prefix : $RUN_PREFIX"
echo "Results dir: $RESULTS_DIR"
echo "Oracle     : $ORACLE_MODEL"
echo "vLLM       : $VLLM_METRICS"
echo ""

echo "=== Run 1 (fresh memory) ==="
cleanup_workspace_extras
bash scripts/run_python.sh runner/run_experiment.py \
    --ambig-tasks "$TASKS_FILE" \
    --experiment-name "${RUN_PREFIX}_run1" \
    --results-dir "$RESULTS_DIR" \
    --oracle-model "$ORACLE_MODEL" \
    --vllm-metrics-url "$VLLM_METRICS" \
    --learning
snapshot_patterns 1

for run_n in 2 3 4 5; do
    echo ""
    echo "=== Run ${run_n} (keep-memory) ==="
    cleanup_workspace_extras
    bash scripts/run_python.sh runner/run_experiment.py \
        --ambig-tasks "$TASKS_FILE" \
        --experiment-name "${RUN_PREFIX}_run${run_n}" \
        --results-dir "$RESULTS_DIR" \
        --oracle-model "$ORACLE_MODEL" \
        --vllm-metrics-url "$VLLM_METRICS" \
        --learning \
        --keep-memory
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
