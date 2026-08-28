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

old_click = '''onClick={() => setToneFilter(toneFilter === tone ? "All" : tone)}'''
new_click = '''onClick={() => hasHeadlineSentiment && setToneFilter(toneFilter === tone ? "All" : tone)} disabled={!hasHeadlineSentiment}'''
if old_click not in text:
    raise SystemExit("tone filter click handler not found")
text = text.replace(old_click, new_click, 1)

PATH.write_text(text, encoding="utf-8")
print("Fixed ticker news sentiment counters: no false 0/0/0 when headline evidence is absent")
