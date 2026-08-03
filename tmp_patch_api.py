from pathlib import Path

path = Path(r"d:\trade_api\backend\app\services\angel_one_feed.py")
text = path.read_text(encoding="utf-8")
needle = '        """Lock exactly 5+5 into intraday_session.json + fixed_trade_plan.json.'
idx = text.find(needle)
if idx < 0:
    raise SystemExit("needle not found")
end = text.find("    @app.get(\"/api/alert-history\")", idx)
if end < 0:
    raise SystemExit("end not found")

insert = '''        """Lock intradAy basket (default 10L+10S) + auto-lock swing portfolio for EOD.

        Manual execution only — no broker orders. Symbols immutable until force unlock.
        """
        try:
            from .intraday_session_engine import commit_session
            result = commit_session(force=force)
            if not result.get("success") and result.get("error"):
                raise HTTPException(status_code=409, detail=result.get("error"))
            return result
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.get("/api/swing-session")
    def swing_session_get() -> dict[str, Any]:
        """Return locked swing portfolio used by Swing Book / EOD."""
        try:
            from .swing_session import load_swing_session
            session = load_swing_session()
            return session or {"locked": False, "long": [], "short": [], "counts": {"total": 0}}
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.post("/api/swing-session/lock")
    def swing_session_lock(force: bool = False) -> dict[str, Any]:
        """Lock current dhanSwingPicks into swing_session.json for EOD."""
        try:
            from .swing_session import lock_swing_session
            result = lock_swing_session(force=force)
            if not result.get("success") and result.get("error"):
                raise HTTPException(status_code=409, detail=result.get("error"))
            return result
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.get("/api/intraday-session")
    def intraday_session() -> dict[str, Any]:
        """Return locked session state + mark-to-market (JSON snapshots only)."""
        try:
            from .intraday_session_engine import get_session
            return get_session(include_live=True)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

'''
# Keep from start of docstring through before alert-history — but we need to also
# skip the old intraday_session route that was between commit and alert-history.
path.write_text(text[:idx] + insert + text[end:], encoding="utf-8")
print("patched", idx, end)
