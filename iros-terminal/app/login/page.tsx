'use client';

import { FormEvent, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";

type Mode = "login" | "register";

export default function LoginPage() {
  const router = useRouter();
  const params = useSearchParams();
  const [mode, setMode] = useState<Mode>("login");
  const [identifier, setIdentifier] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      const res = await fetch(mode === "login" ? "/api/auth/login" : "/api/auth/register", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ identifier, password }),
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(body?.detail || (mode === "login" ? "Sign in failed." : "Registration failed."));
      }
      if (mode === "register") {
        setMessage("Account request submitted. Access will remain locked until the administrator approves it.");
        setMode("login");
        setPassword("");
        return;
      }
      const next = params.get("next");
      router.replace(next && next.startsWith("/") ? next : "/");
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Request failed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="min-h-[100dvh] bg-[#071111] text-slate-100 flex items-center justify-center px-4 py-8 relative overflow-hidden">
      <div className="absolute inset-0 opacity-70 pointer-events-none" style={{
        background:
          "radial-gradient(circle at 18% 20%, rgba(16,185,129,.18), transparent 30%), radial-gradient(circle at 82% 18%, rgba(34,211,238,.13), transparent 28%), linear-gradient(180deg,#071111 0%,#0b1718 100%)",
      }} />
      <section className="relative w-full max-w-md rounded-[28px] border border-white/10 bg-white/[0.055] p-6 sm:p-8 shadow-2xl backdrop-blur-xl">
        <div className="mb-7">
          <div className="inline-flex items-center gap-2 rounded-full border border-emerald-400/20 bg-emerald-400/10 px-3 py-1 text-[10px] font-black uppercase tracking-[0.18em] text-emerald-300">
            Private terminal
          </div>
          <h1 className="mt-4 text-3xl font-black tracking-tight text-white">Alphix Terminal</h1>
          <p className="mt-2 text-sm leading-relaxed text-slate-400">
            Restricted market intelligence. New accounts require administrator approval before any terminal content is accessible.
          </p>
        </div>

        <div className="mb-5 grid grid-cols-2 gap-1 rounded-xl border border-white/10 bg-black/20 p-1">
          <button
            type="button"
            onClick={() => { setMode("login"); setError(null); setMessage(null); }}
            className={`rounded-lg px-3 py-2.5 text-xs font-black uppercase tracking-wider transition ${mode === "login" ? "bg-white text-slate-900" : "text-slate-400 hover:text-white"}`}
          >
            Sign in
          </button>
          <button
            type="button"
            onClick={() => { setMode("register"); setError(null); setMessage(null); }}
            className={`rounded-lg px-3 py-2.5 text-xs font-black uppercase tracking-wider transition ${mode === "register" ? "bg-white text-slate-900" : "text-slate-400 hover:text-white"}`}
          >
            Request access
          </button>
        </div>

        <form onSubmit={submit} className="space-y-4">
          <label className="block">
            <span className="mb-1.5 block text-[11px] font-bold uppercase tracking-wider text-slate-400">Email or phone</span>
            <input
              value={identifier}
              onChange={(e) => setIdentifier(e.target.value)}
              autoComplete="username"
              required
              placeholder="you@example.com or +91..."
              className="w-full rounded-xl border border-white/10 bg-black/25 px-4 py-3 text-sm text-white outline-none placeholder:text-slate-600 focus:border-emerald-400/50 focus:ring-2 focus:ring-emerald-400/10"
            />
          </label>
          <label className="block">
            <span className="mb-1.5 block text-[11px] font-bold uppercase tracking-wider text-slate-400">Password</span>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete={mode === "login" ? "current-password" : "new-password"}
              minLength={8}
              required
              placeholder="Minimum 8 characters"
              className="w-full rounded-xl border border-white/10 bg-black/25 px-4 py-3 text-sm text-white outline-none placeholder:text-slate-600 focus:border-emerald-400/50 focus:ring-2 focus:ring-emerald-400/10"
            />
          </label>

          {error && <div className="rounded-xl border border-red-400/20 bg-red-400/10 px-3 py-2.5 text-xs text-red-200">{error}</div>}
          {message && <div className="rounded-xl border border-emerald-400/20 bg-emerald-400/10 px-3 py-2.5 text-xs text-emerald-200">{message}</div>}

          <button
            disabled={busy}
            className="w-full rounded-xl bg-emerald-400 px-4 py-3 text-sm font-black uppercase tracking-wider text-[#06100e] transition hover:bg-emerald-300 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {busy ? "Please wait…" : mode === "login" ? "Enter terminal" : "Submit for approval"}
          </button>
        </form>

        <p className="mt-5 text-center text-[10px] leading-relaxed text-slate-500">
          Registration does not grant access automatically. Only an approved account can open the terminal or its API-backed content.
        </p>
      </section>
    </main>
  );
}
