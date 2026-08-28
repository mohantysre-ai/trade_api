from pathlib import Path

PATH = Path("iros-terminal/app/components/AITickerNewsPanel.tsx")
text = PATH.read_text(encoding="utf-8")

old_counts = '''  const toneCounts = useMemo(() => headlines.reduce<Record<Tone, number>>((acc, item) => {
    acc[item.tone] += 1;
    return acc;
  }, { Bullish: 0, Bearish: 0, Neutral: 0 }), [headlines]);
'''
new_counts = '''  const toneCounts = useMemo(() => headlines.reduce<Record<Tone, number>>((acc, item) => {
    acc[item.tone] += 1;
    return acc;
  }, { Bullish: 0, Bearish: 0, Neutral: 0 }), [headlines]);
  const hasHeadlineSentiment = headlines.length > 0;
'''

if old_counts not in text:
    raise SystemExit("toneCounts block not found")
text = text.replace(old_counts, new_counts, 1)

old_value = '''{toneCounts[tone]}'''
new_value = '''{hasHeadlineSentiment ? toneCounts[tone] : "—"}'''
if old_value not in text:
    raise SystemExit("tone count display not found")
text = text.replace(old_value, new_value, 1)

# Prevent a meaningless sentiment filter from being selected when there are no
# headline-level observations to filter.
old_click = '''onClick={() => setToneFilter(toneFilter === tone ? "All" : tone)}'''
new_click = '''onClick={() => hasHeadlineSentiment && setToneFilter(toneFilter === tone ? "All" : tone)} disabled={!hasHeadlineSentiment}'''
if old_click not in text:
    raise SystemExit("tone filter click handler not found")
text = text.replace(old_click, new_click, 1)

# Add a provenance note immediately after the three sentiment cards.
anchor = '''            </div>\n\n            <div className="flex items-center justify-between gap-2">'''
note = '''            </div>\n\n            {!hasHeadlineSentiment && (\n              <div className="rounded-lg border border-amber-400/20 bg-amber-400/[0.06] px-2.5 py-2 text-[8px] font-semibold leading-relaxed text-amber-700 dark:text-amber-200">\n                Headline-level sentiment unavailable for this report. Overall bias remains report-level intelligence and is shown separately above.\n              </div>\n            )}\n\n            <div className="flex items-center justify-between gap-2">'''
if anchor not in text:
    # The panel layout may not have this exact next block. In that case, insert
    # before the first Live Tape heading, which is semantically equivalent.
    alt = '''            <div className="flex items-center justify-between gap-2">'''
    if alt not in text:
        raise SystemExit("sentiment grid insertion anchor not found")
    text = text.replace(alt, note.split('            <div className="flex items-center justify-between gap-2">')[0] + alt, 1)
else:
    text = text.replace(anchor, note, 1)

PATH.write_text(text, encoding="utf-8")
print("Fixed ticker news sentiment counters: no false 0/0/0 when headline evidence is absent")
