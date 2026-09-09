"""Gmail SMTP, matching the pattern already proven in nightjet-ticket-checker."""

from __future__ import annotations

import os
import smtplib
from dataclasses import dataclass
from email.message import EmailMessage

from ..digest import Digest

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 465
TIMEOUT = 30


class EmailError(RuntimeError):
    """Sending failed. The caller leaves the digest pending for the next run."""


@dataclass(frozen=True, slots=True)
class EmailSettings:
    sender: str
    password: str
    recipients: tuple[str, ...]

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> EmailSettings | None:
        """Returns None when email is not configured, so local runs just work."""
        env = env if env is not None else dict(os.environ)
        sender = (env.get("GMAIL_ADDRESS") or "").strip()
        password = (env.get("GMAIL_APP_PASSWORD") or "").strip()
        if not sender or not password:
            return None
        raw = env.get("RECIPIENT_EMAIL") or sender
        recipients = tuple(part.strip() for part in raw.split(",") if part.strip())
        return cls(sender=sender, password=password, recipients=recipients)


class EmailNotifier:
    def __init__(self, settings: EmailSettings) -> None:
        self.settings = settings

    def send(self, digest: Digest) -> None:
        message = EmailMessage()
        message["Subject"] = digest.subject
        message["From"] = self.settings.sender
        message["To"] = ", ".join(self.settings.recipients)
        message.set_content(digest.text_body)
        if digest.html_body:
            message.add_alternative(digest.html_body, subtype="html")

        try:
            with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=TIMEOUT) as server:
                server.login(self.settings.sender, self.settings.password)
                server.send_message(message)
        except (smtplib.SMTPException, OSError) as exc:
            raise EmailError(f"could not send mail: {exc}") from exc
