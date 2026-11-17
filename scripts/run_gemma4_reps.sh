#!/usr/bin/env bash
# Runs Gemma4-26B-A4B-it replicates 1-3 one after another. Within each run the
# three conditions (soul-a/b/c) execute as concurrent processes via
# run_full_cumul_parallel.sh, as in the reported Gemma baselines. The other
# model families used the single-process runner run_full_cumul.sh.
set -euo pipefail

cd "$(dirname "$0")/.."

MODEL_LABEL="Gemma4-26B-A4B-it"
RESULTS_ROOT="results/${MODEL_LABEL}"
METRICS_URL="${VLLM_METRICS:?set VLLM_METRICS, e.g. http://<gpu-host>:9022/metrics}"

if [ -z "${OPENAI_API_KEY:-}" ] && [ -f .env ]; then
  set -a
  . ./.env
  set +a
fi

if [ -z "${OPENAI_API_KEY:-}" ]; then
  echo "[ERROR] OPENAI_API_KEY is not set."
  exit 1
fi

mkdir -p "${RESULTS_ROOT}"

for rep in 1 2 3; do
  rep_name="${MODEL_LABEL}_rep${rep}"
  rep_dir="${RESULTS_ROOT}/${rep_name}"

  if [ -e "${rep_dir}" ]; then
    echo "[ERROR] Refusing to start ${rep_name}: ${rep_dir} already exists."
    exit 1
  fi

  echo "[$(date '+%F %T %Z')] starting ${rep_name} (concurrent conditions)"
  export RUN_PREFIX="${rep_name}"
  export RESULTS_DIR="${rep_dir}"
  export VLLM_METRICS="${METRICS_URL}"

  bash scripts/run_full_cumul_parallel.sh

  echo "[$(date '+%F %T %Z')] finished ${rep_name}"
done

echo "[$(date '+%F %T %Z')] all Gemma reps completed"
