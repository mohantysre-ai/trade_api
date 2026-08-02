"use client";

import React, {
  createContext,
  useCallback,
  useContext,
  useLayoutEffect,
  useMemo,
  useState,
} from "react";

export type DeskTheme = "dark" | "light";
export type DeskFontSize = "sm" | "md" | "lg" | "xl";

type DeskPrefs = {
  theme: DeskTheme;
  fontSize: DeskFontSize;
  setTheme: (theme: DeskTheme) => void;
  toggleTheme: () => void;
  setFontSize: (size: DeskFontSize) => void;
  bumpFont: (dir: -1 | 1) => void;
};

const STORAGE_THEME = "iros-desk-theme";
const STORAGE_FONT = "iros-desk-font";
const FONT_ORDER: DeskFontSize[] = ["sm", "md", "lg", "xl"];

const DeskPrefsContext = createContext<DeskPrefs | null>(null);

function readStoredTheme(): DeskTheme {
  if (typeof window === "undefined") return "dark";
  const raw = window.localStorage.getItem(STORAGE_THEME);
  if (raw === "light" || raw === "dark") return raw;
  return window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
}

function readStoredFont(): DeskFontSize {
  if (typeof window === "undefined") return "md";
  const raw = window.localStorage.getItem(STORAGE_FONT);
  if (raw === "sm" || raw === "md" || raw === "lg" || raw === "xl") return raw;
  return "md";
}

function applyDomPrefs(theme: DeskTheme, fontSize: DeskFontSize) {
  const root = document.documentElement;
  root.setAttribute("data-theme", theme);
  root.setAttribute("data-font", fontSize);
  root.style.colorScheme = theme;
}

export function DeskPrefsProvider({ children }: { children: React.ReactNode }) {
  const [theme, setThemeState] = useState<DeskTheme>("dark");
  const [fontSize, setFontState] = useState<DeskFontSize>("md");

  useLayoutEffect(() => {
    const nextTheme = readStoredTheme();
    const nextFont = readStoredFont();
    setThemeState(nextTheme);
    setFontState(nextFont);
    applyDomPrefs(nextTheme, nextFont);
  }, []);

  const setTheme = useCallback((next: DeskTheme) => {
    setThemeState(next);
    window.localStorage.setItem(STORAGE_THEME, next);
    document.documentElement.setAttribute("data-theme", next);
    document.documentElement.style.colorScheme = next;
  }, []);

  const setFontSize = useCallback((next: DeskFontSize) => {
    setFontState(next);
    window.localStorage.setItem(STORAGE_FONT, next);
    document.documentElement.setAttribute("data-font", next);
  }, []);

  const toggleTheme = useCallback(() => {
    setThemeState((prev) => {
      const next = prev === "dark" ? "light" : "dark";
      window.localStorage.setItem(STORAGE_THEME, next);
      document.documentElement.setAttribute("data-theme", next);
      document.documentElement.style.colorScheme = next;
      return next;
    });
  }, []);

  const bumpFont = useCallback((dir: -1 | 1) => {
    setFontState((prev) => {
      const idx = FONT_ORDER.indexOf(prev);
      const next = FONT_ORDER[Math.min(FONT_ORDER.length - 1, Math.max(0, idx + dir))] ?? "md";
      window.localStorage.setItem(STORAGE_FONT, next);
      document.documentElement.setAttribute("data-font", next);
      return next;
    });
  }, []);

  const value = useMemo(
    () => ({ theme, fontSize, setTheme, toggleTheme, setFontSize, bumpFont }),
    [theme, fontSize, setTheme, toggleTheme, setFontSize, bumpFont]
  );

  return <DeskPrefsContext.Provider value={value}>{children}</DeskPrefsContext.Provider>;
}

export function useDeskPrefs() {
  const ctx = useContext(DeskPrefsContext);
  if (!ctx) {
    throw new Error("useDeskPrefs must be used within DeskPrefsProvider");
  }
  return ctx;
}
