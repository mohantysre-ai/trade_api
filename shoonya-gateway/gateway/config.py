from __future__ import annotations

import os
from dataclasses import dataclass, field
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")


def _f(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


def _i(name: str, default: int) -> int:
    try:
        return int(float(os.getenv(name, str(default))))
    except ValueError:
        return default


def _list(name: str) -> list[str]:
    return [p.strip() for p in os.getenv(name, "").split(",") if p.strip()]


@dataclass
class Settings:
    api_base: str = "https://api.shoonya.com"
    ws_url: str = "wss://api.shoonya.com/NorenWSTP/"
    uid: str = ""
    account_id: str = ""
    password: str = ""
    totp_secret: str = ""
    vendor_code: str = ""
    api_secret: str = ""
    source: str = "API"
    auth_mode: str = "manual"
    login_hhmm: str = "08:15"
    login_deadline_hhmm: str = "08:50"
    login_max_attempts: int = 3
    login_attempt_window_s: float = 1800.0
    session_file: str = "/data/session.json"
    gateway_token: str = ""
    admin_token: str = ""
    ws_max_tokens: int = 450
    index_reserve: int = 20
    index_keys: list[str] = field(default_factory=list)
    subscribe_chunk: int = 50
    subscribe_gap_s: float = 1.0
    unpin_grace_s: float = 60.0
    ack_timeout_s: float = 10.0
    reconnect_base_s: float = 1.0
    reconnect_max_s: float = 60.0
    app_heartbeat_s: float = 0.0
    ft_mode: str = "epoch_utc"
    ft_is_heartbeat: bool = False
    trust_c_as_prev_close: bool = False
    stream_flush_s: float = 0.1
    heartbeat_s: float = 1.0
    quote_stale_s: float = 8.0
    rest_rps: float = 2.0
    rest_burst: int = 5
    candle_max_per_min: int = 60
    candle_circuit_s: float = 60.0
    registry_max_age_days: int = 1
    tls_verify: bool = True

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            api_base=os.getenv("SHOONYA_API_BASE", "https://api.shoonya.com").rstrip("/"),
            ws_url=os.getenv("SHOONYA_WS_URL", "wss://api.shoonya.com/NorenWSTP/"),
            uid=os.getenv("SHOONYA_UID", ""),
            account_id=os.getenv("SHOONYA_ACCOUNT_ID", "") or os.getenv("SHOONYA_UID", ""),
            password=os.getenv("SHOONYA_PASSWORD", ""),
            totp_secret=os.getenv("SHOONYA_TOTP_SECRET", ""),
            vendor_code=os.getenv("SHOONYA_CLIENT_ID", ""),
            api_secret=os.getenv("SHOONYA_SECRET_CODE", ""),
            source=os.getenv("SHOONYA_SOURCE", "API"),
            auth_mode=os.getenv("SHOONYA_AUTH_MODE", "manual").lower(),
            login_hhmm=os.getenv("SHOONYA_LOGIN_HHMM", "08:15"),
            login_deadline_hhmm=os.getenv("SHOONYA_LOGIN_DEADLINE_HHMM", "08:50"),
            session_file=os.getenv("SHOONYA_SESSION_FILE", "/data/session.json"),
            gateway_token=os.getenv("SHOONYA_GATEWAY_TOKEN", ""),
            admin_token=os.getenv("SHOONYA_ADMIN_TOKEN", ""),
            ws_max_tokens=_i("SHOONYA_WS_MAX_TOKENS", 450),
            index_reserve=_i("SHOONYA_WS_INDEX_RESERVE", 20),
            index_keys=_list("SHOONYA_INDEX_KEYS"),
            app_heartbeat_s=_f("SHOONYA_APP_HEARTBEAT_SECONDS", 0.0),
            ft_mode=os.getenv("SHOONYA_FT_MODE", "epoch_utc"),
            ft_is_heartbeat=os.getenv("SHOONYA_FT_IS_HEARTBEAT", "0") == "1",
            trust_c_as_prev_close=os.getenv("SHOONYA_TRUST_C_AS_PREV_CLOSE", "0") == "1",
            rest_rps=_f("SHOONYA_REST_RPS", 2.0),
            candle_max_per_min=_i("SHOONYA_CANDLE_MAX_PER_MIN", 60),
        )
