import asyncio
import json
from datetime import datetime

from gateway.auth import AuthManager, Session
from gateway.config import IST, Settings
from gateway.oauth_browser import _authorization_code


class Driver:
    current_url = "https://callback.invalid/"

    def get_log(self, name):
        assert name == "performance"
        return [
            {
                "message": json.dumps(
                    {
                        "message": {
                            "method": "Network.requestWillBeSent",
                            "params": {
                                "request": {
                                    "url": "https://callback.invalid/?code=one-time-code"
                                }
                            },
                        }
                    }
                )
            }
        ]


def test_authorization_code_is_captured_from_redirect_log():
    assert _authorization_code(Driver()) == "one-time-code"


def test_oauth_auto_mode_runs_login_after_window():
    now = datetime(2026, 9, 28, 8, 16, tzinfo=IST)

    async def login():
        return Session("USER1", "ACCOUNT1", "rest", now.isoformat(), "ws")

    manager = AuthManager(
        Settings(auth_mode="oauth_auto", session_file=""),
        login_fn=login,
        clock=lambda: now,
    )

    assert asyncio.run(manager.maybe_login()) is True
    assert manager.authenticated is True
