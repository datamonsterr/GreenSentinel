# Restricted Vercel Token Deployment Tests

Scope: [issue #115](https://github.com/AI20K-Build-Phase-Cohort-4/P-063/issues/115). Use the existing restricted team/project token; do not replace it with a personal token or print credentials.

## Local regression proof

```bash
python -m pytest --confcutdir=tests/test_scripts tests/test_scripts/test_vercel_deploy.py tests/test_scripts/test_vercel_project.py tests/test_scripts/test_deployment_policy.py tests/test_scripts/test_preview_workflow.py -q
actionlint -shellcheck= .github/workflows/deploy-vercel.yml .github/workflows/deploy-railway.yml
```

Expected: submission transport errors retry finitely; authentication errors do not retry; a failed submission or non-Ready deployment never publishes a URL. REST calls carry the exact team ID, reject another project's deployment, and never call `/v2/user`. An incorrect local link fails before submission.

## Hosted PR preview

1. Open the fix PR against `main` with the existing repository secrets.
2. Confirm Railway provisions and verifies the exact PR/head deployment, then Vercel builds successfully.
3. Confirm Vercel submission finishes and project-scoped polling reports readiness without `User not found.`
4. Confirm preview authorization succeeds and the preview job publishes its URL only afterward.
5. Open the preview URL and verify `/workplace` and `/driver` respond with the expected application or protected sign-in flow. Do not disable deployment protection.
6. Record the exact commit, workflow run, preview URL, and check conclusions in the PR. Fixture tests alone do not prove restricted-token access.

## Environment aliases

After an authorized environment rollout, verify `p-063-dev.vercel.app`, `p-063-staging.vercel.app`, or `p-063.vercel.app` resolves to the newly verified deployment. An alias permission error must fail the required alias step. Dotted Dev/Staging compatibility aliases may report a warning while the canonical alias remains available. Staging and Production approval gates still apply.

The fix PR exercises Preview automatically. Dev, Staging, and Production alias changes require their normal authorized rollout; do not report those environments as tested based on Preview success alone.
