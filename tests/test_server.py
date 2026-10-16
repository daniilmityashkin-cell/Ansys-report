"""Сайт: регистрация, замеры → проверка → оплата (тестовый провайдер) → геометрия, доступ только владельцу, подписка."""
import json
import re

import pytest
from fastapi.testclient import TestClient

from server.app import create_app
from server.config import Settings
from tests.test_calc import _points_project


@pytest.fixture()
def site(tmp_path):
    app = create_app(Settings(data_dir=tmp_path, inline_jobs=True, secret_key="t" * 32))
    return app


def csrf_of(c, path):
    html = c.get(path).text
    return re.search(r'name="csrf" value="([^"]+)"', html).group(1)


def register(c, email="a@example.com", password="correct horse battery"):
    tok = csrf_of(c, "/register")
    return c.post("/register", data={"email": email, "password": password, "consent": "1", "csrf": tok}, follow_redirects=False)


def test_register_login_logout_and_csrf(site):
    c = TestClient(site)
    assert c.post("/register", data={"email": "x@example.com", "password": "correct horse battery", "consent": "1"}).status_code == 400   # без CSRF
    r = register(c)
    assert r.status_code == 303 and r.headers["location"] == "/cabinet"
    assert "Личный кабинет" in c.get("/cabinet").text
    assert register(TestClient(site)).status_code == 400                                       # почта уже занята
    c2 = TestClient(site)
    tok = csrf_of(c2, "/register")
    assert c2.post("/register", data={"email": "b@example.com", "password": "short", "consent": "1", "csrf": tok}).status_code == 400
    assert c2.post("/register", data={"email": "b@example.com", "password": "long enough pass", "csrf": tok}).status_code == 400    # нет согласия
    tok = csrf_of(c, "/cabinet")
    assert c.post("/logout", data={"csrf": tok}, follow_redirects=False).status_code == 303
    assert c.get("/cabinet", follow_redirects=False).status_code == 303
    c3 = TestClient(site)
    tok = csrf_of(c3, "/login")
    bad = c3.post("/login", data={"email": "a@example.com", "password": "wrong password!", "csrf": tok})
    assert bad.status_code == 400
    ok = c3.post("/login", data={"email": "a@example.com", "password": "correct horse battery", "csrf": tok}, follow_redirects=False)
    assert ok.status_code == 303


def new_generation(c, project=None, title="РВС-1"):
    tok = csrf_of(c, "/new")
    body = json.dumps(project or _points_project(), ensure_ascii=False)
    return c.post("/new", data={"title": title, "text": body, "csrf": tok}, follow_redirects=False)


def test_full_flow_pay_and_download(site):
    c = TestClient(site)
    register(c)
    bad = c.post("/new", data={"title": "x", "text": "не json", "csrf": csrf_of(c, "/new")})
    assert bad.status_code == 400 and "Не удалось прочитать" in bad.text
    r = new_generation(c)
    assert r.status_code == 303
    gen = r.headers["location"]
    page = c.get(gen).text
    assert "Проверка замеров" in page and "Сгенерировать и оплатить" in page
    assert c.get(gen + "/all.zip").status_code == 404                              # до оплаты файлов нет
    tok = csrf_of(c, gen)
    pay = c.post(gen + "/pay", data={"csrf": tok}, follow_redirects=False)
    assert pay.status_code == 303 and pay.headers["location"].startswith("/pay/fake/")
    pay_url = pay.headers["location"]
    assert "Тестовая оплата" in c.get(pay_url).text
    done = c.post(pay_url, data={"csrf": csrf_of(c, pay_url)}, follow_redirects=False)
    assert done.status_code == 303 and done.headers["location"] == gen
    page = c.get(gen).text
    assert "готово" in page and "Поверхность РВС.step" in page
    zr = c.get(gen + "/all.zip")
    assert zr.status_code == 200 and zr.content[:2] == b"PK"
    again = c.post(pay_url, data={"csrf": csrf_of(c, pay_url)}, follow_redirects=False)       # повтор оплаты не запускает расчёт заново
    assert again.status_code == 303
    for evil in ("/files/..%2F..%2Finput.json", "/files/%2e%2e/%2e%2e/input.json", "/files/../../input.json"):
        assert c.get(gen + evil).status_code in (404, 400, 422)                                # выход из папки результата невозможен


def test_other_user_cannot_see_generation(site):
    a = TestClient(site)
    register(a, "a@example.com")
    gen = new_generation(a).headers["location"]
    b = TestClient(site)
    register(b, "b@example.com")
    assert b.get(gen).status_code == 404
    assert b.get(gen + "/all.zip").status_code == 404
    anon = TestClient(site)
    assert anon.get(gen, follow_redirects=False).status_code == 303


def test_subscription_and_report_gate(site):
    c = TestClient(site)
    register(c)
    gen = new_generation(c).headers["location"]
    assert "Технический отчёт доступен по подписке" in c.get(gen + "/report").text
    tok = csrf_of(c, "/subscription")
    pay = c.post("/subscription/buy", data={"csrf": tok}, follow_redirects=False)
    pay_url = pay.headers["location"]
    c.post(pay_url, data={"csrf": csrf_of(c, pay_url)})
    assert "Подписка активна" in c.get(gen + "/report").text
    with site.state.Session() as db:
        from server.models import User
        u = db.query(User).one()
        first = u.subscription_until
    c.post(pay_url, data={"csrf": csrf_of(c, pay_url)})            # тот же платёж повторно: срок не растёт
    with site.state.Session() as db:
        assert db.query(User).one().subscription_until == first
