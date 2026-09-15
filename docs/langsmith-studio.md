# LangSmith Studio for AITrans

AITrans exposes the production `ReadingAgentGraph` to LangSmith Studio for local graph visualization and debugging. This is a developer-only path; the normal FastAPI/Tauri startup path does not depend on Studio.

## 1. Install the Studio development dependency

From the repository root:

```powershell
cd D:\AITranslator
conda activate aitrans
python -m pip install -e ".[studio]"
langgraph --help
```

`langgraph-cli[inmem]` provides the lightweight local Agent Server used by `langgraph dev`.

## 2. Configure LangSmith access

Create a fresh LangSmith API key and expose it only to the current PowerShell process:

```powershell
$env:LANGSMITH_API_KEY="lsv2_..."
```

Do not commit the key. The repository ignores `.env` and `langgraph.json` loads that local file through:

```json
"env": ".env"
```

The recommended launcher synchronizes the current shell key into the ignored `.env` file without printing it:

```powershell
.\scripts\start_langsmith_studio.ps1
```

Use remote LangSmith tracing only when intentionally debugging non-sensitive content:

```powershell
.\scripts\start_langsmith_studio.ps1 -EnableTracing
```

Without `-EnableTracing`, the launcher writes `LANGSMITH_TRACING=false` to `.env`.

## 3. Start the local Agent Server

Recommended:

```powershell
cd D:\AITranslator
conda activate aitrans
.\scripts\start_langsmith_studio.ps1
```

If the Studio CLI is missing:

```powershell
.\scripts\start_langsmith_studio.ps1 -Install
```

The launcher sets `PYTHONUTF8=1` before spawning LangGraph. This avoids the Windows GBK decoding failure seen when `langgraph_api` reads packaged UTF-8 OpenAPI resources.

AITrans currently uses synchronous local SQLite services for Conversation persistence. LangGraph local development enables a Blockbuster guard that rejects blocking filesystem/SQLite work on the ASGI event loop. The launcher therefore starts Studio with:

```powershell
langgraph dev --allow-blocking
```

This exception is intentionally confined to the local Studio development path. It does not alter the normal FastAPI/Tauri production runtime. A future async persistence adapter could remove the need for this development flag.

The default local Agent Server is available at:

```text
http://127.0.0.1:2024
```

Open Studio:

```text
https://smith.langchain.com/studio/?baseUrl=http://127.0.0.1:2024
```

Select the `reading_agent` graph and use **Graph** mode.

## 4. What you should see

The graph topology evolves with the current Agent stage. At minimum, the production workflow remains wrapped by Conversation preparation/finalization, while newer stages may expose routing/planning/tool branches inside that boundary.

## 5. Running the graph from Studio

The public graph state is deliberately JSON-serializable. Runtime-only objects such as cancellation controls and event callbacks are passed through LangGraph runtime context and do not appear in Studio state.

For precise testing, choose **View Raw** and start with:

```json
{
  "agent_state": {
    "session_id": "studio-session",
    "user_input": "总结一下",
    "selected_text": "Bayesian optimization uses a probabilistic surrogate to select informative evaluations.",
    "browser_context": {
      "source_language": "en",
      "target_language": "zh-CN",
      "resource_title": "LangSmith Studio Sample",
      "source_kind": "desktop",
      "request_id": 1,
      "client_id": "langsmith-studio",
      "client_surface": "main"
    }
  }
}
```

The graph fills the remaining `AgentState` defaults. If the selected action needs an LLM/provider, AITrans must have the same provider credentials/configuration that the normal backend uses.

## 6. Privacy boundary

`LANGSMITH_TRACING=false` is the default launcher behavior. Do not enable remote tracing for private reading content unless you intentionally want that trace data sent to LangSmith.

The SQLite Conversation store remains the AITrans source of truth. Studio threads/checkpoints are debugging state and must not replace the production Conversation lifecycle.
