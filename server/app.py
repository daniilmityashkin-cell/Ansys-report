"""Сайт: регистрация и вход, кабинет, замеры → проверка → оплата → геометрия, подписка на технический отчёт."""
from __future__ import annotations
import io
import json
import zipfile
from pathlib import Path

from fastapi import FastAPI, Form, Request, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse, Response, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from sqlalchemy import select

from .config import Settings
from .db import make_session_factory
from .models import User, Generation, Payment, now
from .auth import (hash_password, verify_password, normalize_email, valid_email, csrf_token, csrf_ok, LoginLimiter)
from .payments import get_provider, settle
from .jobs import JobRunner

HERE = Path(__file__).parent
PUBLIC_FILE_EXT = {".docx", ".step", ".igs", ".csv", ".json", ".html", ".png"}


def create_app(settings: Settings | None = None) -> FastAPI:
    st = settings or Settings()
    engine, Session = make_session_factory(st.db_url)
    app = FastAPI(title="Геометрия РВС", docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(SessionMiddleware, secret_key=st.secret_key, https_only=st.https_only, same_site="lax", max_age=14 * 86400)
    app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
    templates = Jinja2Templates(directory=str(HERE / "templates"))
    limiter = LoginLimiter()

    def gen_dir(gid: int) -> Path:
        return st.data_dir / "generations" / str(gid)

    def on_done(gid: int, result, error: str):
        with Session() as db:
            g = db.get(Generation, gid)
            if not g:
                return
            g.status, g.error = ("done", "") if not error else ("error", error)
            db.commit()
    runner = JobRunner(st.workers, st.inline_jobs, on_done)
    app.state.settings, app.state.Session, app.state.runner = st, Session, runner

    def start_job(db, g: Generation):
        g.status = "running"
        db.commit()
        runner.submit(g.id, gen_dir(g.id), g.title)

    # --- вспомогательное ---
    def current_user(request: Request, db) -> User | None:
        uid = request.session.get("uid")
        return db.get(User, uid) if uid else None

    def render(request: Request, name: str, user=None, status_code: int = 200, **ctx):
        return templates.TemplateResponse(request, name, {"user": user, "csrf": csrf_token(request.session), "st": st, **ctx},
                                          status_code=status_code)

    def deny_csrf(request: Request, token: str | None):
        return None if csrf_ok(request.session, token) else HTMLResponse("Сессия устарела. Обновите страницу.", status_code=400)

    # --- общие страницы ---
    @app.get("/health")
    def health():
        """Для мониторинга доступности (UptimeRobot и т. п.): отвечает 200 только если база читается."""
        try:
            with Session() as db:
                db.execute(select(User.id).limit(1))
            return {"ok": True}
        except Exception:   # noqa: BLE001
            return JSONResponse({"ok": False}, status_code=503)

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request):
        with Session() as db:
            return render(request, "index.html", current_user(request, db))

    @app.get("/privacy", response_class=HTMLResponse)
    def privacy(request: Request):
        with Session() as db:
            return render(request, "privacy.html", current_user(request, db))

    # --- регистрация / вход ---
    @app.get("/register", response_class=HTMLResponse)
    def register_form(request: Request):
        return render(request, "register.html")

    @app.post("/register")
    def register(request: Request, email: str = Form(""), password: str = Form(""), consent: str = Form(""), csrf: str = Form("")):
        bad = deny_csrf(request, csrf)
        if bad:
            return bad
        email = normalize_email(email)
        err = ""
        if not valid_email(email):
            err = "Введите корректный адрес почты."
        elif len(password) < 10:
            err = "Пароль должен быть не короче 10 символов."
        elif not consent:
            err = "Нужно согласие на обработку персональных данных."
        with Session() as db:
            if not err and db.scalar(select(User).where(User.email == email)):
                err = "Этот адрес уже зарегистрирован."
            if err:
                return render(request, "register.html", error=err, email=email, status_code=400)
            u = User(email=email, password_hash=hash_password(password), consent_at=now())
            db.add(u)
            db.commit()
            request.session.clear()
            request.session["uid"] = u.id
        return RedirectResponse("/cabinet", status_code=303)

    @app.get("/login", response_class=HTMLResponse)
    def login_form(request: Request):
        return render(request, "login.html")

    @app.post("/login")
    def login(request: Request, email: str = Form(""), password: str = Form(""), csrf: str = Form("")):
        bad = deny_csrf(request, csrf)
        if bad:
            return bad
        email = normalize_email(email)
        key = f"{request.client.host if request.client else '-'}|{email}"
        if limiter.blocked(key):
            return render(request, "login.html", error="Слишком много попыток. Подождите 5 минут.", status_code=429)
        with Session() as db:
            u = db.scalar(select(User).where(User.email == email))
            if not u or not verify_password(password, u.password_hash):
                limiter.fail(key)
                return render(request, "login.html", error="Неверная почта или пароль.", email=email, status_code=400)
            limiter.ok(key)
            request.session.clear()
            request.session["uid"] = u.id
        return RedirectResponse("/cabinet", status_code=303)

    @app.post("/logout")
    def logout(request: Request, csrf: str = Form("")):
        bad = deny_csrf(request, csrf)
        if bad:
            return bad
        request.session.clear()
        return RedirectResponse("/", status_code=303)

    # --- кабинет ---
    @app.get("/cabinet", response_class=HTMLResponse)
    def cabinet(request: Request):
        with Session() as db:
            u = current_user(request, db)
            if not u:
                return RedirectResponse("/login", status_code=303)
            gens = db.scalars(select(Generation).where(Generation.user_id == u.id).order_by(Generation.id.desc())).all()
            return render(request, "cabinet.html", u, gens=gens)

    @app.get("/new", response_class=HTMLResponse)
    def new_form(request: Request):
        with Session() as db:
            u = current_user(request, db)
            if not u:
                return RedirectResponse("/login", status_code=303)
            return render(request, "new.html", u)

    @app.post("/new")
    async def new_submit(request: Request, title: str = Form(""), text: str = Form(""), csrf: str = Form(""),
                         file: UploadFile | None = File(None)):
        bad = deny_csrf(request, csrf)
        if bad:
            return bad
        with Session() as db:
            u = current_user(request, db)
            if not u:
                return RedirectResponse("/login", status_code=303)
            raw = b""
            if file is not None and file.filename:
                raw = await file.read(st.max_upload_bytes + 1)
            elif text.strip():
                raw = text.encode("utf-8")
            err, project, summary = "", None, None
            if not raw:
                err = "Загрузите файл замеров (.json) или вставьте его содержимое."
            elif len(raw) > st.max_upload_bytes:
                err = "Файл слишком большой."
            else:
                try:
                    project = json.loads(raw.decode("utf-8-sig"))
                    summary = _preview(project)
                except Exception as e:  # noqa: BLE001
                    err = f"Не удалось прочитать замеры: {e}"
            if err:
                return render(request, "new.html", u, error=err, title=title, text=text, status_code=400)
            return RedirectResponse(f"/g/{_create_generation(db, u, title, project, summary).id}", status_code=303)

    def _create_generation(db, u: User, title: str, project: dict, summary: dict) -> Generation:
        g = Generation(user_id=u.id, title=(title.strip() or "Резервуар")[:200], summary=json.dumps(summary, ensure_ascii=False))
        db.add(g)
        db.commit()
        d = gen_dir(g.id)
        d.mkdir(parents=True, exist_ok=True)
        (d / "input.json").write_text(json.dumps(project, ensure_ascii=False), encoding="utf-8")
        return g

    @app.get("/new/table", response_class=HTMLResponse)
    def new_table_form(request: Request):
        with Session() as db:
            u = current_user(request, db)
            if not u:
                return RedirectResponse("/login", status_code=303)
            return render(request, "new_table.html", u, f={"rows_are": "gens"})

    @app.post("/new/table")
    def new_table_submit(request: Request, title: str = Form(""), diameter: str = Form(""), height: str = Form(""),
                         table: str = Form(""), thicknesses: str = Form(""), rows_are: str = Form("gens"), csrf: str = Form("")):
        bad = deny_csrf(request, csrf)
        if bad:
            return bad
        from .tableinput import build_project
        form = {"title": title, "diameter": diameter, "height": height, "table": table, "thicknesses": thicknesses, "rows_are": rows_are}
        with Session() as db:
            u = current_user(request, db)
            if not u:
                return RedirectResponse("/login", status_code=303)
            try:
                project = build_project(diameter, height, table, thicknesses, rows_are if rows_are in ("gens", "belts") else "gens")
                summary = _preview(project)
            except Exception as e:  # noqa: BLE001
                return render(request, "new_table.html", u, error=str(e), f=form, status_code=400)
            return RedirectResponse(f"/g/{_create_generation(db, u, title, project, summary).id}", status_code=303)

    def _owned(db, request: Request, gid: int):
        u = current_user(request, db)
        if not u:
            return None, None
        g = db.get(Generation, gid)
        return u, (g if g and g.user_id == u.id else None)

    def _files(gid: int) -> list[str]:
        root = gen_dir(gid) / "result"
        if not root.exists():
            return []
        out = []
        for p in sorted(root.rglob("*")):
            if p.is_file() and p.suffix.lower() in PUBLIC_FILE_EXT and "images" not in p.relative_to(root).parts[:-1]:
                out.append(p.relative_to(root).as_posix())
        return out

    @app.get("/g/{gid}", response_class=HTMLResponse)
    def generation(request: Request, gid: int):
        with Session() as db:
            u, g = _owned(db, request, gid)
            if not u:
                return RedirectResponse("/login", status_code=303)
            if not g:
                return HTMLResponse("Не найдено", status_code=404)
            if g.status == "draft" and app.state.reconcile(u.id):      # вернулся с оплаты, а уведомление ещё не пришло
                db.refresh(g)
            return render(request, "generation.html", u, g=g, summary=json.loads(g.summary or "{}"),
                          files=_files(g.id) if g.status == "done" else [])

    @app.post("/g/{gid}/pay")
    def pay_generation(request: Request, gid: int, csrf: str = Form("")):
        bad = deny_csrf(request, csrf)
        if bad:
            return bad
        with Session() as db:
            u, g = _owned(db, request, gid)
            if not u:
                return RedirectResponse("/login", status_code=303)
            if not g or g.status != "draft":
                return RedirectResponse(f"/g/{gid}", status_code=303)
            p = Payment(user_id=u.id, kind="generation", generation_id=g.id, amount_rub=st.price_generation_rub, provider=st.payment_provider)
            db.add(p)
            db.flush()
            url = get_provider(st.payment_provider).create(p, f"{st.base_url}/g/{g.id}", f"Генерация геометрии №{g.id}")
            db.commit()
            return RedirectResponse(url, status_code=303)

    @app.get("/g/{gid}/files/{name:path}")
    def download(request: Request, gid: int, name: str):
        with Session() as db:
            u, g = _owned(db, request, gid)
            if not u or not g or g.status != "done":
                return HTMLResponse("Недоступно", status_code=404)
            if name not in _files(g.id):                       # только файлы из списка результата (без выхода из папки)
                return HTMLResponse("Не найдено", status_code=404)
            return FileResponse(gen_dir(g.id) / "result" / name, filename=Path(name).name)

    @app.get("/g/{gid}/all.zip")
    def download_zip(request: Request, gid: int):
        with Session() as db:
            u, g = _owned(db, request, gid)
            if not u or not g or g.status != "done":
                return HTMLResponse("Недоступно", status_code=404)
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
                for n in _files(g.id):
                    z.write(gen_dir(g.id) / "result" / n, n)
            return Response(buf.getvalue(), media_type="application/zip",
                            headers={"Content-Disposition": f'attachment; filename="geometry_{g.id}.zip"'})

    # --- оплата ---
    @app.get("/pay/fake/{pid}", response_class=HTMLResponse)
    def fake_pay_page(request: Request, pid: int):
        if st.payment_provider != "fake":
            return HTMLResponse("Не найдено", status_code=404)
        with Session() as db:
            u = current_user(request, db)
            p = db.get(Payment, pid)
            if not u or not p or p.user_id != u.id:
                return HTMLResponse("Не найдено", status_code=404)
            return render(request, "fakepay.html", u, p=p)

    @app.post("/pay/fake/{pid}")
    def fake_pay_confirm(request: Request, pid: int, csrf: str = Form("")):
        bad = deny_csrf(request, csrf)
        if bad or st.payment_provider != "fake":
            return bad or HTMLResponse("Не найдено", status_code=404)
        with Session() as db:
            u = current_user(request, db)
            p = db.get(Payment, pid)
            if not u or not p or p.user_id != u.id:
                return HTMLResponse("Не найдено", status_code=404)
            back = _apply_payment(db, p)
            return RedirectResponse(back, status_code=303)

    def _apply_payment(db, p: Payment) -> str:
        applied = settle(db, p, st.subscription_days)
        db.commit()
        if p.kind == "generation" and p.generation_id:
            g = db.get(Generation, p.generation_id)
            if applied and g and g.status == "paid":
                start_job(db, g)
            return f"/g/{p.generation_id}"
        return "/subscription"

    def reconcile(user_id: int | None = None) -> int:
        """Сверка ожидающих платежей с провайдером (на случай, если уведомление не дошло: сервер был выключен, сбой сети).
        Вызывается при открытии страниц пользователя, фоновым процессом и при каждом уведомлении."""
        n = 0
        with Session() as db:
            q = select(Payment).where(Payment.status == "pending", Payment.provider != "fake")
            if user_id:
                q = q.where(Payment.user_id == user_id)
            for p in db.scalars(q).all():
                if not p.provider_id:
                    continue
                try:
                    verdict = get_provider(p.provider).verify(p.provider_id)
                except Exception:   # noqa: BLE001  (провайдер недоступен - попробуем в следующий раз)
                    continue
                if verdict == "paid":
                    _apply_payment(db, p)
                    n += 1
                elif verdict == "canceled" or (now() - p.created).days >= 3:
                    p.status = "canceled"
                    db.commit()
        return n
    app.state.reconcile = reconcile

    def start_reconciler(interval_s: float = 120.0):
        import threading
        stop = threading.Event()

        def loop():
            while not stop.wait(interval_s):
                try:
                    reconcile()
                except Exception:   # noqa: BLE001
                    pass
        threading.Thread(target=loop, daemon=True, name="payments-reconciler").start()
        return stop
    app.state.start_reconciler = start_reconciler

    @app.post("/webhooks/yookassa")
    async def yookassa_webhook(request: Request):
        """Уведомление об оплате. Телу не доверяем: статус перепроверяется запросом к API ЮKassa."""
        try:
            data = await request.json()
            pid = data["object"]["id"]
        except Exception:  # noqa: BLE001
            return JSONResponse({"ok": False}, status_code=400)
        with Session() as db:
            p = db.scalar(select(Payment).where(Payment.provider == "yookassa", Payment.provider_id == pid))
            if not p:
                return JSONResponse({"ok": True})
            if get_provider("yookassa").verify(pid) == "paid":
                _apply_payment(db, p)
        return JSONResponse({"ok": True})

    # --- подписка и технический отчёт ---
    @app.get("/subscription", response_class=HTMLResponse)
    def subscription(request: Request):
        with Session() as db:
            u = current_user(request, db)
            if not u:
                return RedirectResponse("/login", status_code=303)
            if app.state.reconcile(u.id):
                db.refresh(u)
            return render(request, "subscription.html", u)

    @app.post("/subscription/buy")
    def subscription_buy(request: Request, csrf: str = Form("")):
        bad = deny_csrf(request, csrf)
        if bad:
            return bad
        with Session() as db:
            u = current_user(request, db)
            if not u:
                return RedirectResponse("/login", status_code=303)
            p = Payment(user_id=u.id, kind="subscription", amount_rub=st.price_subscription_rub, provider=st.payment_provider)
            db.add(p)
            db.flush()
            url = get_provider(st.payment_provider).create(p, f"{st.base_url}/subscription", "Подписка на технический отчёт")
            db.commit()
            return RedirectResponse(url, status_code=303)

    @app.get("/g/{gid}/report", response_class=HTMLResponse)
    def tech_report(request: Request, gid: int):
        with Session() as db:
            u, g = _owned(db, request, gid)
            if not u:
                return RedirectResponse("/login", status_code=303)
            if not g:
                return HTMLResponse("Не найдено", status_code=404)
            return render(request, "report.html", u, g=g)

    def recover():
        """После перезапуска сервера: незавершённые расчёты запускаем заново."""
        with Session() as db:
            for g in db.scalars(select(Generation).where(Generation.status.in_(("paid", "running")))).all():
                start_job(db, g)
    app.state.recover = recover
    return app


def _preview(project: dict) -> dict:
    """Бесплатная проверка замеров: итоги по допускам без файлов (быстро, без записи на диск)."""
    from ansys_report.geometry import check
    r = check.analyze(project)
    wb = max(r["belts"], key=lambda b: b["max_abs"])
    return {"diameter_m": r["diameter_m"], "height_m": r["height_m"], "n_points": r["n_points"], "n_gens": len(r["angles"]),
            "n_belts": len(r["belts"]), "over_a": r["over_a"], "over_b": r["over_b"], "ok_a": r["ok_a"], "ok_b": r["ok_b"],
            "max_abs_mm": round(r["max_abs"], 1), "worst_belt": wb["belt"], "dents": [
                {"name": d["name"], "depth_mm": round(d["depth_mm"], 1)} for d in r["dents"]],
            "groups": [{"thickness_mm": g["thickness_mm"], "bottom_m": g["bottom_m"], "top_m": g["top_m"]} for g in r["groups"]]}
