"""Миграции: файлы migrations/NNN_название.sql применяются по порядку, один раз.

Какие уже применены, записано в таблице schema_migrations. Чтобы поменять таблицы,
добавь новый файл со следующим номером; старые файлы не правь.
"""
from __future__ import annotations

from pathlib import Path

from app.db import connect

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"
LOCK_ID = 774411  # любой постоянный номер: два процесса не применят миграции одновременно


def migrate() -> list[str]:
    applied_now: list[str] = []
    with connect() as c:
        c.execute("SELECT pg_advisory_lock(%s)", (LOCK_ID,))
        try:
            c.execute("""CREATE TABLE IF NOT EXISTS schema_migrations (
                name text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())""")
            done = {r["name"] for r in c.execute("SELECT name FROM schema_migrations").fetchall()}
            for f in sorted(MIGRATIONS_DIR.glob("*.sql")):
                if f.name in done:
                    continue
                with c.transaction():
                    c.execute(f.read_text(encoding="utf-8"))
                    c.execute("INSERT INTO schema_migrations(name) VALUES (%s)", (f.name,))
                applied_now.append(f.name)
        finally:
            c.execute("SELECT pg_advisory_unlock(%s)", (LOCK_ID,))
    return applied_now
