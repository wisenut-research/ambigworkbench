#!/usr/bin/env bash
# run_gate_strip_ablation.sh  (paper section 5.3.4)
#
# Gate-stripping: remove from a replicate's patterns_run4.md every line
# matching the PROHIBITIVE / CONDITIONAL / ASK_FIRST regex families
# (scripts/extract_gating_lines.py), keep the rest of the corpus unchanged,
# install the stripped memory as the Run-5 starting state, and rerun Run 5
# under the original conditions (--learning, souls interleaved).
#
# Usage:
#   export OPENAI_API_KEY=...
#   export VLLM_METRICS=http://<gpu-host>:9022/metrics
#   bash scripts/run_gate_strip_ablation.sh <BASELINE_REP>       # e.g. GPT-OSS-120B_rep1
set -euo pipefail
cd "$(dirname "$0")/.."

BASELINE_REP="${1:?usage: run_gate_strip_ablation.sh <BASELINE_REP>}"
MODEL_LABEL="${BASELINE_REP%_rep*}"
ORACLE_MODEL="${ORACLE_MODEL:-gpt-4o-mini}"
VLLM_METRICS="${VLLM_METRICS:?set VLLM_METRICS, e.g. http://<gpu-host>:9022/metrics}"
TASKS_FILE="${TASKS_FILE:-benchmark/tasks/ambig_queries.json}"
MEMORY_LOG="results/${MODEL_LABEL}/${BASELINE_REP}/${BASELINE_REP}_memory_log"
OUT="results/interventions/${BASELINE_REP}_run5_stripped"
STRIP_DIR="${OUT}/_stripped_patterns"

if [ -z "${OPENAI_API_KEY:-}" ] && [ -f .env ]; then set -a; . ./.env; set +a; fi
[ -n "${OPENAI_API_KEY:-}" ] || { echo "[ERROR] OPENAI_API_KEY not set"; exit 1; }
[ -e "$OUT" ] && { echo "[ERROR] output exists: $OUT"; exit 1; }
mkdir -p "$STRIP_DIR"

echo "=== Step 1: strip gating-matched lines from ${BASELINE_REP} patterns_run4.md ==="
for soul in soul-a soul-b soul-c; do
    src="${MEMORY_LOG}/${soul}/patterns_run4.md"
    [ -f "$src" ] || { echo "[ERROR] missing $src"; exit 1; }
    SRC="$src" DST="${STRIP_DIR}/${soul}_patterns_run4_stripped.md" python3 - <<'PY'
import os, sys
sys.path.insert(0, "scripts")
from extract_gating_lines import has_gating
src, dst = os.environ["SRC"], os.environ["DST"]
lines = open(src, encoding="utf-8", errors="replace").read().splitlines()
kept = [l for l in lines if not has_gating(l)]
open(dst, "w", encoding="utf-8").write("\n".join(kept) + "\n")
print(f"  [{os.path.basename(dst)}] kept {len(kept)}/{len(lines)} lines "
      f"({100*(len(lines)-len(kept))/max(len(lines),1):.1f}% removed)")
PY
done

echo "=== Step 2: reset workspace + install stripped memory ==="
STRIP_DIR="$STRIP_DIR" python3 - <<'PY'
from pathlib import Path
import os, shutil
allowed_files = {"AGENTS.md","SOUL.md","TOOLS.md","IDENTITY.md","USER.md","HEARTBEAT.md","BOOTSTRAP.md",
    "wb-analytics.py","wb-calendar.py","wb-crm.py","wb-email.py","wb-project.py",
    "emails.csv","calendar_events.csv","project_tasks.csv",
    "analytics_data.csv","customer_relationship_manager_data.csv"}
allowed_dirs = {"memory","plots"}
for soul in ("soul-a","soul-b","soul-c"):
    root = Path("workspace")/soul
    for item in root.iterdir():
        if item.is_dir():
            if item.name == "plots": shutil.rmtree(item); item.mkdir()
            elif item.name == "memory":
                for m in list(item.iterdir()):
                    m.unlink() if m.is_file() else shutil.rmtree(m)
            elif item.name not in allowed_dirs: shutil.rmtree(item)
        elif item.name not in allowed_files: item.unlink()
    src = Path(os.environ["STRIP_DIR"])/f"{soul}_patterns_run4_stripped.md"
    dst = root/"memory"/"patterns.md"
    dst.parent.mkdir(exist_ok=True)
    dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    print(f"  [{soul}] installed stripped patterns.md")
PY

echo "=== Step 3: rerun Run 5 with stripped memory ==="
bash scripts/run_python.sh runner/run_experiment.py \
    --souls soul-a,soul-b,soul-c \
    --ambig-tasks "$TASKS_FILE" \
    --experiment-name "${BASELINE_REP}_run5_stripped" \
    --results-dir "$OUT" \
    --oracle-model "$ORACLE_MODEL" \
    --vllm-metrics-url "$VLLM_METRICS" \
    --learning --keep-memory
echo "=== done: $OUT ==="
