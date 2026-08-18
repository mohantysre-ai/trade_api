from pathlib import Path


def test_terminal_intelligence_defaults_snapshot_fallback_false():
    src = Path(__file__).resolve().parents[1] / "app" / "services" / "angel_one_feed.py"
    text = src.read_text(encoding="utf-8")
    assert 'payload.get("isSnapshotFallback", True)' not in text
    assert text.count('payload.get("isSnapshotFallback", False)') >= 3
