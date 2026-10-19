# Запуск сайта на сервере с Windows 10

Характеристики сервера: Windows 10 Домашняя 22H2, Core i3-9100T, 4 ГБ ОЗУ. Для сайта (регистрация, проверка замеров, геометрия, отчёты Word) этого достаточно при 1–2 одновременных расчётах. Для Ansys — нет (см. раздел «Ограничения»).

## 1. Подготовка
1. Установите Python 3.12 или 3.13 (python.org, галочка «Add python.exe to PATH»).
2. Скачайте проект: `git clone <репозиторий> C:\asr` и откройте PowerShell в этой папке.
3. Окружение и пакеты:
   ```
   python -m venv .venv
   .venv\Scripts\python -m pip install -r requirements.txt -r requirements-server.txt
   ```
4. Проверка: `.venv\Scripts\python -m server` → http://127.0.0.1:8000 открывается в браузере.

## 2. Настройки (PowerShell, один раз, постоянные переменные для системы)
```
[Environment]::SetEnvironmentVariable("ASR_SECRET","<длинная случайная строка>","Machine")
[Environment]::SetEnvironmentVariable("ASR_DATA_DIR","D:\asr_data","Machine")
[Environment]::SetEnvironmentVariable("ASR_BASE_URL","https://ВАШ-ДОМЕН","Machine")
[Environment]::SetEnvironmentVariable("ASR_HTTPS_ONLY","1","Machine")
[Environment]::SetEnvironmentVariable("ASR_WORKERS","1","Machine")
```
Секрет можно получить командой: `.venv\Scripts\python -c "import secrets;print(secrets.token_urlsafe(48))"`.
Для 4 ГБ памяти оставьте `ASR_WORKERS=1` и базу SQLite (по умолчанию, файл `site.db` в `ASR_DATA_DIR`).

## 3. Автозапуск как служба (NSSM)
1. Скачайте NSSM (nssm.cc), затем в PowerShell от администратора:
   ```
   nssm install ASRsite C:\asr\.venv\Scripts\python.exe -m uvicorn server.wsgi:app --host 127.0.0.1 --port 8000
   nssm set ASRsite AppDirectory C:\asr
   nssm set ASRsite Start SERVICE_AUTO_START
   nssm start ASRsite
   ```
2. После обновления кода: `git pull` и `nssm restart ASRsite`.

## 4. HTTPS и доступ из интернета (Caddy)
1. Купите домен и направьте A-запись на внешний IP сервера.
2. На маршрутизаторе или в университетской сети откройте порты 80 и 443 на этот компьютер (согласовать с ИТ-отделом).
3. Скачайте Caddy для Windows и создайте файл `Caddyfile`:
   ```
   ВАШ-ДОМЕН {
       reverse_proxy 127.0.0.1:8000
   }
   ```
   Caddy сам получает и продлевает сертификат. Запуск службой: `caddy run --config Caddyfile` под NSSM (аналогично пункту 3).
4. Брандмауэр Windows: разрешить входящие 80 и 443; порт 8000 наружу не открывать.

## 5. Резервные копии
Каждый день: копия папки `ASR_DATA_DIR` на отдельный диск (Планировщик заданий + `robocopy D:\asr_data E:\backup\asr_data /MIR`). Лучше ещё копия вне сервера.

## 6. Ограничения этого сервера (важно)
- **Windows 10 больше не получает обновления безопасности** (поддержка закончилась в октябре 2025 года) — для сайта, открытого в интернет, это риск. Варианты: Windows 11 или Windows 10 с платными обновлениями (ESU), либо **Ubuntu Server** на этой же машине (бесплатно, обновляется, подходит для хостинга; инструкция — `docs/DEPLOY_SERVER.md`).
- **Редакция «Домашняя»** не принимает входящие подключения по удалённому рабочему столу. Для управления издалека нужен другой способ (AnyDesk, SSH на Ubuntu).
- **4 ГБ ОЗУ**: хватает на сайт и геометрию; Ansys для расчёта требует минимум 16 ГБ (практически 32 ГБ и больше) — для этого понадобится отдельная машина или апгрейд. Пока расчёт Ansys на сервере не запускается.
- Один источник питания и один диск: поставьте ИБП и делайте копии.
