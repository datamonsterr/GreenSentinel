# Clerk Authentication, RBAC Sync & Environment Operations Guide

## 1. Executive Summary & Root Cause Analysis

### 1.1 The "Access Denied" (HTTP 403) Failure Mechanism
When real users or newly registered accounts authenticated on the Dev or Preview webapp, the application blocked access with a 403 screen stating **"Access denied"**.

```
Browser (User Login) 
  → Clerk Session Token Issued (sub="user_3JeWYPiqOUbtpsf...", azp="https://green-sentinel-*.vercel.app")
    → Next.js Middleware (/workplace)
      → Backend Request: GET /api/v1/account/settings
        → Backend load_principal(external_subject=sub)
          → PostgreSQL SELECT app.principals WHERE external_subject = %s
            → Record NOT FOUND (None)
              → FastAPI raises 403: "Clerk user has no active assigned role"
      ← Middleware receives 403
    ← Next.js renders: new NextResponse('Access denied', { status: 403 })
```

### 1.2 Root Causes Identified
1. **Unseeded Real Clerk Accounts**: Commit `00c5049` (PR #165) enforced strict database role lookups via `load_principal`, matching only pre-seeded mock users (`user_clerk_analyst_001`..`_010`). Real Clerk users (e.g., `user_3JeWYPiqOUbtpsfCT8tKgIlPAsN`) and new registrations do not exist in `app.principals` initially.
2. **Missing Token Role Claims on New Signups**: Newly registered Clerk users have empty `public_metadata = {}` and no active organization memberships unless explicitly invited or created. Without a fallback role, they were instantly rejected.
3. **Mismatched Edge Backend Resolution**: In preview environments, `route-authorization.ts` fell back to `greensentinel-backend-production.up.railway.app`, which rejected preview origins via strict `CLERK_AUTHORIZED_PARTIES` allow-lists.

---

## 2. Architecture: JIT Principal Provisioning & Role Synchronization

### 2.1 Role Hierarchy & Mapping Contract
The system establishes a clean, unified mapping between Clerk token claims and application RBAC roles:

| Clerk Token Source | Claim Value | Mapped App Role | Effective Inherited Roles |
| :--- | :--- | :--- | :--- |
| Clerk Organization Role | `org:admin` / `admin` | `admin` | `admin`, `manager`, `analyst`, `fraud_analyst` |
| Clerk Organization Role | `org:manager` / `manager` | `manager` | `manager`, `analyst` (oversight) |
| Clerk Organization Role | `org:driver` / `driver` | `driver` | `driver` |
| Clerk Organization Role | `org:member` / `fraud_analyst` | `fraud_analyst` | `fraud_analyst`, `analyst` |
| Fallback (New Signups / Personal) | None / empty | `fraud_analyst` | `fraud_analyst`, `analyst` (safe entry) |

### 2.2 Atomic JIT Database Provisioning (`sync_clerk_principal`)
Implemented in `src/services/access_control.py`:
- On verified Clerk session requests, if `load_principal` finds no active role, `sync_clerk_principal` executes:
  ```sql
  INSERT INTO app.principals (organization_id, external_subject, display_name, status)
  VALUES (%s, %s, %s, 'active')
  ON CONFLICT (organization_id, external_subject)
  DO UPDATE SET status = 'active', display_name = EXCLUDED.display_name
  RETURNING id, organization_id;
  ```
- Assigns the mapped role into `app.principal_roles` via `ON CONFLICT (principal_id, role) DO NOTHING`.
- Eliminates the 403 lockout for all valid Clerk sessions while preserving strict PostgreSQL audit integrity.

### 2.3 Host-Aware Backend Resolution
Implemented in `src/webapp/lib/route-authorization.ts`:
- Requests originating from `*.vercel.app`, `green-sentinel-dev.vercel.app`, or `localhost` dynamically route authorization checks to `https://greensentinel-backend-dev.up.railway.app` (or the PR's scoped ephemeral Railway backend via `API_BASE_URL`), preventing fallback to the isolated production backend.

---

## 3. Clerk Instances & Preview Environments

### 3.1 Instance Topology
Clerk provides two distinct instance types:

```
┌────────────────────────────────────────────────────────┐
│                   CLERK APPLICATION                    │
├───────────────────────────┬────────────────────────────┤
│   DEVELOPMENT INSTANCE    │    PRODUCTION INSTANCE     │
│   (clever-turtle-156.dev) │    (e.g., green-sentinel.vercel.app)│
├───────────────────────────┼────────────────────────────┤
│ • Keys: pk_test_*, sk_test│ • Keys: pk_live_*, sk_live │
│ • Cross-domain auth with  │ • Strict single-domain     │
│   localhost & *.vercel.app│   security posture         │
│ • Uses __clerk_db_jwt     │ • Does NOT allow wildcard  │
│ • Capped at 100 users     │   *.vercel.app origins     │
│ • Targets: Local, Dev,    │ • Targets: Production apex │
│   PR Previews             │   domain ONLY              │
└───────────────────────────┴────────────────────────────┘
```

### 3.2 Preview Environment Rule (Critical)
> **Official Clerk Architecture**: You **cannot** use Clerk Production API keys (`pk_live_...`) with your host's generated preview domains (`*.vercel.app`).
> 
> Preview environments must use **Development API keys** (`pk_test_...` and `sk_test_...`).
> 
> Because each Vercel preview receives a unique sub-origin (e.g. `green-sentinel-xyz.vercel.app`), only Clerk Development instances permit cross-origin session synchronization via `<slug>.accounts.dev`.

### 3.3 Dynamic Preview Authorization on Railway
In `.github/workflows/deploy-vercel.yml` and `scripts/authorize_preview.sh`:
- Every PR preview automatically deploys an ephemeral or scoped Railway backend.
- The step `Authorize exact Vercel preview origin` invokes `scripts/authorize_preview.sh`, dynamically appending the generated Vercel preview URL (`https://green-sentinel-*.vercel.app`) to `CLERK_AUTHORIZED_PARTIES` on Railway.

---

## 4. Clerk Dashboard & Operator Guide

### 4.1 Provisioned Roles on Clerk Instance
The four core RBAC roles are provisioned on Clerk instance `clever-turtle-156`:
1. **Admin (`org:admin`)**: Full privileges, org management, member administration, admin settings.
2. **Manager (`org:manager`)**: Case escalation management, supervisor review, and analytics.
3. **Driver (`org:driver`)**: Driver portal, case disputes, telemetry.
4. **Member (`org:member`)**: Fraud analyst investigation cockpit and dispute resolution.

### 4.2 How to Onboard & Invite Team Members (Email & OTP)

#### Method A: Via In-App Organization Switcher (Recommended)
1. Log in to the application at `https://green-sentinel-dev.vercel.app` (or local/preview).
2. Look at the top-right header: you will see Clerk's `<OrganizationSwitcher />` next to `<UserButton />`.
3. Click the Organization Switcher -> click **"Manage organization"** (or gear icon).
4. Click **Members** -> click **"Invite"**.
5. Enter the invitee's email address and select their Role:
   - **Admin**: Full access.
   - **Manager**: Supervisor review.
   - **Driver**: Driver dispute flows.
   - **Member**: Fraud Analyst (default).
6. Click **"Send invitation"**.
7. The user receives an email containing a secure link. Upon accepting and verifying via OTP/Google OAuth, they immediately enter the workplace with the corresponding RBAC permissions.

#### Method B: Via Clerk Dashboard
1. Open the [Clerk Dashboard](https://dashboard.clerk.com).
2. Select your application instance (`clever-turtle-156`).
3. In the sidebar, navigate to **Organizations**.
4. Select the target organization (e.g., `Hihi`, `GreenSentinel Operations`).
5. Click the **Members** tab.
6. Click **"Invite member"** (top right).
7. Enter email address, choose the Role (`Admin`, `Manager`, `Driver`, or `Member`), and submit.

### 4.3 Assigning Roles to Standalone Users (Outside Organizations)
If a user signs in without creating or joining an organization:
1. Open [Clerk Dashboard](https://dashboard.clerk.com) -> **Users**.
2. Click on the user's name or ID.
3. Scroll down to **Metadata** -> click edit under **Public metadata**.
4. Add the `roles` array:
   ```json
   {
     "roles": ["manager"]
   }
   ```
5. Click **Save**. The backend will read `public_metadata.roles` on their next session token refresh and sync their role.

---

## 5. Verification Checklist & Operations Runbook

| Step | Action | Expected Output | Status |
| :--- | :--- | :--- | :--- |
| 1 | Canonical dev domain updated | `https://green-sentinel-dev.vercel.app` configured in Vercel & Railway | Verified (PR #183 merged) |
| 2 | Railway dev backend | `https://greensentinel-backend-dev.up.railway.app/health` returns `status: ok` | Verified |
| 3 | Scoped PR preview backend | `https://greensentinel-backend-pr-184.up.railway.app/health` returns `status: ok` | Verified |
| 4 | Atomic JIT Sync | Non-seeded Clerk accounts auto-create in `app.principals` on login | Implemented (PR #184) |
| 5 | RBAC Roles on Clerk | `org:admin`, `org:manager`, `org:driver`, `org:member` exist | Verified in Clerk API |
| 6 | In-App Org Switcher | Header provides `<OrganizationSwitcher />` without manual role dropdown | Implemented (PR #184) |
| 7 | Preview Auth | `CLERK_AUTHORIZED_PARTIES` dynamically set per PR preview | Configured in CI/CD |
