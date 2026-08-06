from pathlib import Path

p = Path(r"d:\trade_api\iros-terminal\app\globals.css")
t = p.read_text(encoding="utf-8")
start = t.find("/* Performance mode")
end = t.find("html[data-perf=\"1\"] .terminal-shell::after {")
if start < 0 or end < 0:
    raise SystemExit(f"markers missing start={start} end={end}")
# find end of that rule block
end2 = t.find("}", end) + 1
# also include following blank line if any
while end2 < len(t) and t[end2] in "\r\n":
    end2 += 1

good = """/* Performance mode + reduced transparency — drop blur, keep tint language */
@media (prefers-reduced-transparency: reduce) {
  .glass-shell,
  .glass-card,
  .glass-overlay,
  .desk-metric-tile,
  .right-drawer {
    -webkit-backdrop-filter: none !important;
    backdrop-filter: none !important;
  }
}
html[data-perf="1"] .glass-shell,
html[data-perf="1"] .glass-card,
html[data-perf="1"] .glass-overlay,
html[data-perf="1"] .desk-metric-tile,
html[data-perf="1"] .right-drawer,
html[data-perf="1"] .desk-controls {
  -webkit-backdrop-filter: none !important;
  backdrop-filter: none !important;
  background: var(--glass-flat) !important;
}
html[data-perf="1"] .terminal-shell::before,
html[data-perf="1"] .terminal-shell::after {
  display: none;
}

"""
p.write_text(t[:start] + good + t[end2:], encoding="utf-8")
print("fixed", start, end2)
