# ADR-029: Store CI artifacts in OCI Object Storage

## Status

Accepted for implementation; [issue #492](https://github.com/AI20K-Build-Phase-Cohort-4/P-063/issues/492).

## Context

GitHub artifact storage quota prevents CI diagnostics and the Next.js build transfer from completing. The repository owner selected the private OCI bucket `ai20k-github-artifacts` in `ap-singapore-1`.

## Decision

Repository composite actions archive explicit paths, upload through the S3 compatibility API, and restore them using validated tar extraction. Object keys are `<repository>/<run-id>/<artifact-name>.tar.gz`. Run attempts are deliberately absent from the common prefix so rerunning failed consumer jobs can read an earlier successful build; diagnostic names already include attempt numbers when required.

All concrete CI/CD jobs use the existing self-hosted Linux fleet, including benchmark validation and the OCI smoke. A workflow-wide regression checks runner selectors; reusable workflow calls keep their own runner declarations.

The five existing uploads (main/draft pytest diagnostics, Next.js test build, Playwright report, RAG evaluation report) and the browser build download use these actions. Hidden files require explicit opt-in. Next.js cache is excluded. Missing diagnostics warn; missing required build files and transport errors fail. Fork and Dependabot runs without secrets skip transfer; browser consumers build locally with the same isolated test environment.

## System topology and data flows

The build runner packages files, signs S3 requests with step-scoped repository secrets, and writes the private bucket. A consumer runner downloads the same run/name key and rejects absolute paths, traversal, links, and special files before extraction. The action writes a private S3 URI into the workflow summary for retrieval by an authorized operator.

This is CI infrastructure only: client → FastAPI → service → LangGraph and token streaming do not acquire storage dependencies. Runtime TypedDict schemas, graph nodes/conditional edges, agent tool contracts and HTTP rate limits are unaffected. Transfer inputs are explicit paths plus validated artifact names; shell failures propagate to the workflow.

## Rationale & Alternatives Considered

| Option | Pros | Cons | Decision |
|---|---|---|---|
| OCI private bucket and shared actions | Uses the confirmed bucket; avoids GitHub artifact quota; testable transport | Requires credentials and separate retention management | Selected |
| GitHub artifact storage | Native download UI and retention | Current quota blocks delivery | Rejected for current producers |
| Duplicate inline AWS snippets | Small initial change | Divergent layout, cleanup and safety behavior | Rejected |

## Security & Boundary Protection

Only action steps receive access and secret keys. Region, endpoint and bucket are repository variables; region/endpoint secrets remain supported. Keys are never committed, logged or embedded in object names. Ambient AWS session tokens/profiles are cleared and shared credentials files are ignored. S3 requests use path-style addressing and `WHEN_REQUIRED` checksum compatibility. Temporary AWS configuration, bootstrapped CLI environment and tar files are removed on success or failure. All archives remain private. No public URL or signed URL is emitted.

## Consequences

The GitHub artifact download UI and GitHub retention settings no longer apply. This change does not configure bucket lifecycle or enforce deletion after one or ninety days. Objects remain until an OCI lifecycle rule or authorized operator removes them. Configure lifecycle separately after reviewing shared bucket prefixes; do not apply an unreviewed bucket-wide rule. Existing GitHub artifacts are not moved or deleted. GitHub dependency/build caches remain caches.

The actions need Linux Bash, Python with tar extraction filters, and AWS CLI (the official pinned v2 Linux bundle is installed in temporary storage when absent, without Python venv/ensurepip). Local regression tests isolate AWS transport; the GitHub Actions OCI smoke forces fresh temporary CLI installation on both transfers and checks real upload/download on the existing self-hosted Linux fleet, hidden files, layout and cache exclusion. See [operations and validation](../testing/manual/OCI_ARTIFACTS.md).
