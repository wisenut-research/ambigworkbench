#!/usr/bin/env node
// agent-message-file.mjs — file-body bridge for the experiment runner.
//
// Why this exists: conversation_runner.py sends the agent turn via
//   docker exec node dist/index.js agent --message <BODY> ...
// When BODY is large (injected cumulative memory is ~400KB) it exceeds Linux
// MAX_ARG_STRLEN (128KB per argv string) and execve fails. So the runner
// instead uploads BODY to a file and invokes THIS helper, which reads the file
// and re-runs the official `agent` command IN-PROCESS — the body is then an
// in-memory JS string, never an execve argv, so there is no size limit.
//
// It reuses the official CLI command path (same gateway call, same --json
// output shape: {result:{payloads:[{text}],meta:{...}}}) so its stdout parses
// identically to the normal `agent --json` path in conversation_runner.
//
// Invocation (from conversation_runner.call_agent):
//   node /home/node/.openclaw/agent-message-file.mjs <messageFile> <agentId> <timeoutSecs> [maxTokens]
//
// Note: the official `agent` command has no --max-tokens flag, so [maxTokens]
// (used only for the short memory turn) is not applied here; the model's
// configured maxTokens in models.json bounds output instead. The runner only
// parses "- [" pattern lines from memory-turn output, so extra tokens are
// discarded harmlessly.

import { readFileSync, unlinkSync } from "node:fs";
import process from "node:process";

const messageFile = process.argv[2];
const agentId = process.argv[3];
const timeoutSecs = process.argv[4];
// const maxTokens = process.argv[5]; // no CLI flag; see note above

if (!messageFile || !agentId) {
  process.stderr.write(
    "usage: agent-message-file.mjs <messageFile> <agentId> <timeoutSecs> [maxTokens]\n",
  );
  process.exit(2);
}

let message;
try {
  message = readFileSync(messageFile, "utf8");
} catch (err) {
  process.stderr.write(`[agent-message-file] cannot read ${messageFile}: ${err}\n`);
  process.exit(1);
}
// best-effort cleanup of the uploaded body
try {
  unlinkSync(messageFile);
} catch {
  /* ignore */
}

const INDEX = "/app/dist/index.js";

// Re-create the argv the official CLI expects, with the body as an in-memory
// string. argv[1] is set to the index module path so its `isMainModule` guard
// recognizes it as the entry point and runs program.parseAsync(process.argv).
const argv = ["node", INDEX, "agent", "--message", message, "--agent", agentId, "--no-color", "--json"];
if (timeoutSecs) argv.push("--timeout", String(timeoutSecs));
process.argv = argv;

await import(INDEX);
