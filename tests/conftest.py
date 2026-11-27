"""Тесты гоняются на настоящем Postgres: TEST_DATABASE_URL (база очищается!)."""
from __future__ import annotations

import os
import socket
import threading
import time

import pytest

TEST_DB = os.environ.get("TEST_DATABASE_URL", "")


def _free_port() -> int:
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    return port


PORT = _free_port()
BASE = f"http://127.0.0.1:{PORT}"
os.environ["DATABASE_URL"] = TEST_DB
# первый сервер нарочно мёртвый: агент должен перейти на запасной
os.environ["OVERPASS_URL"] = "http://127.0.0.1:9/dead," + BASE + "/overpass"
os.environ["NOMINATIM_URL"] = BASE + "/nominatim"

from app.passwords import hash_password  # noqa: E402

PASSWORD = "correct horse"
os.environ["PASSWORD_HASH"] = hash_password(PASSWORD)


@pytest.fixture(scope="session")
def fake_server():
    import uvicorn
    from tests import fake_world
    fake_world.BASE = BASE
    server = uvicorn.Server(uvicorn.Config(fake_world.fake, host="127.0.0.1", port=PORT, log_level="warning"))
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    yield fake_world
    server.should_exit = True


@pytest.fixture()
def clean_db():
    if not TEST_DB:
        pytest.skip("нет TEST_DATABASE_URL")
    import psycopg
    with psycopg.connect(TEST_DB, autocommit=True) as c:
        c.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
    from app import main
    main.DbState.ready = False
    main.DbState.last_try = 0
    yield
