"""Bootstrap the local Postgres database used by the project.

Passwords are read from environment variables or prompted interactively so
credentials do not need to live in the repository.
"""

from __future__ import annotations

import os
from getpass import getpass

import psycopg2
from psycopg2 import sql


def _get_password(env_name: str, prompt: str) -> str | None:
    value = os.getenv(env_name)
    if value is not None:
        return value

    value = getpass(prompt)
    return value or None


def main() -> None:
    admin_host = os.getenv("POSTGRES_HOST", "localhost")
    admin_port = int(os.getenv("POSTGRES_PORT", "5432"))
    admin_db = os.getenv("POSTGRES_DB", "postgres")
    admin_user = os.getenv("POSTGRES_ADMIN_USER", "postgres")
    admin_password = _get_password("POSTGRES_ADMIN_PASSWORD", "Postgres admin password: ")

    app_db = os.getenv("BORSA_DB_NAME", "borsa")
    app_user = os.getenv("BORSA_DB_USER", "borsa")
    app_password = _get_password("BORSA_DB_PASSWORD", "Borsa DB password: ")

    conn = None
    try:
        conn_kwargs = {
            "host": admin_host,
            "port": admin_port,
            "database": admin_db,
            "user": admin_user,
        }
        if admin_password is not None:
            conn_kwargs["password"] = admin_password

        conn = psycopg2.connect(**conn_kwargs)
        conn.set_client_encoding("UTF8")
        conn.autocommit = True
        cur = conn.cursor()

        if app_password is None:
            create_user_sql = sql.SQL("CREATE USER {}").format(sql.Identifier(app_user))
            alter_user_sql = sql.SQL("ALTER USER {}").format(sql.Identifier(app_user))
            password_msg = "without password"
        else:
            create_user_sql = sql.SQL("CREATE USER {} WITH PASSWORD %s").format(sql.Identifier(app_user))
            alter_user_sql = sql.SQL("ALTER USER {} WITH PASSWORD %s").format(sql.Identifier(app_user))
            password_msg = "password updated"

        try:
            if app_password is None:
                cur.execute(create_user_sql)
            else:
                cur.execute(create_user_sql, (app_password,))
            print(f"User {app_user!r} created {password_msg}")
        except psycopg2.errors.DuplicateObject:
            if app_password is None:
                cur.execute(alter_user_sql)
            else:
                cur.execute(alter_user_sql, (app_password,))
            print(f"User {app_user!r} already exists; {password_msg}")

        try:
            cur.execute(
                sql.SQL("CREATE DATABASE {} OWNER {}").format(
                    sql.Identifier(app_db),
                    sql.Identifier(app_user),
                )
            )
            print(f"Database {app_db!r} created")
        except psycopg2.errors.DuplicateDatabase:
            print(f"Database {app_db!r} already exists")

        cur.execute(
            sql.SQL("ALTER DATABASE {} OWNER TO {}").format(
                sql.Identifier(app_db),
                sql.Identifier(app_user),
            )
        )
        cur.execute(
            sql.SQL("GRANT ALL PRIVILEGES ON DATABASE {} TO {}").format(
                sql.Identifier(app_db),
                sql.Identifier(app_user),
            )
        )
        print("Privileges granted")
        print("Setup complete!")
    finally:
        if "cur" in locals():
            cur.close()
        if conn is not None:
            conn.close()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("Error:", exc)
