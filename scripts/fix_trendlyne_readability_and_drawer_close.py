from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
COMPONENTS = ROOT / "iros-terminal" / "app" / "components"
WIDGET_FILES = [
    COMPONENTS / "SigqQvtPanel.tsx",
    COMPONENTS / "TechnicalAnalysisPanel.tsx",
    COMPONENTS / "ConfidenceCheckerPanel.tsx",
    COMPONENTS / "SwotAnalysisPanel.tsx",
]

for path in WIDGET_FILES:
    text = path.read_text(encoding="utf-8")

    # Remove the previous CSS-filter based pseudo-dark-mode. It makes the
    # cross-origin Trendlyne document dark at the cost of text/color contrast.
    text, removed = re.subn(
        r'const TRENDLYNE_DARK_FILTER\s*=.*?\n\nfunction forceTrendlyneIframeDark\(host: HTMLElement\) \{[\s\S]*?\n\}\n\n(?=export default)',
        '',
        text,
        count=1,
    )
    if removed == 0 and ("TRENDLYNE_DARK_FILTER" in text or "forceTrendlyneIframeDark" in text):
        raise RuntimeError(f"Could not safely remove iframe dark filter from {path}")

    text = re.sub(r'^\s*const stopTrendlyneDark = forceTrendlyneIframeDark\(host\);\s*\n', '', text, flags=re.M)
    text = text.replace('stopTrendlyneDark(); ', '')
    text = text.replace('stopTrendlyneDark();', '')

    # Trendlyne's native dark behavior is inconsistent across Technical,
    # Checklist, SWOT and QVT. Use its native light document for readable text;
    # the surrounding SIGQ shell remains theme-aware/dark.
    text = text.replace('quote.dataset.theme = "dark";', 'quote.dataset.theme = "light";')
    text = text.replace("quote.dataset.theme = 'dark';", "quote.dataset.theme = 'light';")

    path.write_text(text, encoding="utf-8")

# Keep the drawer header + close action above all scrolling/third-party content.
drawer = COMPONENTS / "RightDrawer.tsx"
text = drawer.read_text(encoding="utf-8")
old_header = '<div className="z-20 shrink-0 border-b border-slate-200 bg-[var(--terminal-panel)]">'
new_header = '<div className="sticky top-0 z-[120] shrink-0 border-b border-slate-200 bg-[var(--terminal-panel)] shadow-sm">'
if old_header not in text and new_header not in text:
    raise RuntimeError("RightDrawer header anchor changed")
text = text.replace(old_header, new_header, 1)

old_close = 'className="right-drawer-close ml-1 shrink-0 w-8 h-8 sm:w-9 sm:h-9 flex items-center justify-center rounded-full text-slate-400 hover:text-slate-700 hover:bg-slate-100 transition-[color,background-color] duration-150"'
new_close = 'className="right-drawer-close relative z-[130] ml-2 shrink-0 w-10 h-10 flex items-center justify-center rounded-full border border-slate-200 bg-[var(--terminal-panel)] text-slate-600 shadow-sm hover:text-slate-950 hover:bg-slate-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400 transition-[color,background-color,box-shadow] duration-150"'
if old_close not in text and new_close not in text:
    raise RuntimeError("RightDrawer close button anchor changed")
text = text.replace(old_close, new_close, 1)
text = text.replace('<button\n            onClick={onClose}\n            className="right-drawer-close', '<button\n            type="button"\n            onClick={onClose}\n            className="right-drawer-close', 1)

drawer.write_text(text, encoding="utf-8")

print("Patched Trendlyne readability and RightDrawer close behavior")
