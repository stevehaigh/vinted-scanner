"""Prints the digest. Used by ``--dry-run`` and by tests."""

from __future__ import annotations

from ..digest import Digest


class ConsoleNotifier:
    def __init__(self) -> None:
        self.sent: list[Digest] = []

    def send(self, digest: Digest) -> None:
        self.sent.append(digest)
        print(f"\n=== {digest.subject} ===\n")
        print(digest.text_body)
