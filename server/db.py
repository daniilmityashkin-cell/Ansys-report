"""Подключение к БД (SQLAlchemy 2). SQLite для старта; для боевого сервера - PostgreSQL через ASR_DB_URL."""
from __future__ import annotations
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker


class Base(DeclarativeBase):
    pass


def make_session_factory(url: str):
    kw = {"connect_args": {"check_same_thread": False}} if url.startswith("sqlite") else {}
    engine = create_engine(url, future=True, **kw)
    Base.metadata.create_all(engine)
    _add_missing_columns(engine)
    return engine, sessionmaker(bind=engine, expire_on_commit=False, future=True)


def _add_missing_columns(engine):
    """Простая миграция: новые столбцы добавляются в уже существующие таблицы (без потери данных)."""
    insp = inspect(engine)
    with engine.begin() as con:
        for table in Base.metadata.sorted_tables:
            if not insp.has_table(table.name):
                continue
            have = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name not in have:
                    con.execute(text(f'ALTER TABLE {table.name} ADD COLUMN {col.name} {col.type.compile(engine.dialect)}'))
        if insp.has_table("users"):
            con.execute(text("UPDATE users SET email_key = email WHERE email_key IS NULL"))
