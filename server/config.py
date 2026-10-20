"""Настройки сайта из переменных окружения (префикс ASR_). Секреты в репозиторий не кладутся."""
from __future__ import annotations
import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path


def _bool(name: str, default: bool) -> bool:
    v = os.environ.get(name)
    return default if v is None else v.strip().lower() in ("1", "true", "yes", "on")


def _packs(text: str) -> dict:
    out = {}
    for part in text.split(","):
        n, _, price = part.partition(":")
        if n.strip().isdigit() and price.strip().isdigit():
            out[int(n)] = int(price)
    return dict(sorted(out.items()))


@dataclass
class Settings:
    data_dir: Path = field(default_factory=lambda: Path(os.environ.get("ASR_DATA_DIR", "server_data")))
    db_url: str = field(default_factory=lambda: os.environ.get("ASR_DB_URL", ""))
    secret_key: str = field(default_factory=lambda: os.environ.get("ASR_SECRET") or secrets.token_urlsafe(32))
    https_only: bool = field(default_factory=lambda: _bool("ASR_HTTPS_ONLY", False))     # на боевом сервере: 1
    base_url: str = field(default_factory=lambda: os.environ.get("ASR_BASE_URL", "http://127.0.0.1:8000"))
    payment_provider: str = field(default_factory=lambda: os.environ.get("ASR_PAYMENT_PROVIDER", "fake"))
    price_generation_rub: int = field(default_factory=lambda: int(os.environ.get("ASR_PRICE_GENERATION", "1500")))
    packs: dict = field(default_factory=lambda: _packs(os.environ.get("ASR_PACKS", "10:12000,25:27500,50:50000")))   # размер пакета: цена, ₽
    max_upload_bytes: int = field(default_factory=lambda: int(os.environ.get("ASR_MAX_UPLOAD", str(2_000_000))))
    inline_jobs: bool = field(default_factory=lambda: _bool("ASR_INLINE_JOBS", False))   # тесты: считать в этом же процессе
    max_reg_per_ip: int = field(default_factory=lambda: int(os.environ.get("ASR_MAX_REG_PER_IP", "3")))     # регистраций с одного IP за сутки
    max_drafts_per_day: int = field(default_factory=lambda: int(os.environ.get("ASR_MAX_DRAFTS_PER_DAY", "30")))
    trust_proxy: bool = field(default_factory=lambda: _bool("ASR_TRUST_PROXY", False))          # IP клиента из X-Forwarded-For (за прокси)
    first_generation_free: bool = field(default_factory=lambda: _bool("ASR_FIRST_FREE", False))  # первая генерация на аккаунте бесплатна
    workers: int = field(default_factory=lambda: int(os.environ.get("ASR_WORKERS", "2")))

    def __post_init__(self):
        self.data_dir = Path(self.data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        if not self.db_url:
            self.db_url = f"sqlite:///{(self.data_dir / 'site.db').as_posix()}"
        (self.data_dir / "generations").mkdir(exist_ok=True)
