'use client';

import { useCallback, useEffect, useState } from "react";

type AccessUser = {
  id: number;
  identifier: string;
  identifierType: string;
  status: string;
  isAdmin: boolean;
  createdAt?: string | null;
  approvedAt?: string | null;
  lastLoginAt?: string | null;
};

export default function AccessAdminPage() {
  const [users, setUsers] = useState<AccessUser[]>([]);
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch("/api/auth/admin/users", { cache: "no-store" });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(body?.detail || "Failed to load access requests.");
      setUsers(body?.users ?? []);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load access requests.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  async function act(userId: number, action: "approve" | "reject") {
    setBusyId(userId);
    setError(null);
    try {
      const res = await fetch("/api/auth/admin/action", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ userId, action }),
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(body?.detail || "Approval action failed.");
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Approval action failed.");
    } finally {
      setBusyId(null);
    }
  }

  return (
    <main className="min-h-[100dvh] bg-[#071111] px-4 py-8 text-slate-100">
      <div className="mx-auto max-w-5xl">
        <div className="mb-6 flex flex-wrap items-end justify-between gap-3">
          <div>
            <div className="text-[10px] font-black uppercase tracking-[0.18em] text-emerald-300">Private access control</div>
            <h1 className="mt-1 text-3xl font-black">User approvals</h1>
            <p className="mt-1 text-sm text-slate-400">Approve only people you want to access the terminal.</p>
          </div>
          <a href="/" className="rounded-xl border border-white/10 bg-white/5 px-4 py-2 text-xs font-bold text-slate-200 hover:bg-white/10">Back to terminal</a>
        </div>

        {error && <div className="mb-4 rounded-xl border border-red-400/20 bg-red-400/10 px-4 py-3 text-sm text-red-200">{error}</div>}

        <section className="overflow-hidden rounded-2xl border border-white/10 bg-white/[0.04]">
          <div className="grid grid-cols-[1.5fr_.7fr_.8fr_1fr] gap-3 border-b border-white/10 px-4 py-3 text-[10px] font-black uppercase tracking-wider text-slate-500">
            <div>Account</div><div>Status</div><div>Requested</div><div className="text-right">Action</div>
          </div>
          {loading ? (
            <div className="p-8 text-center text-sm text-slate-500">Loading access requests…</div>
          ) : users.length === 0 ? (
            <div className="p-8 text-center text-sm text-slate-500">No accounts yet.</div>
          ) : (
            users.map((user) => (
              <div key={user.id} className="grid grid-cols-[1.5fr_.7fr_.8fr_1fr] items-center gap-3 border-b border-white/5 px-4 py-3 last:border-b-0">
                <div className="min-w-0">
                  <div className="truncate text-sm font-bold text-white">{user.identifier}</div>
                  <div className="text-[10px] uppercase tracking-wider text-slate-500">{user.isAdmin ? "Administrator" : user.identifierType}</div>
                </div>
                <div>
                  <span className={`rounded-full px-2 py-1 text-[10px] font-black ${user.status === "APPROVED" ? "bg-emerald-400/10 text-emerald-300" : user.status === "PENDING" ? "bg-amber-400/10 text-amber-300" : "bg-red-400/10 text-red-300"}`}>
                    {user.status}
                  </span>
                </div>
                <div className="text-xs text-slate-400">{user.createdAt ? new Date(user.createdAt).toLocaleString() : "—"}</div>
                <div className="flex justify-end gap-2">
                  {!user.isAdmin && user.status !== "APPROVED" && (
                    <button disabled={busyId === user.id} onClick={() => void act(user.id, "approve")} className="rounded-lg bg-emerald-400 px-3 py-2 text-[10px] font-black uppercase text-[#06100e] disabled:opacity-50">Approve</button>
                  )}
                  {!user.isAdmin && user.status !== "REJECTED" && (
                    <button disabled={busyId === user.id} onClick={() => void act(user.id, "reject")} className="rounded-lg border border-red-400/20 bg-red-400/10 px-3 py-2 text-[10px] font-black uppercase text-red-200 disabled:opacity-50">Reject</button>
                  )}
                </div>
              </div>
            ))
          )}
        </section>
      </div>
    </main>
  );
}
