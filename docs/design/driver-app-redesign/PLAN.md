# Driver App Redesign — Plan

Status: Proposed (awaiting Stitch preview approval)
Scope: `src/webapp/app/driver`, `src/webapp/components/driver`, `src/agents/driver_agent.py`, `src/agents/tools/driver_tools.py`, `src/services/answer_formatter.py`, `db/migrations`.

## 1. Decisions (grilling log)

| # | Decision |
|---|---|
| Q1 | i18n via `next-intl`, locale stored in cookie (no URL prefix), `messages/vi.json` + `messages/en.json`, Driver routes first. |
| Q2 | Real Postgres tables (no Supabase): `driver_trips`, `trip_ratings`. Seed from HF 40k corpus (`releases_v1`). Ratings and comments are nullable. |
| Q3 | `GET /api/v1/driver/trips?cursor=&status=` returns pickup, destination, start/end time, distance, duration, fare, payment method, rating, status, linked case id. |
| Q4 | New case-less chat: `POST /api/v1/driver/chat/stream`. Agent resolves cases via `list_my_cases`. |
| Q5 | Tapping a case opens its chat thread. Auto-send "Check details of case #XXXX" only when the thread is empty. |
| Q6 | New driver tools (below), including scoped analyst evidence tools. Evidence upload deferred to phase 2. |
| Q7 | Driver answer formatter emits typed JSON blocks rendered by dedicated components, bilingual by locale. |
| Q8 | Themes: Light and Dark only. Emerald primary kept. |
| Q9 | Settings: avatar, name, email, "Manage account" (Clerk `UserProfile`), sign out, language, theme, version. |
| Q11 | "Accept violation" always requires a Yes/No confirmation, then routes to analyst. Agent never sanctions (NFR-L06-02). |
| Q12 | Accept/reject suggestion is evidence-backed and labelled advisory: final decision belongs to the analyst. No fraud verdict. |
| Q13 | Reject + Yes: statement (reason summary, tool evidence, timestamp) is submitted to the analyst queue, `dispute_status=escalated`. No: saved as draft. Shown on case timeline. |
| Q14 | Statement completeness uses a deterministic checklist in `assess_statement_completeness`: incident type + concrete description + at least one tool corroboration, or explicit "no evidence". LLM only extracts fields. |
| Q15 | Accept / Reject buttons live in a sticky action bar above the chat input. Hidden when case is closed or already submitted. |
| Q16 | Seed all 40k trips into `driver_trips`. Deterministic fixed-seed ratings: ~60% of trips rated, ~25% with comment, fraud trips skewed lower. Script `scripts/seed/seed_driver_trips.py`, idempotent. |

## 2. Information architecture

Bottom navigation, 5 tabs under `/driver`:

| Tab | Route | Content |
|---|---|---|
| Cases | `/driver/cases` | Model-detected violation cases. Card: short case id, brief title, natural-language status, relative time, response deadline. |
| Profile | `/driver/profile` | Driver identity, vehicle, 90-day scorecard (existing endpoint), rating distribution, customer feedback list. |
| GSupport | `/driver/chat`, `/driver/chat/[caseId]` | Greeting + suggestions when empty; case thread with action bar. |
| History | `/driver/history` | Trips (normal and flagged) grouped by date, monthly summary. Flagged trip links to its case. |
| Settings | `/driver/settings` | Account card, manage account, language, theme, version, sign out. |

`/driver/dispute/[caseId]` redirects to `/driver/chat/[caseId]`.

### Display rules
- Never render raw UUIDs, `trip_id`, `driver_id`. Case id shown as short code (`#` + last 4 alphanumeric chars, uppercase; last-4 avoids collisions between `case-*` ids).
- Never render internal codes (`ERR-01..03`, `AUTO_DISMISSED`, `not_disputed`, ...). Map via `lib/driver/status-copy.ts` to i18n keys with plain-language explanation and tooltip.

## 3. Chatbot

- Stack: existing `components/ai-elements/*` (shadcn AI Elements), `@ai-sdk/react` `useChat`, `streamdown`, `gsap` for greeting/suggestion entrance (gated by `prefers-reduced-motion`).
- Empty state: greeting with driver first name + 4 suggestion chips.
- Case entry: `/driver/chat/[caseId]` loads history; empty thread auto-sends the check-details message.
- Action bar: `Accept violation` / `Reject & explain`.
  - Reject: agent asks reason, calls `assess_statement_completeness` each turn, when complete shows confirmation card (Yes = submit, No = save draft).
  - Accept: confirmation card, Yes = `acknowledge_violation`.
- Confirmation cards are UI-gated: the backend mutating tools require an explicit `confirmation_token` issued by the UI click, so the LLM cannot submit on its own.

## 4. Driver tools

Existing: `get_driver_dispute_context`, `corroborate_traffic_conditions`, `fetch_corridor_historical_traffic`, `query_traffic_incident_feed`, `inspect_trip_telemetry`, `verify_exoneration_rules`, `submit_driver_statement`, `query_driver_policy`, `geocode_address`, `reverse_geocode_coordinates`, `match_trip_telemetry`.

New (all scoped to the authenticated driver's own cases/trips):

| Tool | Source | Purpose |
|---|---|---|
| `list_my_cases` | new | Case-less chat: find open/closed cases. |
| `get_case_timeline` | new | Status history and response deadline (#442). |
| `explain_case_status` | new | Plain-language status explanation (replaces raw codes). |
| `get_my_scorecard` | wraps `driver_service.get_driver_scorecard` | Rating, completion, violations. |
| `list_my_trips` / `get_trip_summary` | new on `driver_trips` | Trip history and single-trip info. |
| `check_weather_condition` | analyst tool, driver-scoped | Weather at trip time/location. |
| `check_traffic_situation` | analyst tool, driver-scoped | Live/derived traffic around trip. |
| `get_forensic_brief` | analyst tool, driver-scoped, redacted | Observed abnormalities only. |
| `suggest_dispute_path` | new | Advisory accept/reject suggestion from evidence. No verdict. |
| `assess_statement_completeness` | new, deterministic | Checklist for reject reason. |
| `acknowledge_violation` | new, confirmation-gated | Driver accepts; routes to analyst. |
| `submit_driver_statement` | existing, now confirmation-gated | Driver rejects; escalates. |
| `get_appeal_options` | new | Next steps and deadlines. |
| `request_evidence_upload` | phase 2 | Needs object storage. |

## 5. Driver answer formatter

New profile in `answer_formatter.py` (driver), output contract:

```json
{
  "markdown": "short natural-language answer",
  "blocks": [
    {"type": "case_card", "case_id": "...", "title": "...", "status_key": "..."},
    {"type": "trip_card", "trip_id": "...", "pickup": "...", "destination": "...", "fare_vnd": 85000},
    {"type": "table", "columns": ["..."], "rows": [["..."]]},
    {"type": "list", "items": [{"label": "...", "href": "case://..."}]},
    {"type": "link", "label": "...", "url": "https://..."},
    {"type": "status_pill", "status_key": "..."},
    {"type": "evidence", "items": [{"kind": "weather", "summary": "...", "source": "..."}]},
    {"type": "next_steps", "items": [{"label": "...", "prompt": "..."}]}
  ]
}
```

- Entity whitelist reused; unknown ids dropped. Raw codes stripped. Locale-aware (vi/en).
- Frontend: `components/driver/blocks/*` one component per type; `case://`/`trip://` links navigate in-app; `next_steps` chips send prompts.
- Contract added to `docs/CHAT_UI_EVENT_CONTRACT.md`.

## 6. Data

Migration `db/migrations/NNN_driver_trips_ratings.sql`:
- `driver_trips(trip_id pk, driver_id, organization_id, pickup_label, pickup_lat, pickup_lng, dropoff_label, dropoff_lat, dropoff_lng, started_at, ended_at, distance_km, duration_min, fare_vnd, payment_method, status, case_id null)`
- `trip_ratings(trip_id pk fk, stars smallint null check 1..5, comment text null, locale, created_at)`
- Indexes on `(driver_id, started_at desc)`.

## 7. Delivery slices (issues)

1. i18n foundation (`next-intl`, cookie locale, status-copy map) — frontend.
2. Driver shell: bottom nav, routes, theme (light/dark), Settings tab with sign out — frontend.
3. Cases tab redesign (no raw ids/codes) — frontend.
4. Postgres trips + ratings migration and HF seed script — backend/data.
5. Trips history API + History tab — full-stack.
6. Profile tab (scorecard + ratings + feedback API) — full-stack.
7. Driver tools expansion (scoped analyst tools + new tools) — agent.
8. Case-less chat endpoint + greeting/suggestions + case auto-send — full-stack.
9. Accept/Reject flow with confirmation-gated tools — full-stack.
10. Driver answer formatter + typed block renderers — full-stack.

Dependencies: 1 before 2,3,6; 4 before 5,6; 7 before 9; 8 and 10 independent of data slices.

## 8. Testing

TDD per slice: vitest for components/hooks, pytest unit for tools/formatter/checklist, integration for new routes against Postgres, Playwright E2E for tab navigation, sign out, auto-send, and reject-confirm flow.
