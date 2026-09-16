"use client";

import { useEffect } from "react";

/** Registers the lightweight service worker for Android/iOS A2HS installability. */
export default function ServiceWorkerRegister() {
  useEffect(() => {
    if (typeof window === "undefined" || !("serviceWorker" in navigator)) return;
    // Never cache dev chunks: a registered SW + stale HTML is exactly the
    // "module factory is not available" loop.
    if (process.env.NODE_ENV !== "production") {
      navigator.serviceWorker.getRegistrations?.()
        .then((regs) => regs.forEach((r) => r.unregister().catch(() => {})))
        .catch(() => {});
      return;
    }
    const ready = () => {
      navigator.serviceWorker
        .register("/sw.js", { updateViaCache: "none" })
        .then((registration) => registration.update())
        .catch(() => {});
    };
    if (document.readyState === "complete") ready();
    else window.addEventListener("load", ready, { once: true });
    return () => window.removeEventListener("load", ready);
  }, []);
  return null;
}
