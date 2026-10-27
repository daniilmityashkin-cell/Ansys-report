"""Сайт: регистрация и вход, кабинет, замеры → проверка → оплата → геометрия, пакеты генераций."""
from __future__ import annotations
import datetime as dt
import io
import json
import re
import time
import zipfile
from pathlib import Path

from fastapi import FastAPI, Form, Request, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse, Response, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from sqlalchemy import select, func

from .config import Settings
from .db import make_session_factory
from .models import User, Generation, Payment, now
from .auth import (hash_password, verify_password, normalize_email, valid_email, csrf_token, csrf_ok, LoginLimiter,
                   canonical_email, is_disposable)
from .fingerprint import data_key
from .loadsinput import DEFAULTS, SNOW, WIND, TERRAINS
from .structinput import DEFAULTS as SDEFAULTS, SHAPES, ROOF_SHAPES
from .payments import get_provider, settle
from .jobs import JobRunner

HERE = Path(__file__).parent
PUBLIC_FILE_EXT = {".docx", ".step", ".igs", ".csv", ".json", ".html", ".png", ".py", ".txt", ".bat", ".wbjn"}


def create_app(settings: Settings | None = None) -> FastAPI:
    st = settings or Settings()
    engine, Session = make_session_factory(st.db_url)
    app = FastAPI(title="ANSYS REPORT", docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(SessionMiddleware, secret_key=st.secret_key, https_only=st.https_only, same_site="lax", max_age=14 * 86400)
    app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
    templates = Jinja2Templates(directory=str(HERE / "templates"))
    templates.env.globals["asset_v"] = int((HERE / "static" / "style.css").stat().st_mtime)    # сброс кэша стилей при обновлении
    templates.env.filters["rub"] = lambda n: f"{int(n):,}".replace(",", "\u00a0")       # 12000 -> 12 000
    templates.env.globals["min_unit"] = min((p // n for n, p in st.packs.items()), default=0)    # самая низкая цена генерации в пакетах
    limiter = LoginLimiter()

    SCTX = {"shapes": SHAPES, "roof_shapes": ROOF_SHAPES}

    def preview_ready(gid: int) -> bool:
        pv = gen_dir(gid) / "preview"
        if (pv / "ready").exists():
            return True
        u = pv / "prev_unfold.png"          # генерации, созданные до появления признака готовности
        return u.exists() and time.time() - u.stat().st_mtime > 120

    def gen_dir(gid: int) -> Path:
        return st.data_dir / "generations" / str(gid)

    def on_done(gid: int, result, error: str):
        with Session() as db:
            g = db.get(Generation, gid)
            if not g:
                return
            g.status, g.error = ("done", "") if not error else ("error", error)
            if error and g.charged == "credit":                      # ошибка расчёта: генерация возвращается в пакет
                u = db.get(User, g.user_id)
                u.credits = (u.credits or 0) + 1
                g.charged = "refunded"
            db.commit()
    runner = JobRunner(st.workers, st.inline_jobs, on_done)
    app.state.settings, app.state.Session, app.state.runner = st, Session, runner

    def start_job(db, g: Generation):
        g.status = "running"
        db.commit()
        runner.submit(g.id, gen_dir(g.id), g.title)

    # --- вспомогательное ---
    def client_ip(request: Request) -> str:
        if st.trust_proxy:                                         # за прокси (Caddy, nginx): реальный адрес в первом значении заголовка
            fwd = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
            if fwd:
                return fwd[:64]
        return (request.client.host if request.client else "")[:64]

    def is_unlimited(u: User) -> bool:
        return bool(st.unlimited_emails) and (u.email.lower() in st.unlimited_emails or (u.email_key or "") in {canonical_email(e) for e in st.unlimited_emails})

    def pay_mode(db, u: User, g: Generation) -> tuple[str, str]:
        """Как оформляется эта генерация: credit - из пакета, free - первая бесплатная, pay - разовая оплата, blocked - нужен пакет."""
        if is_unlimited(u):
            return "unlimited", ""
        if u.credit_count > 0:
            return "credit", ""
        used = db.scalar(select(func.count()).select_from(Generation).where(
            Generation.user_id == u.id, Generation.id != g.id, Generation.status.in_(("paid", "running", "done"))))
        if used:
            return "blocked", "Разовая генерация на этом аккаунте уже использована. Дальше генерации доступны в пакетах."
        if g.data_key and db.scalar(select(func.count()).select_from(Generation).where(
                Generation.data_key == g.data_key, Generation.user_id != u.id, Generation.status.in_(("paid", "running", "done")))):
            return "blocked", "Эти замеры уже обрабатывались на другом аккаунте. Для повторной генерации нужен пакет."
        return ("free" if st.first_generation_free else "pay"), ""

    def current_user(request: Request, db) -> User | None:
        uid = request.session.get("uid")
        return db.get(User, uid) if uid else None

    def render(request: Request, name: str, user=None, status_code: int = 200, **ctx):
        return templates.TemplateResponse(request, name, {"user": user, "csrf": csrf_token(request.session), "st": st, **ctx},
                                          status_code=status_code)

    def deny_csrf(request: Request, token: str | None):
        return None if csrf_ok(request.session, token) else HTMLResponse("Сессия устарела. Обновите страницу.", status_code=400)

    # --- общие страницы ---
    @app.api_route("/health", methods=["GET", "HEAD"])          # HEAD: так стучатся бесплатные мониторы (UptimeRobot)
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
        elif len(password) < 8:
            err = "Пароль должен быть не короче 8 символов."
        elif not consent:
            err = "Нужно согласие на обработку персональных данных."
        if not err and is_disposable(email):
            err = "Временные адреса почты не принимаются. Укажите постоянный адрес."
        key, ip = canonical_email(email), client_ip(request)
        with Session() as db:
            if not err and db.scalar(select(User).where((User.email == email) | (User.email_key == key))):
                err = "Этот адрес уже зарегистрирован."
            if not err and db.scalar(select(func.count()).select_from(User).where(
                    User.reg_ip == ip, User.created > now() - dt.timedelta(days=1))) >= st.max_reg_per_ip:
                err = "С вашего адреса уже создано несколько аккаунтов. Попробуйте позже или напишите в поддержку."
            if err:
                return render(request, "register.html", error=err, email=email, status_code=400)
            u = User(email=email, email_key=key, reg_ip=ip, password_hash=hash_password(password), consent_at=now())
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
            return render(request, "cabinet.html", u, gens=gens, unlimited=is_unlimited(u))

    @app.get("/new")
    def new_form():
        return RedirectResponse("/studio", status_code=303)             # единый вход: пошаговая студия геометрии

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
            if not err:
                try:
                    gid = _create_generation(db, u, title, project, summary).id
                except ValueError as e:
                    err = str(e)
            if err:
                return render(request, "new.html", u, error=err, title=title, text=text, status_code=400)
            return RedirectResponse(f"/g/{gid}", status_code=303)

    def _create_generation(db, u: User, title: str, project: dict, summary: dict, loads_input: dict | None = None, structure: dict | None = None) -> Generation:
        if not is_unlimited(u) and db.scalar(select(func.count()).select_from(Generation).where(
                Generation.user_id == u.id, Generation.created > now() - dt.timedelta(days=1))) >= st.max_drafts_per_day:
            raise ValueError("Слишком много проверок за сутки. Попробуйте завтра.")
        g = Generation(user_id=u.id, title=(title.strip() or "Резервуар")[:200], summary=json.dumps(summary, ensure_ascii=False),
                       data_key=data_key(project))
        db.add(g)
        db.commit()
        d = gen_dir(g.id)
        d.mkdir(parents=True, exist_ok=True)
        (d / "input.json").write_text(json.dumps(project, ensure_ascii=False), encoding="utf-8")
        if structure:
            (d / "structure.json").write_text(json.dumps(structure, ensure_ascii=False), encoding="utf-8")
        if loads_input:
            (d / "loads_input.json").write_text(json.dumps(loads_input, ensure_ascii=False), encoding="utf-8")
        runner.submit_preview(d)
        return g

    @app.get("/new/table")
    def new_table_form():
        return RedirectResponse("/studio", status_code=303)

    @app.post("/new/table")
    async def new_table_submit(request: Request, title: str = Form(""), diameter: str = Form(""), height: str = Form(""),
                               table: str = Form(""), thicknesses: str = Form(""), rows_are: str = Form("gens"), csrf: str = Form(""),
                               sheet: str = Form(""), src: str = Form("xlsx"), xlsx: UploadFile | None = File(None), jsonfile: UploadFile | None = File(None)):
        raw_form = await request.form()                                 # поля расчёта нагрузок (l_*)
        lform = {k: str(v) for k, v in raw_form.items() if k.startswith("l_")}
        sfields = {k: [str(x) for x in raw_form.getlist(k)] for k in raw_form.keys() if k.startswith("s_")}
        sform = {k: v[0] for k, v in sfields.items() if v}
        nz_rows = [dict(zip(("name", "shape", "width", "height", "z", "angle", "t", "in", "out"), r)) for r in zip(*[sfields.get(k, []) for k in (
            "s_nz_name", "s_nz_shape", "s_nz_width", "s_nz_height", "s_nz_z", "s_nz_angle", "s_nz_t", "s_nz_in", "s_nz_out")])]
        bad = deny_csrf(request, csrf)
        if bad:
            return bad
        from .tableinput import build_project, table_from_xlsx, survey_from_xlsx
        from .loadsinput import build_loads_input
        form = {"title": title, "diameter": diameter, "height": height, "table": table, "thicknesses": thicknesses, "rows_are": rows_are, "sheet": sheet, "src": src, **lform, **sform, "s_posted": "1"}
        with Session() as db:
            u = current_user(request, db)
            if not u:
                return RedirectResponse("/login", status_code=303)
            try:
                if src == "json" and jsonfile is not None and jsonfile.filename:
                    raw = await jsonfile.read(st.max_upload_bytes + 1)
                    if len(raw) > st.max_upload_bytes:
                        raise ValueError("Файл слишком большой.")
                    try:
                        jproj = json.loads(raw.decode("utf-8-sig"))
                        jsummary = _preview(jproj)
                    except Exception as e:  # noqa: BLE001
                        raise ValueError(f"Не удалось прочитать файл проекта: {e}")
                    from .structinput import structure_from_project
                    jstruct = structure_from_project(jproj)
                    loads_in = build_loads_input(lform, jproj) if lform.get("l_on") else None
                    gid = _create_generation(db, u, title, jproj, jsummary, loads_in, jstruct).id
                    return RedirectResponse(f"/g/{gid}", status_code=303)
                if src == "json":
                    raise ValueError("Выберите файл проекта (.json).")
                if xlsx is not None and xlsx.filename:
                    raw = await xlsx.read(st.max_upload_bytes + 1)
                    if len(raw) > st.max_upload_bytes:
                        raise ValueError("Файл слишком большой.")
                    try:                                                  # геодезическая съёмка (листы «Т-001 пустой» и т. п.)
                        meta = survey_from_xlsx(raw, sheet)
                    except ValueError as e:
                        if str(e) != "survey:none":
                            raise
                        table = form["table"] = table_from_xlsx(raw)       # простая таблица чисел: подставляется в поле
                    else:
                        table = form["table"] = meta["table"]
                        rows_are = form["rows_are"] = "gens"
                        diameter = form["diameter"] = diameter.strip() or f"{meta['diameter_m']:g}"
                        height = form["height"] = height.strip() or f"{meta['height_m']:g}"
                        form["sheet"] = meta["sheet"]
                if not diameter.strip() and not height.strip():
                    got = "файл получен, но лист со съёмкой в нём не найден" if (xlsx is not None and xlsx.filename) else "файл Excel не был передан (выберите его заново)"
                    raise ValueError(f"Диаметр и высота не определены: {got}. Загрузите файл съёмки или впишите диаметр и высоту вручную.")
                project = build_project(diameter, height, table, thicknesses, rows_are if rows_are in ("gens", "belts") else "gens")
                summary = _preview(project)
                loads_in = build_loads_input(lform, project)
                from .structinput import build_structure
                structure = build_structure(sfields, float(project["diameter"]), float(project["height"]))
                gid = _create_generation(db, u, title, project, summary, loads_in, structure).id
            except Exception as e:  # noqa: BLE001
                return render(request, "new_table.html", u, error=str(e), f=form, snow=SNOW, wind=WIND, terrains=TERRAINS, nz_rows=nz_rows, **SCTX, status_code=400)
            return RedirectResponse(f"/g/{gid}", status_code=303)

    # --- студия: пошаговый ввод геометрии (измерения -> геометрия -> конструкция -> нагрузки) ---
    @app.get("/studio", response_class=HTMLResponse)
    def studio_page(request: Request):
        with Session() as db:
            u = current_user(request, db)
            if not u:
                return RedirectResponse("/login", status_code=303)
            return render(request, "studio.html", u, f={**DEFAULTS, **SDEFAULTS}, snow=SNOW, wind=WIND, terrains=TERRAINS, **SCTX)

    @app.get("/studio/profiles.json")
    def studio_profiles():
        from ansys_report.loads.profiles import catalog_names
        return JSONResponse({"names": catalog_names()})

    @app.get("/studio/profile")
    def studio_profile(label: str = ""):
        """Свойства сечения по подписи (подсказка под полем в студии)."""
        from ansys_report.loads.profiles import parse_profile
        try:
            p = parse_profile(label[:80])
        except ValueError as e:
            return JSONResponse({"error": str(e)}, status_code=400)
        return JSONResponse(p)

    @app.get("/studio/edit/{gid}")
    def studio_edit(request: Request, gid: int):
        """Генерация для правки: замеры и конструкция возвращаются в студию (новая генерация создаётся при «Создать модель», старая остаётся)."""
        with Session() as db:
            u, g = _owned(db, request, gid)
            if not u or not g:
                return JSONResponse({"error": "Не найдено"}, status_code=404)
            d = gen_dir(g.id)
            try:
                project = json.loads((d / "input.json").read_text(encoding="utf-8-sig"))
            except Exception:   # noqa: BLE001
                return JSONResponse({"error": "Файл замеров не найден."}, status_code=404)
            sp = d / "structure.json"
            return JSONResponse({"title": g.title, "project": project, "structure": json.loads(sp.read_text(encoding="utf-8")) if sp.exists() else None})

    @app.post("/studio/thickness")
    async def studio_thickness(request: Request, csrf: str = Form(""), nz: int = Form(0), text: str = Form(""), doc: UploadFile | None = File(None)):
        """Толщины поясов из документа заказчика (xlsx / docx / txt) или вставленного текста. Только распознаёт: результат пользователь проверяет в таблице."""
        bad = deny_csrf(request, csrf)
        if bad:
            return bad
        with Session() as db:
            if not current_user(request, db):
                return JSONResponse({"error": "login"}, status_code=401)
        try:
            from .thickparse import parse_document, read_file
            tables = []
            if doc is not None and doc.filename:
                raw = await doc.read(st.max_upload_bytes + 1)
                if len(raw) > st.max_upload_bytes:
                    return JSONResponse({"error": "Файл слишком большой."}, status_code=400)
                text, tables = read_file(doc.filename, raw)
            return JSONResponse(parse_document(text[:200000], tables, nz or None))
        except ValueError as e:
            return JSONResponse({"error": str(e)}, status_code=400)
        except Exception as e:  # noqa: BLE001
            return JSONResponse({"error": "Не удалось прочитать документ: " + str(e)[:150]}, status_code=400)

    @app.post("/studio/xlsx")
    async def studio_xlsx(request: Request, xlsx: UploadFile = File(...), sheet: str = Form(""), csrf: str = Form("")):
        bad = deny_csrf(request, csrf)
        if bad:
            return bad
        with Session() as db:
            if not current_user(request, db):
                return JSONResponse({"error": "login"}, status_code=401)
        raw = await xlsx.read(st.max_upload_bytes + 1)
        if len(raw) > st.max_upload_bytes:
            return JSONResponse({"error": "Файл слишком большой."}, status_code=400)
        from .tableinput import build_project, table_from_xlsx, survey_from_xlsx
        try:
            try:
                meta = survey_from_xlsx(raw, sheet)
                table, dia, hei = meta["table"], f"{meta['diameter_m']:g}", f"{meta['height_m']:g}"
            except ValueError as e:
                msg = str(e)
                if msg.startswith("В файле несколько листов со съёмкой:"):          # выбор листа делает страница: по умолчанию «пустой»
                    names = [x.strip() for x in msg.split(":", 1)[1].split(". Впишите")[0].split(",")]
                    return JSONResponse({"sheets": names})
                if msg != "survey:none":
                    raise
                table, dia, hei = table_from_xlsx(raw), "", ""
            from .tableinput import _cells
            rows = _cells(table)
            n_belts = len(rows[0]) if rows else 0
            proj = build_project(dia or "30", hei or "18", table, " ".join(["10"] * n_belts), "gens") if n_belts else None
            for b in (proj or {}).get("bands", []):
                b[1] = ""                                             # толщин в геодезии нет: их вводит пользователь, подставлять нельзя
            return JSONResponse({"project": proj, "diameter": dia, "height": hei, "need_dims": not dia, "need_thickness": True})
        except Exception as e:  # noqa: BLE001
            return JSONResponse({"error": str(e)}, status_code=400)

    @app.post("/studio/create")
    async def studio_create(request: Request):
        try:
            body = await request.json()
        except Exception:   # noqa: BLE001
            return JSONResponse({"error": "Некорректный запрос."}, status_code=400)
        if not csrf_ok(request.session, body.get("csrf")):
            return JSONResponse({"error": "Сессия устарела. Обновите страницу."}, status_code=400)
        with Session() as db:
            u = current_user(request, db)
            if not u:
                return JSONResponse({"error": "login"}, status_code=401)
            try:
                project = body["project"]
                from .tableinput import require_thicknesses
                require_thicknesses(project)
                summary = _preview(project)
                from .structinput import build_structure, structure_from_project
                D, H = float(str(project["diameter"]).replace(",", ".")), float(str(project["height"]).replace(",", "."))
                if body.get("struct_source") == "project":
                    structure = structure_from_project(project)
                else:
                    structure = build_structure({k: [str(x) for x in (v if isinstance(v, list) else [v])] for k, v in (body.get("structure") or {}).items()}, D, H, project)
                lform = {k: str(v) for k, v in (body.get("loads") or {}).items() if k.startswith("l_")}
                from .loadsinput import build_loads_input
                loads_in = build_loads_input(lform, project) if lform.get("l_on") else None
                gid = _create_generation(db, u, str(body.get("title") or ""), project, summary, loads_in, structure).id
            except Exception as e:  # noqa: BLE001
                return JSONResponse({"error": str(e)}, status_code=400)
            return JSONResponse({"url": f"/g/{gid}"})

    step_jobs: dict = {}                                           # token -> {"uid", "future", "dir"}

    def _step_struct(body: dict, project: dict):
        from .structinput import build_structure
        D, H = float(str(project["diameter"]).replace(",", ".")), float(str(project["height"]).replace(",", "."))
        return build_structure({k: [str(x) for x in (v if isinstance(v, list) else [v])] for k, v in (body.get("structure") or {}).items()}, D, H, project)

    @app.post("/studio/step")
    async def studio_step(request: Request):
        try:
            body = await request.json()
        except Exception:   # noqa: BLE001
            return JSONResponse({"error": "Некорректный запрос."}, status_code=400)
        if not csrf_ok(request.session, body.get("csrf")):
            return JSONResponse({"error": "Сессия устарела. Обновите страницу."}, status_code=400)
        with Session() as db:
            u = current_user(request, db)
            if not u:
                return JSONResponse({"error": "login"}, status_code=401)
            uid = u.id
        if any(j["uid"] == uid and not j["future"].done() for j in step_jobs.values()):
            return JSONResponse({"error": "Предыдущая модель ещё строится. Подождите минуту."}, status_code=429)
        try:
            project = body["project"]
            from .tableinput import require_thicknesses
            require_thicknesses(project)
            _preview(project)
            structure = _step_struct(body, project)
        except Exception as e:  # noqa: BLE001
            return JSONResponse({"error": str(e)}, status_code=400)
        import secrets, shutil
        root = st.data_dir / "studio"
        for old in (root.glob("*/*") if root.exists() else []):                 # чистим то, что старше суток
            if old.is_dir() and time.time() - old.stat().st_mtime > 86400:
                shutil.rmtree(old, ignore_errors=True)
        tok = secrets.token_urlsafe(12)
        d = root / str(uid) / tok
        d.mkdir(parents=True, exist_ok=True)
        from .jobs import compute_step
        step_jobs[tok] = {"uid": uid, "dir": d, "future": app.state.runner.submit_fn(compute_step, str(d), project, structure)}
        return JSONResponse({"token": tok})

    @app.get("/studio/step/{tok}")
    def studio_step_status(request: Request, tok: str):
        with Session() as db:
            u = current_user(request, db)
        j = step_jobs.get(tok)
        if not u or not j or j["uid"] != u.id:
            return JSONResponse({"error": "not found"}, status_code=404)
        f = j["future"]
        if not f.done():
            return JSONResponse({"state": "running"})
        if f.exception():
            return JSONResponse({"state": "error", "error": f"{type(f.exception()).__name__}: {f.exception()}"[:300]})
        return JSONResponse({"state": "done", "files": [{"name": n, "mb": round((j["dir"] / n).stat().st_size / 1e6, 1)} for n in f.result()]})

    @app.get("/studio/step/{tok}/file/{name}")
    def studio_step_file(request: Request, tok: str, name: str):
        with Session() as db:
            u = current_user(request, db)
        j = step_jobs.get(tok)
        if not u or not j or j["uid"] != u.id or not j["future"].done() or j["future"].exception() or name not in j["future"].result() or not (j["dir"] / name).exists():
            return HTMLResponse("Не найдено", status_code=404)
        return FileResponse(j["dir"] / name, filename=name, media_type="application/step")

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
            loads_view = None
            lp = gen_dir(g.id) / "loads_input.json"
            if lp.exists():
                try:
                    from ansys_report.loads.rvs_loads import compute as compute_loads
                    loads_view = compute_loads(json.loads(lp.read_text(encoding="utf-8")))
                except Exception as e:  # noqa: BLE001
                    loads_view = {"error": str(e)}
            sp = gen_dir(g.id) / "structure.json"
            structure = json.loads(sp.read_text(encoding="utf-8")) if sp.exists() else None
            mode, why = pay_mode(db, u, g) if g.status == "draft" else ("", "")
            return render(request, "generation.html", u, g=g, summary=json.loads(g.summary or "{}"), mode=mode, why=why, loads_view=loads_view, structure=structure,
                          has_loads=lp.exists(), lf=DEFAULTS, snow=SNOW, wind=WIND, terrains=TERRAINS, loads_error=request.query_params.get("loads_error", "")[:300],
                          has_preview=preview_ready(g.id),
                          files=_files(g.id) if g.status == "done" else [],
                          agent_url=(f"ansysreport://run?server={(st.public_url or str(request.base_url)).rstrip('/')}&g={g.id}&t={agent_token(g.id)}"
                                     if g.status == "done" else ""),
                          agent=agent_state(g.id) if g.status == "done" else None)

    @app.post("/g/{gid}/loads")
    async def set_loads(request: Request, gid: int):
        raw_form = await request.form()
        bad = deny_csrf(request, str(raw_form.get("csrf", "")))
        if bad:
            return bad
        with Session() as db:
            u, g = _owned(db, request, gid)
            if not u or not g:
                return HTMLResponse("Не найдено", status_code=404)
            if g.status != "draft":
                return RedirectResponse(f"/g/{gid}", status_code=303)
            try:
                from .loadsinput import build_loads_input
                lform = {k: str(v) for k, v in raw_form.items() if k.startswith("l_")}
                lform["l_on"] = "1"
                project = json.loads((gen_dir(g.id) / "input.json").read_text(encoding="utf-8-sig"))
                loads_in = build_loads_input(lform, project)
                (gen_dir(g.id) / "loads_input.json").write_text(json.dumps(loads_in, ensure_ascii=False), encoding="utf-8")
            except Exception as e:  # noqa: BLE001
                from urllib.parse import quote
                return RedirectResponse(f"/g/{gid}?loads_error={quote(str(e)[:250])}#loads", status_code=303)
            return RedirectResponse(f"/g/{gid}#loads", status_code=303)

    def _loads3d(g, lform: dict | None) -> dict:
        """Нагрузки расчётных случаев отчёта в виде для 3D-показа: сохранённые (или введённые в форме прямо сейчас - без записи на диск)."""
        from ansys_report.loads.export import build_cases, pressure_view, report_fill_levels
        from ansys_report.loads.rvs_loads import compute as compute_loads
        d = gen_dir(g.id)
        project = json.loads((d / "input.json").read_text(encoding="utf-8-sig"))
        if lform is not None:
            from .loadsinput import build_loads_input
            inp = build_loads_input({**lform, "l_on": "1"}, project)
        elif (d / "loads_input.json").exists():
            inp = json.loads((d / "loads_input.json").read_text(encoding="utf-8"))
        else:
            from .loadsinput import build_loads_input
            inp = build_loads_input({"l_on": "1"}, project)
        res = compute_loads(inp)
        cases = build_cases(res, True, report_fill_levels(res))
        H = float(res["inputs"]["H"])
        sp = d / "structure.json"
        roof = (json.loads(sp.read_text(encoding="utf-8")).get("roof") or {}) if sp.exists() else {}
        bands = [float(str(b[0]).replace(",", ".")) for b in project["bands"]]
        z, edges = 0.0, [0.0]
        for h in bands:
            z += h
            edges.append(round(z, 4))
        return {"D": res["inputs"]["D"], "H": H, "rise_m": float(roof.get("rise_m") or inp.get("roof_rise_m") or 0.0), "belts_m": edges,
                "saved": lform is None and (d / "loads_input.json").exists(),
                "cases": [pressure_view(c, H * 1000.0) for c in cases], "notes": ["Ветер задан давлением по поясам и распределён равномерно по окружности (распределение по окружности уточняется)."]}

    @app.get("/g/{gid}/loads3d.json")
    def loads3d_get(request: Request, gid: int):
        with Session() as db:
            u, g = _owned(db, request, gid)
            if not u or not g:
                return JSONResponse({"error": "Не найдено"}, status_code=404)
            try:
                return JSONResponse(_loads3d(g, None))
            except Exception as e:  # noqa: BLE001
                return JSONResponse({"error": str(e)[:300]}, status_code=400)

    @app.post("/g/{gid}/loads3d.json")
    async def loads3d_post(request: Request, gid: int):
        """Нагрузки «как в форме сейчас»: показ обновляется по мере ввода, ничего не сохраняется."""
        form = await request.form()
        bad = deny_csrf(request, str(form.get("csrf", "")))
        if bad:
            return bad
        with Session() as db:
            u, g = _owned(db, request, gid)
            if not u or not g:
                return JSONResponse({"error": "Не найдено"}, status_code=404)
            try:
                return JSONResponse(_loads3d(g, {k: str(v) for k, v in form.items() if k.startswith("l_")}))
            except Exception as e:  # noqa: BLE001
                return JSONResponse({"error": str(e)[:300]}, status_code=400)

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
            mode, _ = pay_mode(db, u, g)
            if mode == "blocked":
                return RedirectResponse(f"/g/{g.id}", status_code=303)
            if mode in ("credit", "free", "unlimited"):         # из пакета, первая бесплатная и безлимитный аккаунт - без платежа
                if mode == "credit":
                    u.credits = u.credit_count - 1
                g.charged = mode
                start_job(db, g)
                return RedirectResponse(f"/g/{g.id}", status_code=303)
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

    @app.get("/g/{gid}/status")
    def generation_status(request: Request, gid: int):
        with Session() as db:
            u, g = _owned(db, request, gid)
            if not u or not g:
                return JSONResponse({"error": "not found"}, status_code=404)
            pv = gen_dir(g.id) / "preview"
            return JSONResponse({"status": g.status, "preview": preview_ready(g.id),
                                 "preview_error": (pv / "error.txt").read_text(encoding="utf-8")[:300] if (pv / "error.txt").exists() else ""})

    @app.get("/g/{gid}/structure.json")
    def structure_json(request: Request, gid: int):
        with Session() as db:
            u, g = _owned(db, request, gid)
            p = gen_dir(g.id) / "structure.json" if g else None
            if not u or not g or not p.exists():
                return HTMLResponse("Не найдено", status_code=404)
            return FileResponse(p, media_type="application/json")

    @app.get("/g/{gid}/viewer.json")
    def viewer_json(request: Request, gid: int):
        with Session() as db:
            u, g = _owned(db, request, gid)
            p = gen_dir(g.id) / "preview" / "viewer.json" if g else None
            if not u or not g:
                return HTMLResponse("Не найдено", status_code=404)
            if not p.exists():                                   # генерация создана до появления 3D - строим данные по входному файлу
                try:
                    from ansys_report.geometry import check
                    from ansys_report.geometry.viewer_data import viewer_data
                    res = check.analyze(check.load_project(gen_dir(g.id) / "input.json"))
                    p.parent.mkdir(parents=True, exist_ok=True)
                    p.write_text(json.dumps(viewer_data(res), separators=(",", ":")), encoding="utf-8")
                except Exception:   # noqa: BLE001
                    return HTMLResponse("Не найдено", status_code=404)
            return FileResponse(p, media_type="application/json")

    @app.get("/g/{gid}/img/{name}")
    def preview_img(request: Request, gid: int, name: str):
        with Session() as db:
            u, g = _owned(db, request, gid)
            if not u or not g or not re.fullmatch(r"prev_points\.png|prev_surface\.png|prev_unfold\.png|dent\d{1,3}\.png", name):
                return HTMLResponse("Не найдено", status_code=404)
            p = gen_dir(g.id) / "preview" / name
            return FileResponse(p) if p.exists() else HTMLResponse("Не найдено", status_code=404)

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

    # --- помощник на компьютере заказчика: кнопка на сайте -> Ansys считает у него -> отчёт возвращается на сайт ---
    import hmac
    import hashlib

    def agent_token(gid: int) -> str:
        return hmac.new(st.secret_key.encode(), f"agent:{gid}".encode(), hashlib.sha256).hexdigest()[:40]

    def agent_ok(gid: int, t: str) -> Generation | None:
        if not t or not hmac.compare_digest(t, agent_token(gid)):
            return None
        with Session() as db:
            g = db.get(Generation, gid)
            return g if g and g.status == "done" else None

    def agent_dir(gid: int) -> Path:
        d = gen_dir(gid) / "agent"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def agent_state(gid: int) -> dict:
        f = gen_dir(gid) / "agent" / "status.json"
        state = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {"stage": "idle", "message": ""}
        fd = gen_dir(gid) / "agent" / "files"
        state["files"] = sorted(x.name for x in fd.iterdir()) if fd.exists() else []
        return state

    @app.get("/agent/{gid}/package.zip")
    def agent_package(gid: int, t: str = ""):
        if not agent_ok(gid, t):
            return HTMLResponse("Недоступно", status_code=404)
        root = gen_dir(gid) / "result" / "ansys_model"
        if not root.exists():
            return HTMLResponse("Пакета нет", status_code=404)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for f in sorted(root.rglob("*")):
                if f.is_file():
                    z.write(f, f.relative_to(root).as_posix())
        return Response(buf.getvalue(), media_type="application/zip")

    @app.post("/agent/{gid}/status")
    async def agent_status_set(request: Request, gid: int, t: str = ""):
        if not agent_ok(gid, t):
            return JSONResponse({"error": "forbidden"}, status_code=403)
        body = await request.json()
        rec = {"stage": str(body.get("stage", ""))[:30], "message": str(body.get("message", ""))[:500], "updated": time.time()}
        (agent_dir(gid) / "status.json").write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")
        return JSONResponse({"ok": True})

    @app.post("/agent/{gid}/upload")
    async def agent_upload(gid: int, t: str = "", file: UploadFile = File(...)):
        if not agent_ok(gid, t):
            return JSONResponse({"error": "forbidden"}, status_code=403)
        name = Path(file.filename or "file").name
        if Path(name).suffix.lower() not in {".docx", ".xlsx", ".txt", ".csv", ".json", ".png"}:
            return JSONResponse({"error": "тип файла не разрешён"}, status_code=400)
        data = await file.read(100 * 1024 * 1024 + 1)
        if len(data) > 100 * 1024 * 1024:
            return JSONResponse({"error": "файл слишком большой"}, status_code=400)
        fd = agent_dir(gid) / "files"
        fd.mkdir(exist_ok=True)
        (fd / name).write_bytes(data)
        return JSONResponse({"ok": True})

    @app.get("/g/{gid}/agent.json")
    def agent_state_json(request: Request, gid: int):
        with Session() as db:
            u, g = _owned(db, request, gid)
            if not u or not g:
                return JSONResponse({"error": "not found"}, status_code=404)
        return JSONResponse(agent_state(gid))

    @app.get("/g/{gid}/agent-files/{name}")
    def agent_file(request: Request, gid: int, name: str):
        with Session() as db:
            u, g = _owned(db, request, gid)
            if not u or not g:
                return HTMLResponse("Не найдено", status_code=404)
        f = gen_dir(gid) / "agent" / "files" / Path(name).name
        if not f.exists():
            return HTMLResponse("Не найдено", status_code=404)
        return FileResponse(f, filename=f.name)

    @app.get("/agent/setup", response_class=HTMLResponse)
    def agent_setup(request: Request):
        with Session() as db:
            return render(request, "agent_setup.html", current_user(request, db))

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
        applied = settle(db, p)
        db.commit()
        if p.kind == "generation" and p.generation_id:
            g = db.get(Generation, p.generation_id)
            if applied and g and g.status == "paid":
                start_job(db, g)
            return f"/g/{p.generation_id}"
        return "/packs"

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

    # --- пакеты генераций ---
    @app.get("/packs", response_class=HTMLResponse)
    def packs(request: Request):
        with Session() as db:
            u = current_user(request, db)
            if not u:
                return RedirectResponse("/login", status_code=303)
            if app.state.reconcile(u.id):
                db.refresh(u)
            return render(request, "packs.html", u)

    @app.get("/subscription")
    def subscription_moved():
        return RedirectResponse("/packs", status_code=303)

    @app.post("/packs/buy")
    def packs_buy(request: Request, size: str = Form(""), csrf: str = Form("")):
        bad = deny_csrf(request, csrf)
        if bad:
            return bad
        with Session() as db:
            u = current_user(request, db)
            if not u:
                return RedirectResponse("/login", status_code=303)
            n = int(size) if size.isdigit() else 0
            if n not in st.packs:
                return RedirectResponse("/packs", status_code=303)
            p = Payment(user_id=u.id, kind="pack", qty=n, amount_rub=st.packs[n], provider=st.payment_provider)
            db.add(p)
            db.flush()
            url = get_provider(st.payment_provider).create(p, f"{st.base_url}/packs", f"Пакет {n} генераций")
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
                {"id": d["id"], "name": d["name"], "depth_mm": round(d["depth_mm"], 1), "sign": d["sign"], "s_m": round(d["s_m"], 2),
                 "angle": round(d["angle"], 1), "z_m": round(d["z_m"], 2), "width_m": round(d["width_m"], 2),
                 "height_m": round(d["height_m"], 2), "n_points": d["n_points"]} for d in r["dents"]],
            "groups": [{"thickness_mm": g["thickness_mm"], "bottom_m": g["bottom_m"], "top_m": g["top_m"]} for g in r["groups"]],
            "belts": [{"belt": b["belt"], "z_m": round(b["z_m"], 2), "lim_a": round(b["lim_a"], 1), "lim_b": round(b["lim_b"], 1), "max_abs": round(b["max_abs"], 1),
                       "max_gen": b["max_gen"], "over_a": b["over_a"], "over_b": b["over_b"], "n": b["n"]} for b in r["belts"]],
            "worst": [{"belt": w["belt"], "gen": w["gen"], "angle": round(w["angle"], 1), "z_m": round(w["z_m"], 2), "dev": round(w["dev"], 1),
                       "lim_a": round(w["lim_a"], 1), "ratio": round(w["ratio_a"], 2)} for w in r["worst"][:10]],
            "thickness_belts": [round(b["thickness_mm"], 1) for b in r["bands"]]}
