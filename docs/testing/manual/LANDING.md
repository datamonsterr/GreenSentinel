# Landing (S4-LANDING #308) — GreenSentinel

Anonymous public entry at `/`. Authed visitors redirect `/workplace`. No live tenant data on `/`; all previews synthetic mock data, zero API calls.

## Preconditions
- Revision + environment recorded (local `pnpm dev` or Vercel preview URL).
- Automated gates first: `pnpm vitest run tests/landing.test.tsx`, `pnpm lint`, `pnpm build` clean.

## Cases
### 1. Anonymous desktop
1. Open `/` signed out.
2. Expect: hero "GreenSentinel", subcopy "detect fraud earlier, process it more efficiently and improve overtime", Try live demo (`/workplace`), Create organization (`/sign-up`), See all features (`#features`), Sign in (`/sign-in`).
3. Expect: page scrolls (landing root `overflow-y-auto`); centered demo tabs (Workplace / Driver Support Agent / Test Console) above a full-width interactive mock with browser chrome `app.local/<route>`; Next button + instruction line per tab.
4. Workplace tab: full 3 panels (triage queue / evidence / copilot + decision) — click cases, press Approve / Request evidence / Sanction, sample decision records locally.
5. Driver tab: chatbot UI — type + Send (or quick reply), mock agent replies in ~1s, zero API calls.
6. Test Console tab: pick trip pattern (detour / normal / fare anomaly) → Generate case → fraud-case-opened or normal result.
7. Click Pause — mock `data-playing="false"`; Play resumes. No `<video>` elements; no "Animated preview" copy.
8. Click feature cards — navigate `/workplace`, `/driver`, `/test` (auth gate may redirect to sign-in; route itself must resolve, no 404).

### 2. Onboarding checklist
1. Scroll to `#onboarding` ("Get started in 3 quick steps").
2. Click Step 1/2/3 — illustration panel updates (org → team + first review → Test Console), CTA links `/sign-up`, `/workplace`, `/test`.
3. Copy is non-technical: create organization, add driver + first review, generate fraud/normal trips in Test Console and watch driver agent resolve.

### 3. Reduced motion
1. Enable OS reduced-motion (or DevTools rendering emulation).
2. Reload `/` — Pause toggle starts as Play (`aria-pressed="true"`), no animation running.

### 4. Keyboard
1. Tab from top: Skip to content → Features → Quick start → Sign in → Try live demo → Create organization → See all features → Pause/Play → centered tabs → Next → mock controls → cards → onboarding steps → footer Sign in.
2. All reachable, visible focus, 44px targets, Enter/Space activates.

### 5. Mobile viewport (390px)
1. No horizontal scroll; hero stacks; mock panes stack 1-col; header wraps without overlap.

### 6. Create-organization entry
1. Click Create organization → Clerk sign-up renders (no redirect loop `/`↔`/sign-up`).
2. Real-account completion (hosted only): named/imaged org creator lands as Admin (org management). Record org + run timestamp; do not use prod tenant data.

## Record
Revision, env, case IDs, pass/fail per case, screenshot/trace links. Skips explicit (e.g. real-account not run locally).
