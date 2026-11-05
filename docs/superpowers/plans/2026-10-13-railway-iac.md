# Railway IaC Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate Railway dev/staging/prod + services from dashboard-managed imperative CLI to `.railway/railway.ts` IaC with saved-plan CI redeploys.

**Architecture:** Single TypeScript authoring file owns project resources (backend service + Postgres + Redis + benchmark DB + volumes). CI replaces `railway up --detach` with `config plan --out` + `apply --plan` per env. Ephemeral `pr-N` previews stay API-driven via `railway_pr.py` but get TTL cleanup + drift gate.

**Tech Stack:** Railway CLI 5.59+, `railway/iac` TS SDK, GitHub Actions self-hosted, pytest TDD boundary `tests/unit/`.

---

### Deep analyze (evidence, 2026-10-13)

- Project `caring-renewal` (`c49458fb-...`): envs dev (`e0d4551b`), staging (`4d6a870f`), production (`388f3c91`) + 7 stale ephemeral `pr-225/239/272/279/312/316/320/321` (cleanup leak).
- Services per env: `greensentinel-backend` (RAILPACK, Dockerfile `python:3.11-slim`, `uvicorn src.main:app`, sfo x1) + `Postgres` (`postgis/postgis:16-3.4-alpine` + `postgres-volume` 500MB) + `Redis` (`redis:8.2` + `redis-volume` 500MB). Dev additionally `greensentinel-benchmark-db` (`ghcr.io/railwayapp-templates/postgres-ssl:18` + 5000MB volume).
- Drift proof: `pr-312` volumes are 5000MB vs dev/prod 500MB (ephemeral duplicate-from-dev grew volumes, never reconciled).
- No `.railway/`, no `railway.toml/json` in repo. All config lives in dashboard + imperative `railway variable set` / `railway up` in `deploy-railway.yml` (`deploy-dev`, `deploy-staging`, `deploy-production`, `deploy-pr-preview`), plus `authorize_preview.sh` mutating `CLERK_AUTHORIZED_PARTIES` then full `railway up` redeploy.
- Redeploy pain: (1) no `config plan` drift detection, (2) `railway up` uploads CWD tarball per env (slow, non-hermetic), (3) `CLERK_AUTHORIZED_PARTIES` merge-append in `auth_config.py:merged_railway_origins` grows unbounded on dev, (4) PR env leak (7 stale), (5) `scripts/railway-config.ts` is a provisioning script, not IaC (uses `railway add`, `variable set`, no `defineRailway`).
- Docs checked: Railway IaC skill `iac.md` (TS GA, `railway.json/toml` deprecated, cutoff 2026-12-01, no UUIDs/domains/secrets in source, `preserve()` for secrets, `plan` before `apply`, saved-plan `plan --out` + `apply --plan` CLI 5.45.1+, `railwayapp/config` GH action for maintained CI).

### Task 1: TDD RED — IaC contract test

**Files:**
- Create: `tests/unit/test_railway_iac.py`
- Modify: none
- Test: `tests/unit/test_railway_iac.py`

- [ ] **Step 1: Write the failing test**

```python
"""Railway IaC contract: single authoring file owns project resources."""

import pathlib
import re


def test_iac_file_exists_and_is_typescript():
    p = pathlib.Path(".railway/railway.ts")
    assert p.exists(), "missing .railway/railway.ts (TS is GA; py/go are beta)"


def test_iac_defines_managed_resources():
    src = pathlib.Path(".railway/railway.ts").read_text()
    assert "defineRailway" in src
    assert "service(" in src  # greensentinel-backend
    assert "postgres(" in src
    assert "redis(" in src
    assert "DATABASE_URL" in src
    assert "REDIS_URL" in src


def test_iac_has_no_uuids_no_generated_domains_no_secrets():
    src = pathlib.Path(".railway/railway.ts").read_text()
    assert not re.search(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", src, re.I), (
        "no Railway UUIDs in source"
    )
    assert "up.railway.app" not in src, "no generated domains in source"
    for secret in ("CLERK_SECRET_KEY", "DATABASE_URL=postgres", "sk-", "RAILWAY_API_TOKEN"):
        if secret.endswith("="):
            continue
        assert secret not in src or "preserve()" in src, f"secret {secret} must use preserve()"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/test_railway_iac.py -v`
Expected: FAIL with "missing .railway/railway.ts"

- [ ] **Step 3: Commit test only (RED proof)**

```bash
git add tests/unit/test_railway_iac.py
git commit -m "test: Railway IaC contract (RED)"
```

### Task 2: TDD RED — CI redeploy contract test

**Files:**
- Create: `tests/unit/test_railway_cicd_iac.py`
- Modify: none
- Test: `tests/unit/test_railway_cicd_iac.py`

- [ ] **Step 1: Write the failing test**

```python
"""CI must redeploy via IaC saved plans, not CWD-upload railway up for persistent envs."""

import pathlib


def _read(p):
    return pathlib.Path(p).read_text()


def test_persistent_envs_use_config_apply():
    wf = _read(".github/workflows/deploy-railway.yml")
    assert "railway config plan" in wf, "CI must run config plan"
    assert "railway config apply" in wf, "CI must apply IaC plan for dev/staging/prod"


def test_no_cwd_upload_for_persistent_envs():
    wf = _read(".github/workflows/deploy-railway.yml")
    # PR previews may still upload ephemeral envs; persistent envs must not.
    for env in ("dev", "staging", "production"):
        section = wf  # coarse boundary: whole file must not contain bare up for these envs
    assert "railway up --service" not in wf or "config apply" in wf, "prefer config apply over railway up"


def test_drift_gate_exists():
    wf = _read(".github/workflows/deploy-railway.yml")
    assert "detailed-exit-code" in wf or "config plan" in wf
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/test_railway_cicd_iac.py -v`
Expected: FAIL with "CI must run config plan"

- [ ] **Step 3: Commit test only (RED proof)**

```bash
git add tests/unit/test_railway_cicd_iac.py
git commit -m "test: CI IaC redeploy contract (RED)"
```

### Task 3: Import live project to IaC (read-only)

**Files:**
- Create: `.railway/railway.ts`, `.railway/README.md` (generated), `.railway/package.json` if emitted
- Modify: none
- Test: `tests/unit/test_railway_iac.py`

- [ ] **Step 1: Link (local only, no commit of link state)**

```bash
railway link --project c49458fb-d741-468f-a3ed-d35b96788f68 --environment dev
railway config pull --omit-preserved-variables
```

Expected: creates `.railway/railway.ts` importing current graph with `preserve()` vars.

- [ ] **Step 2: Normalize to intent (no UUIDs, helpers, refs)**

Keep: `postgres("postgres")`, `redis("redis")`, `postgres("greensentinel-benchmark-db")` or `image()` for template PG, `service("greensentinel-backend", { source: github("AI20K-Build-Phase-Cohort-4/GreenSentinel", { branch: "main" }), build/start from Dockerfile, env: { DATABASE_URL: db.env.DATABASE_URL, REDIS_URL: redis.env.REDIS_URL, APP_ENV: preserve(), CLERK_* : preserve(), ... }, replicas: { sfo: 1 }, volumeMounts only for DBs })`. Delete generated domains, UUIDs, literal secrets.

- [ ] **Step 3: Plan (read-only, no apply)**

```bash
railway config plan
```

Expected: `Plan: 0 to add...` or small normalize diff, no unexpected destroys. Do NOT `apply` from agent session.

- [ ] **Step 4: Run GREEN tests**

Run: `.venv/bin/python -m pytest tests/unit/test_railway_iac.py tests/unit/test_railway_cicd_iac.py -v`
Expected: IaC test PASS, CI test still FAIL (workflows not yet updated).

### Task 4: Update CI/CD for IaC redeploys

**Files:**
- Modify: `.github/workflows/deploy-railway.yml`
- Test: `tests/unit/test_railway_cicd_iac.py`

- [ ] **Step 1: Add drift job + saved-plan redeploy per persistent env**

```yaml
jobs:
  iac-drift:
    runs-on: self-hosted
    steps:
      - uses: actions/checkout@v4
      - run: npm i -g @railway/cli
      - run: railway config plan --detailed-exit-code
```

Replace each persistent `railway up --detach` with:

```bash
railway config plan --out railway-plan.json
railway config apply --plan railway-plan.json --yes
```

Keep `railway_pr.py setup/cleanup` for ephemeral `pr-N` only. Add stale-preview cleanup (delete `pr-*` envs with no open PR). Keep `authorize_preview.sh` origin injection but follow with `config apply`, not full CWD upload.

- [ ] **Step 2: Run tests GREEN**

Run: `.venv/bin/python -m pytest tests/unit/test_railway_iac.py tests/unit/test_railway_cicd_iac.py tests/unit/test_railway_pr.py -v`
Expected: PASS all.

- [ ] **Step 3: Lint + format**

Run: `ruff check scripts/ tests/unit/test_railway_*.py && ruff format --check scripts/ tests/unit/test_railway_*.py`
Expected: PASS.

### Task 5: Verify + PR

- [ ] **Step 1: Full boundary**

Run: `bash scripts/test.sh` (unit discovery auto-includes new tests)
Expected: PASS, counts recorded.

- [ ] **Step 2: Push + PR**

```bash
git push -u origin feat/railway-iac
gh pr create --title "chore(railway): IaC dev/staging/prod + saved-plan redeploys" --body "Plan: docs/superpowers/plans/2026-10-13-railway-iac.md. Evidence: pytest ... CI: ..."
```

- [ ] **Step 3: Watch until green, fix forward**

```bash
gh pr checks <N> --watch
gh run view <failed> --log-failed | grep -E "FAIL|Error|Plan:|error" | head
```

Fix forward on same branch until all workflows PASS. Never `apply --yes --confirm-destructive` from agent without explicit plan approval.

---

## Addendum (execution findings, 2026-10-13)

- **Staging serves test fixture without token**: `GET /api/v1/me` on staging returns the `S4-RETIRE-allow` demo principal while `APP_ENV=staging` in variables -> running container predates the var fix. Fix path: redeploy staging via the new IaC pipeline (approval-gated `workflow_dispatch` on main). Guard added: persistent deploy jobs refuse `APP_ENV=test`/`TEST_AUTH_ENABLED` (test `test_persistent_envs_refuse_test_auth`).
- **Driver E2E harness fix**: post-login landing (`/workplace`) is a bare 403 for driver role with no Clerk JS, so `realApiStatus` threw "no session token". `signInWithRole` now lands each role on its authorized home (`/driver` vs `/workplace`) and waits for session hydration. Local proof: analyst/admin/driver suites pass against local backend+webapp with real Clerk UI logins; `/me` 200, 50 cases listed, workflow ask reaches validation (422 on probe body, auth+route wired).
- **Dev DB provisioning**: analyst `user_3KOf...pN` (+analyst/fraud_analyst), driver `user_3KOf...3EI` (+driver, driver entity linked), admin `user_3KOf...235` already active, all under org `018f2f4e-...` (GreenSM). Clerk org roles verified via API: driver/member/admin.
