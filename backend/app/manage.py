"""Small admin CLI for bootstrapping and recovering users.

Examples (inside the container):
  python -m app.manage list-users
  python -m app.manage create-user admin@example.com --role admin
  python -m app.manage reset-password admin@example.com
  RULESHELF_PASSWORD='...' python -m app.manage create-user ...

Passwords are read from RULESHELF_PASSWORD or prompted for, never logged.
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys

from app.auth import (
    create_user,
    delete_user_sessions,
    hash_password,
    validate_email,
)
from app.db import db, init_db


def _password(explicit: str | None) -> str:
    value = explicit or os.environ.get("RULESHELF_PASSWORD") or ""
    if not value:
        value = getpass.getpass("Password: ")
    if len(value) < 8:
        raise SystemExit("Password must be at least 8 characters.")
    return value


def cmd_list(_args) -> None:
    with db() as conn:
        rows = conn.execute("SELECT * FROM users ORDER BY lower(email)").fetchall()
    if not rows:
        print("No users.")
        return
    for row in rows:
        print(f"{row['email']:40} {row['role']:7} active={bool(row['active'])}")


def cmd_create(args) -> None:
    with db() as conn:
        try:
            row = create_user(conn, args.email, _password(args.password), args.role)
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc
    print(f"Created {row['role']} {row['email']}")


def cmd_reset(args) -> None:
    email = validate_email(args.email)
    with db() as conn:
        row = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        if not row:
            raise SystemExit("User not found.")
        conn.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?",
            (hash_password(_password(args.password)), row["id"]),
        )
        delete_user_sessions(conn, row["id"])
    print(f"Password reset for {email}; existing sessions revoked.")


def cmd_delete(args) -> None:
    email = validate_email(args.email)
    with db() as conn:
        row = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        if not row:
            raise SystemExit("User not found.")
        if row["role"] == "admin":
            count = conn.execute(
                "SELECT COUNT(*) AS n FROM users WHERE role = 'admin' AND active = 1 AND id != ?",
                (row["id"],),
            ).fetchone()["n"]
            if count == 0:
                raise SystemExit("Refusing to delete the last active administrator.")
        delete_user_sessions(conn, row["id"])
        conn.execute("DELETE FROM users WHERE id = ?", (row["id"],))
    print(f"Deleted {email}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Ruleshelf user administration")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("list-users")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("create-user")
    p.add_argument("email")
    p.add_argument("--role", choices=["admin", "viewer"], default="viewer")
    p.add_argument("--password")
    p.set_defaults(func=cmd_create)

    p = sub.add_parser("reset-password")
    p.add_argument("email")
    p.add_argument("--password")
    p.set_defaults(func=cmd_reset)

    p = sub.add_parser("delete-user")
    p.add_argument("email")
    p.set_defaults(func=cmd_delete)

    args = parser.parse_args(argv)
    init_db()
    args.func(args)


if __name__ == "__main__":
    main(sys.argv[1:])
