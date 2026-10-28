"""CRM для владельцев сайта: откуда приходят посетители, кто зарегистрировался, кто и как заплатил, конверсии по воронке,
карточка клиента с историей действий и заметками. Только для администраторов (ASR_ADMIN_EMAILS), удобно открывать с телефона.

Учёт: при первом заходе запоминаем источник (utm_*, домен перехода, страница входа) в сессии, при регистрации - в карточке клиента.
События пишутся в таблицу events (визит раз в сутки на посетителя, регистрация, вход, заказ, нагрузки, данные отчёта, оплата, отчёт готов …)."""
from __future__ import annotations

import csv
import datetime as dt
import io
import json
import secrets
from urllib.parse import urlparse

from fastapi import Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy import func, select, true

from .models import Event, Generation, Payment, User, now

# названия событий в ленте
KINDS = {"visit": "Визит на сайт", "register": "Регистрация", "login": "Вход", "generation": "Создал заказ (замеры)",
         "loads": "Задал нагрузки", "report_data": "Заполнил данные отчёта", "pay_start": "Нажал «Собрать отчёт» / оплату",
         "paid": "Оплата прошла", "pack_start": "Выбрал пакет", "job_done": "Отчёт и файлы готовы", "job_error": "Ошибка расчёта",
         "download": "Скачал файлы", "agent": "Помощник Ansys", "credits": "Выданы генерации (вручную)"}
STATUSES = ["Новый", "В работе", "Клиент", "Постоянный", "Отказ"]
SEARCH = {"yandex": "Яндекс", "google": "Google", "mail.ru": "Mail.ru", "bing": "Bing", "duckduckgo": "DuckDuckGo"}
SOCIAL = {"vk.com": "ВКонтакте", "t.me": "Telegram", "telegram": "Telegram", "ok.ru": "Одноклассники", "dzen.ru": "Дзен",
          "youtube": "YouTube", "whatsapp": "WhatsApp"}
METHODS = {"bank_card": "Карта", "sbp": "СБП", "yoo_money": "ЮMoney", "sberbank": "SberPay", "tinkoff_bank": "T-Pay", "fake": "Тест"}


def source_label(utm_source: str, referrer: str, own_host: str = "") -> str:
    """Понятное имя источника: utm_source как есть, иначе по домену перехода (поиск/соцсети/сайт), иначе «Прямой заход»."""
    if utm_source:
        return utm_source.strip()[:120]
    host = (urlparse(referrer).hostname or "").lower() if referrer else ""
    if not host or (own_host and host == own_host.lower()):
        return "Прямой заход"
    for key, name in SEARCH.items():
        if key in host:
            return f"{name} (поиск)"
    for key, name in SOCIAL.items():
        if key in host:
            return name
    return host.removeprefix("www.")[:120]


def touch(request: Request, db) -> None:
    """Вызывается при показе любой страницы сайта: первое касание (источник) в сессию, визит - одно событие в сутки на посетителя."""
    s = request.session
    if "vid" not in s:
        s["vid"] = secrets.token_hex(8)
    if "src" not in s:
        q = request.query_params
        ref = request.headers.get("referer", "")[:500]
        s["src"] = {"source": source_label(q.get("utm_source", ""), ref, request.url.hostname or ""), "medium": q.get("utm_medium", "")[:120],
                    "campaign": q.get("utm_campaign", "")[:200], "referrer": ref, "landing": str(request.url.path)[:300]}
    today = now().date().isoformat()
    if s.get("vday") != today:
        s["vday"] = today
        log(db, "visit", user_id=s.get("uid"), request=request, path=str(request.url.path))


def log(db, kind: str, user_id: int | None = None, request: Request | None = None, path: str = "", commit: bool = True, **meta) -> None:
    """Событие CRM. Ошибка учёта никогда не ломает основной сценарий."""
    try:
        sess = request.session if request is not None else {}
        db.add(Event(kind=kind, user_id=user_id, visitor=sess.get("vid"), source=(sess.get("src") or {}).get("source"), path=path[:300] or None,
                     meta=json.dumps(meta, ensure_ascii=False, default=str)))
        if commit:
            db.commit()
    except Exception:   # noqa: BLE001
        db.rollback()


def apply_source(u: User, request: Request) -> None:
    """Источник первого касания - в карточку клиента при регистрации."""
    src = request.session.get("src") or {}
    u.source = src.get("source") or "Прямой заход"
    u.utm_medium, u.utm_campaign = src.get("medium") or None, src.get("campaign") or None
    u.referrer, u.landing = src.get("referrer") or None, src.get("landing") or None


# ---------------- отчёты ----------------
PERIODS = {"7": 7, "30": 30, "90": 90, "365": 365, "all": None}


def _since(period: str):
    days = PERIODS.get(period, 30)
    return None if days is None else now() - dt.timedelta(days=days)


def _ge(col, since):
    return true() if since is None else col >= since


def auto_status(paid_count: int, gens: int) -> str:
    return "Постоянный" if paid_count >= 2 else "Клиент" if paid_count == 1 else "В работе" if gens else "Новый"


def pct(a: int, b: int) -> str:
    return f"{100.0 * a / b:.1f}".replace(".", ",") + " %" if b else "—"


def dashboard(db, period: str) -> dict:
    since = _since(period)
    visitors = db.scalar(select(func.count(func.distinct(Event.visitor))).where(Event.kind == "visit", _ge(Event.created, since))) or 0
    regs = db.scalar(select(func.count()).select_from(User).where(_ge(User.created, since))) or 0
    gens = db.scalar(select(func.count()).select_from(Generation).where(_ge(Generation.created, since))) or 0
    started = db.scalar(select(func.count()).select_from(Generation).where(_ge(Generation.created, since),
                                                                          Generation.status.in_(("paid", "running", "done", "error")))) or 0
    paid_q = select(Payment).where(Payment.status == "paid", _ge(Payment.paid_at, since))
    paid = db.scalars(paid_q).all()
    revenue = sum(p.amount_rub for p in paid)
    payers = len({p.user_id for p in paid})
    # воронка по клиентам, зарегистрированным в периоде
    cohort = [u.id for u in db.scalars(select(User).where(_ge(User.created, since))).all()]
    def users_with(kind=None, gen=False, pay=False):
        if not cohort:
            return 0
        if gen:
            q = select(func.count(func.distinct(Generation.user_id))).where(Generation.user_id.in_(cohort))
        elif pay:
            q = select(func.count(func.distinct(Payment.user_id))).where(Payment.user_id.in_(cohort), Payment.status == "paid")
        else:
            q = select(func.count(func.distinct(Event.user_id))).where(Event.user_id.in_(cohort), Event.kind == kind)
        return db.scalar(q) or 0
    funnel = [("Зарегистрировались", len(cohort)), ("Создали заказ", users_with(gen=True)), ("Задали нагрузки", users_with("loads")),
              ("Заполнили данные отчёта", users_with("report_data")), ("Нажали «Собрать отчёт»", users_with("pay_start")),
              ("Оплатили", users_with(pay=True))]
    top = max((n for _, n in funnel), default=0) or 1
    # выручка по дням
    days = 30 if period in ("all", "365", "90") else PERIODS.get(period, 30)
    start = (now() - dt.timedelta(days=days - 1)).date()
    by_day = {start + dt.timedelta(days=i): 0 for i in range(days)}
    for p in db.scalars(select(Payment).where(Payment.status == "paid", Payment.paid_at >= dt.datetime.combine(start, dt.time()))).all():
        by_day[p.paid_at.date()] = by_day.get(p.paid_at.date(), 0) + p.amount_rub
    regs_day = {d: 0 for d in by_day}
    for u in db.scalars(select(User).where(User.created >= dt.datetime.combine(start, dt.time()))).all():
        regs_day[u.created.date()] = regs_day.get(u.created.date(), 0) + 1
    return {
        "visitors": visitors, "regs": regs, "gens": gens, "started": started, "paid_n": len(paid), "revenue": revenue, "payers": payers,
        "avg": round(revenue / len(paid)) if paid else 0,
        "conv": [("Визит → регистрация", pct(regs, visitors)), ("Регистрация → заказ", pct(funnel[1][1], len(cohort))),
                 ("Регистрация → оплата", pct(funnel[5][1], len(cohort))), ("Визит → оплата", pct(payers, visitors))],
        "funnel": [(name, n, round(100 * n / top), pct(n, funnel[0][1])) for name, n in funnel],
        "chart": [(d.strftime("%d.%m"), by_day[d], regs_day.get(d, 0)) for d in sorted(by_day)],
        "chart_max": max(by_day.values(), default=0) or 1, "regs_max": max(regs_day.values(), default=0) or 1,
        "sources": sources(db, since), "methods": methods(paid),
        "feed": feed(db, limit=15),
    }


def sources(db, since) -> list[dict]:
    """По источникам: посетители, регистрации, оплатившие, выручка (клиентов этого источника), конверсия в оплату."""
    rows: dict[str, dict] = {}
    def row(name):
        return rows.setdefault(name or "Прямой заход", {"source": name or "Прямой заход", "visitors": 0, "regs": 0, "payers": 0, "revenue": 0})
    for src, n in db.execute(select(Event.source, func.count(func.distinct(Event.visitor))).where(Event.kind == "visit", _ge(Event.created, since))
                             .group_by(Event.source)).all():
        row(src)["visitors"] += n
    for u in db.scalars(select(User).where(_ge(User.created, since))).all():
        r = row(u.source)
        r["regs"] += 1
        pays = [p.amount_rub for p in db.scalars(select(Payment).where(Payment.user_id == u.id, Payment.status == "paid")).all()]
        if pays:
            r["payers"] += 1
            r["revenue"] += sum(pays)
    out = sorted(rows.values(), key=lambda r: (-r["revenue"], -r["regs"], -r["visitors"]))
    for r in out:
        r["conv"] = pct(r["payers"], r["regs"])
        r["conv_visit"] = pct(r["regs"], r["visitors"])
    return out


def methods(paid: list[Payment]) -> list[tuple]:
    agg: dict[str, list] = {}
    for p in paid:
        key = f"{p.provider} · {METHODS.get(p.method or '', p.method or '—')}"
        a = agg.setdefault(key, [0, 0])
        a[0] += 1
        a[1] += p.amount_rub
    return sorted(((k, n, s) for k, (n, s) in agg.items()), key=lambda x: -x[2])


def feed(db, user_id: int | None = None, limit: int = 50) -> list[dict]:
    q = select(Event, User.email).join(User, User.id == Event.user_id, isouter=True).order_by(Event.id.desc()).limit(limit)
    if user_id:
        q = q.where(Event.user_id == user_id)
    out = []
    for e, email in db.execute(q).all():
        meta = json.loads(e.meta or "{}")
        out.append({"t": e.created, "kind": e.kind, "label": KINDS.get(e.kind, e.kind), "email": email, "user_id": e.user_id,
                    "source": e.source, "path": e.path, "meta": ", ".join(f"{k}: {v}" for k, v in meta.items() if v not in (None, ""))})
    return out


def clients(db, q: str = "", status: str = "", source: str = "") -> list[dict]:
    users = db.scalars(select(User).order_by(User.id.desc())).all()
    gens = dict(db.execute(select(Generation.user_id, func.count()).group_by(Generation.user_id)).all())
    pays: dict[int, list] = {}
    for p in db.scalars(select(Payment).where(Payment.status == "paid")).all():
        pays.setdefault(p.user_id, []).append(p.amount_rub)
    last = dict(db.execute(select(Event.user_id, func.max(Event.created)).where(Event.user_id.is_not(None)).group_by(Event.user_id)).all())
    out = []
    for u in users:
        p = pays.get(u.id, [])
        stt = u.crm_status or auto_status(len(p), gens.get(u.id, 0))
        r = {"u": u, "gens": gens.get(u.id, 0), "paid_n": len(p), "paid_sum": sum(p), "last": last.get(u.id) or u.created, "status": stt,
             "source": u.source or "—"}
        if q and q.lower() not in (u.email + " " + (u.company or "") + " " + (u.phone or "")).lower():
            continue
        if status and stt != status:
            continue
        if source and r["source"] != source:
            continue
        out.append(r)
    return out


# ---------------- страницы ----------------
def install(app, Session, current_user, templates, csrf_token, csrf_ok, settings):
    st = settings

    def admin(request: Request, db):
        u = current_user(request, db)
        return u if (u and u.email.lower() in st.admin_emails) else None

    def page(request, name, u, **ctx):
        return templates.TemplateResponse(request, f"admin/{name}", {"user": u, "csrf": csrf_token(request.session), "st": st,
                                                                    "KINDS": KINDS, "STATUSES": STATUSES, "METHODS": METHODS, **ctx})

    def deny(request):
        return RedirectResponse("/login", status_code=303) if not request.session.get("uid") else HTMLResponse("Нет доступа", status_code=403)

    @app.get("/admin", response_class=HTMLResponse)
    def admin_home(request: Request, p: str = "30"):
        with Session() as db:
            u = admin(request, db)
            if not u:
                return deny(request)
            p = p if p in PERIODS else "30"
            return page(request, "dashboard.html", u, d=dashboard(db, p), period=p, tab="home")

    @app.get("/admin/clients", response_class=HTMLResponse)
    def admin_clients(request: Request, q: str = "", s: str = "", src: str = ""):
        with Session() as db:
            u = admin(request, db)
            if not u:
                return deny(request)
            rows = clients(db, q, s, src)
            return page(request, "clients.html", u, rows=rows, q=q, s=s, src=src, tab="clients",
                        all_sources=sorted({r["source"] for r in clients(db)}))

    @app.get("/admin/clients/{uid}", response_class=HTMLResponse)
    def admin_client(request: Request, uid: int):
        with Session() as db:
            u = admin(request, db)
            if not u:
                return deny(request)
            c = db.get(User, uid)
            if not c:
                return HTMLResponse("Не найдено", status_code=404)
            gens = db.scalars(select(Generation).where(Generation.user_id == uid).order_by(Generation.id.desc())).all()
            pays = db.scalars(select(Payment).where(Payment.user_id == uid).order_by(Payment.id.desc())).all()
            paid = [p for p in pays if p.status == "paid"]
            return page(request, "client.html", u, c=c, gens=gens, pays=pays, paid_sum=sum(p.amount_rub for p in paid),
                        status=c.crm_status or auto_status(len(paid), len(gens)), events=feed(db, uid, 200), tab="clients")

    @app.post("/admin/clients/{uid}")
    def admin_client_save(request: Request, uid: int, csrf: str = Form(""), crm_status: str = Form(""), crm_note: str = Form(""),
                          phone: str = Form(""), company: str = Form(""), add_credits: str = Form("")):
        if not csrf_ok(request.session, csrf):
            return HTMLResponse("Сессия устарела. Обновите страницу.", status_code=400)
        with Session() as db:
            u = admin(request, db)
            if not u:
                return deny(request)
            c = db.get(User, uid)
            if not c:
                return HTMLResponse("Не найдено", status_code=404)
            c.crm_status = crm_status if crm_status in STATUSES else None
            c.crm_note, c.phone, c.company = crm_note.strip()[:5000] or None, phone.strip()[:40] or None, company.strip()[:200] or None
            n = int(add_credits) if add_credits.strip().lstrip("-").isdigit() else 0
            if n:
                c.credits = max(0, (c.credits or 0) + n)
                log(db, "credits", user_id=c.id, commit=False, qty=n, by=u.email)
            db.commit()
        return RedirectResponse(f"/admin/clients/{uid}", status_code=303)

    @app.get("/admin/payments", response_class=HTMLResponse)
    def admin_payments(request: Request, s: str = "", p: str = "all"):
        with Session() as db:
            u = admin(request, db)
            if not u:
                return deny(request)
            since = _since(p)
            q = select(Payment, User.email).join(User, User.id == Payment.user_id).where(_ge(Payment.created, since)).order_by(Payment.id.desc())
            if s:
                q = q.where(Payment.status == s)
            rows = db.execute(q.limit(500)).all()
            total = sum(pm.amount_rub for pm, _ in rows if pm.status == "paid")
            return page(request, "payments.html", u, rows=rows, s=s, period=p, total=total, tab="payments")

    @app.get("/admin/events", response_class=HTMLResponse)
    def admin_events(request: Request, k: str = ""):
        with Session() as db:
            u = admin(request, db)
            if not u:
                return deny(request)
            rows = [e for e in feed(db, limit=500) if not k or e["kind"] == k]
            return page(request, "events.html", u, rows=rows[:300], k=k, tab="events")

    @app.get("/admin/export/{what}.csv")
    def admin_export(request: Request, what: str):
        with Session() as db:
            u = admin(request, db)
            if not u:
                return deny(request)
            buf = io.StringIO()
            w = csv.writer(buf, delimiter=";")
            if what == "clients":
                w.writerow(["id", "почта", "телефон", "компания", "дата регистрации", "источник", "utm_medium", "utm_campaign", "страница входа",
                            "заказов", "оплат", "сумма, ₽", "статус", "заметка"])
                for r in clients(db):
                    c = r["u"]
                    w.writerow([c.id, c.email, c.phone or "", c.company or "", c.created.strftime("%d.%m.%Y %H:%M"), r["source"], c.utm_medium or "",
                                c.utm_campaign or "", c.landing or "", r["gens"], r["paid_n"], r["paid_sum"], r["status"], (c.crm_note or "").replace("\n", " ")])
            elif what == "payments":
                w.writerow(["id", "дата", "почта", "что", "сумма, ₽", "статус", "провайдер", "способ", "оплачен"])
                for pm, email in db.execute(select(Payment, User.email).join(User, User.id == Payment.user_id).order_by(Payment.id.desc())).all():
                    w.writerow([pm.id, pm.created.strftime("%d.%m.%Y %H:%M"), email, "пакет %s" % pm.qty if pm.kind == "pack" else "генерация №%s" % pm.generation_id,
                                pm.amount_rub, pm.status, pm.provider, METHODS.get(pm.method or "", pm.method or ""),
                                pm.paid_at.strftime("%d.%m.%Y %H:%M") if pm.paid_at else ""])
            else:
                return HTMLResponse("Не найдено", status_code=404)
            return Response("﻿" + buf.getvalue(), media_type="text/csv; charset=utf-8",
                            headers={"Content-Disposition": f'attachment; filename="{what}.csv"'})
