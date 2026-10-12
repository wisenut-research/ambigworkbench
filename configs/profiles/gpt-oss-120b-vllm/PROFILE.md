# GPT-OSS-120B Profile

This directory is a read-only OpenClaw model profile for GPT-OSS-120B served via
the external vLLM endpoint on the GPU server.

Purpose:
- Preserve the exact OpenClaw-side config for GPT-OSS-120B experiments
- Allow later restoration for additional reps or follow-up runs
- Keep model-specific config separate from the active profile

Profile name:
- `gpt-oss-120b-vllm`

Captured files:
- `openclaw.json`
- `agents/main/agent/models.json`
- `agents/soul-a/agent/models.json`
- `agents/soul-b/agent/models.json`
- `agents/soul-c/agent/models.json`

Configured model settings:
- provider: `openai`
- api: `openai-completions`
- model id: `openai/gpt-oss-120b`
- default model ref: `openai/openai/gpt-oss-120b`
- baseUrl: `http://<gpu-host>:9022/v1`
- apiKey: `EMPTY`
- reasoning: `true`
- maxTokens: `2048`
- contextWindow: `131072`

Operational notes:
- This profile stores only OpenClaw-side model config.
- External serving details such as Docker launch, GPU allocation, and vLLM serve
  flags are documented in `RUN_SETUP.md`.
- Creating this profile does not modify the live `openclaw-config/` directory.
