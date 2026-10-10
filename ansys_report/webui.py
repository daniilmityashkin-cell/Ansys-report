"""Главное окно программы: локальная веб-страница в окне браузера (Edge/Chrome в режиме приложения).
Сервер работает только на этом компьютере (127.0.0.1) и сам завершается, когда окно закрыто."""
from __future__ import annotations
import json
import os
import subprocess
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .settings import ModelSettings

WEB = Path(__file__).resolve().parent / "web"


def _asset(name: str) -> bytes:
    return (WEB / name).read_bytes()


def app_log_path() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "AnsysReport"
    base.mkdir(parents=True, exist_ok=True)
    return base / "app.log"


def app_log(text: str):
    """Журнал программы в файл (в окне без консоли иначе ошибки не видно): %LOCALAPPDATA%\\AnsysReport\\app.log"""
    try:
        with open(app_log_path(), "a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + text + "\n")
    except Exception:
        pass


class Job:
    """Состояние текущей сборки отчёта (одна за раз)."""
    def __init__(self):
        self.lock = threading.Lock()
        self.reset()

    def reset(self):
        self.running = False
        self.lines: list[str] = []
        self.done = False
        self.error = ""
        self.files: list[str] = []

    def log(self, msg: str):
        with self.lock:
            self.lines.append(str(msg))
        app_log(str(msg))

    def snapshot(self, since: int) -> dict:
        with self.lock:
            return {"running": self.running, "done": self.done, "error": self.error,
                    "files": list(self.files), "lines": self.lines[since:], "total": len(self.lines)}


def _pick(kind: str) -> str:
    """Окно выбора файла/папки средствами Windows (PowerShell), без tkinter."""
    if sys.platform != "win32":
        return ""
    if kind == "folder":
        body = "$d = New-Object System.Windows.Forms.FolderBrowserDialog; if ($d.ShowDialog() -eq 'OK') { $d.SelectedPath }"
    else:
        body = ("$d = New-Object System.Windows.Forms.OpenFileDialog; "
                "$d.Filter = 'Проект Ansys (*.wbpj;*.wbpz;*.mechdb)|*.wbpj;*.wbpz;*.mechdb|Все файлы (*.*)|*.*'; "
                "if ($d.ShowDialog() -eq 'OK') { $d.FileName }")
    ps = ("[Console]::OutputEncoding = [Text.Encoding]::UTF8; Add-Type -AssemblyName System.Windows.Forms; "
          "$f = New-Object System.Windows.Forms.Form; $f.TopMost = $true; " + body)
    r = subprocess.run(["powershell", "-NoProfile", "-STA", "-Command", ps], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    return r.stdout.strip()


def _open(path: str) -> str:
    """Открывает файл/папку программой по умолчанию. Возвращает пустую строку или текст ошибки."""
    if sys.platform != "win32":
        return ""
    path = os.path.normpath(path)
    errors = []
    attempts = [lambda: os.startfile(path)]
    if os.path.isdir(path):
        attempts.append(lambda: subprocess.Popen(["explorer", path]))
    else:
        attempts.append(lambda: subprocess.Popen(["cmd", "/c", "start", "", path],
                                                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)))
    for i, fn in enumerate(attempts, 1):
        try:
            fn()
            app_log(f"Открыто ({i}): {path}")
            return ""
        except Exception as e:  # noqa: BLE001
            errors.append(f"{type(e).__name__}: {e}")
            app_log(f"Не открылось способом {i}: {path} -> {errors[-1]}")
    return "; ".join(errors)


def make_handler(job: Job, state: dict):
    from .wizard import FIELDS, SETTINGS, _load, build_from_ansys
    from .ansys_connect import find_ansys

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):          # без шума в консоли
            pass

        def _send(self, code: int, body: bytes, ctype="application/json; charset=utf-8"):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, obj, code=200):
            self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"))

        def do_GET(self):
            path = self.path.split("?")[0]
            if path in ("/", "/index.html"):
                return self._send(200, _asset("index.html"), "text/html; charset=utf-8")
            if path == "/icon.png":
                return self._send(200, _asset("icon.png"), "image/png")
            if path == "/api/state":
                st = _load()
                installs = find_ansys()
                ver = next(iter(installs), None)
                return self._json({
                    "project": st.get("project", ""), "out": st.get("out", str(Path.home() / "Documents" / "AnsysReport")),
                    "anketa": {k: st.get("anketa", {}).get(k, d) for k, _, d in FIELDS},
                    "fields": [{"key": k, "label": l} for k, l, _ in FIELDS],
                    "solve": st.get("solve", True), "model": ModelSettings.from_dict(st.get("model")).to_dict(),
                    "ansys": {"found": bool(installs), "version": ver}})
            if path == "/api/status":
                since = int(self.path.split("since=")[-1]) if "since=" in self.path else 0
                state["last_ping"] = time.time()
                return self._json(job.snapshot(since))
            self._send(404, b"{}")

        def do_POST(self):
            n = int(self.headers.get("Content-Length") or 0)
            data = json.loads(self.rfile.read(n) or b"{}")
            path = self.path
            state["last_ping"] = time.time()
            if path == "/api/ping":
                return self._json({"ok": True})
            if path == "/api/pick":
                return self._json({"path": _pick(data.get("kind", "file"))})
            if path == "/api/open":
                target = data.get("path", "")
                app_log(f"Просьба открыть: {target}")
                if not target or not Path(target).exists():
                    return self._json({"ok": False, "error": f"Не найден: {target}"})
                err = _open(target)
                return self._json({"ok": not err, "error": err})
            if path == "/api/build":
                if job.running:
                    return self._json({"ok": False, "error": "Сборка уже идёт"})
                try:
                    SETTINGS.write_text(json.dumps({k: data[k] for k in ("project", "out", "anketa", "solve", "model")},
                                                   ensure_ascii=False), encoding="utf-8")
                except Exception:
                    pass
                job.reset()
                job.running = True
                threading.Thread(target=_run, args=(job, data, build_from_ansys), daemon=True).start()
                return self._json({"ok": True})
            self._send(404, b"{}")

    return H


def _run(job: Job, d: dict, build):
    app_log(f"Старт сборки: проект={d.get('project')} папка={d.get('out')} reuse={d.get('reuse')} solve={d.get('solve')}")
    try:
        anketa = d["anketa"]
        from .wizard import FIELDS
        names = {k: label for k, label, _ in FIELDS}
        empty = [names[k] for k in ("number", "executor_name", "site") if not str(anketa.get(k, "")).strip()]
        if empty:
            job.log("Внимание: не заполнены поля отчёта (" + ", ".join(empty) + ") — в отчёте останется пустое место.")
        files = build(str(d["project"]).strip().strip('"'), str(d["out"]).strip().strip('"'), anketa, job.log,
                      bool(d.get("reuse")), bool(d.get("solve", True)), ModelSettings.from_dict(d.get("model")))
        job.files = [str(f) for f in files]
        job.log("ГОТОВО.")
    except PermissionError:
        job.error = "Файл открыт в Word или Excel. Закройте его и повторите."
    except BaseException as e:  # noqa: BLE001
        import traceback
        app_log("ОШИБКА:\n" + traceback.format_exc())
        job.error = f"{type(e).__name__}: {e}  (подробности: {app_log_path()})"
    finally:
        job.done = True
        job.running = False


def _browser_cmd(url: str) -> list[str] | None:
    """Окно без адресной строки: Edge/Chrome в режиме приложения."""
    for base in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles"), os.environ.get("LocalAppData")):
        if not base:
            continue
        for rel in (r"Microsoft\Edge\Application\msedge.exe", r"Google\Chrome\Application\chrome.exe"):
            exe = Path(base) / rel
            if exe.exists():
                return [str(exe), f"--app={url}", "--window-size=1320,900", "--window-position=80,40"]
    return None


def main(open_window: bool = True, port: int = 0) -> int:
    app_log("=== запуск программы ===")
    job, state = Job(), {"last_ping": time.time()}
    srv = ThreadingHTTPServer(("127.0.0.1", port), make_handler(job, state))
    url = f"http://127.0.0.1:{srv.server_address[1]}/"
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    if open_window:
        cmd = _browser_cmd(url)
        if cmd:
            subprocess.Popen(cmd)
        else:
            webbrowser.open(url)
        # окно закрыто = страница перестала присылать ping
        started = time.time()
        try:
            while True:
                time.sleep(1)
                if time.time() - started > 20 and time.time() - state["last_ping"] > 15 and not job.running:
                    break
        except KeyboardInterrupt:
            pass
        srv.shutdown()
        return 0
    print(url)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        return 0
