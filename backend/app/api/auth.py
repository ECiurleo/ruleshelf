"""Login, logout, current user and self-service password change."""

from __future__ import annotations

import time

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from app.auth import (
    COOKIE_NAME,
    authenticate,
    clear_session_cookie,
    create_session,
    delete_session,
    hash_password,
    iso,
    public_user,
    require_user,
    set_session_cookie,
    user_from_token,
    utcnow_dt,
    verify_password,
)
from app.db import db

router = APIRouter(prefix="/api/auth", tags=["auth"])

# Very small login throttle: 10 failures per key per 5 minutes.
_ATTEMPTS: dict[str, list[float]] = {}
_WINDOW = 300
_LIMIT = 10


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=128)


class PasswordChange(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


def _attempt_key(request: Request, email: str) -> str:
    forwarded = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
    ip = forwarded or (request.client.host if request.client else "unknown")
    return f"{ip}|{email.strip().lower()}"


def _check_throttle(key: str) -> None:
    now = time.time()
    attempts = [value for value in _ATTEMPTS.get(key, []) if now - value < _WINDOW]
    _ATTEMPTS[key] = attempts
    if len(attempts) >= _LIMIT:
        raise HTTPException(429, "Too many login attempts. Try again in a few minutes.")


def _record_failure(key: str) -> None:
    _ATTEMPTS.setdefault(key, []).append(time.time())


@router.post("/login")
def login(payload: LoginRequest, request: Request, response: Response):
    key = _attempt_key(request, payload.email)
    _check_throttle(key)
    with db() as conn:
        row = authenticate(conn, payload.email, payload.password)
        if not row:
            _record_failure(key)
            raise HTTPException(401, "Incorrect email or password.")
        token = create_session(conn, row["id"])
        user = public_user(row)
    _ATTEMPTS.pop(key, None)
    set_session_cookie(response, token, request)
    return {"user": user}


@router.get("/me")
def me(request: Request):
    with db() as conn:
        row = user_from_token(conn, request.cookies.get(COOKIE_NAME))
        if not row:
            raise HTTPException(401, "Sign in to continue.")
        return {"user": public_user(row)}


@router.post("/logout")
def logout(request: Request, response: Response):
    with db() as conn:
        delete_session(conn, request.cookies.get(COOKIE_NAME))
    clear_session_cookie(response)
    return {"ok": True}


@router.post("/password")
def change_password(payload: PasswordChange, request: Request):
    user = require_user(request)
    with db() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user["id"],)).fetchone()
        if not row or not verify_password(payload.current_password, row["password_hash"]):
            raise HTTPException(400, "Current password is incorrect.")
        if payload.current_password == payload.new_password:
            raise HTTPException(400, "Choose a different new password.")
        conn.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?",
            (hash_password(payload.new_password), user["id"]),
        )
        delete_session_except = request.cookies.get(COOKIE_NAME)
        from app.auth import delete_user_sessions

        delete_user_sessions(conn, user["id"], except_token=delete_session_except)
    return {"ok": True}


@router.get("/session-debug", include_in_schema=False)
def _session_debug(request: Request):
    # Deliberately minimal and authenticated; useful when diagnosing a proxy.
    user = require_user(request)
    return {"user": user, "now": iso(utcnow_dt())}
