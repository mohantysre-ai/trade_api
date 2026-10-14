'use client';

import { useEffect, useState } from "react";

type User = { identifier?: string; isAdmin?: boolean };

export default function AccessMenu() {
  const [user, setUser] = useState<User | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetch("/api/auth/session", { cache: "no-store" })
      .then((r) => r.json())
      .then((body) => { if (!cancelled && body?.authenticated) setUser(body.user ?? null); })
      .catch(() => {});
    return () => { cancelled = true; };
  }, []);

  if (!user) return null;

  async function logout() {
    await fetch("/api/auth/logout", { method: "POST" }).catch(() => {});
    window.location.href = "/login";
  }

  return (
    <div className="fixed bottom-4 right-4 z-[90] flex items-center gap-1 rounded-xl border border-slate-300/40 bg-white/90 p-1 shadow-xl backdrop-blur dark:border-white/10 dark:bg-[#0b1718]/90">
      {user.isAdmin && (
        <a href="/admin/access" className="rounded-lg px-2.5 py-2 text-[10px] font-black uppercase tracking-wider text-emerald-700 hover:bg-emerald-50 dark:text-emerald-300 dark:hover:bg-emerald-400/10">Access</a>
      )}
      <button onClick={() => void logout()} className="rounded-lg px-2.5 py-2 text-[10px] font-black uppercase tracking-wider text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-white/5">Logout</button>
    </div>
  );
}
