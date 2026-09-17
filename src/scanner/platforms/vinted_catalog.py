"""Parse Vinted's server-rendered catalog page.

Vinted withdrew ``/api/v2/catalog/items`` for anonymous callers; it now answers
404 with an HTML error page while the rest of ``/api/v2`` stays alive, so this
is a deliberate removal rather than a block on us. The public catalog page is
still fully server-rendered, and every listing on it carries a stable
``data-testid`` and an accessibility label holding the title, brand, condition,
size and both prices. That label is what we read.

Anchoring on ``data-testid`` matters: the surrounding class names are hashed
per build (``ItemBox-module-scss-module__NoC3Da__``) and change whenever Vinted
deploys, whereas the test ids are part of their own test suite and move rarely.

Only the *mapping* of label keys to our field names is locale-specific. Title
and price fall out of the label's structure, so a locale we have never seen
still yields a usable listing, just without brand, size or condition.
"""

from __future__ import annotations

import html as html_module
import re
from decimal import Decimal, InvalidOperation
from typing import Any

#: One anchor per listing. The back-reference ties href, id and label together,
#: so a malformed neighbour cannot splice two listings into one.
_ANCHOR = re.compile(
    r'<a\s[^>]*?href="(?P<href>/items/(?P<id>\d+)-[^"]*)"[^>]*?'
    r'data-testid="product-item-id-(?P=id)--overlay-link"[^>]*?'
    r'title="(?P<label>[^"]*)"',
    re.S,
)
_IMAGE = re.compile(
    r'<img\s+src="(?P<src>[^"]+)"[^>]*?'
    r'data-testid="product-item-id-(?P<id>\d+)--image--img"'
)
_FAVOURITE = re.compile(
    r'aria-label="(?P<text>[^"]*)"[^>]*?'
    r'data-testid="product-item-id-(?P<id>\d+)--favourite"'
)
_FAVOURITE_COUNT = re.compile(r"(\d+)")

#: Money at the very end of the label. A currency symbol is required on one
#: side or the other, which is what stops a size like "M / UK 12-14" being read
#: as a price of 14. The digit groups allow a thousands separator, so this is
#: matched against the raw label *before* it is split on commas - splitting
#: first would tear "1,234.50" and the French "45,00" in half.
_SYMBOL = r"[£€$]|zł|Kč|lei|Ft|kr"
_TRAILING_MONEY = re.compile(
    rf"(?:(?P<pre>{_SYMBOL})\s*)?"
    r"(?P<amount>\d{1,3}(?:[.,\u00a0 ]\d{3})*(?:[.,]\d{1,2})?)"
    rf"(?:\s*(?P<post>{_SYMBOL}))?\s*$"
)

_LABELLED = re.compile(r"^(?P<key>[^:]{2,24}):\s*(?P<value>.+)$")

#: Vinted renders this when a search legitimately matches nothing. Telling that
#: apart from markup we can no longer read is the difference between a quiet
#: watch and a broken one that looks quiet.
_EMPTY_STATE = re.compile(r'data-testid="[a-z-]*empty-state', re.I)
#: The results container. Present whether or not it holds anything.
_GRID = re.compile(r"feed-grid|data-testid=\"grid-item\"")

SYMBOL_TO_CURRENCY = {
    "£": "GBP", "€": "EUR", "$": "USD",
    "zł": "PLN", "Kč": "CZK", "lei": "RON", "Ft": "HUF", "kr": "SEK",
}

#: Label keys by locale. Unknown keys are ignored rather than guessed at.
LABEL_KEYS = {
    "brand": {"brand", "marque", "marke", "merk", "marca", "märke", "marka", "znacka", "značka"},
    "condition": {"condition", "état", "etat", "zustand", "staat", "conditie", "condizione",
                  "estado", "stan", "stav", "skick"},
    "size": {"size", "taille", "größe", "grosse", "maat", "taglia", "talla", "rozmiar",
              "velikost", "storlek"},
}


def _normalise_amount(raw: str) -> str:
    """'1 234,50' and '1,234.50' both become '1234.50'.

    Always two decimal places, so a price never appears to change merely
    because it was written '24.0' one day and '24.00' the next.
    """
    cleaned = raw.replace(" ", "")
    if "," in cleaned and "." in cleaned:
        # Whichever separator comes last is the decimal point.
        cleaned = (
            cleaned.replace(",", "") if cleaned.rfind(".") > cleaned.rfind(",")
            else cleaned.replace(".", "").replace(",", ".")
        )
    elif cleaned.count(",") == 1 and len(cleaned.split(",")[1]) in (1, 2):
        cleaned = cleaned.replace(",", ".")
    else:
        cleaned = cleaned.replace(",", "")
    try:
        return f"{Decimal(cleaned):.2f}"
    except InvalidOperation:
        return cleaned


def parse_label(label: str) -> tuple[str, dict[str, str], list[tuple[str, str | None]]]:
    """Split an accessibility label into title, labelled fields and prices.

    The label looks like::

        Patagonia Retro-X fleece jacket, size M, Brand: Patagonia,
        Condition: New without tags, Size: M, 110.00 £, 116.20 £

    Order matters. Prices come off the raw end of the string first, because
    they may themselves contain commas. Only then is what remains split on
    commas - and the title is everything before the first ``Key: value``
    segment, since titles routinely contain commas too.
    """
    remainder = label.strip()
    prices: list[tuple[str, str | None]] = []
    while True:
        match = _TRAILING_MONEY.search(remainder)
        if not match:
            break
        symbol = match.group("pre") or match.group("post")
        if not symbol:
            # A bare number at the end is part of a size or title, not a price.
            break
        prices.insert(
            0, (_normalise_amount(match.group("amount")), SYMBOL_TO_CURRENCY.get(symbol))
        )
        remainder = remainder[: match.start()].rstrip().rstrip(",").rstrip()

    segments = [segment.strip() for segment in remainder.split(",")]

    fields: dict[str, str] = {}
    first_labelled: int | None = None
    for index, segment in enumerate(segments):
        match = _LABELLED.match(segment)
        if not match:
            continue
        if first_labelled is None:
            first_labelled = index
        key = match.group("key").strip().casefold()
        for name, aliases in LABEL_KEYS.items():
            if key in aliases:
                fields[name] = match.group("value").strip()
                break

    title_segments = segments[:first_labelled] if first_labelled is not None else segments
    return ", ".join(title_segments).strip(), fields, prices


def looks_empty(page: str) -> bool:
    """True when the page rendered fine and simply had no results.

    A search that matches nothing must read as "nothing new", not as a failure;
    markup we cannot read must read as a failure, not as "nothing new". Only
    the page itself can tell the two apart.
    """
    return bool(_EMPTY_STATE.search(page)) or bool(_GRID.search(page))


def parse_catalog(page: str, host: str) -> list[dict[str, Any]]:
    """Every listing on one rendered catalog page, in page order."""
    images = {match.group("id"): match.group("src") for match in _IMAGE.finditer(page)}
    favourites = {match.group("id"): match.group("text") for match in _FAVOURITE.finditer(page)}

    listings: list[dict[str, Any]] = []
    seen: set[str] = set()
    for match in _ANCHOR.finditer(page):
        item_id = match.group("id")
        if item_id in seen:
            continue
        seen.add(item_id)

        label = html_module.unescape(match.group("label"))
        title, fields, prices = parse_label(label)
        href = html_module.unescape(match.group("href")).split("?")[0]

        price, currency = prices[0] if prices else (None, None)
        # Vinted shows the item price then the price including buyer protection.
        total = prices[1][0] if len(prices) > 1 else None

        listings.append(
            {
                "id": item_id,
                "url": f"https://{host}{href}",
                "title": title or label,
                "price": price,
                "currency": currency,
                "brand": fields.get("brand"),
                "size": fields.get("size"),
                "condition": fields.get("condition"),
                "image": images.get(item_id),
                "total_price": total,
                "favourites": _favourite_count(favourites.get(item_id)),
            }
        )
    return listings


def _favourite_count(text: str | None) -> int | None:
    """'Add to favourites, favourited by 18 users' -> 18; bare label -> 0."""
    if text is None:
        return None
    match = _FAVOURITE_COUNT.search(text)
    return int(match.group(1)) if match else 0
