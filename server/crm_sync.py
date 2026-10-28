"""Отправка событий сайта в CRM (crm/): очередь в таблице events (sent_at пусто - не отправлено), пачками по API с токеном.
CRM недоступна - события ждут и уходят при следующей попытке; повторная доставка в CRM безопасна (у события постоянный id)."""
from __future__ import annotations
import json

from sqlalchemy import select

from .models import Event, User, now


def user_payload(u: User | None) -> dict:
    if not u:
        return {}
    return {"site_user_id": u.id, "email": u.email, "phone": u.phone, "company": u.company, "source": u.source, "utm_medium": u.utm_medium,
            "utm_campaign": u.utm_campaign, "referrer": u.referrer, "landing": u.landing}


def payload(db, e: Event) -> dict:
    return {"id": f"site-{e.id}", "kind": e.kind, "at": e.created.isoformat(timespec="seconds"), "visitor": e.visitor, "source": e.source,
            "path": e.path, "meta": json.loads(e.meta or "{}"), "user": user_payload(db.get(User, e.user_id) if e.user_id else None)}


def push(Session, url: str, token: str, post=None, batch: int = 200) -> int:
    """Отправляет неотправленные события; возвращает число отправленных. post(url, json, headers) -> ответ с .status_code (для тестов)."""
    if not (url and token):
        return 0
    if post is None:
        import httpx
        post = lambda u, json, headers: httpx.post(u, json=json, headers=headers, timeout=20)   # noqa: E731
    sent = 0
    with Session() as db:
        while True:
            evs = db.scalars(select(Event).where(Event.sent_at.is_(None)).order_by(Event.id).limit(batch)).all()
            if not evs:
                break
            try:
                r = post(url.rstrip("/") + "/api/v1/events", json={"events": [payload(db, e) for e in evs]}, headers={"Authorization": f"Bearer {token}"})
            except Exception:   # noqa: BLE001  (CRM недоступна - попробуем позже)
                break
            if r.status_code != 200:
                break
            t = now()
            for e in evs:
                e.sent_at = t
            db.commit()
            sent += len(evs)
            if len(evs) < batch:
                break
    return sent
