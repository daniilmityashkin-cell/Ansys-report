# Развёртывание сайта на своём сервере (Linux)

Проверено только в режиме разработки (`python -m server`) и тестами. Боевые настройки ниже — рекомендации, их нужно проверить на сервере.

## 1. Установка
```bash
sudo apt install python3-venv nginx postgresql certbot python3-certbot-nginx
git clone <репозиторий> /opt/asr && cd /opt/asr
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements-server.txt
```

## 2. Переменные окружения (файл `/etc/asr.env`, права 600)
```
ASR_SECRET=<длинная случайная строка, python -c "import secrets;print(secrets.token_urlsafe(48))">
ASR_DATA_DIR=/var/lib/asr
ASR_DB_URL=postgresql+psycopg://asr:ПАРОЛЬ@127.0.0.1/asr
ASR_BASE_URL=https://ВАШ-ДОМЕН
ASR_HTTPS_ONLY=1
ASR_PAYMENT_PROVIDER=yookassa      # fake - только для разработки
ASR_YOOKASSA_SHOP_ID=...
ASR_YOOKASSA_SECRET=...
ASR_PRICE_GENERATION=1500
ASR_PRICE_SUBSCRIPTION=9900
ASR_WORKERS=2
```

## 3. Служба systemd (`/etc/systemd/system/asr.service`)
```
[Unit]
Description=ASR site
After=network.target postgresql.service
[Service]
User=asr
WorkingDirectory=/opt/asr
EnvironmentFile=/etc/asr.env
ExecStart=/opt/asr/.venv/bin/uvicorn server.wsgi:app --host 127.0.0.1 --port 8000
Restart=always
[Install]
WantedBy=multi-user.target
```
`sudo systemctl enable --now asr`

## 4. nginx + HTTPS
```
server {
    server_name ВАШ-ДОМЕН;
    client_max_body_size 5m;
    location / { proxy_pass http://127.0.0.1:8000; proxy_set_header Host $host;
                 proxy_set_header X-Forwarded-Proto $scheme; proxy_set_header X-Forwarded-For $remote_addr; }
}
```
`sudo certbot --nginx -d ВАШ-ДОМЕН`. Открыть наружу только порты 80 и 443.

## 5. Платежи (ЮKassa)
В личном кабинете ЮKassa указать адрес уведомлений `https://ВАШ-ДОМЕН/webhooks/yookassa` (событие `payment.succeeded`). Сайт перепроверяет статус запросом к API.
Для ООО по 54-ФЗ в запрос нужно добавить данные чека (`receipt`) — доработать `server/payments.py` после настройки онлайн-кассы.

## 6. Эксплуатация
- Резервные копии: `pg_dump` и каталог `ASR_DATA_DIR` ежедневно, копия вне сервера.
- Источник бесперебойного питания, мониторинг доступности (`/health`), ротация логов.
- После обновления: `git pull && systemctl restart asr`; незавершённые генерации перезапускаются сами.

## Временная демонстрация в GitHub Codespaces
GitHub Pages для сайта не подходит (только статика). Для показа можно запустить сайт в Codespaces:
1. Репозиторий на GitHub → Code → Codespaces → Create codespace on `claude/ansys-report-automation-8asxtm`.
2. После установки зависимостей в терминале: `bash tools/codespace_run.sh`.
3. Вкладка Ports → порт 8000 → Port Visibility → Public. Ссылка вида `https://<имя>-8000.app.github.dev`.
Данные пропадают при удалении Codespace, оплата тестовая. Это только для демонстрации, не для заказчиков.

## Демо на Render (бесплатный тариф, из GitHub)
1. render.com -> войти через GitHub -> New -> Blueprint -> репозиторий `ansys-report` -> ветка `claude/ansys-report-automation-8asxtm` (файл `render.yaml`).
2. После сборки появится ссылка `https://rvs-geometry-….onrender.com`.
Ограничения бесплатного тарифа: сервис засыпает через ~15 минут без запросов (первый заход после этого грузится около минуты), диск временный: база и файлы пропадают при каждом новом развёртывании и перезапуске. Оплата тестовая. Для заказчиков и платежей не подходит. Свой домен можно подключить позже в настройках сервиса.
