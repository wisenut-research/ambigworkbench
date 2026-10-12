# Qwen3.5-27B Profile

This directory is a read-only snapshot of the active Qwen experiment config.

Purpose:
- Preserve the exact OpenClaw model config used for Qwen3.5-27B runs
- Allow later restoration for additional reps or follow-up runs
- Avoid mutating the live `openclaw-config/` directory during an active run

Profile name:
- `qwen3.5-27b-vllm`

Captured files:
- `openclaw.json`
- `agents/main/agent/models.json`
- `agents/soul-a/agent/models.json`
- `agents/soul-b/agent/models.json`
- `agents/soul-c/agent/models.json`

Current model settings in this snapshot:
- provider: `openai`
- api: `openai-completions`
- model id: `Qwen/Qwen3.5-27B`
- baseUrl: `http://<gpu-host>:9022/v1`
- apiKey: `EMPTY`
- reasoning: `false`
- maxTokens: `2048`
- contextWindow: `262100`

Operational notes:
- This profile stores only OpenClaw-side model config.
- External serving details such as the GPU server, proxy container, and injected serving parameters are managed outside this snapshot.
- Creating this snapshot does not modify the live `openclaw-config/` directory.
