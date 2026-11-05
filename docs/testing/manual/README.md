# Manual verification

Use a disposable local environment or the exact deployed revision. Record revision, environment, case IDs, steps, observed results and screenshot/trace links. A fixture response, local API, isolated database and authenticated hosted session are different evidence classes.

- [Cockpit](COCKPIT.md): queue, source evidence, replay, authorization and explicit reviewer decisions.
- [Landing](LANDING.md): anonymous entry, animated mock, chapters, pause/reduced-motion, keyboard/mobile, create-org entry.
- [Generator](GENERATOR.md): dataset replay presets, seed/count/rate/duration validation, scheduled queue publication, tenant-scoped runs and durable logs.
- [Driver motivation](DRIVER_MOTIVATION.md): source-backed reward, Vietnamese narrative, Copilot consistency and fallback checks.
- [Road telemetry](ROAD_TELEMETRY.md): pinned synthetic road corpus, ingestion and playback.
- [Issue #60 runtime](ISSUE_60.md): correlated tool execution, stream telemetry and recovery checks.

Run the automated suites first using [the test guide](../README.md). Use explicit test authentication only locally; hosted checks require real analyst authentication. Do not dismiss or sanction automatically. Deferred driver workflows and broader release QA are not acceptance scope for this test-layout change.

Authentication browser checks live in `tests/e2e/browser/auth/` and run with `pnpm --dir src/webapp test:e2e:auth`. They require explicit credentials and remain separate from the default fixture browser suite; traces and screenshots stay disabled for credential protection.

- [Authentication](AUTHENTICATION.md): identity and origin checks, with optional live browser proof.
- [Deployment](DEPLOYMENT.md): environment routing and approval-gate verification.

- [OCI CI artifacts](OCI_ARTIFACTS.md): private upload/download, retention boundaries, secretless fallback and hosted storage smoke.
