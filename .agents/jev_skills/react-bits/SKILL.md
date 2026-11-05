---
name: react-bits
description: React Bits animated UI components (text animations, backgrounds, micro-interactions) installed as owned source via CLI or copy-paste. Use when asked for animated React components, text effects, backgrounds, or React Bits install/usage.
---

# React Bits

React Bits (https://reactbits.dev) is an open-source collection of animated
React UI elements — components, text animations, backgrounds, micro-interactions.
Every component installs as source code you own, in four variants:
JS|TS x CSS|Tailwind.

## Install a component (CLI)

```bash
# shadcn (preferred) — swap SplitText for the wanted component
npx shadcn@latest add @react-bits/SplitText-TS-TW

# jsrepo alternative
npx jsrepo@latest add https://reactbits.dev/r/SplitText-TS-TW
```

Variant suffix: `-JS-CSS`, `-JS-TW`, `-TS-CSS`, `-TS-TW`.
This repo uses TypeScript + Tailwind → always pick the `-TS-TW` variant.
Component pages show the exact copy-ready command; manual copy-paste from the
docs page works too (no CLI required).

## Rules

- Install only the components actually used; keep installed source in the
  project's components directory, do not fork the whole library.
- Free registry only (`@react-bits/...`). Pro (`@reactbits-starter`,
  `@reactbits-pro`) is license-gated — never suggest Pro install commands
  without a buyer license key in `.env.local` + registries in `components.json`.
- Prefer Tailwind variants to match this repo's styling stack.
- Gate motion behind `prefers-reduced-motion` where the component supports it.
- Combine with `gsap`/`lenis` skills for scroll-linked React Bits effects;
  call `ScrollTrigger.refresh()` after mounting animated components.

## Sources

- Docs: https://reactbits.dev/get-started/installation
- Component index for agents: https://reactbits.dev/llms.txt
- Repo: https://github.com/davidhdev/react-bits
