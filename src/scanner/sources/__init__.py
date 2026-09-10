"""Source registry.

Adding a site is a new module plus one line here.
"""

from __future__ import annotations

from .base import Source, SourceError
from .shopify import ShopifySource
from .vinted import VintedSource

_SOURCES: dict[str, Source] = {
    source.name: source
    for source in (VintedSource(), ShopifySource())
}


def get_source(name: str) -> Source:
    try:
        return _SOURCES[name]
    except KeyError:
        known = ", ".join(sorted(_SOURCES)) or "none"
        raise SourceError(f"unknown source {name!r} (known: {known})") from None


def source_names() -> list[str]:
    return sorted(_SOURCES)


__all__ = ["Source", "SourceError", "get_source", "source_names"]
