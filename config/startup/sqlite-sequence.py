import sqlite3
import sys
from pathlib import Path


path = Path(sys.argv[1]).resolve()
with sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True) as db:
    exists = db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='swing_events'"
    ).fetchone()
    if not exists:
        print(-1)
    else:
        print(db.execute("SELECT COALESCE(MAX(sequence), 0) FROM swing_events").fetchone()[0])
