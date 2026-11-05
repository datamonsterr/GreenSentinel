---
name: lenis
description: Smooth-scroll library (Lenis) setup, options, and GSAP ScrollTrigger sync for React/Next.js. Use when asked for smooth scrolling, Lenis config, scroll sync with GSAP, anchor handling, or nested-scroll prevention.
---

# Lenis smooth scroll

Lenis ("smooth" in latin) is a lightweight, dependency-free smooth-scroll library
by darkroom.engineering. Runs on native scroll, so `position: sticky`, anchor
links, and accessibility keep working.

## Install

```bash
pnpm --prefix src/webapp add lenis
```

```ts
import Lenis from 'lenis';
import 'lenis/dist/lenis.css';
```

## Basic setup (auto RAF loop)

```ts
const lenis = new Lenis({ autoRaf: true });
lenis.on('scroll', (e) => console.log(e));
```

Custom RAF loop:

```ts
const lenis = new Lenis();
function raf(time: number) {
  lenis.raf(time);
  requestAnimationFrame(raf);
}
requestAnimationFrame(raf);
```

## GSAP ScrollTrigger sync (canonical)

```ts
import { gsap } from 'gsap';
import { ScrollTrigger } from 'gsap/ScrollTrigger';
gsap.registerPlugin(ScrollTrigger);

const lenis = new Lenis();
lenis.on('scroll', ScrollTrigger.update);
gsap.ticker.add((time) => lenis.raf(time * 1000));
gsap.ticker.lagSmoothing(0);
```

After DOM/layout changes: `ScrollTrigger.refresh()`.

## Key options

- `duration` (default 1.2s) or `lerp` (default 0.1) — pick one style.
- `anchors: true` — smooth anchor-link scrolling (`scrollTo` options allowed).
- `allowNestedScroll: true` — simplest nested-scroll handling (costs a DOM-tree
  check per scroll event); or set `data-lenis-prevent` on the nested element.
- `smoothWheel: true` (default), `orientation: 'vertical'|'horizontal'`.
- `respectReducedMotion` (default true) — honors `prefers-reduced-motion`;
  keep it on.

## Methods / events

- `lenis.scrollTo(target, options)` — target is pixels | selector | element
  (`top|bottom|start|end` keywords); options: `offset`, `lerp|duration|easing`,
  `immediate`, `lock`, `force`, `onComplete`.
- `lenis.start()` / `lenis.stop()` / `lenis.destroy()` / `lenis.resize()`.
- Events: `scroll` (instance), `virtual-scroll` (`{deltaX, deltaY, event}`).

## Limits

- No CSS scroll-snap support (use the `lenis/snap` package).
- Capped at 60fps on Safari; smooth scroll stops over iframes.
- Source: https://github.com/darkroomengineering/lenis
