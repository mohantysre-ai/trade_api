from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, Field

_DB_PATH = Path(os.getenv("SIGQ_AUTH_DB", "/app/backend/app/data/sigq_access.db"))
_SESSION_DAYS = int(os.getenv("SIGQ_AUTH_SESSION_DAYS", "14"))
_LOCK = threading.RLock()
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_PHONE_RE = re.compile(r"^\+?[0-9]{8,15}$")


class RegisterBody(BaseModel):
    identifier: str = Field(min_length=3, max_length=190)
    password: str = Field(min_length=8, max_length=128)


class LoginBody(BaseModel):
    identifier: str = Field(min_length=3, max_length=190)
    password: str = Field(min_length=8, max_length=128)


class UserActionBody(BaseModel):
    userId: int


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_identifier(value: str) -> tuple[str, str]:
    raw = (value or "").strip()
    if "@" in raw:
        normalized = raw.lower()
        if not _EMAIL_RE.match(normalized):
            raise HTTPException(status_code=400, detail="Enter a valid email address.")
        return normalized, "email"
    phone = re.sub(r"[\s()\-]", "", raw)
    if not _PHONE_RE.match(phone):
        raise HTTPException(status_code=400, detail="Enter a valid email address or phone number.")
    return phone, "phone"


def _connect() -> sqlite3.Connection:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_DB_PATH), timeout=10, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _init_db() -> None:
    with _LOCK, _connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS access_users (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              identifier TEXT NOT NULL UNIQUE,
              identifier_type TEXT NOT NULL,
              password_hash TEXT NOT NULL,
              password_salt TEXT NOT NULL,
              status TEXT NOT NULL DEFAULT 'PENDING',
              is_admin INTEGER NOT NULL DEFAULT 0,
              created_at TEXT NOT NULL,
              approved_at TEXT,
              approved_by INTEGER,
              last_login_at TEXT
            );
            CREATE TABLE IF NOT EXISTS access_sessions (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              user_id INTEGER NOT NULL,
              token_hash TEXT NOT NULL UNIQUE,
              created_at TEXT NOT NULL,
              expires_at TEXT NOT NULL,
              revoked_at TEXT,
              FOREIGN KEY(user_id) REFERENCES access_users(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_access_sessions_token
              ON access_sessions(token_hash);
            CREATE INDEX IF NOT EXISTS idx_access_users_status
              ON access_users(status);
            """
        )
        conn.commit()
    _ensure_admin()


def _hash_password(password: str, salt: bytes | None = None) -> tuple[str, str]:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 240_000)
    return digest.hex(), salt.hex()


def _verify_password(password: str, expected_hex: str, salt_hex: str) -> bool:
    actual, _ = _hash_password(password, bytes.fromhex(salt_hex))
    return hmac.compare_digest(actual, expected_hex)


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _ensure_admin() -> None:
    identifier = (os.getenv("SIGQ_ADMIN_IDENTIFIER") or "").strip()
    password = os.getenv("SIGQ_ADMIN_PASSWORD") or ""
    if not identifier or not password:
        return
    normalized, kind = _normalize_identifier(identifier)
    pw_hash, salt = _hash_password(password)
    with _LOCK, _connect() as conn:
        row = conn.execute(
            "SELECT id FROM access_users WHERE identifier = ?",
            (normalized,),
        ).fetchone()
        if row:
            conn.execute(
                """
                UPDATE access_users
                   SET password_hash = ?, password_salt = ?, status = 'APPROVED',
                       is_admin = 1, approved_at = COALESCE(approved_at, ?)
                 WHERE id = ?
                """,
                (pw_hash, salt, _now(), int(row["id"])),
            )
        else:
            conn.execute(
                """
                INSERT INTO access_users
                  (identifier, identifier_type, password_hash, password_salt,
                   status, is_admin, created_at, approved_at)
                VALUES (?, ?, ?, ?, 'APPROVED', 1, ?, ?)
                """,
                (normalized, kind, pw_hash, salt, _now(), _now()),
            )
        conn.commit()


def _token_from_request(
    request: Request,
    authorization: str | None,
) -> str | None:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization.split(" ", 1)[1].strip()
    return request.cookies.get("sigq_session")


def _session_user(token: str | None) -> dict[str, Any] | None:
    if not token:
        return None
    token_hash = _hash_token(token)
    with _LOCK, _connect() as conn:
        row = conn.execute(
            """
            SELECT u.id, u.identifier, u.identifier_type, u.status, u.is_admin,
                   s.expires_at, s.revoked_at
              FROM access_sessions s
              JOIN access_users u ON u.id = s.user_id
             WHERE s.token_hash = ?
            """,
            (token_hash,),
        ).fetchone()
    if not row or row["revoked_at"]:
        return None
    try:
        if datetime.fromisoformat(str(row["expires_at"])) <= datetime.now(timezone.utc):
            return None
    except ValueError:
        return None
    if str(row["status"]) != "APPROVED":
        return None
    return {
        "id": int(row["id"]),
        "identifier": str(row["identifier"]),
        "identifierType": str(row["identifier_type"]),
        "status": str(row["status"]),
        "isAdmin": bool(row["is_admin"]),
        "expiresAt": str(row["expires_at"]),
    }


def _require_user(request: Request, authorization: str | None) -> dict[str, Any]:
    user = _session_user(_token_from_request(request, authorization))
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required.")
    return user


def _require_admin(request: Request, authorization: str | None) -> dict[str, Any]:
    user = _require_user(request, authorization)
    if not user.get("isAdmin"):
        raise HTTPException(status_code=403, detail="Administrator approval required.")
    return user


def create_access_router() -> APIRouter:
    _init_db()
    router = APIRouter(prefix="/api/auth", tags=["access"])

    @router.post("/register")
    def register(body: RegisterBody) -> dict[str, Any]:
        identifier, kind = _normalize_identifier(body.identifier)
        pw_hash, salt = _hash_password(body.password)
        with _LOCK, _connect() as conn:
            existing = conn.execute(
                "SELECT id, status FROM access_users WHERE identifier = ?",
                (identifier,),
            ).fetchone()
            if existing:
                status = str(existing["status"])
                if status == "REJECTED":
                    conn.execute(
                        """
                        UPDATE access_users
                           SET password_hash = ?, password_salt = ?, status = 'PENDING',
                               created_at = ?, approved_at = NULL, approved_by = NULL
                         WHERE id = ?
                        """,
                        (pw_hash, salt, _now(), int(existing["id"])),
                    )
                    conn.commit()
                    return {"success": True, "status": "PENDING"}
                raise HTTPException(
                    status_code=409,
                    detail="An account already exists for this email or phone.",
                )
            conn.execute(
                """
                INSERT INTO access_users
                  (identifier, identifier_type, password_hash, password_salt,
                   status, is_admin, created_at)
                VALUES (?, ?, ?, ?, 'PENDING', 0, ?)
                """,
                (identifier, kind, pw_hash, salt, _now()),
            )
            conn.commit()
        return {"success": True, "status": "PENDING"}

    @router.post("/login")
    def login(body: LoginBody) -> dict[str, Any]:
        identifier, _ = _normalize_identifier(body.identifier)
        with _LOCK, _connect() as conn:
            row = conn.execute(
                """
                SELECT id, identifier, identifier_type, password_hash,
                       password_salt, status, is_admin
                  FROM access_users
                 WHERE identifier = ?
                """,
                (identifier,),
            ).fetchone()
            if not row or not _verify_password(
                body.password,
                str(row["password_hash"]),
                str(row["password_salt"]),
            ):
                raise HTTPException(status_code=401, detail="Invalid email/phone or password.")
            status = str(row["status"])
            if status == "PENDING":
                raise HTTPException(status_code=403, detail="Your access request is waiting for approval.")
            if status == "REJECTED":
                raise HTTPException(status_code=403, detail="Your access request was not approved.")
            token = secrets.token_urlsafe(48)
            created = datetime.now(timezone.utc)
            expires = created + timedelta(days=_SESSION_DAYS)
            conn.execute(
                """
                INSERT INTO access_sessions
                  (user_id, token_hash, created_at, expires_at)
                VALUES (?, ?, ?, ?)
                """,
                (int(row["id"]), _hash_token(token), created.isoformat(), expires.isoformat()),
            )
            conn.execute(
                "UPDATE access_users SET last_login_at = ? WHERE id = ?",
                (created.isoformat(), int(row["id"])),
            )
            conn.commit()
        return {
            "success": True,
            "token": token,
            "expiresAt": expires.isoformat(),
            "user": {
                "id": int(row["id"]),
                "identifier": str(row["identifier"]),
                "identifierType": str(row["identifier_type"]),
                "status": status,
                "isAdmin": bool(row["is_admin"]),
            },
        }

    @router.get("/session")
    def session(
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        user = _session_user(_token_from_request(request, authorization))
        return {"authenticated": bool(user), "user": user}

    @router.post("/logout")
    def logout(
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        token = _token_from_request(request, authorization)
        if token:
            with _LOCK, _connect() as conn:
                conn.execute(
                    "UPDATE access_sessions SET revoked_at = ? WHERE token_hash = ?",
                    (_now(), _hash_token(token)),
                )
                conn.commit()
        return {"success": True}

    @router.get("/admin/users")
    def admin_users(
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        _require_admin(request, authorization)
        with _LOCK, _connect() as conn:
            rows = conn.execute(
                """
                SELECT id, identifier, identifier_type, status, is_admin,
                       created_at, approved_at, last_login_at
                  FROM access_users
                 ORDER BY
                   CASE status WHEN 'PENDING' THEN 0 WHEN 'APPROVED' THEN 1 ELSE 2 END,
                   created_at DESC
                """
            ).fetchall()
        return {
            "success": True,
            "users": [
                {
                    "id": int(row["id"]),
                    "identifier": str(row["identifier"]),
                    "identifierType": str(row["identifier_type"]),
                    "status": str(row["status"]),
                    "isAdmin": bool(row["is_admin"]),
                    "createdAt": row["created_at"],
                    "approvedAt": row["approved_at"],
                    "lastLoginAt": row["last_login_at"],
                }
                for row in rows
            ],
        }

    @router.post("/admin/approve")
    def approve(
        body: UserActionBody,
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        admin = _require_admin(request, authorization)
        with _LOCK, _connect() as conn:
            cur = conn.execute(
                """
                UPDATE access_users
                   SET status = 'APPROVED', approved_at = ?, approved_by = ?
                 WHERE id = ? AND is_admin = 0
                """,
                (_now(), int(admin["id"]), body.userId),
            )
            conn.commit()
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="User not found or cannot be changed.")
        return {"success": True, "status": "APPROVED"}

    @router.post("/admin/reject")
    def reject(
        body: UserActionBody,
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        admin = _require_admin(request, authorization)
        with _LOCK, _connect() as conn:
            cur = conn.execute(
                """
                UPDATE access_users
                   SET status = 'REJECTED', approved_at = NULL, approved_by = ?
                 WHERE id = ? AND is_admin = 0
                """,
                (int(admin["id"]), body.userId),
            )
            conn.execute(
                """
                UPDATE access_sessions SET revoked_at = ?
                 WHERE user_id = ? AND revoked_at IS NULL
                """,
                (_now(), body.userId),
            )
            conn.commit()
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="User not found or cannot be changed.")
        return {"success": True, "status": "REJECTED"}

    return router
