---
description: "Frontend standards for React, Next.js, SSE streaming integration, Tailwind CSS, and UI components"
activation: model_decision
---

# Frontend & UI Engineering Guidelines

## 1. Architecture & Framework
- Modern React / Next.js with TypeScript and App Router.
- Tailwind CSS for responsive, utility-first styling.
- Clean separation between presentation components, state hooks, and API clients.

## 2. SSE Stream Ingestion
- Connect to backend `/api/v1/chat/stream` using `fetch` with `ReadableStream` or `EventSource`.
- Handle chunk decoding (`TextDecoder`), parse SSE data frames (`data: {...}`), and update chat state incrementally.
- Provide explicit visual states: Idle, Streaming, Completed, Error.

## 3. UI Design Standards
- Generate only the actual interface components; do not wrap mockups in external device frames (laptops, phones) unless requested.
- Ensure accessible color contrast, keyboard navigability, and clear loading/disabled states for buttons.
- Responsive layout supporting both desktop and mobile viewports.
- Progressive disclosure for metrics: do not display static, redundant metric title labels; show direct values/pills and provide contextual explanations via interactive hover tooltips (`title` attribute / tooltip components). Use collapsible toggle boxes with dropdown icons for multi-metric panels.

## 4. Stitch CLI (no Stitch MCP)
- No Stitch MCP server is configured in any harness. Generate/import screens with the Stitch CLI instead:
  - Install: `npm install -g @google/stitch` (Node.js 20+), then `stitch login`.
  - Generate: `stitch create project --title "<App>"`, `stitch generate screen --device DESKTOP --prompt "<screen>"`, preview with `stitch serve`.
  - Variants: `stitch generate variants --creative-range REFINE|EXPLORE|REIMAGINE`.
  - Agent skills: `stitch agent-skills add --user` (installs `/stitch` for Claude Code, Cursor, Codex, Gemini CLI, Antigravity).
- Workflow: generate screen → iterate variants → freeze visual rules in `DESIGN.md` → implement pages against `DESIGN.md` → verify in browser.

## 5. Motion & Component Stack (gsap + lenis + react-bits)
- Packages (in `src/webapp/package.json`): `gsap` (animation, ScrollTrigger), `lenis` (smooth scroll). Install: `pnpm --prefix src/webapp add gsap lenis`.
- Skills (in `.agents/jev_skills/`): `gsap-*` (official GreenSock skills: core, timeline, scrolltrigger, react, performance), `lenis` (smooth-scroll setup + GSAP sync), `react-bits` (copy-paste animated components via `npx shadcn@latest add @react-bits/<Comp>-TS-TW` or jsrepo), `scrollytelling` (pinned sections, progressive reveals, narrative scroll).
- Canonical Lenis + ScrollTrigger sync:
  ```ts
  import Lenis from 'lenis';
  import { gsap } from 'gsap';
  import { ScrollTrigger } from 'gsap/ScrollTrigger';
  gsap.registerPlugin(ScrollTrigger);
  const lenis = new Lenis({ autoRaf: true });
  lenis.on('scroll', ScrollTrigger.update);
  gsap.ticker.add((time) => lenis.raf(time * 1000));
  gsap.ticker.lagSmoothing(0);
  ```
  Import `lenis/dist/lenis.css`. Honor `prefers-reduced-motion` (Lenis does by default; gate GSAP timelines behind the same media query).
- React: use `@gsap/react` `useGSAP` with a scope ref; always `ScrollTrigger.refresh()` after layout changes and revert context on unmount.

## 6. Chat UI & Domain Separation
- Separate Driver GSupport UI (`/driver`) and Analyst Cockpit UI (`/workplace`): do not artificially couple or force shared monolithic widgets across divergent operational domains.
- Replicate and adapt domain-tailored chat components (Map preview, Thinking/Tool traces, RAG policy highlights) to maintain independent velocity and domain autonomy.
- **Cockpit Decision Rationale Box (`aria-label="Decision rationale"`)**: Pre-populate with the objective `forensic_brief.summary_text` aggregated from case telemetry/features/guardrails on case selection, summarizing only observed abnormalities without faked metrics or case judgments.

