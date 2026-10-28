"""Уведомления: Telegram (команде) и почта (клиенту). Без настроек - ничего не отправляется; ошибки не ломают обработку."""
from __future__ import annotations
import smtplib
import threading
from email.message import EmailMessage


class Notifier:
    def __init__(self, st):
        self.st = st
        self.outbox: list[tuple] = []            # тесты (send_inline): что было бы отправлено

    def telegram(self, text: str) -> None:
        if self.st.send_inline:
            self.outbox.append(("tg", text))
            return
        if not (self.st.tg_token and self.st.tg_chat):
            return
        threading.Thread(target=self._tg, args=(text,), daemon=True).start()

    def _tg(self, text: str) -> None:
        try:
            import httpx
            httpx.post(f"https://api.telegram.org/bot{self.st.tg_token}/sendMessage",
                       json={"chat_id": self.st.tg_chat, "text": text, "disable_web_page_preview": True}, timeout=10)
        except Exception:   # noqa: BLE001
            pass

    def email(self, to: str, subject: str, body: str) -> bool:
        if not to:
            return False
        if self.st.send_inline:
            self.outbox.append(("email", to, subject, body))
            return True
        if not (self.st.smtp_host and self.st.mail_from):
            return False
        threading.Thread(target=self._mail, args=(to, subject, body), daemon=True).start()
        return True

    def _mail(self, to: str, subject: str, body: str) -> None:
        try:
            m = EmailMessage()
            m["From"], m["To"], m["Subject"] = self.st.mail_from, to, subject
            m.set_content(body)
            cls = smtplib.SMTP_SSL if self.st.smtp_port == 465 else smtplib.SMTP
            with cls(self.st.smtp_host, self.st.smtp_port, timeout=20) as s:
                if cls is smtplib.SMTP:
                    s.starttls()
                if self.st.smtp_user:
                    s.login(self.st.smtp_user, self.st.smtp_password)
                s.send_message(m)
        except Exception:   # noqa: BLE001
            pass
