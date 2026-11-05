# Provider tool-schema verification

Issue #118 repairs the shared native-content path used by OpenAI and OpenRouter. The original adapter exported Google schema types such as `OBJECT` and `STRING`, which are invalid JSON Schema types. The minimal repair exports JSON with aliases and applies the existing type normalizer only to non-Gemini parameters. Native Gemini requests and raw tool arguments remain unchanged.

The worker reproduced two failures at the actual SDK request boundary, then observed both passing after the repair. The conductor independently ran the provider/SDK/policy suite: **67 tests passed**. Outgoing OpenAI and OpenRouter parameters are checked with `Draft202012Validator.check_schema`; nested types, required camel-case property names, `additionalProperties`, and enum values are independently asserted. Real SDK serialization uses mocked HTTP transport and synthetic keys, not live-provider or hosted proof.

Ruff and whitespace checks passed. Current-head CI and final merge revision are recorded in the issue and PR. This change introduces no workflow YAML, model-selection, authorization or UI changes.
