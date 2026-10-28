"""Настройки CRM из переменных окружения (префикс CRM_). Секреты в репозиторий не кладутся."""
from __future__ import annotations
import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


@dataclass
class Settings:
    data_dir: Path = field(default_factory=lambda: Path(_env("CRM_DATA_DIR", "crm_data")))
    db_url: str = field(default_factory=lambda: _env("CRM_DB_URL"))
    secret_key: str = field(default_factory=lambda: _env("CRM_SECRET"))
    api_token: str = field(default_factory=lambda: _env("CRM_API_TOKEN"))          # токен для сайта и форм (заголовок Authorization: Bearer …)
    https_only: bool = field(default_factory=lambda: _env("CRM_HTTPS_ONLY") in ("1", "true", "yes"))
    admin_email: str = field(default_factory=lambda: _env("CRM_ADMIN_EMAIL").lower())   # первый администратор создаётся при старте
    admin_password: str = field(default_factory=lambda: _env("CRM_ADMIN_PASSWORD"))
    site_url: str = field(default_factory=lambda: _env("CRM_SITE_URL", "http://127.0.0.1:8000"))
    public_url: str = field(default_factory=lambda: _env("CRM_PUBLIC_URL", "http://127.0.0.1:8100"))
    # уведомления: Telegram-бот и почта (пусто - отключено)
    tg_token: str = field(default_factory=lambda: _env("CRM_TG_TOKEN"))
    tg_chat: str = field(default_factory=lambda: _env("CRM_TG_CHAT"))
    smtp_host: str = field(default_factory=lambda: _env("CRM_SMTP_HOST"))
    smtp_port: int = field(default_factory=lambda: int(_env("CRM_SMTP_PORT", "465") or 465))
    smtp_user: str = field(default_factory=lambda: _env("CRM_SMTP_USER"))
    smtp_password: str = field(default_factory=lambda: _env("CRM_SMTP_PASSWORD"))
    mail_from: str = field(default_factory=lambda: _env("CRM_MAIL_FROM"))
    lead_call_minutes: int = field(default_factory=lambda: int(_env("CRM_LEAD_CALL_MIN", "15") or 15))   # «позвонить в течение N минут»
    unpaid_hours: int = field(default_factory=lambda: int(_env("CRM_UNPAID_HOURS", "24") or 24))         # не оплатил за N часов - задача
    send_inline: bool = False                     # тесты: уведомления не отправляются в сеть, а копятся в app.state.outbox

    def __post_init__(self):
        self.data_dir = Path(self.data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        if not self.db_url:
            self.db_url = f"sqlite:///{(self.data_dir / 'crm.db').as_posix()}"
        kf = self.data_dir / "secret.key"
        if not self.secret_key:
            if kf.exists() and kf.read_text(encoding="utf-8").strip():
                self.secret_key = kf.read_text(encoding="utf-8").strip()
            else:
                self.secret_key = secrets.token_urlsafe(32)
                kf.write_text(self.secret_key, encoding="utf-8")
        tf = self.data_dir / "api_token.txt"
        if not self.api_token:
            if tf.exists() and tf.read_text(encoding="utf-8").strip():
                self.api_token = tf.read_text(encoding="utf-8").strip()
            else:
                self.api_token = secrets.token_urlsafe(24)
                tf.write_text(self.api_token, encoding="utf-8")
