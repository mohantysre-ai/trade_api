"use client";

/**
 * Desk motion primitives — glass + purposeful live feedback.
 * Grounded in lib/motion-tokens.ts; no data invention.
 */

import React, {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type CSSProperties,
  type ReactNode,
} from "react";
import {
  animate,
  motion,
  useMotionValue,
  useReducedMotion,
  useSpring,
} from "motion/react";
import MarketSymbolBadge from "@/app/components/MarketSymbolBadge";
import {
  deskNumClass,
  deskTransition,
  duration,
  spring,
  tickCoalesceMs,
  tilt,
} from "@/lib/motion-tokens";
import { formatDeskDelta } from "@/lib/format-delta";

export type TickDirection = "up" | "down" | "neutral";

function parseNumeric(raw: string | number | null | undefined): number | null {
  if (typeof raw === "number" && Number.isFinite(raw)) return raw;
  if (raw == null) return null;
  const cleaned = String(raw).replace(/,/g, "").match(/-?\d+(?:\.\d+)?/);
  if (!cleaned) return null;
  const n = Number(cleaned[0]);
  return Number.isFinite(n) ? n : null;
}

function formatLike(sample: string, value: number): string {
  const hasRupee = sample.includes("₹");
  const decimalsMatch = sample.replace(/,/g, "").match(/\.(\d+)/);
  const decimals = decimalsMatch ? decimalsMatch[1].length : value % 1 === 0 ? 0 : 2;
  const body = value.toLocaleString("en-IN", {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
  if (hasRupee) return `₹${body}`;
  if (sample.trim().startsWith("+") || sample.includes("%")) {
    const sign = value > 0 && sample.includes("+") ? "+" : "";
    const pct = sample.includes("%") ? "%" : "";
    return `${sign}${body}${pct}`;
  }
  return body;
}

/** Directional flash + scale pulse + tabular tween; coalesces rapid ticks. */
export function LiveTickNumber({
  value,
  className = "",
  prefix = "",
  suffix = "",
  decimals,
}: {
  value: string | number | null | undefined;
  className?: string;
  prefix?: string;
  suffix?: string;
  decimals?: number;
}) {
  const reduce = useReducedMotion();
  const display = value == null || value === "" ? "—" : String(value);
  const numeric = parseNumeric(display);
  const prevNum = useRef<number | null>(null);
  const lastFlashAt = useRef(0);
  const pendingDir = useRef<TickDirection | null>(null);
  const [flash, setFlash] = useState<TickDirection | null>(null);
  const [shown, setShown] = useState(display);
  const motionVal = useMotionValue(numeric ?? 0);
  const scale = useSpring(1, spring.snap);

  useEffect(() => {
    if (numeric == null) {
      setShown(display);
      prevNum.current = null;
      return;
    }

    const prev = prevNum.current;
    if (prev != null && prev !== numeric) {
      const dir: TickDirection = numeric > prev ? "up" : numeric < prev ? "down" : "neutral";
      const now = performance.now();
      const sinceFlash = now - lastFlashAt.current;
      const canFlash = sinceFlash >= tickCoalesceMs;

      if (canFlash) {
        lastFlashAt.current = now;
        pendingDir.current = null;
        setFlash(dir);
        if (!reduce) {
          scale.set(1.03);
          const settle = window.setTimeout(() => scale.set(1), 180);
          const clearId = window.setTimeout(() => setFlash(null), duration.flash * 1000);
          motionVal.set(prev);
          const controls = animate(motionVal, numeric, {
            ...spring.tick,
            onUpdate: (v) => {
              const sample =
                typeof value === "string"
                  ? value
                  : decimals != null
                    ? (0).toFixed(decimals)
                    : String(numeric);
              setShown(`${prefix}${formatLike(sample, v)}${suffix}`);
            },
            onComplete: () =>
              setShown(
                display.startsWith("₹") || prefix || suffix
                  ? display
                  : `${prefix}${formatLike(display, numeric)}${suffix}`,
              ),
          });
          prevNum.current = numeric;
          return () => {
            controls.stop();
            window.clearTimeout(clearId);
            window.clearTimeout(settle);
          };
        }
        setShown(display);
        prevNum.current = numeric;
        const clearId = window.setTimeout(() => setFlash(null), duration.flash * 1000);
        return () => window.clearTimeout(clearId);
      }

      // Coalesce: update displayed value without queueing another flash
      pendingDir.current = dir;
      prevNum.current = numeric;
      setShown(display);
      return undefined;
    }

    prevNum.current = numeric;
    setShown(display);
    return undefined;
  }, [display, numeric, reduce, motionVal, prefix, suffix, value, decimals, scale]);

  const flashClass =
    flash === "up"
      ? "is-tick-up"
      : flash === "down"
        ? "is-tick-down"
        : flash === "neutral"
          ? "is-tick-neutral"
          : "";

  return (
    <motion.span
      className={`desk-live-tick ${flashClass} ${deskNumClass} ${className}`.trim()}
      style={{ scale: reduce ? 1 : scale }}
    >
      {shown}
    </motion.span>
  );
}

/** Pointer-tracked tilt + soft elevation. Caps: 4°, scale 1.015. */
export function DeskCardTilt({
  children,
  className = "",
  style,
  onClick,
  role,
  tabIndex,
  onKeyDown,
  "aria-label": ariaLabel,
}: {
  children: ReactNode;
  className?: string;
  style?: CSSProperties;
  onClick?: () => void;
  role?: string;
  tabIndex?: number;
  onKeyDown?: (e: React.KeyboardEvent) => void;
  "aria-label"?: string;
}) {
  const reduce = useReducedMotion();
  const ref = useRef<HTMLDivElement>(null);
  const rotX = useSpring(0, spring.hover);
  const rotY = useSpring(0, spring.hover);
  const scale = useSpring(1, spring.hover);

  const onMove = useCallback(
    (e: React.PointerEvent) => {
      if (reduce || !ref.current) return;
      const rect = ref.current.getBoundingClientRect();
      const px = (e.clientX - rect.left) / rect.width - 0.5;
      const py = (e.clientY - rect.top) / rect.height - 0.5;
      rotY.set(px * tilt.maxDeg * 2);
      rotX.set(-py * tilt.maxDeg * 2);
    },
    [reduce, rotX, rotY],
  );

  const onEnter = useCallback(() => {
    if (reduce) return;
    scale.set(tilt.scaleHover);
  }, [reduce, scale]);

  const reset = useCallback(() => {
    rotX.set(0);
    rotY.set(0);
    scale.set(1);
  }, [rotX, rotY, scale]);

  return (
    <motion.div
      ref={ref}
      className={`desk-card-tilt ${className}`.trim()}
      style={{
        ...style,
        rotateX: reduce ? 0 : rotX,
        rotateY: reduce ? 0 : rotY,
        scale: reduce ? 1 : scale,
        transformPerspective: tilt.perspectivePx,
        transformStyle: "preserve-3d",
        willChange: reduce ? undefined : "transform",
      }}
      onPointerMove={onMove}
      onPointerEnter={onEnter}
      onPointerLeave={reset}
      onClick={onClick}
      onKeyDown={onKeyDown}
      role={role}
      tabIndex={tabIndex}
      aria-label={ariaLabel}
      whileTap={reduce ? undefined : { scale: tilt.scalePress }}
      transition={deskTransition("hover", reduce)}
    >
      {children}
    </motion.div>
  );
}

/** Score / conviction bar that fills like a gauge. */
export function DeskGaugeFill({
  pct,
  className = "",
  toneClass = "bg-emerald-500",
}: {
  pct: number;
  className?: string;
  toneClass?: string;
}) {
  const reduce = useReducedMotion();
  const clamped = Math.max(0, Math.min(100, pct));
  return (
    <div className={`h-1.5 overflow-hidden rounded-full bg-slate-100 ${className}`.trim()}>
      <motion.div
        className={`h-full rounded-full ${toneClass}`}
        initial={false}
        animate={{ width: `${clamped}%` }}
        transition={deskTransition("gauge", reduce)}
      />
    </div>
  );
}

/** IC Gate / desk decision badge — distinct moment on status change. */
export function IcStatusChip({
  status,
  children,
  className = "",
}: {
  status: string;
  children: ReactNode;
  className?: string;
}) {
  const reduce = useReducedMotion();
  const key = status.toUpperCase();
  return (
    <motion.span
      key={key}
      className={className}
      initial={reduce ? false : { scale: 0.92, opacity: 0.6 }}
      animate={{ scale: 1, opacity: 1 }}
      transition={deskTransition("snap", reduce)}
    >
      {children}
    </motion.span>
  );
}

/** Cascading list wrapper — extends desk-panel-enter with springs. */
export function DeskCascade({
  children,
  className = "",
}: {
  children: ReactNode;
  className?: string;
}) {
  const reduce = useReducedMotion();
  const items = React.Children.toArray(children);
  return (
    <div className={className}>
      {items.map((child, i) => (
        <motion.div
          key={React.isValidElement(child) && child.key != null ? String(child.key) : i}
          initial={reduce ? false : { opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{
            ...deskTransition("entrance", reduce),
            delay: reduce ? 0 : Math.min(i, 12) * 0.04,
          }}
        >
          {child}
        </motion.div>
      ))}
    </div>
  );
}

/** Macro / index tile with live val tick + optional directional update class. */
export function DeskLiveTile({
  label,
  value,
  delta,
  positive,
  accent,
  sparkline,
  tilesLive,
  tilesUpdating,
  onActivate,
}: {
  label: string;
  value: string;
  delta?: string;
  positive?: boolean;
  accent: string;
  sparkline?: ReactNode;
  tilesLive?: boolean;
  tilesUpdating?: boolean;
  onActivate: () => void;
}) {
  const prev = useRef(value);
  const [dirClass, setDirClass] = useState("");
  const lastFlashAt = useRef(0);

  useLayoutEffect(() => {
    if (prev.current === value) return;
    const a = parseNumeric(prev.current);
    const b = parseNumeric(value);
    let cls = "is-updating";
    if (a != null && b != null) {
      if (b > a) cls = "is-updating-up";
      else if (b < a) cls = "is-updating-down";
    }
    const now = performance.now();
    if (now - lastFlashAt.current >= tickCoalesceMs) {
      lastFlashAt.current = now;
      setDirClass(cls);
      const id = window.setTimeout(() => setDirClass(""), duration.flash * 1000);
      prev.current = value;
      return () => window.clearTimeout(id);
    }
    prev.current = value;
    return undefined;
  }, [value]);

  const updating = tilesUpdating || Boolean(dirClass);
  const deltaLabel = formatDeskDelta(value, delta);

  return (
    <DeskCardTilt
      className={`desk-metric-tile${tilesLive ? " is-live-tile" : ""}${updating ? ` ${dirClass || "is-updating"}` : ""}`}
      style={{ ["--tile-accent" as string]: accent }}
      onClick={onActivate}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onActivate();
        }
      }}
      tabIndex={0}
      role="link"
      aria-label={`View ${label} details`}
    >
      <div className="flex min-w-0 flex-1 items-center gap-2 z-10 overflow-hidden">
        <MarketSymbolBadge symbol={label} kind="index" size="sm" />
        <div className="flex min-w-0 flex-1 flex-col justify-center overflow-hidden">
          <span className="desk-metric-label">{label}</span>
          <LiveTickNumber value={value} className="desk-metric-value" />
          {deltaLabel != null && (
            <span className={`desk-metric-delta ${positive ? "is-up" : "is-down"}`}>
              {positive ? "↑" : "↓"} {deltaLabel}
            </span>
          )}
        </div>
      </div>
      {sparkline}
    </DeskCardTilt>
  );
}

export function useDeskReducedMotion(): boolean {
  return Boolean(useReducedMotion());
}

export { motion, useReducedMotion, animate };
