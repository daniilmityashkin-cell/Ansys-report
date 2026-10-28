"""Платежи: интерфейс провайдера, тестовая заглушка и ЮKassa.

Карты на нашем сервере не обрабатываются: пользователь платит на странице провайдера, мы получаем уведомление
и перепроверяем статус платежа запросом к API провайдера (тело уведомления не принимается на веру).
"""
from __future__ import annotations
import datetime as dt
import json
import os
import uuid

from .models import Payment, User, Generation, now


class PaymentProvider:
    name = "base"

    def create(self, payment: Payment, return_url: str, description: str) -> str:
        """Создаёт платёж у провайдера, записывает provider_id, возвращает адрес для перехода пользователя."""
        raise NotImplementedError

    def verify(self, provider_id: str) -> str:
        """Статус платежа у провайдера: paid | pending | canceled."""
        raise NotImplementedError


class FakeProvider(PaymentProvider):
    """Только для разработки: страница «оплатить» на нашем же сайте, деньги не списываются."""
    name = "fake"

    def create(self, payment, return_url, description):
        payment.provider_id = f"fake-{payment.id}"
        return f"/pay/fake/{payment.id}"

    def verify(self, provider_id):
        return "pending"


class YooKassaProvider(PaymentProvider):
    """ЮKassa (API v3). НЕ ПРОВЕРЕНО на реальном магазине: нужны ASR_YOOKASSA_SHOP_ID и ASR_YOOKASSA_SECRET.
    Для ООО по 54-ФЗ в запрос нужно добавить данные чека (receipt) - заполнить после настройки кассы."""
    name = "yookassa"
    API = "https://api.yookassa.ru/v3/payments"

    def __init__(self):
        self.shop = os.environ.get("ASR_YOOKASSA_SHOP_ID", "")
        self.secret = os.environ.get("ASR_YOOKASSA_SECRET", "")
        if not (self.shop and self.secret):
            raise RuntimeError("Не заданы ASR_YOOKASSA_SHOP_ID и ASR_YOOKASSA_SECRET")

    def _client(self):
        import httpx
        return httpx.Client(auth=(self.shop, self.secret), timeout=20)

    def create(self, payment, return_url, description):
        body = {"amount": {"value": f"{payment.amount_rub}.00", "currency": "RUB"}, "capture": True,
                "confirmation": {"type": "redirect", "return_url": return_url}, "description": description[:128],
                "metadata": {"payment_id": str(payment.id)}}
        with self._client() as c:
            r = c.post(self.API, json=body, headers={"Idempotence-Key": f"asr-{payment.id}-{uuid.uuid4().hex[:8]}"})
            r.raise_for_status()
            data = r.json()
        payment.provider_id = data["id"]
        return data["confirmation"]["confirmation_url"]

    def verify(self, provider_id):
        with self._client() as c:
            r = c.get(f"{self.API}/{provider_id}")
            r.raise_for_status()
            data = r.json()
        st = data.get("status")
        self.last_method = ((data.get("payment_method") or {}).get("type") or "")[:40]      # для CRM: bank_card, sbp, yoo_money …
        return {"succeeded": "paid", "canceled": "canceled"}.get(st, "pending")


def get_provider(name: str) -> PaymentProvider:
    if name == "yookassa":
        return YooKassaProvider()
    return FakeProvider()


def settle(db, payment: Payment) -> bool:
    """Помечает платёж оплаченным (один раз) и применяет результат: оплата генерации или зачисление пакета генераций.
    Возвращает True, если оплата применена сейчас (повторные вызовы безопасны - платёж не засчитается дважды)."""
    if payment.status == "paid":
        return False
    payment.status = "paid"
    payment.paid_at = now()
    if payment.kind == "generation" and payment.generation_id:
        g = db.get(Generation, payment.generation_id)
        if g and g.status == "draft":
            g.status = "paid"
    elif payment.kind == "pack":
        u = db.get(User, payment.user_id)
        u.credits = (u.credits or 0) + (payment.qty or 0)
    return True
