"""Turning events into something readable on a phone."""

from __future__ import annotations

import html
from dataclasses import dataclass, field

from .models import Event


@dataclass(frozen=True, slots=True)
class Digest:
    subject: str
    text_body: str
    html_body: str = ""
    events: tuple[Event, ...] = field(default_factory=tuple)


def _price(event: Event) -> str:
    attrs = event.observation.attributes
    amount = attrs.get("price")
    if amount is None:
        return ""
    symbol = {"GBP": "£", "EUR": "€", "USD": "$"}.get(attrs.get("currency") or "", "")
    return f"{symbol}{amount}" if symbol else str(amount)


def _detail(event: Event) -> str:
    attrs = event.observation.attributes
    parts = [p for p in (attrs.get("brand"), attrs.get("size"), attrs.get("condition")) if p]
    if attrs.get("variant") and attrs["variant"] != "Default Title":
        parts.append(str(attrs["variant"]))
    return " · ".join(parts)


def _headline(event: Event) -> str:
    if event.kind == "appeared":
        return "new"
    if "price" in event.changes:
        before, after = event.changes["price"]
        return f"price {before} → {after}"
    if "available" in event.changes:
        return "back in stock" if event.changes["available"][1] else "sold out"
    return "changed: " + ", ".join(sorted(event.changes))


def build(events: list[Event], *, watch_labels: dict[str, str] | None = None) -> Digest:
    labels = watch_labels or {}
    by_watch: dict[str, list[Event]] = {}
    for event in events:
        by_watch.setdefault(event.watch_id, []).append(event)

    count = len(events)
    noun = "find" if count == 1 else "finds"
    if len(by_watch) == 1:
        only = labels.get(next(iter(by_watch)), next(iter(by_watch)))
        subject = f"[scanner] {count} {noun} — {only}"
    else:
        subject = f"[scanner] {count} {noun} across {len(by_watch)} watches"

    text_lines: list[str] = []
    html_parts: list[str] = [
        "<div style=\"font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',"
        "Helvetica,Arial,sans-serif;max-width:640px;margin:0 auto;color:#1a1a1a\">"
    ]

    for watch_id, group in by_watch.items():
        label = labels.get(watch_id, watch_id)
        text_lines += [label, "=" * len(label), ""]
        html_parts.append(
            f'<h2 style="font-size:17px;margin:24px 0 12px;padding-bottom:6px;'
            f'border-bottom:1px solid #e5e5e5">{html.escape(label)}</h2>'
        )

        for event in group:
            observation = event.observation
            price = _price(event)
            detail = _detail(event)
            flag = _headline(event)

            text_lines.append(f"  {observation.title}")
            text_lines.append(f"    {price}  {detail}".rstrip())
            if event.kind == "changed":
                text_lines.append(f"    [{flag}]")
            text_lines.append(f"    {observation.url}")
            text_lines.append("")

            image = observation.extra.get("image")
            thumb = (
                f'<td width="76" valign="top" style="padding-right:12px">'
                f'<img src="{html.escape(str(image))}" width="64" height="64" '
                f'alt="" style="border-radius:6px;object-fit:cover;display:block"></td>'
                if image
                else ""
            )
            badge = (
                ""
                if event.kind == "appeared"
                else f'<span style="font-size:11px;background:#fff3cd;color:#7a5c00;'
                f'padding:2px 6px;border-radius:3px;margin-left:6px">{html.escape(flag)}</span>'
            )
            html_parts.append(
                f'<table cellpadding="0" cellspacing="0" style="margin-bottom:14px;width:100%">'
                f"<tr>{thumb}<td valign=\"top\">"
                f'<a href="{html.escape(observation.url)}" '
                f'style="font-size:15px;font-weight:600;color:#0b5cff;text-decoration:none">'
                f"{html.escape(observation.title)}</a>{badge}"
                f'<div style="font-size:14px;font-weight:600;margin-top:3px">'
                f"{html.escape(price)}</div>"
                f'<div style="font-size:13px;color:#666;margin-top:2px">'
                f"{html.escape(detail)}</div>"
                f"</td></tr></table>"
            )

    html_parts.append(
        '<p style="font-size:12px;color:#999;margin-top:28px;border-top:1px solid #eee;'
        'padding-top:10px">Sent by vinted-scanner.</p></div>'
    )

    return Digest(
        subject=subject,
        text_body="\n".join(text_lines).rstrip() + "\n",
        html_body="".join(html_parts),
        events=tuple(events),
    )


def heartbeat(*, watches: int, log_size: int) -> Digest:
    text = (
        "vinted-scanner is alive.\n\n"
        f"  active watches: {watches}\n"
        f"  events on record: {log_size}\n\n"
        "Nothing needs your attention. This message means the schedule is running.\n"
    )
    return Digest(
        subject="[scanner] weekly heartbeat",
        text_body=text,
        html_body=f"<pre style=\"font-family:ui-monospace,monospace\">{html.escape(text)}</pre>",
    )
