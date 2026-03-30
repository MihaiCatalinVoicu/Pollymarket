from __future__ import annotations

from sqlalchemy import create_engine

from src.storage.models import Base


def create_db_engine(database_url: str):
    return create_engine(database_url, future=True)


def ensure_schema(database_url: str) -> None:
    engine = create_db_engine(database_url)
    Base.metadata.create_all(engine)

