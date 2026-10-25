"""Сквозной прогон на одном компьютере: сайт -> модель -> нагрузки -> помощник -> Ansys -> отчёт.

Запуск (из C:\\Ansys-report):
    python tools/e2e_local.py --project "C:\\путь\\проект.json" --out C:\\ansys_report_work\\e2e
Что делает: поднимает свой экземпляр сайта на отдельном порту с временной базой, регистрирует тестовый аккаунт без лимита,
создаёт расчёт из файла проекта (как студия), задаёт нагрузки, нажимает «Собрать отчёт», запускает помощника (Ansys), ждёт
готовый отчёт и скачивает его. Флаг --no-agent останавливается на готовой модели (без Ansys).
"""
from __future__ import annotations
import argparse
import html
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True, help="файл проекта .json (РВС Геометрия)")
    ap.add_argument("--out", default=str(Path(tempfile.gettempdir()) / "e2e_out"), help="куда скачать готовые файлы")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--fill", type=float, default=0.0, help="уровень налива, м (0 = 60%% высоты стенки)")
    ap.add_argument("--no-agent", action="store_true", help="не запускать помощника и Ansys")
    ap.add_argument("--keep-server", action="store_true", help="не останавливать сайт в конце")
    a = ap.parse_args()
    import socket
    with socket.socket() as sk:                       # занят порт - берём свободный
        if sk.connect_ex(("127.0.0.1", a.port)) == 0:
            sk2 = socket.socket(); sk2.bind(("127.0.0.1", 0)); a.port = sk2.getsockname()[1]; sk2.close()

    project = json.loads(Path(a.project).read_text(encoding="utf-8-sig"))
    H = float(str(project["height"]).replace(",", "."))
    data = Path(tempfile.mkdtemp(prefix="e2e_data_"))
    env = {**os.environ, "ASR_DATA_DIR": str(data), "ASR_PORT": str(a.port), "ASR_SECRET": "e" * 32, "ASR_UNLIMITED_EMAILS": "e2e@example.com",
           "ASR_PUBLIC_URL": f"http://127.0.0.1:{a.port}", "ASR_INLINE_JOBS": "0"}
    log = open(data / "server.log", "w", encoding="utf-8")
    srv = subprocess.Popen([sys.executable, "-m", "server"], cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
    base = f"http://127.0.0.1:{a.port}"
    s = requests.Session()
    try:
        for _ in range(60):
            try:
                if s.get(base + "/health", timeout=2).status_code == 200:
                    break
            except requests.RequestException:
                time.sleep(1)
        else:
            raise RuntimeError("сайт не запустился, см. " + str(data / "server.log"))
        csrf = lambda html_: re.search(r'name="csrf" value="([^"]+)"', html_).group(1)       # noqa: E731
        r = s.post(base + "/register", data={"email": "e2e@example.com", "password": "e2e-pass-12345", "consent": "1", "csrf": csrf(s.get(base + "/register").text)}, allow_redirects=False)
        assert r.status_code == 303, "регистрация: " + str(r.status_code)
        tok = re.search(r'data-csrf="([^"]+)"', s.get(base + "/studio").text).group(1)
        r = s.post(base + "/studio/create", json={"csrf": tok, "title": "E2E " + Path(a.project).stem, "project": project, "struct_source": "project", "loads": {}})
        assert r.status_code == 200, "создание: " + r.text
        gurl = base + r.json()["url"]
        gid = int(gurl.rsplit("/", 1)[1])
        print("расчёт создан:", gurl)
        page = s.get(gurl).text
        from server.loadsinput import DEFAULTS
        fill = a.fill or round(H * 0.6, 1)
        form = {**DEFAULTS, "l_fill": str(fill), "l_hydro": str(fill), "l_roof_rise": str(DEFAULTS["l_roof_rise"]), "csrf": csrf(page)}
        roof = project.get("roof") or {}
        try:
            R = float(str(project["diameter"]).replace(",", ".")) / 2
            Rs = float(str(roof.get("sphere_radius_m")).replace(",", "."))
            form["l_roof_rise"] = str(round(Rs - (Rs * Rs - R * R) ** 0.5, 3))
        except (TypeError, ValueError):
            pass
        r = s.post(f"{gurl}/loads", data=form, allow_redirects=False)
        assert "loads_error" not in r.headers.get("location", ""), "нагрузки: " + r.headers.get("location", "")
        r = s.post(f"{gurl}/pay", data={"csrf": csrf(s.get(gurl).text)}, allow_redirects=True)
        print("ждём модель и пакет для Ansys…")
        t0 = time.time()
        while time.time() - t0 < 900:
            st = s.get(f"{gurl}/status").json()
            if st["status"] in ("done", "error"):
                break
            time.sleep(3)
        assert st["status"] == "done", "расчёт на сайте: " + str(st)
        link = html.unescape(re.search(r'(ansysreport://run\?[^"\'<> ]+)', s.get(gurl).text).group(1))
        print("модель готова (%.0f с). Ссылка помощника:" % (time.time() - t0), link)
        if a.no_agent:
            return 0
        out = Path(a.out)
        out.mkdir(parents=True, exist_ok=True)
        print("запускаю помощника (Ansys); журнал помощника: C:\\ansys_report_work\\agent.log")
        subprocess.run([sys.executable, "-m", "ansys_report", "agent", link], cwd=ROOT, check=False)
        ag = s.get(f"{gurl}/agent.json").json()
        print("состояние помощника:", ag.get("stage"), ag.get("message"))
        for name in ag.get("files") or []:
            rr = s.get(f"{gurl}/agent-files/{requests.utils.quote(name)}")
            (out / name).write_bytes(rr.content)
            print("скачан:", out / name, len(rr.content) // 1024, "КБ")
        return 0 if ag.get("files") else 1
    finally:
        if not a.keep_server:
            srv.terminate()
        log.close()


if __name__ == "__main__":
    raise SystemExit(main())
