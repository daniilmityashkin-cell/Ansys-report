"""Аналитика CRM: лиды по источникам и страницам входа, воронка по этапам, выручка, средний чек, скорость сделок, работа менеджеров."""
from __future__ import annotations
import datetime as dt

from sqlalchemy import func, select, true

from .models import LOST, STAGES, WON, Activity, Contact, Deal, Manager, Task, Visit, now

PERIODS = {"7": 7, "30": 30, "90": 90, "365": 365, "all": None}


def since(period: str):
    d = PERIODS.get(period, 30)
    return None if d is None else now() - dt.timedelta(days=d)


def ge(col, t):
    return true() if t is None else col >= t


def pct(a, b) -> str:
    return (f"{100.0 * a / b:.1f}".replace(".", ",") + " %") if b else "—"


def rub(n) -> str:
    return f"{int(n or 0):,}".replace(",", " ")


def summary(db, period: str) -> dict:
    t = since(period)
    visitors = db.scalar(select(func.count(func.distinct(Visit.visitor))).where(ge(Visit.created, t))) or 0
    leads = db.scalar(select(func.count()).select_from(Contact).where(ge(Contact.created, t))) or 0
    deals = db.scalars(select(Deal).where(ge(Deal.created, t))).all()
    paid = db.scalars(select(Deal).where(Deal.paid_at.is_not(None), ge(Deal.paid_at, t))).all()
    revenue = sum(d.amount for d in paid)
    won = [d for d in deals if d.stage == WON]
    lost = [d for d in deals if d.stage == LOST]
    days = [((d.paid_at - d.created).total_seconds() / 86400) for d in paid if d.paid_at and d.created]
    # воронка: сколько сделок периода дошло до каждого этапа (этап или дальше; проигранные - по истории этапов)
    reached = []
    for i, s in enumerate(STAGES[:-1]):
        n = sum(1 for d in deals if _reached(db, d, i))
        reached.append((s, n))
    top = reached[0][1] or 1
    return {"visitors": visitors, "leads": leads, "deals": len(deals), "paid_n": len(paid), "revenue": revenue,
            "avg": round(revenue / len(paid)) if paid else 0, "won": len(won), "lost": len(lost),
            "win_rate": pct(len(won), len(won) + len(lost)), "lead_conv": pct(leads, visitors), "pay_conv": pct(len({d.contact_id for d in paid}), leads),
            "days_to_pay": (f"{sum(days) / len(days):.1f}".replace(".", ",") if days else "—"),
            "funnel": [(s, n, round(100 * n / top), pct(n, reached[0][1]), pct(n, reached[i - 1][1]) if i else "") for i, (s, n) in enumerate(reached)],
            "open_by_stage": [(s, db.scalar(select(func.count()).select_from(Deal).where(Deal.stage == s)) or 0,
                               db.scalar(select(func.coalesce(func.sum(Deal.amount), 0)).where(Deal.stage == s)) or 0) for s in STAGES]}


def _reached(db, d: Deal, i: int) -> bool:
    if d.stage != LOST:
        return STAGES.index(d.stage) >= i
    if i == 0:
        return True
    texts = db.scalars(select(Activity.text).where(Activity.deal_id == d.id, Activity.kind == "stage")).all()
    return any(("→ " + s) in x for x in texts for s in STAGES[i:-1])


def by_source(db, period: str, field: str = "source") -> list[dict]:
    t = since(period)
    col_v = Visit.source if field == "source" else Visit.landing
    rows: dict[str, dict] = {}
    def row(k):
        k = k or ("Прямой заход" if field == "source" else "—")
        return rows.setdefault(k, {"key": k, "visitors": 0, "leads": 0, "payers": 0, "revenue": 0})
    for k, n in db.execute(select(col_v, func.count(func.distinct(Visit.visitor))).where(ge(Visit.created, t)).group_by(col_v)).all():
        row(k)["visitors"] += n
    for c in db.scalars(select(Contact).where(ge(Contact.created, t))).all():
        r = row(getattr(c, field))
        r["leads"] += 1
        s = sum(d.amount for d in c.deals if d.paid_at)
        if s:
            r["payers"] += 1
            r["revenue"] += s
    out = sorted(rows.values(), key=lambda r: (-r["revenue"], -r["leads"], -r["visitors"]))
    for r in out:
        r["lead_conv"], r["pay_conv"] = pct(r["leads"], r["visitors"]), pct(r["payers"], r["leads"])
    return out


def revenue_by_day(db, days: int = 30) -> list[tuple]:
    start = (now() - dt.timedelta(days=days - 1)).date()
    out = {start + dt.timedelta(days=i): [0, 0] for i in range(days)}
    for d in db.scalars(select(Deal).where(Deal.paid_at >= dt.datetime.combine(start, dt.time()))).all():
        out.setdefault(d.paid_at.date(), [0, 0])[0] += d.amount
    for c in db.scalars(select(Contact).where(Contact.created >= dt.datetime.combine(start, dt.time()))).all():
        out.setdefault(c.created.date(), [0, 0])[1] += 1
    return [(k.strftime("%d.%m"), v[0], v[1]) for k, v in sorted(out.items())]


def managers(db, period: str) -> list[dict]:
    t = since(period)
    out = []
    for m in db.scalars(select(Manager).where(Manager.active.is_(True))).all():
        tasks_done = db.scalar(select(func.count()).select_from(Task).where(Task.assignee_id == m.id, Task.done.is_(True), ge(Task.done_at, t))) or 0
        overdue = db.scalar(select(func.count()).select_from(Task).where(Task.assignee_id == m.id, Task.done.is_(False), Task.due < now())) or 0
        acts = db.scalar(select(func.count()).select_from(Activity).where(Activity.manager_id == m.id, ge(Activity.created, t))) or 0
        won = db.scalars(select(Deal).where(Deal.owner_id == m.id, Deal.paid_at.is_not(None), ge(Deal.paid_at, t))).all()
        out.append({"m": m, "tasks_done": tasks_done, "overdue": overdue, "acts": acts, "won": len(won), "revenue": sum(d.amount for d in won)})
    return out
