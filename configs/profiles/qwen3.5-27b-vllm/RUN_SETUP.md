- agent model: `Qwen/Qwen3.5-27B`
- OpenClaw provider: `openai-completions`
- external client endpoint: `http://<gpu-host>:9022/v1`
- token metrics endpoint: `http://<gpu-host>:9022/metrics`
- oracle model: `gpt-4o-mini`
- tasks file: `benchmark/tasks/ambig_queries.json`
- script: `scripts/run_full_cumul.sh`
- default RUN_PREFIX: `Qwen3.5-27B`
- default RESULTS_DIR: `results/Qwen3.5-27B/...`

Serving topology:
- OpenClaw -> local proxy -> upstream vLLM backend
- proxy external endpoint port: `9022`
- upstream vLLM endpoint: `http://127.0.0.1:19022`

Proxy-forced generation parameters:
- `presence_penalty: 1.5`
- `repetition_penalty: 1.2`
- `enable_thinking: true`

Proxy runtime notes:
- proxy image: `python:3.11-slim`
- proxy forwards requests to the upstream vLLM backend after injecting the forced parameters

Backend vLLM configuration:
- model alias: `qwen3_5_27b_backend`
- docker image: `vllm/vllm-openai:v0.18.0`
- GPUs: `2` on devices `4,5`
- host port: `19022`
- container port: `19022`
- tensor parallel size: `2`
- max model len: `262100`
- dtype: `auto`
- shm size: `32g`
- extra serve args: `--reasoning-parser qwen3 --enable-auto-tool-choice --tool-call-parser qwen3_coder`

Notes:
- OpenClaw connected to the proxy endpoint rather than directly to the upstream vLLM server.
- Forced generation parameters were injected at the proxy layer, not by OpenClaw directly.
