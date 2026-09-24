"""Tests run against the real PostGIS database (make up && make migrate first).

Each test runs inside a transaction that is rolled back afterwards, so tests
never leave data behind and never see each other's rows.
"""

import pytest
from sqlalchemy.orm import Session

from app.db import engine


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
