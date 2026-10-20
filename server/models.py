from __future__ import annotations
import datetime as dt
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    created: Mapped[dt.datetime] = mapped_column(DateTime, default=now)
    subscription_until: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    consent_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)      # согласие на обработку персональных данных
    email_key: Mapped[str | None] = mapped_column(String(254), nullable=True, index=True)  # почта без псевдонимов (точки, +метки): защита от дублей
    reg_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    credits: Mapped[int | None] = mapped_column(Integer, nullable=True, default=0)          # остаток генераций из купленных пакетов
    generations: Mapped[list["Generation"]] = relationship(back_populates="user")

    @property
    def credit_count(self) -> int:
        return self.credits or 0


class Generation(Base):
    """Заказ: замеры → геометрия. Статусы: draft (проверка пройдена, не оплачено) → paid → running → done | error."""
    __tablename__ = "generations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(200), default="")
    status: Mapped[str] = mapped_column(String(20), default="draft", index=True)
    created: Mapped[dt.datetime] = mapped_column(DateTime, default=now)
    summary: Mapped[str] = mapped_column(Text, default="{}")       # JSON: итоги проверки по допускам
    error: Mapped[str] = mapped_column(Text, default="")
    data_key: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)   # отпечаток замеров (одни и те же данные на разных аккаунтах)
    charged: Mapped[str | None] = mapped_column(String(10), nullable=True)                # как оплачена: credit | free | payment | refunded
    user: Mapped[User] = relationship(back_populates="generations")


class Payment(Base):
    __tablename__ = "payments"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    kind: Mapped[str] = mapped_column(String(20))                   # generation | pack
    qty: Mapped[int | None] = mapped_column(Integer, nullable=True)  # для пакета: число генераций
    generation_id: Mapped[int | None] = mapped_column(ForeignKey("generations.id"), nullable=True)
    amount_rub: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)     # pending | paid | canceled
    provider: Mapped[str] = mapped_column(String(30), default="fake")
    provider_id: Mapped[str] = mapped_column(String(100), default="")
    created: Mapped[dt.datetime] = mapped_column(DateTime, default=now)
    paid_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
