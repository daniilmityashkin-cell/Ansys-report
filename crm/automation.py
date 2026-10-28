"""Обработка событий сайта и заявок: контакт, сделка по этапам, история, задачи менеджеру, письма и уведомления.

Событие сайта (POST /api/v1/events): {"id": "site-123", "kind": "register|login|visit|generation|loads|report_data|pay_start|pack_start|paid|
job_done|job_error|download|agent|lead", "at": "...", "visitor": "...", "source": "...", "path": "...", "meta": {...},
"user": {"site_user_id", "email", "phone", "company", "source", "utm_medium", "utm_campaign", "referrer", "landing"}}.
Заявка с формы (POST /api/v1/leads): {"name", "phone", "email", "company", "message", "form", "page", "utm_source", ...}."""
from __future__ import annotations
import datetime as dt
import json

from sqlalchemy import select

from .models import (LOST, OPEN_STAGES, STAGES, WON, Activity, Contact, Deal, InboundEvent, Manager, Setting, Task, Visit, now)

SITE_LABELS = {"register": "Зарегистрировался на сайте", "login": "Вошёл на сайт", "generation": "Загрузил замеры (заказ №{generation})",
               "loads": "Задал нагрузки (заказ №{generation})", "report_data": "Заполнил данные отчёта (заказ №{generation})",
               "pay_start": "Нажал «Собрать отчёт» (заказ №{generation})", "pack_start": "Выбрал пакет {qty} генераций ({amount} ₽)",
               "paid": "Оплата {amount} ₽: {what} ({provider}{method})", "job_done": "Отчёт и файлы готовы (заказ №{generation})",
               "job_error": "Ошибка расчёта (заказ №{generation}): {error}", "download": "Скачал файлы (заказ №{generation})",
               "agent": "Помощник Ansys: {stage} (заказ №{generation})", "credits": "Выданы генерации: {qty}", "lead": "Заявка с сайта"}
# какой этап сделки означает действие клиента
STAGE_BY_KIND = {"generation": "Замеры загружены", "loads": "Готовит расчёт", "report_data": "Готовит расчёт", "pay_start": "Ожидает оплаты",
                 "pack_start": "Ожидает оплаты", "paid": "Оплачено", "job_done": WON}
# автосценарии (можно выключать в настройках)
RULES = {"lead_task": "Новый лид: задача менеджеру «связаться» в течение N минут",
         "lead_email": "Новый лид: письмо клиенту «спасибо, мы свяжемся»",
         "lead_tg": "Новый лид: уведомление команде в Telegram",
         "unpaid_task": "Нажал «Собрать отчёт», но не оплатил за N часов: задача «дожать»",
         "paid_tg": "Оплата: уведомление в Telegram",
         "error_task": "Ошибка расчёта у клиента: срочная задача и уведомление",
         "done_email": "Отчёт готов: письмо клиенту со ссылкой на сайт"}


def rule_on(db, key: str) -> bool:
    s = db.get(Setting, "rule:" + key)
    return s is None or s.value != "0"


def _fmt(kind: str, meta: dict) -> str:
    t = SITE_LABELS.get(kind, kind)
    m = dict(meta)
    if kind == "paid":
        m["method"] = (", " + m["method"]) if m.get("method") else ""
    class _D(dict):
        def __missing__(self, k):
            return "—"
    try:
        return t.format_map(_D({k: ("—" if v in (None, "") else v) for k, v in m.items()}))
    except (ValueError, IndexError):
        return t.split("{")[0].strip(" (:")


def _first_admin(db) -> Manager | None:
    return db.scalar(select(Manager).where(Manager.active.is_(True)).order_by((Manager.role != "admin"), Manager.id))


def find_contact(db, user: dict) -> Contact | None:
    sid, email, phone = user.get("site_user_id"), (user.get("email") or "").strip().lower(), (user.get("phone") or "").strip()
    c = db.scalar(select(Contact).where(Contact.site_user_id == sid)) if sid else None
    if not c and email:
        c = db.scalar(select(Contact).where(Contact.email == email))
    if not c and phone:
        c = db.scalar(select(Contact).where(Contact.phone == phone))
    return c


def upsert_contact(db, user: dict, visitor: str | None = None) -> tuple[Contact, bool]:
    c = find_contact(db, user)
    created = c is None
    if created:
        owner = _first_admin(db)
        c = Contact(owner_id=owner.id if owner else None)
        db.add(c)
    for key in ("site_user_id", "phone", "name", "company", "region", "source", "utm_medium", "utm_campaign", "referrer", "landing"):
        v = user.get(key)
        if v not in (None, "") and (created or not getattr(c, key)):
            setattr(c, key, v if key == "site_user_id" else str(v)[:500])
    if user.get("email") and not c.email:
        c.email = str(user["email"]).strip().lower()[:254]
    if visitor and not c.visitor:
        c.visitor = visitor
    c.last_activity = now()
    db.flush()
    return c, created


def open_deal(db, c: Contact, title: str = "", generation: int | None = None) -> tuple[Deal, bool]:
    """Текущая открытая сделка клиента; если её нет (новый клиент или прошлая закрыта) - новая на этапе «Новый лид» (повторная покупка)."""
    d = db.scalar(select(Deal).where(Deal.contact_id == c.id, Deal.stage.in_(OPEN_STAGES)).order_by(Deal.id.desc()))
    if d:
        if generation and not d.site_generation_id:
            d.site_generation_id = generation
        return d, False
    repeat = db.scalar(select(Deal.id).where(Deal.contact_id == c.id, Deal.stage == WON)) is not None
    d = Deal(contact_id=c.id, title=title or (("Повторный заказ: " if repeat else "") + c.title), source=c.source, owner_id=c.owner_id,
             site_generation_id=generation)
    db.add(d)
    db.flush()
    activity(db, c, d, "stage", f"Новая сделка: {d.title}")
    return d, True


def move(db, d: Deal, stage: str, manager: Manager | None = None, forward_only: bool = True) -> bool:
    if stage not in STAGES or d.stage == stage:
        return False
    if forward_only and (d.stage in (WON, LOST) or STAGES.index(stage) < STAGES.index(d.stage)):
        return False
    old, d.stage, d.stage_changed = d.stage, stage, now()
    if stage in (WON, LOST):
        d.closed_at = now()
    activity(db, d.contact, d, "stage", f"Этап: {old} → {stage}", manager)
    return True


def activity(db, c: Contact | None, d: Deal | None, kind: str, text: str, manager: Manager | None = None, at=None) -> Activity:
    a = Activity(contact_id=c.id if c else None, deal_id=d.id if d else None, kind=kind, text=text[:4000], manager_id=manager.id if manager else None,
                 created=at or now())
    db.add(a)
    return a


def task(db, title: str, c: Contact | None, d: Deal | None, minutes: int | None = None, auto: str | None = None, priority: str = "normal") -> Task:
    if auto and c and db.scalar(select(Task).where(Task.contact_id == c.id, Task.auto == auto, Task.done.is_(False))):
        return None                                             # такая автозадача уже открыта
    t = Task(title=title, contact_id=c.id if c else None, deal_id=d.id if d else None, auto=auto, priority=priority,
             assignee_id=(c.owner_id if c else None), due=now() + dt.timedelta(minutes=minutes) if minutes is not None else None)
    db.add(t)
    return t


def close_auto_tasks(db, c: Contact, auto: str) -> None:
    for t in db.scalars(select(Task).where(Task.contact_id == c.id, Task.auto == auto, Task.done.is_(False))).all():
        t.done, t.done_at = True, now()


def _parse_at(v):
    try:
        return dt.datetime.fromisoformat(str(v)).replace(tzinfo=None) if v else None
    except ValueError:
        return None


def handle_event(db, ev: dict, notifier, st) -> str:
    """Возвращает 'ok' | 'duplicate'. Вызывающий делает commit."""
    ext = str(ev.get("id") or "")[:80]
    if ext and db.scalar(select(InboundEvent.id).where(InboundEvent.ext_id == ext)):
        return "duplicate"
    kind = str(ev.get("kind") or "")[:40]
    db.add(InboundEvent(ext_id=ext or f"noid-{now().timestamp()}", kind=kind, payload=json.dumps(ev, ensure_ascii=False, default=str)[:20000]))
    meta = ev.get("meta") or {}
    user = ev.get("user") or {}
    at = _parse_at(ev.get("at"))
    if kind == "visit":
        db.add(Visit(visitor=ev.get("visitor"), source=ev.get("source"), landing=ev.get("path"), created=at or now()))
        if not user:
            return "ok"
    if not user and kind != "lead":
        return "ok"
    if kind == "lead":
        return handle_lead(db, {**meta, **user}, notifier, st, ev.get("visitor"), at)
    c, created = upsert_contact(db, user, ev.get("visitor"))
    if kind == "visit":
        return "ok"
    activity(db, c, None, "site", _fmt(kind, meta), at=at)
    if kind == "register" or created:
        d, _ = open_deal(db, c)
        if kind == "register":                                 # лид - только новая регистрация (старые клиенты при подключении CRM - без задач)
            new_lead_rules(db, c, d, notifier, st, "Регистрация на сайте")
    gen = meta.get("generation")
    if kind in STAGE_BY_KIND:
        d, _ = open_deal(db, c, generation=gen if isinstance(gen, int) else None)
        if kind == "paid":
            d.amount = (d.amount or 0) + int(meta.get("amount") or 0)
            d.paid_at = at or now()
            activity(db, c, d, "payment", _fmt(kind, meta), at=at)
            close_auto_tasks(db, c, "unpaid")
            if rule_on(db, "paid_tg"):
                notifier.telegram(f"💰 Оплата {meta.get('amount')} ₽ — {c.title}\n{meta.get('what', '')}\n{st.public_url}/contacts/{c.id}")
        move(db, d, STAGE_BY_KIND[kind])
        if kind in ("pay_start", "pack_start") and meta.get("mode") not in ("credit", "unlimited", "free") and rule_on(db, "unpaid_task"):
            task(db, f"Не оплатил за {st.unpaid_hours} ч — связаться и помочь с оплатой", c, d, minutes=st.unpaid_hours * 60, auto="unpaid")
        if kind == "job_done" and rule_on(db, "done_email") and c.email:
            notifier.email(c.email, "Ваш технический отчёт готов",
                           f"Здравствуйте!\n\nРасчёт по заказу №{gen} завершён, отчёт и файлы доступны в личном кабинете: {st.site_url}/g/{gen}\n\n"
                           "Если будут вопросы — ответьте на это письмо.\n\nANSYS REPORT")
    if kind == "job_error" and rule_on(db, "error_task"):
        d, _ = open_deal(db, c)
        task(db, f"Ошибка расчёта у клиента (заказ №{gen}) — разобраться и связаться", c, d, minutes=60, auto="job_error", priority="high")
        notifier.telegram(f"⚠️ Ошибка расчёта у {c.title}, заказ №{gen}: {meta.get('error', '')}")
    return "ok"


def new_lead_rules(db, c: Contact, d: Deal, notifier, st, what: str) -> None:
    if rule_on(db, "lead_task"):
        task(db, f"Связаться с новым клиентом в течение {st.lead_call_minutes} минут", c, d, minutes=st.lead_call_minutes, auto="call_lead", priority="high")
    if rule_on(db, "lead_email") and c.email:
        notifier.email(c.email, "Спасибо за обращение — ANSYS REPORT",
                       "Здравствуйте!\n\nСпасибо, что обратились в ANSYS REPORT. Мы получили вашу заявку и свяжемся с вами в ближайшее время.\n\n"
                       f"Личный кабинет: {st.site_url}\n\nANSYS REPORT")
    if rule_on(db, "lead_tg"):
        notifier.telegram(f"🆕 Новый лид: {c.title}\n{what}\nИсточник: {c.source or '—'}" + (f"\nТел.: {c.phone}" if c.phone else "")
                          + f"\n{st.public_url}/contacts/{c.id}")


def handle_lead(db, lead: dict, notifier, st, visitor: str | None = None, at=None) -> str:
    """Заявка с формы сайта или виджета: контакт, сделка «Новый лид», заявка в историю, сценарии нового лида."""
    user = {"email": lead.get("email"), "phone": lead.get("phone"), "name": lead.get("name"), "company": lead.get("company"),
            "region": lead.get("region"), "source": lead.get("utm_source") or lead.get("source"), "utm_medium": lead.get("utm_medium"),
            "utm_campaign": lead.get("utm_campaign"), "referrer": lead.get("referrer"), "landing": lead.get("page") or lead.get("landing"),
            "site_user_id": lead.get("site_user_id")}
    if not (user["email"] or user["phone"]):
        raise ValueError("Нужна почта или телефон")
    c, created = upsert_contact(db, user, visitor)
    d, new_deal = open_deal(db, c)
    form = lead.get("form") or "форма на сайте"
    activity(db, c, d, "site", f"Заявка ({form}){': ' + lead['message'] if lead.get('message') else ''}" + (f" · страница {user['landing']}" if user["landing"] else ""), at=at)
    if created or new_deal:
        new_lead_rules(db, c, d, notifier, st, f"Заявка: {form}")
    return "ok"
