from pathlib import Path

path = Path('iros-terminal/app/components/AITickerNewsPanel.tsx')
text = path.read_text(encoding='utf-8')

old_effect = '''  useEffect(() => {\n    if (!ticker || initialReport) return;\n    let cancelled = false;\n    setLoading(true);\n    setError(null);\n    fetchTickerNewsReport(ticker, { company: companyName, maxArticles: 8, includeRaw: true })\n      .then((result) => { if (!cancelled) setReport(result); })\n      .catch((err) => { if (!cancelled) setError(err instanceof Error ? err.message : "Failed to fetch news report"); })\n      .finally(() => { if (!cancelled) setLoading(false); });\n    return () => { cancelled = true; };\n  }, [ticker, companyName, initialReport]);\n'''
new_effect = '''  useEffect(() => {\n    if (!ticker) return;\n    const initialArticleCount = initialReport?.articles_after_dedup ?? initialReport?.articles_scraped ?? 0;\n    const initialHeadlineCount = initialReport?.latest_verified_headlines?.length ?? 0;\n    const initialEvidenceStatus = String(initialReport?.evidence_status ?? "").toUpperCase();\n    const initialReportNeedsHydration = Boolean(\n      initialReport &&\n      initialArticleCount > 0 &&\n      initialHeadlineCount === 0 &&\n      (initialEvidenceStatus === "VERIFIED_RECENT" || initialArticleCount > 0)\n    );\n    if (initialReport && !initialReportNeedsHydration) return;\n\n    let cancelled = false;\n    setLoading(!initialReport);\n    setRefreshing(Boolean(initialReport));\n    setError(null);\n    fetchTickerNewsReport(ticker, { company: companyName, maxArticles: 8, includeRaw: true })\n      .then((result) => { if (!cancelled) setReport(result); })\n      .catch((err) => { if (!cancelled) setError(err instanceof Error ? err.message : "Failed to fetch news report"); })\n      .finally(() => {\n        if (!cancelled) {\n          setLoading(false);\n          setRefreshing(false);\n        }\n      });\n    return () => { cancelled = true; };\n  }, [ticker, companyName, initialReport]);\n'''
if old_effect not in text:
    raise SystemExit('hydration effect anchor not found')
text = text.replace(old_effect, new_effect, 1)

replacements = {
'''  if (tone === "Bullish") return "border-emerald-400/30 bg-emerald-400/10 text-emerald-300";\n  if (tone === "Bearish") return "border-rose-400/30 bg-rose-400/10 text-rose-300";\n  return "border-slate-500/30 bg-slate-500/10 text-slate-300";''':
'''  if (tone === "Bullish") return "border-emerald-300 bg-emerald-50 text-emerald-700 dark:border-emerald-400/30 dark:bg-emerald-400/10 dark:text-emerald-300";\n  if (tone === "Bearish") return "border-rose-300 bg-rose-50 text-rose-700 dark:border-rose-400/30 dark:bg-rose-400/10 dark:text-rose-300";\n  return "border-slate-300 bg-slate-50 text-slate-700 dark:border-slate-500/30 dark:bg-slate-500/10 dark:text-slate-300";''',
'''<section className="group relative overflow-hidden rounded-2xl border border-cyan-300/10 bg-[linear-gradient(145deg,rgba(8,15,28,.98),rgba(12,22,38,.96)_45%,rgba(6,13,25,.99))] text-slate-100 shadow-[0_20px_70px_rgba(2,8,23,.42)]">''':
'''<section className="group relative overflow-hidden rounded-2xl border border-slate-200 bg-white text-slate-900 shadow-[0_16px_45px_rgba(15,23,42,.10)] dark:border-cyan-300/10 dark:bg-[linear-gradient(145deg,rgba(8,15,28,.98),rgba(12,22,38,.96)_45%,rgba(6,13,25,.99))] dark:text-slate-100 dark:shadow-[0_20px_70px_rgba(2,8,23,.42)]">''',
'''<header className="relative border-b border-white/[0.06] px-4 pb-3.5 pt-4">''':
'''<header className="relative border-b border-slate-200 px-4 pb-3.5 pt-4 dark:border-white/[0.06]">''',
'''<div className="relative rounded-xl border border-white/10 bg-slate-950/70 p-1.5">''':
'''<div className="relative rounded-xl border border-slate-200 bg-white p-1.5 shadow-sm dark:border-white/10 dark:bg-slate-950/70 dark:shadow-none">''',
'''text-slate-100">Live News Intelligence''':
'''text-slate-900 dark:text-slate-100">Live News Intelligence''',
'''border border-white/[0.07] bg-white/[0.035] px-1.5 py-0.5 text-[8px] font-bold uppercase tracking-wider text-slate-400''':
'''border border-slate-200 bg-slate-50 px-1.5 py-0.5 text-[8px] font-bold uppercase tracking-wider text-slate-600 dark:border-white/[0.07] dark:bg-white/[0.035] dark:text-slate-400''',
'''<p className="truncate text-[9px] text-slate-500">''':
'''<p className="truncate text-[9px] text-slate-600 dark:text-slate-500">''',
'''className="group/item relative block overflow-hidden rounded-xl border border-white/[0.055] bg-white/[0.025] p-3 transition duration-300 hover:-translate-y-0.5 hover:border-cyan-300/20 hover:bg-cyan-300/[0.045] hover:shadow-[0_10px_30px_rgba(6,182,212,.06)] motion-reduce:transform-none"''':
'''className="group/item relative block overflow-hidden rounded-xl border border-slate-200 bg-white p-3 shadow-sm transition duration-300 hover:-translate-y-0.5 hover:border-cyan-300 hover:bg-cyan-50 hover:shadow-md dark:border-white/[0.055] dark:bg-white/[0.025] dark:shadow-none dark:hover:border-cyan-300/20 dark:hover:bg-cyan-300/[0.045] dark:hover:shadow-[0_10px_30px_rgba(6,182,212,.06)] motion-reduce:transform-none"''',
'''text-slate-200 transition-colors group-hover/item:text-white''':
'''text-slate-800 transition-colors group-hover/item:text-slate-950 dark:text-slate-200 dark:group-hover/item:text-white''',
'''rounded-xl border border-dashed border-white/[0.07] px-3 py-6 text-center text-[9px] text-slate-600''':
'''rounded-xl border border-dashed border-slate-300 bg-slate-50 px-3 py-6 text-center text-[9px] text-slate-500 dark:border-white/[0.07] dark:bg-transparent dark:text-slate-600''',
'''rounded-full border border-white/[0.05] px-1.5 py-0.5 text-[7px] text-slate-600''':
'''rounded-full border border-slate-200 bg-slate-50 px-1.5 py-0.5 text-[7px] text-slate-600 dark:border-white/[0.05] dark:bg-transparent''',
'''expanded ? "col-span-2 border-violet-300/20 bg-violet-300/[0.055]" : "border-white/[0.055] bg-white/[0.02] hover:border-violet-300/15 hover:bg-violet-300/[0.035]"''':
'''expanded ? "col-span-2 border-violet-300 bg-violet-50 dark:border-violet-300/20 dark:bg-violet-300/[0.055]" : "border-slate-200 bg-white shadow-sm hover:border-violet-300 hover:bg-violet-50 dark:border-white/[0.055] dark:bg-white/[0.02] dark:shadow-none dark:hover:border-violet-300/15 dark:hover:bg-violet-300/[0.035]"''',
}

for old, new in replacements.items():
    if old not in text:
        print(f'warning: style anchor not found: {old[:80]}')
        continue
    text = text.replace(old, new, 1)

# Make key labels and metadata readable in light mode without changing dark mode.
text = text.replace('text-[8px] font-black uppercase tracking-[0.18em] text-slate-500', 'text-[8px] font-black uppercase tracking-[0.18em] text-slate-600 dark:text-slate-500')
text = text.replace('text-[8px] text-slate-600', 'text-[8px] text-slate-500 dark:text-slate-600')

path.write_text(text, encoding='utf-8')
print('Fixed ticker-news incomplete initial report hydration and full light-theme surface')
