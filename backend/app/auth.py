"""Password hashing, sessions and role checks."""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import HTTPException, Request, Response

COOKIE_NAME = "ruleshelf_session"
SESSION_DAYS = 30
PBKDF2_ITERATIONS = 600_000
ROLES = {"admin", "viewer"}

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def utcnow_dt() -> datetime:
    return datetime.now(timezone.utc)


def iso(value: datetime) -> str:
    return value.isoformat(timespec="seconds")


def normalize_email(email: str) -> str:
    return email.strip().lower()


def validate_email(email: str) -> str:
    email = normalize_email(email)
    if not _EMAIL_RE.match(email) or len(email) > 254:
        raise ValueError("Enter a valid email address.")
    return email


def hash_password(password: str) -> str:
    if len(password) < 8:
        raise ValueError("Password must be at least 8 characters.")
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS
    )
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, iterations, salt_hex, digest_hex = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            bytes.fromhex(salt_hex),
            int(iterations),
        )
        return hmac.compare_digest(digest.hex(), digest_hex)
    except (ValueError, TypeError):
        return False


def public_user(row: Any) -> dict:
    return {
        "id": row["id"],
        "email": row["email"],
        "role": row["role"],
        "active": bool(row["active"]),
        "created_at": row["created_at"],
    }


def create_user(
    conn, email: str, password: str, role: str = "viewer", active: bool = True
) -> Any:
    email = validate_email(email)
    if role not in ROLES:
        raise ValueError("Role must be admin or viewer.")
    if conn.execute("SELECT 1 FROM users WHERE email = ?", (email,)).fetchone():
        raise ValueError("A user with that email already exists.")
    user_id = secrets.token_hex(8)
    conn.execute(
        "INSERT INTO users (id, email, password_hash, role, active, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (user_id, email, hash_password(password), role, 1 if active else 0, iso(utcnow_dt())),
    )
    return conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()


def authenticate(conn, email: str, password: str) -> Any | None:
    row = conn.execute(
        "SELECT * FROM users WHERE email = ? AND active = 1",
        (normalize_email(email),),
    ).fetchone()
    if not row or not verify_password(password, row["password_hash"]):
        return None
    return row


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_session(conn, user_id: str, days: int = SESSION_DAYS) -> str:
    token = secrets.token_urlsafe(32)
    now = utcnow_dt()
    expires = now + timedelta(days=days)
    conn.execute(
        "DELETE FROM sessions WHERE expires_at < ?", (iso(now),)
    )
    conn.execute(
        "INSERT INTO sessions (token_hash, user_id, created_at, expires_at) "
        "VALUES (?, ?, ?, ?)",
        (_token_hash(token), user_id, iso(now), iso(expires)),
    )
    return token


def delete_session(conn, token: str | None) -> None:
    if token:
        conn.execute("DELETE FROM sessions WHERE token_hash = ?", (_token_hash(token),))


def delete_user_sessions(conn, user_id: str, except_token: str | None = None) -> None:
    if except_token:
        conn.execute(
            "DELETE FROM sessions WHERE user_id = ? AND token_hash != ?",
            (user_id, _token_hash(except_token)),
        )
    else:
        conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))


def user_from_token(conn, token: str | None) -> Any | None:
    if not token:
        return None
    row = conn.execute(
        """
        SELECT u.* FROM sessions s
        JOIN users u ON u.id = s.user_id
        WHERE s.token_hash = ? AND s.expires_at >= ? AND u.active = 1
        """,
        (_token_hash(token), iso(utcnow_dt())),
    ).fetchone()
    return row


def cookie_secure(request: Request) -> bool:
    forwarded = (request.headers.get("x-forwarded-proto") or "").split(",")[0].strip()
    return forwarded == "https" or request.url.scheme == "https"


def set_session_cookie(response: Response, token: str, request: Request) -> None:
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=SESSION_DAYS * 24 * 60 * 60,
        httponly=True,
        samesite="lax",
        secure=cookie_secure(request),
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(COOKIE_NAME, path="/")


def require_user(request: Request) -> dict:
    user = getattr(request.state, "user", None)
    if not user:
        raise HTTPException(401, "Sign in to continue.")
    return user


def require_admin(request: Request) -> dict:
    user = require_user(request)
    if user.get("role") != "admin":
        raise HTTPException(403, "Administrator access is required.")
    return user
