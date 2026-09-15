# Agent Production Runtime

This document describes the Stage 8 production boundaries used by the WebReBuild Agent runtime.

## 1. Prompt registry

AI-facing system prompts are addressed by stable code-reviewed IDs rather than being supplied by runtime callers.

| Prompt | Version | Purpose |
| --- | --- | --- |
| `agent.planner` | `1.1.0` | Select direct answer vs one registered tool |
| `chat.reading` | `1.1.0` | Reading/Agent synthesis and grounded chat |
| `text.translate` | `1.0.0` | AI translation |
| `text.polish` | `1.0.0` | AI polishing |
| `text.strict_retry` | `1.0.0` | Output-contract repair attempt |

A prompt ID is `<name>@<version>`, for example `agent.planner@1.1.0`.

`PromptRegistry` rejects replacing an existing name/version with different prompt content. Prompt text is not returned by the runtime-config API.

## 2. LLM Gateway and model routing

`app.ai.gateway.LLMGateway` owns role-to-model selection. Model output and document content cannot choose a model/provider.

Current provider support remains intentionally limited to DeepSeek. The gateway is the extension boundary for future providers rather than a claim that multiple providers are already implemented.

Default routes:

| Role | Provider | Default model |
| --- | --- | --- |
| `planner` | DeepSeek | `deepseek-v4-flash` |
| `agent_synthesis` | DeepSeek | `deepseek-v4-pro` |
| `reading` | DeepSeek | `deepseek-v4-pro` |
| `translation_ai` | DeepSeek | existing default DeepSeek model |
| `polish` | DeepSeek | existing default DeepSeek model |

Supported route models are restricted to the allowlist exported by `app.ai.client.SUPPORTED_DEEPSEEK_MODELS`.

Optional environment overrides:

```text
AITRANS_MODEL_PLANNER
AITRANS_MODEL_AGENT_SYNTHESIS
AITRANS_MODEL_READING
AITRANS_MODEL_TRANSLATION_AI
AITRANS_MODEL_POLISH
```

An unsupported model value fails configuration validation rather than silently falling back.

Routed AI services are lazy. Constructing the FastAPI app or reading `/api/agent/runtime/config` does not require an API key. Provider credentials are resolved only when an actual model request is made.

## 3. Context budget

Context budgeting is deterministic and dependency-free. It uses bounded character allocation plus a conservative token estimate rather than adding a tokenizer dependency.

Planner budget: `18,000` characters.

Planner priority:

1. current user request
2. selected source text
3. translation/title/section metadata
4. bounded before/after reading context
5. resource URL

Reading/chat budget: `24,000` characters.

Chat priority:

1. current user request
2. tool observation and selected source text
3. current translation/title/section
4. bounded before/after context
5. conversation history
6. resource URL

Each field also has an individual hard cap. Context-budget metadata records used characters, estimated tokens, and fields that were truncated. If character truncation makes serialized conversation-history JSON invalid, that history block is dropped rather than repaired from untrusted content.

## 4. Security boundary

PDF, DOCX, browser, reading-context, tool-observation, and conversation-history content are treated as untrusted data.

The planner system prompt explicitly instructs the model not to follow instructions embedded in source/document content. `AgentSecurityService` additionally records suspicious prompt-injection patterns for diagnostic purposes.

Security flags are advisory evidence, not arbitrary content filters: suspicious academic/source text remains available as data while system/tool authority remains code-owned.

Planner tool authority is bounded by both:

- a small planner argument allowlist (`target_language`, `style`, `user_note`), and
- the selected tool's declared `input_schema`.

Fields such as `conversation_id`, file paths, URLs, capability scopes, confirmation state, or arbitrary tool names cannot be supplied by the planner unless explicitly added to both policy and tool schema.

Write tools retain the existing confirmation gate and are never automatically retried.

## 5. Safe runtime metadata API

```text
GET /api/agent/runtime/config
```

Returns only:

- model role/provider/model metadata,
- prompt name/version/prompt ID,
- planner/chat context budgets,
- document trust policy,
- planner argument policy,
- write-confirmation policy.

It does **not** expose:

- system prompt text,
- API keys or secrets,
- selected/source text,
- model output,
- private local paths.

The desktop Agent Observability panel displays this safe metadata alongside Batch 7 reliability metrics.

## 6. Trace and evaluation relationship

Batch 6/7 `run_id`, `trace_id`, reliability events, redacted SQLite persistence, and deterministic evaluation remain authoritative.

Live `plan_ready` and `synthesis_ready` events include the routed model and active prompt ID where available. The runtime-config endpoint provides the current route/prompt configuration without requiring raw prompt persistence.

## 7. Durable LangGraph checkpoints

Production `ReadingAgentGraph` instances use a process-wide synchronous
`SqliteSaver` stored at `config/agent_checkpoints.sqlite3`. The Agent `run_id`
is also the LangGraph `thread_id`, so checkpoints from different tasks cannot
share state.

LangGraph writes a checkpoint after every completed graph node. A caller can
explicitly continue the latest checkpoint by sending the original run ID as
`resume_run_id` in the normal `/api/agent/run`, `/api/agent/run/trace`, or
WebSocket start request. Resume loads the persisted `run_id`, `trace_id`,
conversation context, route, plan, ReAct observations, tool results, evidence,
and response state. Context resolution and the advisory multi-Agent bridge are
the first two explicit graph nodes. The initial task state is checkpointed
before either runs, so an interruption inside either stage can resume safely;
nodes already completed in the previous process are not repeated.

After the WebSocket accepts a run, the desktop stores only its `run_id`,
`trace_id`, `session_id`, request number, and acceptance time in local storage.
It never duplicates the user prompt or document content there. A new desktop
runtime automatically resumes a pending record younger than 24 hours and
clears it after completion, cancellation, or a terminal backend error.

Resume is deliberately explicit:

- omitting `resume_run_id` always starts a new run;
- an unknown run ID fails with `checkpoint_not_found`;
- resuming a completed run returns its final checkpoint without executing nodes again;
- a checkpoint waiting at a read/compute node continues from that node;
- a checkpoint waiting to execute a write tool is blocked with
  `write_checkpoint_requires_manual_recovery` so a crash cannot silently replay
  a potentially completed side effect.

Checkpoint state contains task and document content and is therefore not the
redacted observability database. It remains local under the same per-user data
root as the Conversation store. Serialization uses strict msgpack module
loading without pickle fallback.

## 8. Local verification

From PowerShell:

```powershell
cd D:\AITranslator
git pull origin WebReBuild
conda activate aitrans

python -m pytest tests/agent -q
python -m pytest tests/test_ai_chat.py tests/test_ai_chat_streaming.py tests/test_ai_context_budget.py tests/test_ai_prompts.py tests/test_deepseek_provider.py -q
python -m pytest tests -q
```

Frontend:

```powershell
cd D:\AITranslator\apps\desktop
npm run lint
npm run test
npm run build
```

Tauri:

```powershell
cd D:\AITranslator
cargo check `
  --manifest-path apps/desktop/src-tauri/Cargo.toml `
  --no-default-features
```

The existing GitHub CI executes the full Python test suite, React lint/test/build, and Tauri shell check on pushes to `WebReBuild`.
