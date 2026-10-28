"""Данные CRM: менеджеры, контакты, сделки, задачи, история взаимодействий, визиты сайта, сегменты, журнал событий API."""
from __future__ import annotations
import datetime as dt
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker

# этапы воронки по порядку; автоматически сделка двигается только вперёд
STAGES = ["Новый лид", "Связались", "Замеры загружены", "Готовит расчёт", "Ожидает оплаты", "Оплачено", "Отчёт выдан", "Проигран"]
WON, LOST = "Отчёт выдан", "Проигран"
OPEN_STAGES = [s for s in STAGES if s not in (WON, LOST)]


def now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class Manager(Base):
    __tablename__ = "managers"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120), default="")
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), default="manager")        # admin | manager
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created: Mapped[dt.datetime] = mapped_column(DateTime, default=now)


class Contact(Base):
    __tablename__ = "contacts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    site_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True, unique=True, index=True)
    email: Mapped[str | None] = mapped_column(String(254), nullable=True, index=True)
    phone: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    company: Mapped[str | None] = mapped_column(String(200), nullable=True)
    region: Mapped[str | None] = mapped_column(String(120), nullable=True)
    tags: Mapped[str] = mapped_column(String(500), default="")             # через запятую
    source: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    utm_medium: Mapped[str | None] = mapped_column(String(120), nullable=True)
    utm_campaign: Mapped[str | None] = mapped_column(String(200), nullable=True)
    referrer: Mapped[str | None] = mapped_column(String(500), nullable=True)
    landing: Mapped[str | None] = mapped_column(String(300), nullable=True, index=True)
    visitor: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("managers.id"), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created: Mapped[dt.datetime] = mapped_column(DateTime, default=now, index=True)
    last_activity: Mapped[dt.datetime] = mapped_column(DateTime, default=now, index=True)
    deals: Mapped[list["Deal"]] = relationship(back_populates="contact", order_by="Deal.id.desc()")
    owner: Mapped[Manager | None] = relationship()

    @property
    def title(self) -> str:
        return self.name or self.email or self.phone or f"Контакт №{self.id}"

    @property
    def tag_list(self) -> list[str]:
        return [t.strip() for t in self.tags.split(",") if t.strip()]


class Deal(Base):
    __tablename__ = "deals"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    contact_id: Mapped[int] = mapped_column(ForeignKey("contacts.id"), index=True)
    title: Mapped[str] = mapped_column(String(200), default="")
    stage: Mapped[str] = mapped_column(String(40), default=STAGES[0], index=True)
    amount: Mapped[int] = mapped_column(Integer, default=0)                 # ₽, сумма оплат по сделке
    source: Mapped[str | None] = mapped_column(String(120), nullable=True)
    site_generation_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("managers.id"), nullable=True)
    lost_reason: Mapped[str | None] = mapped_column(String(300), nullable=True)
    created: Mapped[dt.datetime] = mapped_column(DateTime, default=now, index=True)
    stage_changed: Mapped[dt.datetime] = mapped_column(DateTime, default=now)
    paid_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    closed_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    contact: Mapped[Contact] = relationship(back_populates="deals")
    owner: Mapped[Manager | None] = relationship()


class Task(Base):
    __tablename__ = "tasks"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(300))
    contact_id: Mapped[int | None] = mapped_column(ForeignKey("contacts.id"), nullable=True, index=True)
    deal_id: Mapped[int | None] = mapped_column(ForeignKey("deals.id"), nullable=True, index=True)
    assignee_id: Mapped[int | None] = mapped_column(ForeignKey("managers.id"), nullable=True, index=True)
    due: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    done: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    done_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    auto: Mapped[str | None] = mapped_column(String(40), nullable=True)    # каким сценарием создана (call_lead, unpaid, job_error …)
    priority: Mapped[str] = mapped_column(String(10), default="normal")    # normal | high
    created: Mapped[dt.datetime] = mapped_column(DateTime, default=now)
    contact: Mapped[Contact | None] = relationship()
    deal: Mapped[Deal | None] = relationship()
    assignee: Mapped[Manager | None] = relationship()

    @property
    def overdue(self) -> bool:
        return (not self.done) and self.due is not None and self.due < now()


class Activity(Base):
    """История взаимодействий: действия на сайте, звонки, письма, заметки, смена этапа, оплаты."""
    __tablename__ = "activities"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    contact_id: Mapped[int | None] = mapped_column(ForeignKey("contacts.id"), nullable=True, index=True)
    deal_id: Mapped[int | None] = mapped_column(ForeignKey("deals.id"), nullable=True, index=True)
    manager_id: Mapped[int | None] = mapped_column(ForeignKey("managers.id"), nullable=True)
    kind: Mapped[str] = mapped_column(String(30), index=True)               # site | call | email | note | meeting | stage | payment | system
    text: Mapped[str] = mapped_column(Text, default="")
    created: Mapped[dt.datetime] = mapped_column(DateTime, default=now, index=True)
    manager: Mapped[Manager | None] = relationship()


class Visit(Base):
    """Визиты сайта (в том числе анонимные): для аналитики по источникам и страницам входа."""
    __tablename__ = "visits"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    visitor: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    source: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    landing: Mapped[str | None] = mapped_column(String(300), nullable=True, index=True)
    created: Mapped[dt.datetime] = mapped_column(DateTime, default=now, index=True)


class InboundEvent(Base):
    """Журнал принятых событий API (повторная доставка того же события не обрабатывается дважды)."""
    __tablename__ = "inbound_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ext_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    kind: Mapped[str] = mapped_column(String(40), index=True)
    payload: Mapped[str] = mapped_column(Text, default="{}")
    created: Mapped[dt.datetime] = mapped_column(DateTime, default=now)


class Segment(Base):
    __tablename__ = "segments"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    filters: Mapped[str] = mapped_column(Text, default="{}")


class Setting(Base):
    """Переключатели автосценариев и прочие настройки, изменяемые из кабинета."""
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(60), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")


def make_db(url: str):
    kw = {"connect_args": {"check_same_thread": False}} if url.startswith("sqlite") else {}
    engine = create_engine(url, future=True, **kw)
    Base.metadata.create_all(engine)
    insp = inspect(engine)                                   # простая миграция: новые столбцы в существующие таблицы
    with engine.begin() as con:
        for table in Base.metadata.sorted_tables:
            have = {c["name"] for c in insp.get_columns(table.name)} if insp.has_table(table.name) else None
            for col in (table.columns if have is not None else []):
                if col.name not in have:
                    con.execute(text(f"ALTER TABLE {table.name} ADD COLUMN {col.name} {col.type.compile(engine.dialect)}"))
    return engine, sessionmaker(bind=engine, expire_on_commit=False, future=True)
