"""Prints the digest. Used by ``--dry-run``."""

from __future__ import annotations

from ..digest import Digest


class ConsoleNotifier:
    def send(self, digest: Digest) -> None:
        print(f"\n=== {digest.subject} ===\n")
        print(digest.text_body)
