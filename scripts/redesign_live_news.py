from pathlib import Path

PAGE = Path("iros-terminal/app/page.tsx")
text = PAGE.read_text(encoding="utf-8")

start_marker = "  // Sidebar mode: compact, vertically scrollable news list\n  if (sidebar) {"
end_marker = "  // Non-sidebar (full-width horizontal) mode - unchanged"
start = text.index(start_marker)
end = text.index(end_marker, start)

replacement = r'''  // Sidebar mode: terminal-native live intelligence stream
  if (sidebar) {
    const bullishCount = baseItems.filter((item) => (item.sentiment ?? "Neutral") === "Bullish").length;
    const bearishCount = baseItems.filter((item) => (item.sentiment ?? "Neutral") === "Bearish").length;
    const neutralCount = baseItems.filter((item) => (item.sentiment ?? "Neutral") === "Neutral").length;

    return (
      <section className="relative isolate flex h-auto max-h-[min(58dvh,560px)] min-h-[360px] flex-col overflow-hidden rounded-2xl border border-[var(--terminal-line)] bg-[color:var(--terminal-panel)] shadow-[var(--shadow-panel)] xl:h-[1270px] xl:max-h-none">
        <div aria-hidden className="pointer-events-none absolute inset-0 overflow-hidden">
          <div className="absolute -left-16 -top-20 h-48 w-48 rounded-full bg-[color:var(--terminal-cyan)] opacity-[0.07] blur-3xl motion-safe:animate-pulse" />
          <div className="absolute -bottom-20 -right-16 h-56 w-56 rounded-full bg-[color:var(--terminal-violet)] opacity-[0.06] blur-3xl motion-safe:animate-pulse" />
          <div className="absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-[var(--terminal-cyan)] to-transparent opacity-70" />
        </div>

        <header className="relative z-10 border-b border-[var(--terminal-line)] bg-[color:var(--glass-1)] px-3 py-3 backdrop-blur-xl">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <span className="relative flex h-3 w-3 shrink-0 items-center justify-center">
                  <span className="absolute h-3 w-3 rounded-full bg-emerald-400/35 motion-safe:animate-ping" />
                  <span className="relative h-1.5 w-1.5 rounded-full bg-emerald-400 shadow-[0_0_14px_rgba(52,211,153,.9)]" />
                </span>
                <h3 className="truncate text-[11px] font-black uppercase tracking-[0.16em] text-[var(--fg-strong)]">Live News Intelligence</h3>
              </div>
              <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-[8px] font-semibold uppercase tracking-wider text-[var(--fg-subtle)]">
                <span>{filtered.length} stories</span>
                <span className="opacity-40">•</span>
                <span>{sources.length} sources</span>
                <span className="opacity-40">•</span>
                <span className="text-emerald-400">streaming</span>
              </div>
            </div>
            <div className="flex shrink-0 items-center gap-1.5">
              <span className="rounded-full border border-emerald-400/25 bg-emerald-400/10 px-2 py-1 text-[8px] font-black uppercase tracking-[0.12em] text-emerald-300">Live</span>
              {hasFilters && (
                <button onClick={resetFilters} className="rounded-full border border-[var(--terminal-line)] bg-[color:var(--glass-flat)] px-2 py-1 text-[8px] font-bold uppercase tracking-wider text-[var(--fg-muted)] transition hover:border-rose-400/40 hover:text-rose-300">Clear</button>
              )}
            </div>
          </div>

          <div className="mt-3 grid grid-cols-3 gap-1.5">
            {([
              ["Bullish", bullishCount, "border-emerald-400/30 bg-emerald-400/10 text-emerald-300"],
              ["Bearish", bearishCount, "border-rose-400/30 bg-rose-400/10 text-rose-300"],
              ["Neutral", neutralCount, "border-slate-400/25 bg-slate-400/10 text-slate-300"],
            ] as const).map(([label, count, tone]) => {
              const active = sentimentFilter === label;
              return (
                <button
                  key={label}
                  onClick={() => setSentimentFilter(active ? null : label)}
                  className={`group rounded-xl border px-2 py-2 text-left transition-all duration-200 hover:-translate-y-0.5 hover:shadow-lg ${tone} ${active ? "ring-1 ring-current" : "opacity-85 hover:opacity-100"}`}
                >
                  <div className="flex items-center justify-between gap-1">
                    <span className="text-[8px] font-black uppercase tracking-wider">{label}</span>
                    <span className="text-[13px] font-black tabular-nums">{count}</span>
                  </div>
                  <div className="mt-1 h-0.5 overflow-hidden rounded-full bg-black/10 dark:bg-white/5">
                    <div className="h-full rounded-full bg-current opacity-70 transition-all duration-500" style={{ width: `${Math.max(8, Math.min(100, (count / Math.max(1, baseItems.length)) * 100))}%` }} />
                  </div>
                </button>
              );
            })}
          </div>

          <div className="mt-2 flex items-center gap-1.5 overflow-x-auto pb-0.5 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
            <button
              onClick={() => setCategoryFilter(null)}
              className={`whitespace-nowrap rounded-full border px-2 py-1 text-[8px] font-bold uppercase tracking-wider transition ${!categoryFilter ? "border-[var(--terminal-cyan)] bg-[color:var(--terminal-cyan-dim)] text-[var(--terminal-mint-bright)]" : "border-[var(--terminal-line)] bg-[color:var(--glass-flat)] text-[var(--fg-muted)] hover:text-[var(--foreground)]"}`}
            >
              All sectors
            </button>
            {categories.slice(0, 8).map((category) => (
              <button
                key={category}
                onClick={() => setCategoryFilter(categoryFilter === category ? null : category)}
                className={`whitespace-nowrap rounded-full border px-2 py-1 text-[8px] font-bold uppercase tracking-wider transition ${categoryFilter === category ? "border-[var(--terminal-cyan)] bg-[color:var(--terminal-cyan-dim)] text-[var(--terminal-mint-bright)]" : "border-[var(--terminal-line)] bg-[color:var(--glass-flat)] text-[var(--fg-muted)] hover:text-[var(--foreground)]"}`}
              >
                {category}
              </button>
            ))}
          </div>
        </header>

        <div
          className="relative z-10 flex-1 min-h-0 space-y-2 overflow-y-auto overflow-x-hidden p-2.5 pr-2"
          tabIndex={0}
          ref={railRef}
          onScroll={handleSidebarScroll}
          aria-label="Live market news intelligence stream"
        >
          {displayed.length === 0 ? (
            <div className="flex min-h-40 items-center justify-center rounded-xl border border-dashed border-[var(--terminal-line)] bg-[color:var(--glass-flat)] p-4 text-center text-[10px] text-[var(--fg-muted)]">No stories match the current intelligence filters.</div>
          ) : displayed.map((item, i) => {
            const color = sourceColor(item.source);
            const sentiment = item.sentiment ?? "Neutral";
            const sentimentTone = sentiment === "Bullish" ? "text-emerald-300 border-emerald-400/25 bg-emerald-400/10" : sentiment === "Bearish" ? "text-rose-300 border-rose-400/25 bg-rose-400/10" : "text-slate-300 border-slate-400/20 bg-slate-400/10";
            const sourceInitials = item.source.split(/\s+/).filter(Boolean).slice(0, 2).map((part) => part[0]).join("").toUpperCase() || "N";
            return (
              <motion.a
                key={`${item.title}-${i}`}
                href={item.link}
                target="_blank"
                rel="noopener noreferrer"
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.28, delay: Math.min(i, 8) * 0.025 }}
                whileHover={{ y: -2, scale: 1.005 }}
                className="group relative block overflow-hidden rounded-xl border border-[var(--terminal-line)] bg-[color:var(--glass-flat)] p-3 shadow-sm transition-colors hover:border-[var(--terminal-line-strong)] hover:bg-[color:var(--glass-2)] focus:outline-none focus:ring-1 focus:ring-[var(--terminal-cyan)]"
              >
                <span aria-hidden className="absolute inset-y-0 left-0 w-[2px] opacity-90" style={{ background: color }} />
                <span aria-hidden className="absolute inset-x-0 top-0 h-px origin-left scale-x-0 bg-gradient-to-r from-transparent via-[var(--terminal-cyan)] to-transparent opacity-70 transition-transform duration-500 group-hover:scale-x-100" />

                <div className="flex items-start gap-2.5">
                  <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg border border-white/10 text-[8px] font-black text-white shadow-sm" style={{ background: color }} title={item.source}>{sourceInitials}</div>
                  <div className="min-w-0 flex-1">
                    <div className="flex min-w-0 items-center gap-1.5">
                      <span className="truncate text-[8px] font-black uppercase tracking-[0.12em] text-[var(--fg-muted)]">{item.source}</span>
                      <span className="text-[7px] text-[var(--fg-subtle)]">•</span>
                      <time className="shrink-0 text-[8px] font-mono text-[var(--fg-subtle)]" dateTime={item.publishedAt}>{timeAgo(item.publishedAt)}</time>
                    </div>
                    <h4 className="mt-1 line-clamp-3 text-[11px] font-bold leading-[1.35] text-[var(--foreground)] transition-colors group-hover:text-[var(--terminal-mint-bright)]">{item.title}</h4>
                    <div className="mt-2 flex flex-wrap items-center gap-1.5">
                      <span className="rounded-full border border-[var(--terminal-line)] bg-[color:var(--terminal-panel-2)] px-1.5 py-0.5 text-[7px] font-bold uppercase tracking-wider text-[var(--fg-muted)]">{item.category ?? "Market"}</span>
                      <span className={`rounded-full border px-1.5 py-0.5 text-[7px] font-bold uppercase tracking-wider ${sentimentTone}`}>{sentiment}</span>
                    </div>
                    {item.summary && (
                      <div className="grid grid-rows-[0fr] opacity-0 transition-all duration-300 group-hover:grid-rows-[1fr] group-hover:opacity-100 group-focus:grid-rows-[1fr] group-focus:opacity-100">
                        <p className="mt-0 overflow-hidden text-[9px] leading-relaxed text-[var(--fg-muted)] group-hover:mt-2 group-focus:mt-2">{item.summary}</p>
                      </div>
                    )}
                  </div>
                  <span className="mt-0.5 shrink-0 text-[10px] text-[var(--fg-subtle)] transition-transform duration-200 group-hover:translate-x-0.5 group-hover:text-[var(--terminal-cyan)]">↗</span>
                </div>
              </motion.a>
            );
          })}

          {infiniteLoading && (
            <div className="relative overflow-hidden rounded-xl border border-[var(--terminal-line)] bg-[color:var(--glass-flat)] p-3">
              <div className="absolute inset-0 -translate-x-full bg-gradient-to-r from-transparent via-[var(--terminal-cyan-dim)] to-transparent motion-safe:animate-pulse" />
              <div className="relative flex items-center justify-center gap-2 text-[8px] font-bold uppercase tracking-wider text-[var(--fg-muted)]">
                <span className="h-1.5 w-1.5 rounded-full bg-[var(--terminal-cyan)] motion-safe:animate-pulse" />
                Receiving more market intelligence
              </div>
            </div>
          )}
          {infiniteError && (
            <div className="rounded-lg border border-amber-400/25 bg-amber-400/10 px-2.5 py-2 text-[8px] text-amber-300">Feed degraded: {infiniteError}</div>
          )}
        </div>

        <footer className="relative z-10 flex items-center justify-between gap-2 border-t border-[var(--terminal-line)] bg-[color:var(--glass-1)] px-3 py-2 text-[7px] font-semibold uppercase tracking-wider text-[var(--fg-subtle)] backdrop-blur-xl">
          <span>{infiniteHasMore ? "Scroll for more" : "Latest batch complete"}</span>
          <span className="flex items-center gap-1.5"><span className="h-1 w-1 rounded-full bg-emerald-400 motion-safe:animate-pulse" /> RSS intelligence mesh</span>
        </footer>
      </section>
    );
  }

'''

new_text = text[:start] + replacement + text[end:]
if new_text == text:
    raise SystemExit("No page.tsx change produced")
if "AITickerNewsPanel" not in new_text:
    raise SystemExit("Safety check failed: unrelated page structure changed")
PAGE.write_text(new_text, encoding="utf-8")
print("Updated only NewsFeedPanel sidebar block in", PAGE)
