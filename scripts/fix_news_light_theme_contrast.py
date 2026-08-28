from pathlib import Path

page = Path("iros-terminal/app/page.tsx")
text = page.read_text(encoding="utf-8")
old = '''<div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg border border-white/10 text-[8px] font-black text-white shadow-sm" style={{ background: color }} title={item.source}>{sourceInitials}</div>'''
new = '''<div
                    className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg border text-[8px] font-black shadow-sm"
                    style={{
                      background: `color-mix(in srgb, ${color} 22%, var(--terminal-panel-2))`,
                      borderColor: `color-mix(in srgb, ${color} 55%, var(--terminal-line))`,
                      color: "var(--fg-strong)",
                    }}
                    title={item.source}
                  >{sourceInitials}</div>'''
if old not in text:
    raise SystemExit("main news source badge target not found")
text = text.replace(old, new, 1)
page.write_text(text, encoding="utf-8")

panel = Path("iros-terminal/app/components/AITickerNewsPanel.tsx")
text = panel.read_text(encoding="utf-8")
repls = {
'''<div className="mt-3 grid grid-cols-[1fr_auto] items-center gap-3 rounded-xl border border-cyan-300/10 bg-gradient-to-r from-cyan-300/[0.07] via-white/[0.025] to-transparent p-3">''':
'''<div className="mt-3 grid grid-cols-[1fr_auto] items-center gap-3 rounded-xl border border-cyan-600/20 bg-white/95 p-3 shadow-sm dark:border-cyan-300/10 dark:bg-gradient-to-r dark:from-cyan-300/[0.07] dark:via-white/[0.025] dark:to-transparent dark:shadow-none">''',
'''<div className="mb-1 flex items-center gap-1.5 text-[8px] font-black uppercase tracking-[0.18em] text-cyan-300/80"><span className="h-1 w-1 animate-pulse rounded-full bg-cyan-300 motion-reduce:animate-none" /> Desk headline</div>''':
'''<div className="mb-1 flex items-center gap-1.5 text-[8px] font-black uppercase tracking-[0.18em] text-cyan-700 dark:text-cyan-300/80"><span className="h-1 w-1 animate-pulse rounded-full bg-cyan-500 dark:bg-cyan-300 motion-reduce:animate-none" /> Desk headline</div>''',
'''<p className="line-clamp-2 text-[10px] font-medium leading-relaxed text-slate-200">{report.summary_headline}</p>''':
'''<p className="line-clamp-2 text-[10px] font-semibold leading-relaxed text-slate-800 dark:font-medium dark:text-slate-200">{report.summary_headline}</p>''',
}
for old, new in repls.items():
    if old not in text:
        raise SystemExit(f"ticker news target not found: {old[:80]}")
    text = text.replace(old, new, 1)
panel.write_text(text, encoding="utf-8")

print("Fixed main news source badges and ticker Desk Headline light-theme contrast")
