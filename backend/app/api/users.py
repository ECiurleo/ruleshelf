"""Administrator user management."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.auth import (
    ROLES,
    create_user,
    delete_user_sessions,
    hash_password,
    public_user,
    require_admin,
    validate_email,
)
from app.db import db

router = APIRouter(
    prefix="/api/users",
    tags=["users"],
    dependencies=[Depends(require_admin)],
)


class UserCreate(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=8, max_length=128)
    role: str = "viewer"


class UserUpdate(BaseModel):
    email: str | None = Field(default=None, min_length=3, max_length=254)
    password: str | None = Field(default=None, min_length=8, max_length=128)
    role: str | None = None
    active: bool | None = None


def _active_admin_count(conn: sqlite3.Connection, exclude_id: str | None = None) -> int:
    if exclude_id:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM users WHERE role = 'admin' AND active = 1 AND id != ?",
            (exclude_id,),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM users WHERE role = 'admin' AND active = 1"
        ).fetchone()
    return row["n"] if row else 0


@router.get("")
def list_users():
    with db() as conn:
        rows = conn.execute("SELECT * FROM users ORDER BY lower(email)").fetchall()
        return {"users": [public_user(row) for row in rows]}


@router.post("", status_code=201)
def add_user(payload: UserCreate):
    if payload.role not in ROLES:
        raise HTTPException(400, "Role must be admin or viewer.")
    try:
        email = validate_email(payload.email)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    try:
        with db() as conn:
            row = create_user(conn, email, payload.password, payload.role)
            return public_user(row)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.patch("/{user_id}")
def update_user(user_id: str, payload: UserUpdate, admin: dict = Depends(require_admin)):
    fields = payload.model_dump(exclude_unset=True)
    with db() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if not row:
            raise HTTPException(404, "User not found.")

        if "role" in fields:
            if fields["role"] not in ROLES:
                raise HTTPException(400, "Role must be admin or viewer.")
            if row["role"] == "admin" and fields["role"] != "admin":
                if _active_admin_count(conn, exclude_id=user_id) == 0:
                    raise HTTPException(400, "At least one active administrator is required.")
            if user_id == admin["id"] and fields["role"] != "admin":
                raise HTTPException(400, "You cannot remove your own administrator role.")
        if fields.get("active") is False:
            if user_id == admin["id"]:
                raise HTTPException(400, "You cannot deactivate your own account.")
            if row["role"] == "admin" and _active_admin_count(conn, exclude_id=user_id) == 0:
                raise HTTPException(400, "At least one active administrator is required.")
        if "email" in fields and fields["email"] is not None:
            try:
                fields["email"] = validate_email(fields["email"])
            except ValueError as exc:
                raise HTTPException(400, str(exc)) from exc
        if "password" in fields and fields["password"] is not None:
            fields["password_hash"] = hash_password(fields["password"])
            fields.pop("password")
            delete_user_sessions(conn, user_id)
        if "active" in fields and fields["active"] is not None:
            fields["active"] = 1 if fields["active"] else 0

        if fields:
            assignments = ", ".join(f"{key} = ?" for key in fields)
            try:
                conn.execute(
                    f"UPDATE users SET {assignments} WHERE id = ?",
                    [*fields.values(), user_id],
                )
            except sqlite3.IntegrityError as exc:
                raise HTTPException(409, "That email is already in use.") from exc
            if "active" in fields and not fields["active"]:
                delete_user_sessions(conn, user_id)

        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return public_user(row)


@router.delete("/{user_id}")
def delete_user(user_id: str, admin: dict = Depends(require_admin)):
    if user_id == admin["id"]:
        raise HTTPException(400, "You cannot delete your own account.")
    with db() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if not row:
            raise HTTPException(404, "User not found.")
        if row["role"] == "admin" and _active_admin_count(conn, exclude_id=user_id) == 0:
            raise HTTPException(400, "At least one active administrator is required.")
        delete_user_sessions(conn, user_id)
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
    return {"deleted": True}
