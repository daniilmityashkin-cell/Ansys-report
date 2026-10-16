"""Подключение к БД (SQLAlchemy 2). SQLite для старта; для боевого сервера - PostgreSQL через ASR_DB_URL."""
from __future__ import annotations
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker


class Base(DeclarativeBase):
    pass


def make_session_factory(url: str):
    kw = {"connect_args": {"check_same_thread": False}} if url.startswith("sqlite") else {}
    engine = create_engine(url, future=True, **kw)
    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine, expire_on_commit=False, future=True)
