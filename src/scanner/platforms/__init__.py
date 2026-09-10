"""Platform registry.

Adding a site is a new module plus one line here.
"""

from __future__ import annotations

from .base import Platform, PlatformError
from .shopify import ShopifyPlatform
from .vinted import VintedPlatform

_PLATFORMS: dict[str, Platform] = {
    platform.name: platform
    for platform in (VintedPlatform(), ShopifyPlatform())
}


def get_platform(name: str) -> Platform:
    try:
        return _PLATFORMS[name]
    except KeyError:
        known = ", ".join(sorted(_PLATFORMS)) or "none"
        raise PlatformError(f"unknown platform {name!r} (known: {known})") from None


def platform_names() -> list[str]:
    return sorted(_PLATFORMS)


__all__ = ["Platform", "PlatformError", "get_platform", "platform_names"]
