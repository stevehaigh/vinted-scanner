"""The ``Notifier`` seam."""

from __future__ import annotations

from typing import Protocol

from ..digest import Digest


class Notifier(Protocol):
    def send(self, digest: Digest) -> None:
        """Deliver a digest. Raises on failure so the caller can leave it pending."""
        ...


from .console import ConsoleNotifier  # noqa: E402
from .email import EmailError, EmailNotifier, EmailSettings  # noqa: E402

__all__ = ["ConsoleNotifier", "EmailError", "EmailNotifier", "EmailSettings", "Notifier"]
