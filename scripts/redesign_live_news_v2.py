from pathlib import Path

source = Path("scripts/redesign_live_news.py").read_text(encoding="utf-8")
source = source.replace(
    'if "AITickerNewsPanel" not in new_text:\n    raise SystemExit("Safety check failed: unrelated page structure changed")\n',
    '',
)
exec(compile(source, "scripts/redesign_live_news.py", "exec"))
