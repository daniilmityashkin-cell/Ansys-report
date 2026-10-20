"""Пароли (argon2), сессии, CSRF, простая защита от подбора пароля."""
from __future__ import annotations
import secrets
import time
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, InvalidHashError

_ph = PasswordHasher()
EMAIL_MAX = 254


def hash_password(pw: str) -> str:
    return _ph.hash(pw)


def verify_password(pw: str, hashed: str) -> bool:
    try:
        return _ph.verify(hashed, pw)
    except (VerifyMismatchError, InvalidHashError):
        return False


def normalize_email(email: str) -> str:
    return (email or "").strip().lower()


DISPOSABLE_DOMAINS = {
    "mailinator.com", "guerrillamail.com", "guerrillamail.net", "guerrillamail.org", "sharklasers.com", "10minutemail.com", "10minutemail.net",
    "temp-mail.org", "tempmail.com", "tempmail.net", "temp-mail.io", "tempail.com", "yopmail.com", "yopmail.net", "trashmail.com", "trashmail.net",
    "getnada.com", "nada.email", "dispostable.com", "maildrop.cc", "throwawaymail.com", "fakeinbox.com", "mailnesia.com", "mohmal.com",
    "emailondeck.com", "mintemail.com", "spamgourmet.com", "mytemp.email", "tmpmail.org", "tmpmail.net", "burnermail.io", "moakt.com",
    "discard.email", "inboxkitten.com", "tempinbox.com", "mailcatch.com", "33mail.com", "anonbox.net", "1secmail.com", "1secmail.net",
    "dropmail.me", "emlhub.com", "tempr.email", "luxusmail.org",
}
_GMAIL = {"gmail.com", "googlemail.com"}
_YANDEX = {"yandex.ru", "ya.ru", "yandex.com", "yandex.kz", "yandex.by", "yandex.ua"}


def email_domain(email: str) -> str:
    return normalize_email(email).rsplit("@", 1)[-1]


def is_disposable(email: str) -> bool:
    return email_domain(email) in DISPOSABLE_DOMAINS


def canonical_email(email: str) -> str:
    """Один человек - одна почта: убираем метки «+что-то», у Gmail точки, сводим синонимы доменов Gmail и Яндекса."""
    e = normalize_email(email)
    local, _, dom = e.rpartition("@")
    local = local.split("+", 1)[0]
    if dom in _GMAIL:
        local, dom = local.replace(".", ""), "gmail.com"
    elif dom in _YANDEX:
        local, dom = local.replace(".", "-"), "yandex.ru"
    return f"{local}@{dom}"


def valid_email(email: str) -> bool:
    e = normalize_email(email)
    return 3 <= len(e) <= EMAIL_MAX and "@" in e and "." in e.rsplit("@", 1)[-1] and " " not in e


def csrf_token(session: dict) -> str:
    tok = session.get("csrf")
    if not tok:
        tok = session["csrf"] = secrets.token_urlsafe(24)
    return tok


def csrf_ok(session: dict, given: str | None) -> bool:
    tok = session.get("csrf")
    return bool(tok and given and secrets.compare_digest(tok, given))


class LoginLimiter:
    """5 неудачных входов с одного адреса/почты - пауза на 5 минут (в памяти процесса)."""
    def __init__(self, limit: int = 5, window: float = 300.0):
        self.limit, self.window, self.fails = limit, window, {}

    def blocked(self, key: str) -> bool:
        n, t = self.fails.get(key, (0, 0.0))
        if n >= self.limit and time.time() - t < self.window:
            return True
        if n >= self.limit:
            self.fails.pop(key, None)
        return False

    def fail(self, key: str):
        n, _ = self.fails.get(key, (0, 0.0))
        self.fails[key] = (n + 1, time.time())

    def ok(self, key: str):
        self.fails.pop(key, None)
