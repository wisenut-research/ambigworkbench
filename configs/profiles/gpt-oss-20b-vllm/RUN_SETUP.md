- model alias: gpt_oss_20b
- agent model: openai/gpt-oss-20b
- OpenClaw provider: openai-completions
- baseUrl: http://<gpu-host>:9022/v1
- token metrics endpoint: http://<gpu-host>:9022/metrics
- oracle model: gpt-4o-mini
- tasks file: benchmark/tasks/ambig_queries.json
- script: scripts/run_full_cumul.sh
- docker image: vllm/vllm-openai:v0.19.0
- GPUs: 2
- GPU devices: 4,5
- host port: 9022
- container port: 9022
- tensor parallel size: 2
- max model len: 131072
- dtype: auto
- shm size: 32g
- extra serve args: --gpu-memory-utilization 0.90 --reasoning-parser openai_gptoss --enable-auto-tool-choice --tool-call-parser openai
- note: serving-side repetition penalty or other launch-time args should be recorded with the GPU server command history if changed later

Comparability notes (20B vs 120B):
- All serving parameters above are deliberately IDENTICAL to the
  gpt-oss-120b-vllm profile (same vLLM image v0.19.0, TP=2 on 2 GPUs,
  max-model-len 131072, same reasoning/tool parsers, same port) so that the
  only varying factor is model size within the same family.
- 20B would fit on a single GPU, but TP=2 is kept to preserve the serving
  topology; do not change without recording it.
- default RUN_PREFIX: `GPT-OSS-20B`
- default RESULTS_DIR: `results/GPT-OSS-20B/...`
- purpose: within-family size point for the regime taxonomy (does the Run-5
  cliff track the family or the scale?); plan = 1 replicate x 5 cumulative
  runs x 3 identities (4,710 tasks) before deciding on further reps.
