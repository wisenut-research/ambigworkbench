#!/usr/bin/env bash
# Run one targeted GPT-OSS content-volume control after building its corpus.
# The three conditions run concurrently, matching the completed control runs.
#
# Usage:
#   export OPENAI_API_KEY=...
#   export VLLM_METRICS=http://<gpu-host>:9022/metrics
#   bash scripts/run_content_volume_control.sh random 1
#   bash scripts/run_content_volume_control.sh nongating-loadmatched 1
set -euo pipefail
cd "$(dirname "$0")/.."

ARM="${1:?arm must be random or nongating-loadmatched}"
SEED="${2:-1}"
SOURCE_REP="${SOURCE_REP:-GPT-OSS-120B_rep1}"
ORACLE_MODEL="${ORACLE_MODEL:-gpt-4o-mini}"
VLLM_METRICS="${VLLM_METRICS:?set VLLM_METRICS, e.g. http://<gpu-host>:9022/metrics}"
TASKS_FILE="${TASKS_FILE:-benchmark/tasks/ambig_queries.json}"
SEED_PADDED=$(printf '%02d' "$SEED")

case "$ARM" in
  random)
    ROOT="results/interventions/${SOURCE_REP}_run5_random_stripped_size_matched/seed_${SEED_PADDED}"
    SUFFIX="patterns_run4_random_stripped.md"
    ;;
  nongating-loadmatched)
    ROOT="results/interventions/${SOURCE_REP}_run5_nongating_loadmatched/seed_${SEED_PADDED}"
    SUFFIX="patterns_run4_nongating_loadmatched.md"
    ;;
  *) echo "[ERROR] unknown arm: $ARM"; exit 1 ;;
esac

[ -n "${OPENAI_API_KEY:-}" ] || { echo "[ERROR] OPENAI_API_KEY not set"; exit 1; }
[ -d "$ROOT" ] || { echo "[ERROR] build the corpus first: $ROOT"; exit 1; }
OUT="${ROOT}/run"
[ ! -e "$OUT" ] || { echo "[ERROR] output exists: $OUT"; exit 1; }
mkdir -p "$OUT"

echo "=== Reset workspace and install $ARM corpora ==="
ROOT="$ROOT" SUFFIX="$SUFFIX" python3 - <<'PY'
from pathlib import Path
import os, shutil

allowed_files = {
    "AGENTS.md", "SOUL.md", "TOOLS.md", "IDENTITY.md", "USER.md",
    "HEARTBEAT.md", "BOOTSTRAP.md", "wb-analytics.py", "wb-calendar.py",
    "wb-crm.py", "wb-email.py", "wb-project.py", "emails.csv",
    "calendar_events.csv", "project_tasks.csv", "analytics_data.csv",
    "customer_relationship_manager_data.csv",
}
allowed_dirs = {"memory", "plots"}
root = Path(os.environ["ROOT"])
suffix = os.environ["SUFFIX"]
for soul in ("soul-a", "soul-b", "soul-c"):
    workspace = Path("workspace") / soul
    for item in list(workspace.iterdir()):
        if item.is_dir():
            if item.name == "plots":
                shutil.rmtree(item); item.mkdir()
            elif item.name == "memory":
                for child in list(item.iterdir()):
                    child.unlink() if child.is_file() else shutil.rmtree(child)
            elif item.name not in allowed_dirs:
                shutil.rmtree(item)
        elif item.name not in allowed_files:
            item.unlink()
    source = root / f"{soul}_{suffix}"
    if not source.exists():
        raise FileNotFoundError(source)
    destination = workspace / "memory" / "patterns.md"
    destination.parent.mkdir(exist_ok=True)
    destination.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    print(f"  {soul}: {source.name}")
PY

echo "=== Run the three conditions concurrently ==="
pids=()
for soul in soul-a soul-b soul-c; do
  bash scripts/run_python.sh runner/run_experiment.py \
    --souls "$soul" \
    --ambig-tasks "$TASKS_FILE" \
    --experiment-name "${SOURCE_REP}_run5_${ARM}_seed_${SEED_PADDED}_${soul}" \
    --results-dir "$OUT" \
    --oracle-model "$ORACLE_MODEL" \
    --vllm-metrics-url "$VLLM_METRICS" \
    --learning --keep-memory >"${OUT}/${soul}.log" 2>&1 &
  pids+=("$!")
done

failed=0
for pid in "${pids[@]}"; do
  wait "$pid" || failed=$((failed + 1))
done
[ "$failed" -eq 0 ] || { echo "[ERROR] $failed condition runs failed"; exit 1; }
echo "=== done: $OUT ==="
