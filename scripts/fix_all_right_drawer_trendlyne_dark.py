from pathlib import Path
import re

FILES = [
    Path('iros-terminal/app/components/ConfidenceCheckerPanel.tsx'),
    Path('iros-terminal/app/components/TechnicalAnalysisPanel.tsx'),
]

EFFECT = r'''

  useEffect(() => {
    if (activeView !== "widget" || !normalizedTicker) return;
    const host = widgetHostRef.current;
    if (!host) return;

    setLoaded(false);
    setErrored(false);
    host.replaceChildren();

    const quote = document.createElement("blockquote");
    quote.className = "trendlyne-widgets";
    quote.dataset.getUrl = widgetUrl;
    quote.dataset.theme = "dark";
    quote.dataset.posCol = "00A25B";
    quote.dataset.primaryCol = "4DA3FF";
    quote.dataset.negCol = "FF5A4F";
    quote.dataset.neuCol = "F6B94A";
    host.appendChild(quote);

    const script = document.createElement("script");
    script.async = true;
    script.src = "https://cdn-static.trendlyne.com/static/js/webwidgets/tl-widgets.js";
    script.charset = "utf-8";
    script.onload = () => setLoaded(true);
    script.onerror = () => setErrored(true);
    host.appendChild(script);

    return () => host.replaceChildren();
  }, [activeView, normalizedTicker, widgetUrl]);
'''

for path in FILES:
    text = path.read_text(encoding='utf-8')

    if path.name == 'TechnicalAnalysisPanel.tsx':
        text = text.replace(
            'import React, { useMemo, useState } from "react";',
            'import React, { useEffect, useMemo, useRef, useState } from "react";',
        )

    if 'const widgetHostRef = useRef<HTMLDivElement>(null);' not in text:
        # Put the ref next to the widget view state.
        text, count = re.subn(
            r'(const \[activeView, setActiveView\][^;]+;)',
            r'\1\n  const widgetHostRef = useRef<HTMLDivElement>(null);',
            text,
            count=1,
        )
        if count != 1:
            raise SystemExit(f'Could not add widgetHostRef to {path}')

    if 'quote.dataset.theme = "dark";' not in text:
        marker = re.search(
            r'(  const widgetUrl = useMemo\(\(\) => \{[\s\S]*?\n  \}, \[normalizedTicker\]\);)',
            text,
        )
        if not marker:
            raise SystemExit(f'Could not locate widgetUrl block in {path}')
        text = text[:marker.end()] + EFFECT + text[marker.end():]

    # Replace the raw cross-origin Trendlyne iframe with its supported widget host.
    text, count = re.subn(
        r'\n\s*<iframe\s+[\s\S]*?src=\{widgetUrl\}[\s\S]*?\n\s*/>',
        '\n              <div\n                ref={widgetHostRef}\n                className="min-h-[240px] sm:min-h-[320px] md:min-h-[400px] h-[min(70dvh,500px)] md:h-[500px] w-full bg-slate-950"\n              />',
        text,
        count=1,
    )
    if count != 1 and 'ref={widgetHostRef}' not in text:
        raise SystemExit(f'Could not replace raw Trendlyne iframe in {path}')

    # Make the widget viewport itself dark so there is no white flash around the iframe Trendlyne creates.
    text = text.replace(
        'relative overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-inner',
        'relative overflow-hidden rounded-2xl border border-slate-700 bg-slate-950 shadow-inner',
        1,
    )

    path.write_text(text, encoding='utf-8')
    print(f'patched {path}')
