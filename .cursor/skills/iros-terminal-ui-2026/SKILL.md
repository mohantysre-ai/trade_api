---
name: iros-terminal-ui-2026
description: >-
  Apply modern 2026 desk UI/UX and motion to iros-terminal while preserving
  Bloomberg-like institutional density. Use when restyling panels, cards,
  drawers, tabs, or micro-interactions in the frontend only — never change
  backend logic or invent data.
---

# IROS Terminal UI 2026

Installed companions (read when relevant):

| Skill | Path |
|-------|------|
| UI Design Brain | `.cursor/skills/ui-design-brain/` |
| Animation / Motion | `.cursor/skills/animation-motion-design/` |
| Frontend Design | `.cursor/skills/frontend-design/` |
| Desk standards | `.cursor/skills/iros-hedge-fund-terminal-standards/` |

## Visual direction

- **Enterprise / data dashboard** density (ui-design-brain preset), not marketing SaaS.
- Single accent: cyan/teal (`--terminal-cyan`). No purple gradients, no emoji chrome.
- Dark glass panels over `#060d18` canvas; light utility classes are remapped in `globals.css`.
- Motion: CSS only (`transform` / `opacity`), tokens `--ease-out-strong`, `--ease-drawer`, `--dur-*`.
- Always honor `prefers-reduced-motion`.

## Where styles live

1. `iros-terminal/app/globals.css` — design tokens, panel remaps, drawer, tabs, keyframes
2. Component classNames — structural only; prefer inheriting desk surfaces
3. Inline gradient helpers in `page.tsx` (`deskGlass`) for metric tiles

## Do not

- Change FastAPI / snapshot / scoring logic
- Add Framer Motion unless explicitly requested (CSS is enough)
- Invent metrics or verdicts for empty states
