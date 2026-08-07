"use client";

import React, { useEffect, useState } from "react";
import { useDeskPrefs, type DeskFontSize, type DeskTheme } from "./DeskPrefsProvider";

const FONT_LABEL: Record<DeskFontSize, string> = {
  sm: "A−",
  md: "A",
  lg: "A+",
  xl: "A++",
};

export default function DeskControls({
  clockLabel,
  feedStatus,
}: {
  clockLabel: string;
  feedStatus: string;
}) {
  const {
    theme,
    fontSize,
    performanceMode,
    setTheme,
    bumpFont,
    setFontSize,
    togglePerformanceMode,
  } = useDeskPrefs();
  const [liveClock, setLiveClock] = useState(clockLabel);

  useEffect(() => {
    setLiveClock(clockLabel);
  }, [clockLabel]);

  useEffect(() => {
    const id = window.setInterval(() => {
      setLiveClock(new Date().toLocaleTimeString("en-IN", { hour12: false }));
    }, 1000);
    return () => window.clearInterval(id);
  }, []);

  const feedLive = feedStatus === "live";
  const feedLoading = feedStatus === "loading";
  const breatheClass = feedLive
    ? "desk-breathe-dot"
    : feedLoading
      ? "desk-breathe-dot is-warn"
      : "desk-breathe-dot is-error";

  return (
    <div
      className="desk-controls flex flex-nowrap items-center gap-1.5 overflow-x-auto desk-scroll-x max-w-full"
      role="group"
      aria-label="Display controls"
    >
      <div className="desk-live-chip shrink-0" title={`Feed ${feedStatus}`} suppressHydrationWarning>
        <span className={breatheClass} aria-hidden />
        <span className="desk-live-label">{feedLive ? "LIVE" : feedStatus.toUpperCase()}</span>
        <span className="desk-live-clock tabular-nums hidden min-[420px]:inline" suppressHydrationWarning>
          {liveClock} IST
        </span>
      </div>

      <div className="desk-seg shrink-0" role="group" aria-label="Theme">
        <button
          type="button"
          className={theme === "dark" ? "is-on" : undefined}
          aria-pressed={theme === "dark"}
          onClick={() => setTheme("dark" as DeskTheme)}
          title="Dark background · light text"
        >
          Dark
        </button>
        <button
          type="button"
          className={theme === "light" ? "is-on" : undefined}
          aria-pressed={theme === "light"}
          onClick={() => setTheme("light" as DeskTheme)}
          title="Light background · dark text"
        >
          Light
        </button>
      </div>

      <div className="desk-seg shrink-0" role="group" aria-label="Font size">
        <button type="button" onClick={() => bumpFont(-1)} title="Smaller text" aria-label="Decrease font size">
          −
        </button>
        <button
          type="button"
          className="is-on desk-font-indicator"
          title={`Font size ${fontSize}`}
          onClick={() => {
            const order: DeskFontSize[] = ["sm", "md", "lg", "xl"];
            const i = order.indexOf(fontSize);
            setFontSize(order[(i + 1) % order.length]);
          }}
        >
          {FONT_LABEL[fontSize]}
        </button>
        <button type="button" onClick={() => bumpFont(1)} title="Larger text" aria-label="Increase font size">
          +
        </button>
      </div>

      <div className="desk-seg shrink-0" role="group" aria-label="Performance">
        <button
          type="button"
          className={performanceMode ? "is-on" : undefined}
          aria-pressed={performanceMode}
          onClick={togglePerformanceMode}
          title="Drop blur and ambient motion for long sessions"
        >
          Perf
        </button>
      </div>
    </div>
  );
}
