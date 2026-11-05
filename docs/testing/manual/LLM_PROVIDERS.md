# LLM provider configuration and verification

`LLM_MODEL` is a provider selector, not a model ID. Default: `gemini`. Configure credentials in an ignored local `.env` or deployment secret settings; do not paste key values into recorded commands or logs. Restart the backend after configuration changes. `LLM_TEMPERATURE` applies where the chosen model supports it; the installed SDK reports fixed sampling defaults for Gemini 3.5 Flash-Lite.

| Selector | Model setting | Credential | Transport |
|---|---|---|---|
| `gemini` | `GEMINI_MODEL` | `GEMINI_API_KEY` (`GOOGLE_API_KEY` alias) | Native Gemini Developer API |
| `openai` | `OPENAI_MODEL` (`MODEL_NAME` compatibility) | `OPENAI_API_KEY` | Native OpenAI API |
| `openrouter` | `OPENROUTER_MODEL` | `OPENROUTER_API_KEY` | `OPENROUTER_BASE_URL` |

Optional `DRIVER_AGENT_MODEL` overrides the selected provider's model for the driver role; leave it unset to inherit. Jev Decisions uses its dedicated `PROJECT_JEV_*`/`JEV_*` settings, independently of general chat selection. Do not configure a provider-prefixed OpenRouter model ID as a native Gemini model.

Run provider contract tests with `.venv/bin/python -m pytest tests/unit/services/ -q`. Those tests use synthetic credentials and controlled SDK boundaries. App startup/health must work without model credentials; chat then reports unavailable/falls back to retrieved facts safely, without calling another provider.

For optional live verification, use an isolated API/database and legitimately configured provider key:

1. Set one selector and its model/key. Check `/health`, then open the existing case cockpit.
2. Ask a source-backed case/policy question. Confirm tool execution, public answer/citations and existing SSE completion; no private reasoning or new automatic case action is exposed.
3. Repeat independently for each configured provider. Confirm model/provider identity in controlled operator diagnostics and keep credential values out of artifacts.
4. Remove the selected key or use a documented placeholder. Confirm an unavailable state without a request to a different provider.
5. Verify an explicit role model override and confirm Jev Decisions/embedding configuration remains independent.

Record revision, provider/model, environment, request/case IDs, actual results and sanitized artifacts. Mark unavailable credentials as an unverified optional live check. Mocked SDK contracts, local API, real provider calls and authenticated hosted browser acceptance are separate evidence.

Primary references: [LangChain Google](https://docs.langchain.com/oss/python/integrations/chat/google_generative_ai), [Gemini models](https://ai.google.dev/gemini-api/docs/models), and [provider architecture](../../architecture/adr-012-llm-provider-selection.md).
