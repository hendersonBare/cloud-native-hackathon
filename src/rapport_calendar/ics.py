"""RFC 5545 export. Pure functions: no I/O, no clock (the caller passes ``now``)."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timezone

from .models import CalendarEvent

PRODID = "-//Rapport//Calendar//EN"
_LIMIT = 75  # octets per line, excluding the CRLF


def escape_text(value: str) -> str:
    """Escape a TEXT value: backslash, semicolon, comma and newlines."""
    return (
        value.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\r\n", "\\n")
        .replace("\n", "\\n")
        .replace("\r", "\\n")
    )


def fold_line(line: str) -> str:
    """Fold at 75 octets; each continuation starts with one space. Never splits a UTF-8 character."""
    if len(line.encode("utf-8")) <= _LIMIT:
        return line
    parts: list[str] = []
    current = ""
    size = 0
    for char in line:
        width = len(char.encode("utf-8"))
        if size + width > _LIMIT:
            parts.append(current)
            current, size = " ", 1  # the continuation space counts toward the limit
        current += char
        size += width
    parts.append(current)
    return "\r\n".join(parts)


def format_utc(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def render_calendar(events: Iterable[CalendarEvent], *, now: datetime, name: str = "Rapport") -> str:
    """A VCALENDAR with one VEVENT per event. Declined events are left out; proposed ones are TENTATIVE."""
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        f"PRODID:{PRODID}",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{escape_text(name)}",
    ]
    stamp = format_utc(now)
    for ev in sorted(events, key=lambda e: (e.starts_at, e.event_id)):
        if ev.status == "declined":
            continue
        lines += [
            "BEGIN:VEVENT",
            f"UID:{ev.event_id}@rapport.dev",
            f"DTSTAMP:{stamp}",
            f"DTSTART:{format_utc(ev.starts_at)}",
            f"DTEND:{format_utc(ev.ends_at)}",
            f"SUMMARY:{escape_text(ev.title)}",
        ]
        if ev.location:
            lines.append(f"LOCATION:{escape_text(ev.location)}")
        if ev.note:
            lines.append(f"DESCRIPTION:{escape_text(ev.note)}")
        lines += [
            f"CATEGORIES:{ev.kind.upper()}",
            f"STATUS:{'TENTATIVE' if ev.status == 'proposed' else 'CONFIRMED'}",
            "END:VEVENT",
        ]
    lines.append("END:VCALENDAR")
    return "".join(fold_line(line) + "\r\n" for line in lines)
