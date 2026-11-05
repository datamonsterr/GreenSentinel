# ADR-012: Explicit chat provider selection

Date: 2026-10-02. Context: user-confirmed provider requirements, issue #88.

`LLM_MODEL` selects `gemini`, `openai` or `openrouter`; Gemini is the default in every application environment. Actual model IDs remain in provider-specific settings. A shared service resolves provider, model, credential and endpoint before constructing the SDK client. Explicit arguments/settings take precedence over environment aliases and defaults. Missing or placeholder keys fail without an embedded credential or another provider fallback.

General analyst/driver/telemetry LangChain calls and the Cockpit/Policy RAG content seam use the selected provider. Gemini uses native Google APIs; OpenAI uses its native endpoint; OpenRouter uses its configured endpoint. A small content adapter preserves existing RAG tool declarations, system instructions, text/tool response shapes and buffering behavior. Model creation is deferred so app import/health does not require chat credentials. Provider text normalization must not expose private reasoning blocks.

Provider-specific model IDs are separate from optional role overrides. Jev Decisions keeps its dedicated settings and transport; embedding/retrieval adapters retain their existing configuration. Tool authorization, source evidence, structured application responses and reviewer decision boundaries are unchanged. This decision does not add product flows, classifier calibration, or new streaming/performance architecture.

Unit and SDK/agent/API contracts verify selection, precedence, native endpoints, key isolation, tools, public text, failures and existing SSE event behavior. Synthetic credentials and mocked transport results establish code contracts, not live model quality. Optional live/hosted checks are recorded separately. See [configuration and manual verification](../testing/manual/LLM_PROVIDERS.md).
