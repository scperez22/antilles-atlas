from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import settings

engine = create_engine(settings.database_url, echo=False, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    """Shared declarative base. All models (polity, claim, source, etc.)
    will subclass this once schema design begins in Phase 2."""

    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
