from __future__ import annotations

import asyncio
import logging
import smtplib
import threading
from email.mime.text import MIMEText
from email.utils import formataddr

from src.config import SMTPConfig

LOGGER = logging.getLogger(__name__)


class EmailNotifier:
    def __init__(self, config: SMTPConfig) -> None:
        self._config = config

    @property
    def enabled(self) -> bool:
        return self._config.enabled

    def _send_sync(self, subject: str, body: str) -> None:
        if not self.enabled:
            LOGGER.warning("SMTP is not fully configured, skip alert email: %s", subject)
            return

        message = MIMEText(body, "plain", "utf-8")
        message["From"] = formataddr((self._config.from_name, self._config.user))
        message["To"] = self._config.to_email
        message["Subject"] = subject

        with smtplib.SMTP_SSL(self._config.host, self._config.port, timeout=30) as server:
            server.login(self._config.user, self._config.password)
            server.sendmail(self._config.user, [self._config.to_email], message.as_string())

    def send_with_timeout(self, subject: str, body: str, timeout_seconds: int) -> None:
        error_holder: list[Exception] = []

        def _worker() -> None:
            try:
                self._send_sync(subject, body)
            except Exception as error:
                error_holder.append(error)

        thread = threading.Thread(target=_worker, daemon=True)
        thread.start()
        thread.join(timeout=max(1, timeout_seconds))
        if thread.is_alive():
            raise TimeoutError(f"alert email send timeout after {timeout_seconds}s")
        if error_holder:
            raise error_holder[0]

    async def send(self, subject: str, body: str) -> None:
        await asyncio.to_thread(self._send_sync, subject, body)
