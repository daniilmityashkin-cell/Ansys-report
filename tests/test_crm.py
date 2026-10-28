"""CRM /admin: доступ только администраторам, источник лида (utm), события воронки, оплата, карточка клиента, выгрузка."""
import re

from fastapi.testclient import TestClient

from server.app import create_app
from server.config import Settings
from server.crm import source_label
from tests.test_server import _pay_fake, csrf_of, new_generation, register


def _site(tmp_path):
    return create_app(Settings(data_dir=tmp_path, inline_jobs=True, secret_key="t" * 32, admin_emails=frozenset({"boss@example.com"})))


def test_source_label():
    assert source_label("vk_ads", "") == "vk_ads"
    assert source_label("", "https://yandex.ru/search/?text=рвс") == "Яндекс (поиск)"
    assert source_label("", "https://t.me/channel") == "Telegram"
    assert source_label("", "https://www.partner-site.ru/page") == "partner-site.ru"
    assert source_label("", "") == "Прямой заход"
    assert source_label("", "https://ansys-report.ru/x", "ansys-report.ru") == "Прямой заход"


def test_crm_flow(tmp_path):
    site = _site(tmp_path)
    c = TestClient(site)
    c.get("/?utm_source=yandex_direct&utm_medium=cpc&utm_campaign=rvs_osen", headers={"referer": "https://yandex.ru/"})
    register(c, email="client@example.com")
    gen = new_generation(c).headers["location"]
    _pay_fake(c, gen)
    assert c.get("/admin").status_code == 403                                  # обычный клиент в CRM не попадает
    a = TestClient(site)
    assert a.get("/admin", follow_redirects=False).status_code == 303          # без входа - на страницу входа
    register(a, email="boss@example.com")
    assert '<a href="/admin">CRM</a>' in a.get("/cabinet").text
    page = a.get("/admin?p=30").text
    assert "Выручка" in page and "yandex_direct" in page and "Воронка" in page and "Оплата прошла" in page
    rows = a.get("/admin/clients?q=client").text
    uid = re.search(r'href="/admin/clients/(\d+)">client@example.com', rows).group(1)
    card = a.get(f"/admin/clients/{uid}").text
    assert "yandex_direct" in card and "cpc" in card and "rvs_osen" in card and "Создал заказ" in card and "Оплата прошла" in card
    assert "Клиент" in card                                                     # статус по оплате - автоматически
    r = a.post(f"/admin/clients/{uid}", data={"csrf": csrf_of(a, f"/admin/clients/{uid}"), "crm_status": "Постоянный", "crm_note": "Звонил, нужен РВС-20000",
                                               "phone": "+7 900 000-00-00", "company": "ООО Резервуар", "add_credits": "5"}, follow_redirects=False)
    assert r.status_code == 303
    card = a.get(f"/admin/clients/{uid}").text
    assert "Звонил, нужен РВС-20000" in card and "ООО Резервуар" in card and "Выданы генерации" in card and "<b>5</b>" in card
    assert a.post(f"/admin/clients/{uid}", data={"csrf": "x"}).status_code == 400
    pays = a.get("/admin/payments?s=paid").text
    assert "client@example.com" in pays and "Тест" in pays
    csv_ = a.get("/admin/export/clients.csv")
    assert csv_.status_code == 200 and "client@example.com" in csv_.text and "yandex_direct" in csv_.text and "Постоянный" in csv_.text
    assert "client@example.com" in a.get("/admin/export/payments.csv").text
    ev = a.get("/admin/events?k=register").text
    assert "client@example.com" in ev and "boss@example.com" in ev
    assert c.get("/admin/export/clients.csv").status_code == 403
