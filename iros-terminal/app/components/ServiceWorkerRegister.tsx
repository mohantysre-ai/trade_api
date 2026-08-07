"use client";

import { useEffect } from "react";

/** Registers the lightweight service worker for Android/iOS A2HS installability. */
export default function ServiceWorkerRegister() {
  useEffect(() => {
    if (typeof window === "undefined" || !("serviceWorker" in navigator)) return;
    const ready = () => {
      navigator.serviceWorker.register("/sw.js").catch(() => {});
    };
    if (document.readyState === "complete") ready();
    else window.addEventListener("load", ready, { once: true });
    return () => window.removeEventListener("load", ready);
  }, []);
  return null;
}
