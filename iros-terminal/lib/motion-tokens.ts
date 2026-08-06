/**
 * IROS desk motion vocabulary — Stage A.
 *
 * Single source for springs, timing, easing, live-tick feedback, and tilt caps.
 * CSS mirrors live under `--motion-*` / extended `--dur-*` / `--ease-*` in globals.css.
 *
 * Repo map (requested names → actual surfaces):
 *   MarketMovers.jsx        → ForensicPanel BUY cards + page.tsx desk-metric-tile grids
 *   NewsWire.jsx            → NewsFeedPanel (page.tsx) + AITickerNewsPanel
 *   MarketIndicesDashboard  → GlobalIndicesGrid / India macros / Nifty100HeatMap (page.tsx)
 *   RightDrawer.tsx         → app/components/RightDrawer.tsx (CSS drawer → spring in Stage C)
 *
 * Accent: keep cyan terminal shell; marigold #E2A33D is the secondary live accent
 * (confidence / IC attention), not a competing theme.
 */

import type { Transition, Variants } from "motion/react";

/** Brand accents that motion may tint — never invent data colors beyond these. */
export const deskMotionColor = {
  marigold: "#E2A33D",
  cyan: "#22D3EE",
  up: "#34D399",
  down: "#F87171",
  canvas: "#07111F",
} as const;

/** Duration scale (seconds). Prefer these over ad-hoc ms. */
export const duration = {
  /** Price / score digit tween — must stay readable every frame */
  tick: 0.38,
  /** Directional flash behind a changed figure (~600ms wash) */
  flash: 0.6,
  /** Sparkline stroke draw-in on first paint */
  sparkDraw: 1.3,
  /** Cascading panel / list entrance (matches desk-fade-up) */
  entrance: 0.45,
  /** Soft collapse / color settle */
  settle: 0.28,
  /** Drawer / sheet (CSS fallback; spring preferred) */
  drawer: 0.32,
  /** Confidence gauge fill */
  gauge: 0.7,
  /** IC Gate flip highlight */
  gateFlip: 0.5,
} as const;

/** Cascading entrance stagger (ms) — mirrors .desk-panel-enter / news-card nth-child. */
export const stagger = {
  stepMs: 40,
  newsStepMs: 40,
  maxTracked: 12,
} as const;

/** Coalesce rapid LTP ticks — skip flash queue if updates arrive faster than flash window. */
export const tickCoalesceMs = Math.round(duration.flash * 1000);

/**
 * Spring physics for Motion — physical, interruptible.
 * Named for intent, not component.
 */
export const spring = {
  /** Number / KPI settle after a live tick */
  tick: { type: "spring", stiffness: 460, damping: 38, mass: 0.72 } satisfies Transition,
  /** Card hover lift / tilt return */
  hover: { type: "spring", stiffness: 380, damping: 28, mass: 0.85 } satisfies Transition,
  /** Drawer / panel slide */
  drawer: { type: "spring", stiffness: 360, damping: 34, mass: 0.95 } satisfies Transition,
  /** Soft list / cascade children */
  entrance: { type: "spring", stiffness: 320, damping: 30, mass: 1 } satisfies Transition,
  /** Snappy IC Gate / badge flip */
  snap: { type: "spring", stiffness: 520, damping: 36, mass: 0.7 } satisfies Transition,
  /** Gauge / barGrow fill (slightly underdamped) */
  gauge: { type: "spring", stiffness: 240, damping: 26, mass: 1 } satisfies Transition,
} as const;

/** Cubic-bezier curves shared with CSS `--ease-*`. */
export const ease = {
  outStrong: [0.16, 1, 0.3, 1] as const,
  drawer: [0.32, 0.72, 0, 1] as const,
  collapse: [0.4, 0, 0.2, 1] as const,
  /** Linear for sparkline dashoffset only */
  linear: "linear" as const,
};

/**
 * Pointer tilt — terminal depth, not a game.
 * Cap 3–5°; scale ≤ 1.02.
 */
export const tilt = {
  maxDeg: 4,
  scaleHover: 1.015,
  scalePress: 0.995,
  perspectivePx: 920,
  shadowRest: "0 10px 28px rgba(0,0,0,0.28), inset 0 1px 0 rgba(255,255,255,0.04)",
  shadowLift:
    "0 18px 40px rgba(0,0,0,0.42), 0 0 0 1px color-mix(in srgb, var(--terminal-marigold, #E2A33D) 22%, transparent), inset 0 1px 0 rgba(255,255,255,0.06)",
} as const;

/** Live tick flash — directional wash behind the changed number. */
export const tickFlash = {
  up: "color-mix(in srgb, var(--terminal-green) 32%, transparent)",
  down: "color-mix(in srgb, var(--terminal-red) 32%, transparent)",
  neutral: "color-mix(in srgb, var(--terminal-marigold, #E2A33D) 22%, transparent)",
  durationSec: duration.flash,
} as const;

/** Opacity-only fallbacks when prefers-reduced-motion is on. */
export const reduced = {
  transition: { duration: 0.01 } satisfies Transition,
  fade: {
    initial: { opacity: 0 },
    animate: { opacity: 1 },
    exit: { opacity: 0 },
    transition: { duration: 0.12 },
  },
} as const;

/** Cascading entrance variants — extends .desk-panel-enter / desk-fade-up. */
export const cascadeVariants: Variants = {
  hidden: { opacity: 0, y: 12 },
  show: (i: number) => ({
    opacity: 1,
    y: 0,
    transition: {
      ...spring.entrance,
      delay: Math.min(i, stagger.maxTracked) * (stagger.stepMs / 1000),
    },
  }),
};

export const cascadeReduced: Variants = {
  hidden: { opacity: 0 },
  show: { opacity: 1, transition: reduced.transition },
};

/** Drawer slide — Stage C will replace CSS transform with these. */
export const drawerVariants: Variants = {
  closed: { x: "100%" },
  open: { x: 0, transition: spring.drawer },
};

export const drawerReduced: Variants = {
  closed: { opacity: 0 },
  open: { opacity: 1, transition: { duration: 0.12 } },
};

/** CSS duration strings for non-Motion call sites. */
export const cssDuration = {
  tick: `${duration.tick}s`,
  flash: `${duration.flash}s`,
  sparkDraw: `${duration.sparkDraw}s`,
  entrance: `${duration.entrance}s`,
  settle: `${duration.settle}s`,
  drawer: `${duration.drawer}s`,
  gauge: `${duration.gauge}s`,
  gateFlip: `${duration.gateFlip}s`,
  fast: "160ms",
  med: "280ms",
} as const;

/**
 * Pick spring vs reduced transition.
 * Pass `useReducedMotion()` result from motion/react.
 */
export function deskTransition(
  name: keyof typeof spring,
  reduceMotion: boolean | null | undefined,
): Transition {
  if (reduceMotion) return reduced.transition;
  return spring[name];
}

export function deskCascadeVariants(reduceMotion: boolean | null | undefined): Variants {
  return reduceMotion ? cascadeReduced : cascadeVariants;
}

export function deskDrawerVariants(reduceMotion: boolean | null | undefined): Variants {
  return reduceMotion ? drawerReduced : drawerVariants;
}

/** Tabular / mono utility for prices & scores mid-tween. */
export const deskNumClass =
  "font-mono tabular-nums tracking-tight [font-variant-numeric:tabular-nums]";
