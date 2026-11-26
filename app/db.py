"""Подключение к Postgres (Supabase). Соединение открывается на каждую операцию:
на Free-тарифе запросов мало, а пул через Supabase Session pooler не нужен."""
from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app import config

__all__ = ["connect", "fetch_one", "fetch_all", "execute", "Jsonb", "DbNotConfigured"]


class DbNotConfigured(RuntimeError):
    pass


@contextmanager
def connect() -> Iterator[psycopg.Connection]:
    if not config.DATABASE_URL:
        raise DbNotConfigured("Не задана переменная DATABASE_URL — сайт не знает, где база.")
    # prepare_threshold=None: пулеры Supabase не любят подготовленные запросы.
    with psycopg.connect(config.DATABASE_URL, row_factory=dict_row, autocommit=True,
                         prepare_threshold=None, connect_timeout=15) as conn:
        yield conn


def fetch_one(sql: str, params: Any = None) -> dict | None:
    with connect() as c:
        return c.execute(sql, params).fetchone()


def fetch_all(sql: str, params: Any = None) -> list[dict]:
    with connect() as c:
        return c.execute(sql, params).fetchall()


def execute(sql: str, params: Any = None) -> int:
    with connect() as c:
        return c.execute(sql, params).rowcount
