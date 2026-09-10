"""Which events are worth emailing about.

Rules are pure functions over events. Because the log records *appearances* and
*attribute changes* uniformly, "new listing", "price drop" and "back in stock"
are three predicates over one stream rather than three pipelines.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable

from .models import Event

Rule = Callable[[Event], bool]


def new_listing(event: Event) -> bool:
    return event.kind == "appeared"


def price_drop(event: Event) -> bool:
    if event.kind != "changed" or "price" not in event.changes:
        return False
    before, after = event.changes["price"]
    try:
        return float(after) < float(before)
    except (TypeError, ValueError):
        return False


def back_in_stock(event: Event) -> bool:
    if event.kind != "changed" or "available" not in event.changes:
        return False
    before, after = event.changes["available"]
    return bool(after) and not bool(before)


def went_on_sale(event: Event) -> bool:
    if event.kind != "changed" or "on_sale" not in event.changes:
        return False
    before, after = event.changes["on_sale"]
    return bool(after) and not bool(before)


RULES: dict[str, Rule] = {
    "new_listing": new_listing,
    "price_drop": price_drop,
    "back_in_stock": back_in_stock,
    "went_on_sale": went_on_sale,
}


def rule_names() -> list[str]:
    return sorted(RULES)


def select(events: Iterable[Event], notify_on: Iterable[str]) -> list[Event]:
    """Events matching any of the named rules, order preserved."""
    rules = [RULES[name] for name in notify_on if name in RULES]
    if not rules:
        return []
    return [event for event in events if any(rule(event) for rule in rules)]
