"""Tests run against a SEPARATE database, <your db name>_test, never your dev data.

Why: once real seed data is loaded (make load-seed), tests that insert keys like
"C002" or "xaragua" collide with it, and spatial queries start returning the
real polygons. The test database is created and migrated automatically.

Each test still runs inside a transaction that is rolled back afterwards.
"""

import pathlib

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.config import settings

# Repoint settings BEFORE app.db is imported (it builds its engine at import).
_url = make_url(settings.database_url)
if not _url.database.endswith("_test"):
    _url = _url.set(database=f"{_url.database}_test")
settings.database_url = _url.render_as_string(hide_password=False)

from app.db import engine  # noqa: E402

assert engine.url.database.endswith("_test"), "refusing to run tests against a non-test database"

ROOT = pathlib.Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session", autouse=True)
def _test_database():
    admin = create_engine(_url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        exists = conn.scalar(text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": _url.database})
        if not exists:
            conn.execute(text(f'CREATE DATABASE "{_url.database}"'))
    admin.dispose()

    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))

    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "alembic"))
    command.upgrade(cfg, "head")
    yield


@pytest.fixture
def db():
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()