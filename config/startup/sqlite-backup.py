import sqlite3
import sys
from pathlib import Path


source_path = Path(sys.argv[1]).resolve()
backup_path = Path(sys.argv[2]).resolve()

if source_path == backup_path:
    raise ValueError("Source and backup paths must differ")

with sqlite3.connect(f"file:{source_path.as_posix()}?mode=ro", uri=True) as source:
    with sqlite3.connect(backup_path) as backup:
        source.backup(backup)
        result = backup.execute("PRAGMA integrity_check").fetchone()
        if result != ("ok",):
            raise RuntimeError(f"SQLite backup integrity check failed: {result}")
