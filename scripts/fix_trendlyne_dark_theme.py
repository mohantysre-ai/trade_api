from pathlib import Path
import re

root = Path(__file__).resolve().parents[1]
swot = root / "iros-terminal" / "app" / "components" / "SwotAnalysisPanel.tsx"
qvt = root / "iros-terminal" / "app" / "components" / "SigqQvtPanel.tsx"

# QVT: use Trendlyne's supported dark theme and dark terminal shell.
qvt_text = qvt.read_text(encoding="utf-8")
if 'quote.dataset.theme = "light";' not in qvt_text and 'quote.dataset.theme = "dark";' not in qvt_text:
    raise SystemExit("QVT theme anchor not found")
qvt_text = qvt_text.replace('quote.dataset.theme = "light";', 'quote.dataset.theme = "dark";')
qvt_text = qvt_text.replace(
    'className="rounded-xl border border-slate-200 bg-white px-4 py-3"',
    'className="rounded-xl border border-slate-700 bg-slate-950 px-4 py-3"',
)
qvt_text = qvt_text.replace(
    'className="text-xs font-black uppercase tracking-wider text-slate-800"',
    'className="text-xs font-black uppercase tracking-wider text-slate-100"',
)
qvt_text = qvt_text.replace(
    'className="mt-1 text-[11px] text-slate-500"',
    'className="mt-1 text-[11px] text-slate-400"',
)
qvt_text = qvt_text.replace(
    'className="min-h-[420px] overflow-hidden rounded-xl border border-slate-200 bg-white p-2"',
    'className="min-h-[420px] overflow-hidden rounded-xl border border-slate-700 bg-slate-950 p-2"',
)
qvt.write_text(qvt_text, encoding="utf-8")

# SWOT: stop loading the raw widget URL directly as an iframe. The raw iframe
# has no theme contract. Bootstrap Trendlyne's widget script with data-theme=dark.
swot_text = swot.read_text(encoding="utf-8")
swot_text = swot_text.replace(
    'import React, { useMemo, useState, useEffect } from "react";',
    'import React, { useMemo, useState, useEffect, useRef } from "react";',
)
anchor = "  const [loaded, setLoaded] = useState(false);\n  const [errored, setErrored] = useState(false);"
if anchor not in swot_text:
    raise SystemExit("SWOT state anchor not found")
swot_text = swot_text.replace(
    anchor,
    anchor + '\n  const widgetHostRef = useRef<HTMLDivElement>(null);',
    1,
)

insert_after = '''  const widgetUrl = useMemo(() => {\n    if (!normalizedTicker) return "";\n    return `https://trendlyne.com/web-widget/swot-widget/Poppins/${encodeURIComponent(normalizedTicker)}`;\n  }, [normalizedTicker]);\n'''
if insert_after not in swot_text:
    raise SystemExit("SWOT widgetUrl anchor not found")
effect = '''\n  useEffect(() => {\n    if (activeView !== 'widget' || !normalizedTicker) return;\n    const host = widgetHostRef.current;\n    if (!host) return;\n\n    setLoaded(false);\n    setErrored(false);\n    host.replaceChildren();\n\n    const quote = document.createElement("blockquote");\n    quote.className = "trendlyne-widgets";\n    quote.dataset.getUrl = widgetUrl;\n    quote.dataset.theme = "dark";\n    quote.dataset.posCol = "00A25B";\n    quote.dataset.primaryCol = "4DA3FF";\n    quote.dataset.negCol = "FF5A4F";\n    quote.dataset.neuCol = "F6B94A";\n    host.appendChild(quote);\n\n    const script = document.createElement("script");\n    script.async = true;\n    script.src = "https://cdn-static.trendlyne.com/static/js/webwidgets/tl-widgets.js";\n    script.charset = "utf-8";\n    script.onload = () => setLoaded(true);\n    script.onerror = () => setErrored(true);\n    host.appendChild(script);\n\n    return () => host.replaceChildren();\n  }, [activeView, normalizedTicker, widgetUrl]);\n'''
swot_text = swot_text.replace(insert_after, insert_after + effect, 1)

iframe_re = re.compile(r'''\n\s*<iframe\n\s*key=\{widgetUrl\}.*?\n\s*/>''', re.S)
replacement = '''\n              <div\n                ref={widgetHostRef}\n                className="min-h-[240px] sm:min-h-[320px] md:min-h-[400px] bg-slate-950"\n                aria-label={`SIGQ SWOT analysis for ${normalizedTicker}`}\n              />'''
swot_text, count = iframe_re.subn(replacement, swot_text, count=1)
if count != 1:
    raise SystemExit(f"Expected one SWOT iframe replacement, got {count}")

# Make the widget shell dark so there is no white flash around the third-party embed.
swot_text = swot_text.replace(
    'className="relative overflow-hidden rounded-3xl border border-slate-200 bg-white shadow-sm"',
    'className="relative overflow-hidden rounded-3xl border border-slate-700 bg-slate-950 shadow-sm"',
    1,
)
swot_text = swot_text.replace(
    'className="relative overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-inner"',
    'className="relative overflow-hidden rounded-2xl border border-slate-700 bg-slate-950 shadow-inner"',
    1,
)
swot_text = swot_text.replace(
    'className="flex flex-col items-center justify-center gap-4 bg-white min-h-[240px] sm:min-h-[320px] md:min-h-[400px]"',
    'className="flex flex-col items-center justify-center gap-4 bg-slate-950 min-h-[240px] sm:min-h-[320px] md:min-h-[400px]"',
    1,
)
swot.write_text(swot_text, encoding="utf-8")

print("Forced Trendlyne SWOT and QVT widgets to dark theme")
