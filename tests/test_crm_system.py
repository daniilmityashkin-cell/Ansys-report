"""Отдельная CRM: API приёма событий сайта и заявок, автосценарии (сделка по этапам, задачи, письма, Telegram), кабинет, аналитика."""
import re

from fastapi.testclient import TestClient

from crm.app import create_app
from crm.config import Settings
from crm.models import Contact, Deal, Task

TOKEN = "test-token-123"


def _crm(tmp_path, all_rules=True):
    app = create_app(Settings(data_dir=tmp_path / "crm", api_token=TOKEN, admin_email="boss@example.com", admin_password="secret-pass-1",
                              send_inline=True, public_url="http://crm.local", site_url="http://site.local"))
    if all_rules:                                       # сценарии уведомлений по умолчанию выключены - для проверки включаем все
        from crm.automation import RULES
        from crm.models import Setting
        with app.state.Session() as db:
            for k in RULES:
                db.merge(Setting(key="rule:" + k, value="1"))
            db.commit()
    return app


def test_default_rules_quiet(tmp_path):
    """По умолчанию: без задачи «связаться за 15 минут», без писем и Telegram; задача «не оплатил» и ошибка расчёта - остаются."""
    app = _crm(tmp_path, all_rules=False)
    api = TestClient(app)
    H = {"Authorization": f"Bearer {TOKEN}"}
    api.post("/api/v1/events", json={"events": [ev(1, "register", U), ev(2, "pay_start", U, generation=5, mode="pay"),
                                                ev(3, "job_error", U, generation=5, error="x"), ev(4, "paid", U, amount=1500)]}, headers=H)
    api.post("/api/v1/leads", json={"phone": "+7 900", "name": "Лид"}, headers=H)
    assert app.state.notifier.outbox == []
    with app.state.Session() as db:
        autos = sorted(t.auto for t in db.query(Task).all())
        assert autos == ["job_error", "unpaid"]


def _login(c, email="boss@example.com", pw="secret-pass-1"):
    tok = re.search(r'name="csrf" value="([^"]+)"', c.get("/login").text).group(1)
    return c.post("/login", data={"csrf": tok, "email": email, "password": pw}, follow_redirects=False)


def _csrf(c, path):
    return re.search(r'name="csrf" value="([^"]+)"', c.get(path).text).group(1)


def ev(i, kind, user=None, **meta):
    return {"id": f"site-{i}", "kind": kind, "at": "2026-10-28T10:00:00", "visitor": "v1", "source": "yandex_direct", "path": "/",
            "meta": meta, "user": user or {}}


U = {"site_user_id": 7, "email": "client@zavod.ru", "source": "yandex_direct", "utm_medium": "cpc", "utm_campaign": "osen", "landing": "/"}


def test_api_auth_and_site_flow(tmp_path):
    app = _crm(tmp_path)
    api = TestClient(app)
    assert api.post("/api/v1/events", json=ev(1, "visit")).status_code == 401
    H = {"Authorization": f"Bearer {TOKEN}"}
    flow = [ev(1, "visit"), ev(2, "register", U), ev(3, "generation", U, generation=11, title="РВС-9985"), ev(4, "loads", U, generation=11),
            ev(5, "report_data", U, generation=11), ev(6, "pay_start", U, generation=11, mode="pay")]
    r = api.post("/api/v1/events", json={"events": flow}, headers=H)
    assert r.status_code == 200 and r.json()["results"] == ["ok"] * 6
    assert api.post("/api/v1/events", json=ev(3, "generation", U, generation=11), headers=H).json()["results"] == ["duplicate"]   # повторная доставка
    S = app.state.Session
    with S() as db:
        c = db.query(Contact).one()
        d = db.query(Deal).one()
        assert c.email == "client@zavod.ru" and c.source == "yandex_direct" and c.utm_campaign == "osen" and c.site_user_id == 7
        assert d.stage == "Ожидает оплаты" and d.site_generation_id == 11
        autos = {t.auto for t in db.query(Task).filter(Task.done.is_(False))}
        assert autos == {"call_lead", "unpaid"}
    out = app.state.notifier.outbox
    assert any(x[0] == "email" and x[1] == "client@zavod.ru" and "Спасибо" in x[2] for x in out)        # письмо «спасибо за заявку»
    assert any(x[0] == "tg" and "Новый лид" in x[1] for x in out)
    api.post("/api/v1/events", json={"events": [ev(7, "paid", U, amount=1500, provider="yookassa", method="sbp", what="генерация №11"),
                                                ev(8, "job_done", U, generation=11)]}, headers=H)
    with S() as db:
        d = db.query(Deal).one()
        assert d.stage == "Отчёт выдан" and d.amount == 1500 and d.paid_at is not None and d.closed_at is not None
        assert not db.query(Task).filter(Task.auto == "unpaid", Task.done.is_(False)).count()            # оплатил - задача «дожать» закрыта
    assert any(x[0] == "tg" and "Оплата 1500" in x[1] for x in app.state.notifier.outbox)
    assert any(x[0] == "email" and "отчёт готов" in x[2] for x in app.state.notifier.outbox)
    # повторная покупка - новая сделка
    api.post("/api/v1/events", json=ev(9, "generation", U, generation=12), headers=H)
    with S() as db:
        assert db.query(Deal).count() == 2 and db.query(Deal).order_by(Deal.id.desc()).first().title.startswith("Повторный заказ")
    # ошибка расчёта - срочная задача
    api.post("/api/v1/events", json=ev(10, "job_error", U, generation=12, error="лицензия"), headers=H)
    with S() as db:
        assert db.query(Task).filter(Task.auto == "job_error", Task.priority == "high").count() == 1


def test_lead_form_and_cabinet(tmp_path):
    app = _crm(tmp_path)
    api = TestClient(app)
    H = {"X-CRM-Token": TOKEN}
    assert api.post("/api/v1/leads", data={"name": "Иван"}, headers=H).status_code == 400                # без контактов - ошибка
    r = api.post("/api/v1/leads", data={"name": "Иван Петров", "phone": "+7 900 111-22-33", "company": "НПЗ", "message": "Нужен расчёт РВС-20000",
                                        "form": "главная: заявка", "page": "/", "utm_source": "vk_ads"}, headers=H)
    assert r.status_code == 200
    c = TestClient(app)
    assert c.get("/", follow_redirects=False).status_code == 303
    assert _login(c, pw="wrong").status_code == 400
    assert _login(c).status_code == 303
    home = c.get("/").text
    assert "Иван Петров" in home and "vk_ads" in home and "Связаться с новым клиентом" in home
    cid = re.search(r'href="/contacts/(\d+)">Иван Петров', home).group(1)
    card = c.get(f"/contacts/{cid}").text
    assert "Нужен расчёт РВС-20000" in card and "tel:+7 900 111-22-33" in card
    # звонок: сделка «Связались», задача «связаться» закрыта, следующая задача создана
    c.post(f"/contacts/{cid}/activity", data={"csrf": _csrf(c, f"/contacts/{cid}"), "kind": "call", "text": "Обсудили объём, пришлёт замеры",
                                              "next_task": "Проверить, загрузил ли замеры", "next_days": "1"})
    card = c.get(f"/contacts/{cid}").text
    assert "Обсудили объём" in card and "Новый лид → Связались" in card and "Проверить, загрузил ли замеры" in card
    with app.state.Session() as db:
        assert not db.query(Task).filter(Task.auto == "call_lead", Task.done.is_(False)).count()
    deals = c.get("/deals").text
    did = re.search(r'href="/deals/(\d+)"', deals).group(1)
    c.post(f"/deals/{did}", data={"csrf": _csrf(c, "/deals"), "stage": "Проигран", "lost_reason": "дорого"})
    assert "Проигран" in c.get(f"/deals/{did}").text
    assert "Конверсия по этапам" in c.get("/analytics?p=all").text
    lst = c.get("/contacts?source=vk_ads").text
    assert "Иван Петров" in lst
    csv_ = c.get("/contacts.csv?source=vk_ads")
    assert "Иван Петров" in csv_.text and "vk_ads" in csv_.text
    # менеджер: без настроек
    c.post("/settings/managers", data={"csrf": _csrf(c, "/settings"), "email": "m1@example.com", "name": "Маша", "password": "manager-pass", "role": "manager"})
    m = TestClient(app)
    assert _login(m, "m1@example.com", "manager-pass").status_code == 303
    assert m.get("/settings").status_code == 403 and m.get("/tasks").status_code == 200
    # выключенный сценарий не срабатывает
    c.post("/settings/rules", data={"csrf": _csrf(c, "/settings"), "lead_task": "", "lead_email": "1", "lead_tg": "1"})
    api.post("/api/v1/leads", json={"email": "new@x.ru", "name": "Б"}, headers=H)
    with app.state.Session() as db:
        nc = db.query(Contact).filter(Contact.email == "new@x.ru").one()
        assert not db.query(Task).filter(Task.contact_id == nc.id).count()


def test_site_sends_events_and_lead_to_crm(tmp_path):
    """Сайт -> CRM: заявка с формы на главной и действия клиента уходят в CRM через очередь; CRM недоступна - события ждут."""
    from server.app import create_app as site_app
    from server.config import Settings as SiteSettings
    from server.crm_sync import push
    from server.models import Event
    from tests.test_server import _pay_fake, csrf_of, new_generation, register
    crm = _crm(tmp_path)
    crm_c = TestClient(crm)
    site = site_app(SiteSettings(data_dir=tmp_path / "site", inline_jobs=True, secret_key="t" * 32, crm_url="http://crm", crm_token=TOKEN))
    s = TestClient(site)
    page = s.get("/?utm_source=telegram_post&utm_campaign=noyabr").text
    assert 'action="/lead"' in page
    r = s.post("/lead", data={"csrf": csrf_of(s, "/"), "name": "Олег", "phone": "+7 911 000-00-00", "message": "РВС-5000, есть нивелировка"}, follow_redirects=False)
    assert r.headers["location"] == "/?lead=ok#lead" and "Заявка принята" in s.get("/?lead=ok").text
    assert "Укажите телефон" in s.get(s.post("/lead", data={"csrf": csrf_of(s, "/"), "name": "x"}, follow_redirects=False).headers["location"]).text
    register(s, email="olga@neft.ru")
    _pay_fake(s, new_generation(s).headers["location"])
    down = lambda u, json, headers: (_ for _ in ()).throw(ConnectionError("CRM выключена"))   # noqa: E731
    assert push(site.state.Session, "http://crm", TOKEN, post=down) == 0                         # CRM недоступна - ничего не потеряно
    via_crm = lambda u, json, headers: crm_c.post(u.replace("http://crm", ""), json=json, headers=headers)   # noqa: E731
    n = push(site.state.Session, "http://crm", TOKEN, post=via_crm)
    assert n >= 6
    assert push(site.state.Session, "http://crm", TOKEN, post=via_crm) == 0                       # всё отправлено
    with site.state.Session() as db:
        assert not db.query(Event).filter(Event.sent_at.is_(None)).count()
    with crm.state.Session() as db:
        oleg = db.query(Contact).filter(Contact.phone == "+7 911 000-00-00").one()
        assert oleg.name == "Олег" and oleg.source == "telegram_post" and oleg.utm_campaign == "noyabr"
        olga = db.query(Contact).filter(Contact.email == "olga@neft.ru").one()
        d = db.query(Deal).filter(Deal.contact_id == olga.id).one()
        assert d.stage in ("Ожидает оплаты", "Оплачено", "Отчёт выдан")
