# OCI CI artifact operations and validation

## Configuration

Repository secrets: `OCI_S3_ACCESS_KEY`, `OCI_S3_SECRET_KEY`, `OCI_REGION`, `OCI_S3_ENDPOINT`.
Repository variables: `OCI_REGION=ap-singapore-1`, `OCI_S3_ENDPOINT=https://axzzoehw5jtz.compat.objectstorage.ap-singapore-1.oraclecloud.com`, `OCI_S3_BUCKET=ai20k-github-artifacts`.

Credentials are injected only into transfer steps. The region and endpoint variables take precedence over equivalent secrets. GitHub does not supply Actions secrets to fork PR or Dependabot runs ([GitHub documentation](https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/use-secrets)); those runs skip transfers and the browser job rebuilds the test bundle locally.

All repository CI/CD jobs use the existing self-hosted Linux fleet. Workflow regression tests inspect every concrete runner selector, including benchmark validation.

## Storage contract

Objects use `s3://ai20k-github-artifacts/<owner>/<repo>/<run-id>/<name>.tar.gz`. Retry attempts share the build object key; diagnostics may put the attempt in the artifact name. Workflow summaries contain the exact private URI.

`path` accepts explicit files/directories, one per line; glob syntax is not supported. One directory stores its contents at archive root. Multiple paths preserve paths relative to their common root, including duplicate basenames in different directories. Hidden files default to excluded; the Next.js bundle opts in. Newline-separated `exclude` patterns match relative names or exact path components (`cache` excludes the build cache). `if-no-files-found` applies when no selected files remain: `error`, `warn`, or `ignore`. Existing selected files still upload when another optional report is absent.

Required download errors fail CI. Secretless skips return `downloaded=false`, which activates the consumer build fallback. Downloads reject traversal, absolute paths, symlinks, hard links and device files. Runners use temporary directories with cleanup traps.

If `aws` is missing, the action downloads the pinned official AWS CLI **2.34.56** Linux bundle for `x86_64` or `aarch64`, extracts it using Python's standard library while retaining executable permissions, and installs into the transfer's temporary directory. Python `venv`, `ensurepip`, `pip`, `unzip`, `sudo`, and global installations are not needed. Supported Linux runners require Bash, Python, curl, standard shell utilities, and glibc compatible with AWS CLI v2. Unsupported architectures, failed downloads, and installer failures stop the step and clean temporary files. An existing AWS CLI is reused by default.

The optional `force-install-cli: true` input installs the pinned CLI even if `aws` already exists. Both smoke transfers use this input to prove fresh installation and real OCI transfer rather than depending on runner state. The input never modifies a runner's installed CLI; secretless runs skip before installation. This follows AWS's [versioned bundles](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-version.html) and [installation into writable directories](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html).

## Retention and retrieval

GitHub artifact retention no longer applies. This migration neither creates an OCI lifecycle rule nor promises automatic expiration. Objects persist until separately configured bucket lifecycle or authorized deletion removes them. Configure lifecycle deliberately for the repository prefix; avoid a bucket-wide change that could affect unrelated users. The former one-day Next.js retention is not enforced by this change.

Use an authorized local AWS profile or injected credentials; never put credentials into commands or documentation:

```bash
export AWS_DEFAULT_REGION=ap-singapore-1
export AWS_REQUEST_CHECKSUM_CALCULATION=WHEN_REQUIRED
export AWS_RESPONSE_CHECKSUM_VALIDATION=WHEN_REQUIRED
aws s3 cp s3://ai20k-github-artifacts/OWNER/REPO/RUN_ID/NAME.tar.gz artifact.tar.gz \
  --endpoint-url https://axzzoehw5jtz.compat.objectstorage.ap-singapore-1.oraclecloud.com
python3 .github/actions/oci-common/archive.py extract artifact.tar.gz ./artifact
```

Keep the bucket private. S3 URIs in workflow summaries require authorization and do not provide anonymous downloads. Historical GitHub artifacts and dependency/build caches are not migrated.

## Validation

1. Run `.venv/bin/python -m pytest tests/unit/test_oci_artifacts.py tests/unit/test_cicd_efficiency.py --noconftest -q` from the repository root. Fake AWS transport exercises real action scripts, archive layout, hidden exclusion/inclusion, missing paths, duplicate basenames, rerun keys, secrets unavailable, transport/bootstrap failures, cleanup and unsafe extraction.
2. Validate action/workflow YAML and Bash syntax. Confirm no `actions/upload-artifact` or `actions/download-artifact` remains under `.github/workflows/`.
3. Open a PR changing OCI actions, the smoke workflow or regression tests. The **OCI artifact smoke** workflow uses the existing Linux `self-hosted` runner fleet. GitHub-hosted runners were blocked by account billing during migration validation. Confirm both transfer logs contain `Bootstrapping AWS CLI 2.34.56` and `aws-cli/2.34.56`, upload/download/compare steps actually run, byte comparison succeeds, `.hidden` survives, and `cache/ignored.txt` is absent. A secretless skipped transfer is not hosted OCI proof.
4. Inspect the workflow summary URI with authenticated OCI access if needed. Record run URL and commit in the PR. Do not publish secret values.
5. On a normal ready PR, confirm the browser job downloads `webapp-next` into `src/webapp/.next-gis`. On fork/Dependabot runs, confirm the local build fallback uses the same three `NEXT_PUBLIC_*` values as the producer.

The smoke is storage evidence; it does not establish application/browser correctness or deployment acceptance.
