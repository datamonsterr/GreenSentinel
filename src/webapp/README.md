# GreenSentinel webapp

Next.js/React analyst cockpit. Install with `pnpm install --frozen-lockfile`; run `pnpm dev` and point the app at the intended local API through the documented API base URL settings.

| Command | Scope |
|---|---|
| `pnpm test` | Unit/component behavior under `tests/unit/` |
| `pnpm test:typecheck` | Unit and central browser test TypeScript |
| `pnpm test:browser` | Playwright specs in repository `tests/e2e/browser/` |
| `pnpm test:e2e` | Existing CI-compatible bundle: units, test types, browser |
| `pnpm build` | Production build and app TypeScript |

Add correctly located tests; discovery runs them without editing CI or filename lists. Browser tests use their own server and an explicit fixture basemap. They do not establish live provider/basemap or hosted authentication acceptance. Run build and browser/dev server sequentially in one checkout.

Use [the repository test guide](../../docs/testing/README.md) for fixtures, TDD, integration targets and manual evidence. Active manual steps live in [docs/testing/manual/](../../docs/testing/manual/README.md).
