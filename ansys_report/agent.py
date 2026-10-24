"""Помощник на компьютере заказчика: ссылка ansysreport://run?... с сайта -> скачать пакет -> Ansys строит модель и считает ->
отчёт собирается -> файлы отправляются обратно на сайт. Установка ссылки (один раз): python -m ansys_report agent --install"""
from __future__ import annotations
import json
import os
import subprocess
import sys
import urllib.parse
import urllib.request
import uuid
import zipfile
from pathlib import Path

WORK = Path(os.environ.get("ANSYS_REPORT_AGENT_DIR") or r"C:\ansys_report_work")
SKIP_DIAG = {"AR_NODIAG": "1", "AR_NOPAUSE": "1"}


def say(msg: str) -> None:
    """Печатает в окно и дописывает в журнал помощника (C:\\ansys_report_work\\agent.log)."""
    print(msg, flush=True)
    try:
        WORK.mkdir(parents=True, exist_ok=True)
        with open(WORK / "agent.log", "a", encoding="utf-8") as f:
            f.write(msg + "\n")
    except OSError:
        pass


def parse_link(link: str) -> dict:
    q = urllib.parse.urlparse(link)
    p = {k: v[0] for k, v in urllib.parse.parse_qs(q.query).items()}
    if q.scheme != "ansysreport" or not {"server", "g", "t"} <= set(p):
        raise ValueError("Неверная ссылка помощника")
    if not p["server"].startswith(("http://", "https://")):
        raise ValueError("Неверный адрес сервера")
    return {"server": p["server"].rstrip("/"), "gid": int(p["g"]), "token": p["t"]}


class Site:
    def __init__(self, server: str, gid: int, token: str):
        self.base, self.gid, self.t = server, gid, token

    def url(self, path: str) -> str:
        return f"{self.base}/agent/{self.gid}/{path}?t={urllib.parse.quote(self.t)}"

    def status(self, stage: str, message: str = "") -> None:
        req = urllib.request.Request(self.url("status"), data=json.dumps({"stage": stage, "message": message}).encode("utf-8"),
                                     headers={"Content-Type": "application/json"}, method="POST")
        try:
            urllib.request.urlopen(req, timeout=30).read()
        except Exception as e:      # noqa: BLE001  - сбой связи не должен останавливать расчёт
            print("(статус не отправлен:", e, ")")

    def download(self, dest: Path) -> None:
        with urllib.request.urlopen(self.url("package.zip"), timeout=300) as r, open(dest, "wb") as f:
            while chunk := r.read(1 << 20):
                f.write(chunk)

    def upload(self, path: Path) -> None:
        boundary = uuid.uuid4().hex
        body = (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{path.name}"\r\n'
                "Content-Type: application/octet-stream\r\n\r\n").encode("utf-8") + path.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
        req = urllib.request.Request(self.url("upload"), data=body, method="POST",
                                     headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
        urllib.request.urlopen(req, timeout=600).read()


def _run_bat(bat: Path, env_extra: dict) -> int:
    env = dict(os.environ, **env_extra)
    return subprocess.call(["cmd", "/c", str(bat)], cwd=str(bat.parent), env=env)


def run(link: str) -> int:
    say(f"Запуск помощника: {link[:80]}…")
    info = parse_link(link)
    site = Site(info["server"], info["gid"], info["token"])
    home = str(Path(__file__).resolve().parent.parent)                      # папка, где лежит пакет ansys_report
    env = dict(SKIP_DIAG, ANSYS_REPORT_HOME=home, PYTHONPATH=home + os.pathsep + os.environ.get("PYTHONPATH", ""))
    try:
        pkg = WORK / f"pkg_{info['gid']}"
        pkg.mkdir(parents=True, exist_ok=True)
        say("Скачиваю модель…")
        site.status("download")
        zpath = WORK / f"pkg_{info['gid']}.zip"
        site.download(zpath)
        with zipfile.ZipFile(zpath) as z:
            z.extractall(pkg)
        say("Строю модель в Ansys (несколько минут)…")
        site.status("build")
        rc = _run_bat(pkg / "Open_in_Ansys.bat", env)
        if rc != 0:
            raise RuntimeError(f"Open_in_Ansys.bat завершился с кодом {rc}")
        say("Считаю и собираю отчёт (до 40 минут)…")
        site.status("solve")
        rc = _run_bat(pkg / "Make_report.bat", env)
        out = WORK / "model" / "report"
        files = [f for pattern in ("*.docx", "*.xlsx") for f in out.rglob(pattern)]
        if not files:
            raise RuntimeError("отчёт не сформирован (смотрите журналы в C:\\ansys_report_work\\model\\out)")
        site.status("upload")
        for f in files:
            site.upload(f)
        site.status("done", "Отчёт сформирован")
        say("Готово: отчёт отправлен на сайт.")
        return 0
    except Exception as e:      # noqa: BLE001
        site.status("error", str(e)[:400])
        say(f"Ошибка: {e}")
        return 1


def install() -> int:
    """Регистрирует ссылки ansysreport:// для текущего пользователя Windows (без прав администратора).
    Помощник запускается из папки программы (иначе python не найдёт модуль) и при ошибке оставляет окно открытым."""
    import winreg
    home = str(Path(__file__).resolve().parent.parent)
    cmd = f'cmd /c "cd /d "{home}" && "{sys.executable}" -m ansys_report agent "%1" || pause"'
    key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Classes\ansysreport")
    winreg.SetValueEx(key, "", 0, winreg.REG_SZ, "URL:ANSYS REPORT")
    winreg.SetValueEx(key, "URL Protocol", 0, winreg.REG_SZ, "")
    winreg.SetValue(winreg.HKEY_CURRENT_USER, r"Software\Classes\ansysreport\shell\open\command", winreg.REG_SZ, cmd)
    print("Готово: ссылки «Собрать отчёт в Ansys» на сайте теперь открывают помощника.")
    print("Команда запуска:", cmd)
    return 0
