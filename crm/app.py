"""Сервер CRM (FastAPI): API для сайта и форм, кабинет администратора и менеджеров (удобен с телефона)."""
from __future__ import annotations
import csv
import datetime as dt
import hashlib
import hmac
import io
import json
import secrets
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, or_, select
from starlette.middleware.sessions import SessionMiddleware

from . import analytics as A
from .automation import RULES, activity, handle_event, handle_lead, move, rule_on
from .config import Settings
from .models import (LOST, OPEN_STAGES, STAGES, WON, Activity, Contact, Deal, Manager, Segment, Setting, Task, make_db, now)
from .notify import Notifier

HERE = Path(__file__).parent
ACT_KINDS = {"note": "Заметка", "call": "Звонок", "email": "Письмо", "meeting": "Встреча", "message": "Мессенджер"}
ACT_ICONS = {"site": "🌐", "call": "📞", "email": "✉️", "note": "📝", "meeting": "🤝", "message": "💬", "stage": "➡️", "payment": "💰", "system": "⚙️"}


def hash_password(pw: str) -> str:
    salt = secrets.token_hex(16)
    return f"pbkdf2${salt}${hashlib.pbkdf2_hmac('sha256', pw.encode(), salt.encode(), 200_000).hex()}"


def verify_password(pw: str, h: str) -> bool:
    try:
        _, salt, dig = h.split("$")
    except ValueError:
        return False
    return hmac.compare_digest(hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), 200_000).hex(), dig)


def segment_query(f: dict):
    """Контакты по фильтрам сегмента: этап сделки, источник, тег, регион, тип (новый/повторный/оплатил/не оплатил), без активности N дней."""
    q = select(Contact)
    if f.get("q"):
        like = f"%{f['q'].strip().lower()}%"
        q = q.where(or_(func.lower(Contact.email).like(like), func.lower(Contact.name).like(like), func.lower(Contact.company).like(like),
                        Contact.phone.like(like)))
    if f.get("source"):
        q = q.where(Contact.source == f["source"])
    if f.get("region"):
        q = q.where(func.lower(Contact.region) == f["region"].strip().lower())
    if f.get("tag"):
        q = q.where(func.lower(Contact.tags).like(f"%{f['tag'].strip().lower()}%"))
    if f.get("stage"):
        q = q.where(Contact.id.in_(select(Deal.contact_id).where(Deal.stage == f["stage"])))
    paid_ids = select(Deal.contact_id).where(Deal.paid_at.is_not(None))
    kind = f.get("kind")
    if kind == "paid":
        q = q.where(Contact.id.in_(paid_ids))
    elif kind == "unpaid":
        q = q.where(Contact.id.not_in(paid_ids))
    elif kind == "repeat":
        q = q.where(Contact.id.in_(select(Deal.contact_id).where(Deal.paid_at.is_not(None)).group_by(Deal.contact_id).having(func.count() >= 2)))
    elif kind == "new":
        q = q.where(Contact.created >= now() - dt.timedelta(days=30))
    if str(f.get("idle", "")).isdigit():
        q = q.where(Contact.last_activity < now() - dt.timedelta(days=int(f["idle"])))
    return q.order_by(Contact.last_activity.desc())


def create_app(settings: Settings | None = None) -> FastAPI:
    st = settings or Settings()
    engine, Session = make_db(st.db_url)
    notifier = Notifier(st)
    app = FastAPI(title="CRM ANSYS REPORT", docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(SessionMiddleware, secret_key=st.secret_key, https_only=st.https_only, same_site="lax", max_age=30 * 86400,
                       session_cookie="crm_session")
    app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
    tpl = Jinja2Templates(directory=str(HERE / "templates"))
    tpl.env.filters["rub"] = A.rub
    tpl.env.filters["fromjson"] = lambda s: json.loads(s or "{}")
    tpl.env.filters["dt"] = lambda d, f="%d.%m %H:%M": d.strftime(f) if d else ""
    tpl.env.globals.update(STAGES=STAGES, OPEN_STAGES=OPEN_STAGES, WON=WON, LOST=LOST, ACT_KINDS=ACT_KINDS, ACT_ICONS=ACT_ICONS,
                           asset_v=int((HERE / "static" / "crm.css").stat().st_mtime))
    app.state.settings, app.state.Session, app.state.notifier = st, Session, notifier

    with Session() as db:                                       # первый администратор из переменных окружения
        if st.admin_email and st.admin_password and not db.scalar(select(Manager).where(Manager.email == st.admin_email)):
            db.add(Manager(email=st.admin_email, name="Администратор", password_hash=hash_password(st.admin_password), role="admin"))
            db.commit()

    # --- вспомогательное ---
    def me(request: Request, db) -> Manager | None:
        mid = request.session.get("mid")
        m = db.get(Manager, mid) if mid else None
        return m if m and m.active else None

    def csrf(request: Request) -> str:
        if "csrf" not in request.session:
            request.session["csrf"] = secrets.token_urlsafe(16)
        return request.session["csrf"]

    def csrf_ok(request: Request, token: str) -> bool:
        return bool(token) and hmac.compare_digest(token, request.session.get("csrf", ""))

    def page(request: Request, name: str, m: Manager, **ctx):
        with Session() as db:
            my_open = db.scalar(select(func.count()).select_from(Task).where(Task.done.is_(False), Task.due < now(),
                                                                               or_(Task.assignee_id == m.id, Task.assignee_id.is_(None)))) or 0
        return tpl.TemplateResponse(request, name, {"me": m, "csrf": csrf(request), "overdue_n": my_open, "st": st, **ctx})

    def guard(request: Request, db, admin: bool = False):
        m = me(request, db)
        if not m:
            return None, RedirectResponse("/login", status_code=303)
        if admin and m.role != "admin":
            return None, HTMLResponse("Только для администратора", status_code=403)
        return m, None

    def api_ok(request: Request) -> bool:
        auth = request.headers.get("authorization", "")
        tok = auth[7:] if auth.lower().startswith("bearer ") else request.headers.get("x-crm-token", "")
        return bool(tok) and hmac.compare_digest(tok, st.api_token)

    # --- API: сайт и формы ---
    @app.get("/api/v1/health")
    def health():
        with Session() as db:
            db.execute(select(Manager.id).limit(1))
        return {"ok": True}

    @app.post("/api/v1/events")
    async def api_events(request: Request):
        """Событие сайта или пачка событий ({"events": [...]}). Повторная доставка того же id игнорируется."""
        if not api_ok(request):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        body = await request.json()
        events = body.get("events") if isinstance(body, dict) and "events" in body else [body]
        out = []
        with Session() as db:
            for ev in events[:500]:
                try:
                    out.append(handle_event(db, ev, notifier, st))
                    db.commit()
                except Exception as e:   # noqa: BLE001  (одно плохое событие не останавливает пачку)
                    db.rollback()
                    out.append(f"error: {e}"[:200])
        return {"ok": True, "results": out}

    @app.post("/api/v1/leads")
    async def api_leads(request: Request):
        """Заявка с любой формы или виджета (JSON или обычная форма): name, phone, email, company, message, form, page, utm_*."""
        if not api_ok(request):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        ct = request.headers.get("content-type", "")
        lead = await request.json() if "json" in ct else {k: str(v) for k, v in (await request.form()).items()}
        with Session() as db:
            try:
                handle_lead(db, lead, notifier, st)
                db.commit()
            except ValueError as e:
                return JSONResponse({"error": str(e)}, status_code=400)
        return {"ok": True}

    # --- вход ---
    @app.get("/login", response_class=HTMLResponse)
    def login_form(request: Request):
        return tpl.TemplateResponse(request, "login.html", {"csrf": csrf(request), "error": ""})

    @app.post("/login")
    def login(request: Request, email: str = Form(""), password: str = Form(""), token: str = Form("", alias="csrf")):
        if not csrf_ok(request, token):
            return HTMLResponse("Сессия устарела. Обновите страницу.", status_code=400)
        with Session() as db:
            m = db.scalar(select(Manager).where(Manager.email == email.strip().lower()))
            if not m or not m.active or not verify_password(password, m.password_hash):
                return tpl.TemplateResponse(request, "login.html", {"csrf": csrf(request), "error": "Неверная почта или пароль"}, status_code=400)
            request.session.clear()
            request.session["mid"] = m.id
        return RedirectResponse("/", status_code=303)

    @app.post("/logout")
    def logout(request: Request, token: str = Form("", alias="csrf")):
        if csrf_ok(request, token):
            request.session.clear()
        return RedirectResponse("/login", status_code=303)

    # --- сводка ---
    @app.get("/", response_class=HTMLResponse)
    def home(request: Request, p: str = "30"):
        with Session() as db:
            m, r = guard(request, db)
            if r:
                return r
            p = p if p in A.PERIODS else "30"
            tasks = db.scalars(select(Task).where(Task.done.is_(False), or_(Task.assignee_id == m.id, Task.assignee_id.is_(None)))
                               .order_by(Task.due.is_(None), Task.due).limit(8)).all()
            new_leads = db.scalars(select(Contact).order_by(Contact.created.desc()).limit(6)).all()
            feed = db.execute(select(Activity, Contact).join(Contact, Contact.id == Activity.contact_id, isouter=True)
                              .order_by(Activity.id.desc()).limit(12)).all()
            return page(request, "home.html", m, s=A.summary(db, p), period=p, tasks=tasks, new_leads=new_leads, feed=feed,
                        chart_rows=A.revenue_by_day(db, 30), sources=A.by_source(db, p)[:6], tab="home")

    # --- сделки (канбан) ---
    @app.get("/deals", response_class=HTMLResponse)
    def deals(request: Request, mine: str = "", closed: str = ""):
        with Session() as db:
            m, r = guard(request, db)
            if r:
                return r
            q = select(Deal).order_by(Deal.stage_changed.desc())
            if mine:
                q = q.where(Deal.owner_id == m.id)
            if not closed:
                q = q.where(or_(Deal.stage.in_(OPEN_STAGES), Deal.closed_at >= now() - dt.timedelta(days=14)))
            rows = db.scalars(q).all()
            cols = [(s, [d for d in rows if d.stage == s]) for s in STAGES]
            for d in rows:
                _ = d.contact.title
            return page(request, "deals.html", m, cols=cols, mine=mine, closed=closed, tab="deals")

    @app.get("/deals/{did}", response_class=HTMLResponse)
    def deal(request: Request, did: int):
        with Session() as db:
            m, r = guard(request, db)
            if r:
                return r
            d = db.get(Deal, did)
            if not d:
                return HTMLResponse("Не найдено", status_code=404)
            acts = db.scalars(select(Activity).where(Activity.deal_id == did).order_by(Activity.id.desc())).all()
            tasks = db.scalars(select(Task).where(Task.deal_id == did).order_by(Task.done, Task.due)).all()
            _ = d.contact.title
            return page(request, "deal.html", m, d=d, acts=acts, tasks=tasks, managers=db.scalars(select(Manager).where(Manager.active.is_(True))).all(), tab="deals")

    @app.post("/deals/{did}")
    def deal_save(request: Request, did: int, token: str = Form("", alias="csrf"), stage: str = Form(""), title: str = Form(""),
                  amount: str = Form(""), owner_id: str = Form(""), lost_reason: str = Form("")):
        if not csrf_ok(request, token):
            return HTMLResponse("Сессия устарела", status_code=400)
        with Session() as db:
            m, r = guard(request, db)
            if r:
                return r
            d = db.get(Deal, did)
            if not d:
                return HTMLResponse("Не найдено", status_code=404)
            if title.strip():
                d.title = title.strip()[:200]
            if amount.strip().isdigit():
                d.amount = int(amount)
            if owner_id.isdigit():
                d.owner_id = int(owner_id)
            if lost_reason.strip():
                d.lost_reason = lost_reason.strip()[:300]
            if stage in STAGES and stage != d.stage:
                move(db, d, stage, m, forward_only=False)
                if stage not in (WON, LOST):
                    d.closed_at = None
            db.commit()
        return RedirectResponse(request.headers.get("referer") or f"/deals/{did}", status_code=303)

    @app.post("/deal-new")
    def deal_new(request: Request, token: str = Form("", alias="csrf"), contact_id: str = Form(""), title: str = Form("")):
        if not csrf_ok(request, token):
            return HTMLResponse("Сессия устарела", status_code=400)
        with Session() as db:
            m, r = guard(request, db)
            if r:
                return r
            c = db.get(Contact, int(contact_id)) if contact_id.isdigit() else None
            if not c:
                return HTMLResponse("Не найдено", status_code=404)
            d = Deal(contact_id=c.id, title=title.strip()[:200] or c.title, source=c.source, owner_id=m.id)
            db.add(d)
            db.flush()
            activity(db, c, d, "stage", f"Новая сделка (вручную): {d.title}", m)
            db.commit()
            return RedirectResponse(f"/deals/{d.id}", status_code=303)

    # --- контакты ---
    @app.get("/contacts", response_class=HTMLResponse)
    def contacts(request: Request, q: str = "", source: str = "", stage: str = "", kind: str = "", tag: str = "", region: str = "", idle: str = ""):
        with Session() as db:
            m, r = guard(request, db)
            if r:
                return r
            f = {"q": q, "source": source, "stage": stage, "kind": kind, "tag": tag, "region": region, "idle": idle}
            rows = db.scalars(segment_query(f).limit(500)).all()
            for c in rows:
                _ = [d.stage for d in c.deals]
            sources = [s for (s,) in db.execute(select(Contact.source).distinct()).all() if s]
            segs = db.scalars(select(Segment).order_by(Segment.name)).all()
            return page(request, "contacts.html", m, rows=rows, f=f, sources=sorted(sources), segs=segs, tab="contacts")

    @app.get("/contacts/new", response_class=HTMLResponse)
    def contact_new_form(request: Request):
        with Session() as db:
            m, r = guard(request, db)
            if r:
                return r
            return page(request, "contact_new.html", m, tab="contacts")

    @app.post("/contacts/new")
    def contact_new(request: Request, token: str = Form("", alias="csrf"), name: str = Form(""), phone: str = Form(""), email: str = Form(""),
                    company: str = Form(""), source: str = Form(""), message: str = Form("")):
        if not csrf_ok(request, token):
            return HTMLResponse("Сессия устарела", status_code=400)
        with Session() as db:
            m, r = guard(request, db)
            if r:
                return r
            try:
                handle_lead(db, {"name": name, "phone": phone, "email": email, "company": company, "source": source or "Вручную",
                                 "message": message, "form": f"добавил {m.name or m.email}"}, notifier, st)
            except ValueError as e:
                return page(request, "contact_new.html", m, error=str(e), tab="contacts")
            db.commit()
            c = db.scalar(select(Contact).order_by(Contact.id.desc()))
            return RedirectResponse(f"/contacts/{c.id}", status_code=303)

    @app.get("/contacts/{cid}", response_class=HTMLResponse)
    def contact(request: Request, cid: int):
        with Session() as db:
            m, r = guard(request, db)
            if r:
                return r
            c = db.get(Contact, cid)
            if not c:
                return HTMLResponse("Не найдено", status_code=404)
            acts = db.scalars(select(Activity).where(Activity.contact_id == cid).order_by(Activity.created.desc(), Activity.id.desc()).limit(300)).all()
            for a in acts:
                _ = a.manager
            tasks = db.scalars(select(Task).where(Task.contact_id == cid).order_by(Task.done, Task.due)).all()
            paid = sum(d.amount for d in c.deals if d.paid_at)
            return page(request, "contact.html", m, c=c, acts=acts, tasks=tasks, paid=paid,
                        managers=db.scalars(select(Manager).where(Manager.active.is_(True))).all(), tab="contacts",
                        mail_on=bool(st.smtp_host and st.mail_from) or st.send_inline)

    @app.post("/contacts/{cid}")
    def contact_save(request: Request, cid: int, token: str = Form("", alias="csrf"), name: str = Form(""), phone: str = Form(""),
                     email: str = Form(""), company: str = Form(""), region: str = Form(""), tags: str = Form(""), note: str = Form(""),
                     owner_id: str = Form("")):
        if not csrf_ok(request, token):
            return HTMLResponse("Сессия устарела", status_code=400)
        with Session() as db:
            m, r = guard(request, db)
            if r:
                return r
            c = db.get(Contact, cid)
            if not c:
                return HTMLResponse("Не найдено", status_code=404)
            c.name, c.phone, c.company, c.region = name.strip() or None, phone.strip() or None, company.strip() or None, region.strip() or None
            c.email = email.strip().lower() or c.email
            c.tags = ", ".join(t.strip() for t in tags.split(",") if t.strip())[:500]
            c.note = note.strip() or None
            if owner_id.isdigit():
                c.owner_id = int(owner_id)
            db.commit()
        return RedirectResponse(f"/contacts/{cid}", status_code=303)

    @app.post("/contacts/{cid}/activity")
    def contact_activity(request: Request, cid: int, token: str = Form("", alias="csrf"), kind: str = Form("note"), text: str = Form(""),
                         send: str = Form(""), subject: str = Form(""), next_task: str = Form(""), next_days: str = Form("")):
        """Записать звонок/письмо/заметку; письмо можно сразу отправить клиенту; следом - задача на следующий шаг."""
        if not csrf_ok(request, token):
            return HTMLResponse("Сессия устарела", status_code=400)
        with Session() as db:
            m, r = guard(request, db)
            if r:
                return r
            c = db.get(Contact, cid)
            if not c:
                return HTMLResponse("Не найдено", status_code=404)
            d = db.scalar(select(Deal).where(Deal.contact_id == cid, Deal.stage.in_(OPEN_STAGES)).order_by(Deal.id.desc()))
            kind = kind if kind in ACT_KINDS else "note"
            body = text.strip()
            if kind == "email" and send and c.email and body:
                ok = notifier.email(c.email, subject.strip() or "ANSYS REPORT", body)
                body = ("Отправлено письмо" if ok else "Письмо НЕ отправлено (почта не настроена)") + (f" «{subject.strip()}»" if subject.strip() else "") + ":\n" + body
            if body:
                activity(db, c, d, kind, body, m)
                c.last_activity = now()
                if kind in ("call", "email", "meeting", "message") and d and d.stage == STAGES[0]:
                    move(db, d, "Связались", m)
                for t in db.scalars(select(Task).where(Task.contact_id == cid, Task.auto == "call_lead", Task.done.is_(False))).all():
                    if kind in ("call", "email", "meeting", "message"):
                        t.done, t.done_at = True, now()
            if next_task.strip():
                days = int(next_days) if next_days.strip().isdigit() else 1
                db.add(Task(title=next_task.strip()[:300], contact_id=cid, deal_id=d.id if d else None, assignee_id=m.id,
                            due=now() + dt.timedelta(days=days)))
            db.commit()
        return RedirectResponse(f"/contacts/{cid}", status_code=303)

    # --- задачи ---
    @app.get("/tasks", response_class=HTMLResponse)
    def tasks(request: Request, v: str = "my"):
        with Session() as db:
            m, r = guard(request, db)
            if r:
                return r
            q = select(Task).order_by(Task.done, Task.due.is_(None), Task.due)
            if v == "my":
                q = q.where(Task.done.is_(False), or_(Task.assignee_id == m.id, Task.assignee_id.is_(None)))
            elif v == "all":
                q = q.where(Task.done.is_(False))
            elif v == "done":
                q = q.where(Task.done.is_(True)).order_by(Task.done_at.desc())
            rows = db.scalars(q.limit(300)).all()
            for t in rows:
                _ = (t.contact.title if t.contact else "", t.assignee)
            return page(request, "tasks.html", m, rows=rows, v=v, managers=db.scalars(select(Manager).where(Manager.active.is_(True))).all(), tab="tasks")

    @app.post("/tasks")
    def task_new(request: Request, token: str = Form("", alias="csrf"), title: str = Form(""), contact_id: str = Form(""), due: str = Form(""),
                 assignee_id: str = Form(""), priority: str = Form("normal")):
        if not csrf_ok(request, token):
            return HTMLResponse("Сессия устарела", status_code=400)
        with Session() as db:
            m, r = guard(request, db)
            if r:
                return r
            if title.strip():
                try:
                    due_dt = dt.datetime.fromisoformat(due) if due else None
                except ValueError:
                    due_dt = None
                cid = int(contact_id) if contact_id.isdigit() else None
                d = db.scalar(select(Deal).where(Deal.contact_id == cid, Deal.stage.in_(OPEN_STAGES)).order_by(Deal.id.desc())) if cid else None
                db.add(Task(title=title.strip()[:300], contact_id=cid, deal_id=d.id if d else None, due=due_dt,
                            assignee_id=int(assignee_id) if assignee_id.isdigit() else m.id, priority="high" if priority == "high" else "normal"))
                db.commit()
        return RedirectResponse(request.headers.get("referer") or "/tasks", status_code=303)

    @app.post("/tasks/{tid}/done")
    def task_done(request: Request, tid: int, token: str = Form("", alias="csrf")):
        if not csrf_ok(request, token):
            return HTMLResponse("Сессия устарела", status_code=400)
        with Session() as db:
            m, r = guard(request, db)
            if r:
                return r
            t = db.get(Task, tid)
            if t:
                t.done, t.done_at = (not t.done), (now() if not t.done else None)
                if t.done and t.contact_id:
                    activity(db, db.get(Contact, t.contact_id), db.get(Deal, t.deal_id) if t.deal_id else None, "system", f"Задача выполнена: {t.title}", m)
                db.commit()
        return RedirectResponse(request.headers.get("referer") or "/tasks", status_code=303)

    # --- аналитика ---
    @app.get("/analytics", response_class=HTMLResponse)
    def analytics(request: Request, p: str = "30"):
        with Session() as db:
            m, r = guard(request, db)
            if r:
                return r
            p = p if p in A.PERIODS else "30"
            return page(request, "analytics.html", m, s=A.summary(db, p), period=p, sources=A.by_source(db, p), landings=A.by_source(db, p, "landing"),
                        mgrs=A.managers(db, p), chart_rows=A.revenue_by_day(db, 30), tab="analytics")

    # --- сегменты и рассылка ---
    @app.post("/segments")
    def segment_save(request: Request, token: str = Form("", alias="csrf"), name: str = Form(""), filters: str = Form("{}")):
        if not csrf_ok(request, token):
            return HTMLResponse("Сессия устарела", status_code=400)
        with Session() as db:
            m, r = guard(request, db)
            if r:
                return r
            if name.strip():
                db.add(Segment(name=name.strip()[:120], filters=filters))
                db.commit()
        return RedirectResponse("/contacts?" + "&".join(f"{k}={v}" for k, v in json.loads(filters or "{}").items() if v), status_code=303)

    @app.post("/mail")
    def segment_mail(request: Request, token: str = Form("", alias="csrf"), filters: str = Form("{}"), subject: str = Form(""), body: str = Form("")):
        """Рассылка по текущему фильтру (сегменту): письмо каждому контакту с почтой, запись в историю."""
        if not csrf_ok(request, token):
            return HTMLResponse("Сессия устарела", status_code=400)
        with Session() as db:
            m, r = guard(request, db, admin=True)
            if r:
                return r
            n = 0
            if subject.strip() and body.strip():
                for c in db.scalars(segment_query(json.loads(filters or "{}"))).all():
                    if c.email and notifier.email(c.email, subject.strip(), body.strip()):
                        activity(db, c, None, "email", f"Рассылка «{subject.strip()}»", m)
                        n += 1
                db.commit()
            return page(request, "done.html", m, text=f"Отправлено писем: {n}", back="/contacts", tab="contacts")

    @app.get("/contacts.csv")
    def contacts_csv(request: Request, q: str = "", source: str = "", stage: str = "", kind: str = "", tag: str = "", region: str = "", idle: str = ""):
        with Session() as db:
            m, r = guard(request, db)
            if r:
                return r
            buf = io.StringIO()
            w = csv.writer(buf, delimiter=";")
            w.writerow(["id", "имя", "почта", "телефон", "компания", "регион", "теги", "источник", "utm_medium", "utm_campaign", "страница входа",
                        "этап последней сделки", "оплачено, ₽", "создан", "последняя активность"])
            for c in db.scalars(segment_query({"q": q, "source": source, "stage": stage, "kind": kind, "tag": tag, "region": region, "idle": idle})).all():
                w.writerow([c.id, c.name or "", c.email or "", c.phone or "", c.company or "", c.region or "", c.tags, c.source or "", c.utm_medium or "",
                            c.utm_campaign or "", c.landing or "", c.deals[0].stage if c.deals else "", sum(d.amount for d in c.deals if d.paid_at),
                            c.created.strftime("%d.%m.%Y"), c.last_activity.strftime("%d.%m.%Y %H:%M")])
            return Response("﻿" + buf.getvalue(), media_type="text/csv; charset=utf-8", headers={"Content-Disposition": 'attachment; filename="contacts.csv"'})

    # --- настройки ---
    @app.get("/settings", response_class=HTMLResponse)
    def settings_page(request: Request):
        with Session() as db:
            m, r = guard(request, db, admin=True)
            if r:
                return r
            rules = [(k, t, rule_on(db, k)) for k, t in RULES.items()]
            return page(request, "settings.html", m, managers=db.scalars(select(Manager).order_by(Manager.id)).all(), rules=rules,
                        tg_on=bool(st.tg_token and st.tg_chat), mail_on=bool(st.smtp_host and st.mail_from), tab="settings")

    @app.post("/settings/rules")
    async def settings_rules(request: Request):
        form = await request.form()
        if not csrf_ok(request, str(form.get("csrf", ""))):
            return HTMLResponse("Сессия устарела", status_code=400)
        with Session() as db:
            m, r = guard(request, db, admin=True)
            if r:
                return r
            for k in RULES:
                s = db.get(Setting, "rule:" + k) or Setting(key="rule:" + k)
                s.value = "1" if form.get(k) else "0"
                db.merge(s)
            db.commit()
        return RedirectResponse("/settings", status_code=303)

    @app.post("/settings/managers")
    def settings_manager(request: Request, token: str = Form("", alias="csrf"), email: str = Form(""), name: str = Form(""), password: str = Form(""),
                         role: str = Form("manager"), toggle: str = Form("")):
        if not csrf_ok(request, token):
            return HTMLResponse("Сессия устарела", status_code=400)
        with Session() as db:
            m, r = guard(request, db, admin=True)
            if r:
                return r
            if toggle.isdigit():
                x = db.get(Manager, int(toggle))
                if x and x.id != m.id:
                    x.active = not x.active
            elif email.strip() and len(password) >= 8 and not db.scalar(select(Manager).where(Manager.email == email.strip().lower())):
                db.add(Manager(email=email.strip().lower(), name=name.strip()[:120], password_hash=hash_password(password),
                               role="admin" if role == "admin" else "manager"))
            db.commit()
        return RedirectResponse("/settings", status_code=303)

    @app.post("/settings/test")
    def settings_test(request: Request, token: str = Form("", alias="csrf")):
        if not csrf_ok(request, token):
            return HTMLResponse("Сессия устарела", status_code=400)
        with Session() as db:
            m, r = guard(request, db, admin=True)
            if r:
                return r
            notifier.telegram("Проверка уведомлений CRM ANSYS REPORT ✅")
            notifier.email(m.email, "Проверка почты CRM", "Почта CRM настроена верно.")
            return page(request, "done.html", m, text="Тестовые уведомления отправлены (Telegram и письмо на вашу почту, если настроены).",
                        back="/settings", tab="settings")

    return app
