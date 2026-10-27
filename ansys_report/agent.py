"""Помощник на компьютере заказчика: ссылка ansysreport://run?... с сайта -> скачать пакет -> Ansys строит модель и считает ->
отчёт собирается -> файлы отправляются обратно на сайт. Установка ссылки (один раз): python -m ansys_report agent --install"""
from __future__ import annotations
import json
import os
import shutil
import subprocess
import sys
import urllib.parse
import urllib.request
import uuid
import zipfile
from pathlib import Path

WORK = Path(os.environ.get("ANSYS_REPORT_AGENT_DIR") or r"C:\ansys_report_work")
SKIP_DIAG = {"AR_NODIAG": "1", "AR_NOPAUSE": "1"}


NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)       # дочерние процессы без окна консоли (заказчик не должен видеть чёрные окна)


def say(msg: str) -> None:
    """Печатает в окно (если оно есть) и дописывает в журнал помощника (C:\\ansys_report_work\\agent.log)."""
    try:
        if sys.stdout:                                  # под pythonw консоли нет
            print(msg, flush=True)
    except (OSError, ValueError):
        pass
    try:
        WORK.mkdir(parents=True, exist_ok=True)
        with open(WORK / "agent.log", "a", encoding="utf-8") as f:
            f.write(msg + "\n")
    except OSError:
        pass


def parse_link(link: str) -> dict:
    import html
    link = html.unescape(link.strip().strip('"'))          # на случай «&amp;» вместо «&»
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
            say(f"(статус не отправлен: {e})")

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


def _ideal_cache(ideal_pkg: Path) -> Path:
    """Файл кэша результата идеального РВС: хэш всех файлов пакета ideal и скриптов Mechanical (меняются вход или код - считаем заново)."""
    import hashlib
    h = hashlib.sha256()
    scripts = Path(__file__).resolve().parent.parent / "ansys_scripts"
    for f in sorted([p for p in ideal_pkg.rglob("*") if p.is_file()]) + sorted(scripts.glob("*.py")):
        h.update(f.name.encode("utf-8"))
        data = f.read_bytes()
        if f.suffix.lower() in (".step", ".stp"):              # в заголовке STEP - время создания файла: хэшируем только геометрию
            i = data.find(b"DATA;")
            data = data[i:] if i >= 0 else data
        h.update(data)
    return WORK / "ideal_cache" / (h.hexdigest()[:32] + ".json")


def _run_bat(bat: Path, env_extra: dict) -> int:
    env = dict(os.environ, **env_extra)
    return subprocess.call(["cmd", "/c", str(bat)], cwd=str(bat.parent), env=env, creationflags=NO_WINDOW, stdin=subprocess.DEVNULL)


def run(link: str) -> int:
    say(f"Запуск помощника: {link[:80]}…")
    info = parse_link(link)
    site = Site(info["server"], info["gid"], info["token"])
    lock = _take_lock()
    if lock is None:                     # второй расчёт в ту же рабочую папку испортил бы первый (общие model, ideal, timing.log)
        busy = "На этом компьютере уже идёт расчёт в Ansys - дождитесь его окончания и нажмите «Собрать отчёт» ещё раз."
        site.status("error", busy)
        say(busy)
        return 1
    try:
        return _run(info, site)
    finally:
        try:
            lock.unlink()
        except OSError:
            pass


def _pid_alive(pid: int) -> bool:
    """Жив ли процесс (Windows: OpenProcess + GetExitCodeProcess; os.kill(pid, 0) на Windows завершает процесс - нельзя)."""
    if os.name != "nt":
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False
    import ctypes
    k = ctypes.windll.kernel32
    h = k.OpenProcess(0x1000, False, pid)                  # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return False
    code = ctypes.c_ulong()
    ok = k.GetExitCodeProcess(h, ctypes.byref(code))
    k.CloseHandle(h)
    return bool(ok) and code.value == 259                  # STILL_ACTIVE


def _take_lock() -> Path | None:
    """Файл-блокировка рабочей папки с PID помощника; занят живым процессом - None. Брошенный (процесс умер) - забираем."""
    WORK.mkdir(parents=True, exist_ok=True)
    lock = WORK / "agent.lock"
    for _ in range(2):
        try:
            fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            return lock
        except FileExistsError:
            try:
                pid = int(lock.read_text().strip() or 0)
            except (OSError, ValueError):
                pid = 0
            if pid and _pid_alive(pid):
                return None
            try:
                lock.unlink()
            except OSError:
                return None
    return None


def _run(info: dict, site: "Site") -> int:
    home = str(Path(__file__).resolve().parent.parent)                      # папка, где лежит пакет ansys_report
    from . import timing
    tpath = WORK / "timing.log"                                            # замер времени по этапам (tools/timing_report.py)
    try:
        tpath.unlink()
    except OSError:
        pass
    env = dict(SKIP_DIAG, ANSYS_REPORT_HOME=home, PYTHONPATH=home + os.pathsep + os.environ.get("PYTHONPATH", ""), AR_TIMING=str(tpath),
               PATH=str(Path(sys.executable).parent) + os.pathsep + os.environ.get("PATH", ""))      # bat-файлы вызывают просто python: должен быть тот же (с установленными пакетами), что запустил помощника
    os.environ["AR_TIMING"] = str(tpath)
    try:
        pkg = WORK / f"pkg_{info['gid']}"
        shutil.rmtree(pkg, ignore_errors=True)                # без файлов прошлого пакета (dents.json, beams.json другого резервуара)
        pkg.mkdir(parents=True, exist_ok=True)
        timing.mark("Агент: скачивание пакета")
        say("Скачиваю модель…")
        site.status("download")
        zpath = WORK / f"pkg_{info['gid']}.zip"
        site.download(zpath)
        with zipfile.ZipFile(zpath) as z:
            z.extractall(pkg)
        ideal = pkg / "ideal"
        cached = _ideal_cache(ideal) if (ideal / "Open_in_Ansys.bat").exists() else None
        if cached is not None and cached.exists():          # тот же идеальный РВС уже считали (те же входные данные и скрипты)
            say("Идеальный РВС: беру готовый результат (входные данные не менялись)…")
            timing.mark("Агент: идеальный РВС из кэша")
            shutil.rmtree(WORK / "ideal", ignore_errors=True)
            (WORK / "ideal").mkdir(parents=True, exist_ok=True)
            shutil.copy2(cached, WORK / "ideal" / "ideal.json")
        elif cached is not None:                             # сначала идеальный РВС (без отклонений): результаты нужны для выводов отчёта
            say("Строю и считаю идеальный РВС (без отклонений)…")
            site.status("build", "Идеальный РВС: модель")
            env_i = dict(env, AR_WORK=str(WORK / "ideal"), AR_TIMING_TAG="идеальный")
            timing.mark("Агент: запуск Open_in_Ansys (идеальный)")
            if _run_bat(ideal / "Open_in_Ansys.bat", env_i) == 0:
                site.status("solve", "Идеальный РВС: расчёт")
                timing.mark("Агент: запуск Make_ideal")
                _run_bat(ideal / "Make_ideal.bat", env_i)
                res = WORK / "ideal" / "ideal.json"
                if res.exists():
                    cached.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(res, cached)
        say("Строю модель в Ansys (несколько минут)…")
        site.status("build", "Фактическая форма")
        env = dict(env, AR_TIMING_TAG="модель")
        timing.mark("Агент: запуск Open_in_Ansys (модель)")
        rc = _run_bat(pkg / "Open_in_Ansys.bat", env)
        if rc != 0:
            raise RuntimeError(f"Open_in_Ansys.bat завершился с кодом {rc}")
        say("Считаю и собираю отчёт (до 40 минут)…")
        site.status("solve")
        timing.mark("Агент: запуск Make_report")
        rc = _run_bat(pkg / "Make_report.bat", env)
        timing.mark("Агент: загрузка отчёта на сайт")
        out = WORK / "model" / "report"
        files = [f for pattern in ("*.docx", "*.xlsx") for f in out.rglob(pattern)]
        if not files:
            raise RuntimeError("отчёт не сформирован (смотрите журналы в C:\\ansys_report_work\\model\\out)")
        site.status("upload")
        for f in files:
            site.upload(f)
        site.status("done", "Отчёт сформирован")
        say("Готово: отчёт отправлен на сайт.")
        timing.mark("Агент: diag-logs")
        diag = Path(home) / "diag.bat"
        if diag.exists() and (Path(home) / ".git").exists():       # рабочая копия разработчика: логи и отчёт уходят в ветку diag-logs
            _run_bat(diag, {"AR_NOPAUSE": "1"})
        timing.mark("конец")
        return 0
    except Exception as e:      # noqa: BLE001
        site.status("error", str(e)[:400])
        say(f"Ошибка: {e}")
        return 1


def _pythonw() -> str:
    """pythonw.exe рядом с текущим python.exe (запуск без окна консоли); если нет - обычный python."""
    exe = Path(sys.executable)
    w = exe.with_name("pythonw.exe")
    return str(w if w.exists() else exe)


def popup(title: str, text: str) -> None:
    """Окно сообщения Windows (когда консоли нет и показать ошибку иначе нечем)."""
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, text, title, 0x10)
    except Exception:      # noqa: BLE001
        pass


def launch(link: str) -> int:
    """Точка входа для ссылки ansysreport:// из браузера: работает без окна консоли; при ошибке - окно сообщения и журнал."""
    try:
        return run(link)
    except Exception as e:      # noqa: BLE001
        say(f"Ошибка запуска: {e}")
        popup("ANSYS REPORT", f"Помощник не смог выполнить расчёт:\n{e}\n\nПодробности: {WORK / 'agent.log'}")
        return 1


def install() -> int:
    """Регистрирует ссылки ansysreport:// для текущего пользователя Windows (без прав администратора).
    Помощник запускается через pythonw (без окна консоли) из папки программы; ошибки показываются окном сообщения и пишутся в agent.log."""
    import winreg
    home = str(Path(__file__).resolve().parent.parent)
    boot = ("import os, sys; os.chdir(r'%s'); sys.path.insert(0, r'%s'); "
            "from ansys_report import agent; sys.exit(agent.launch(sys.argv[1]))") % (home, home)
    cmd = f'"{_pythonw()}" -c "{boot}" "%1"'
    key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Classes\ansysreport")
    winreg.SetValueEx(key, "", 0, winreg.REG_SZ, "URL:ANSYS REPORT")
    winreg.SetValueEx(key, "URL Protocol", 0, winreg.REG_SZ, "")
    winreg.SetValue(winreg.HKEY_CURRENT_USER, r"Software\Classes\ansysreport\shell\open\command", winreg.REG_SZ, cmd)
    print("Готово: ссылки «Собрать отчёт в Ansys» на сайте теперь открывают помощника без окон.")
    print("Команда запуска:", cmd)
    return 0
