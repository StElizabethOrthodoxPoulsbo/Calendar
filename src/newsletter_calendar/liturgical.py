"""Orthocal's Gregorian (New Calendar), Slavic/OCA liturgical metadata."""

import calendar
import json
from dataclasses import dataclass, replace
from datetime import date, timedelta
from urllib.error import URLError

from .presentation import Note, Period, Presentation


@dataclass(frozen=True)
class LiturgicalDay:
    day: date
    fast_level: int
    fast_description: str
    fast_exception: str
    abstentions: tuple[str, ...]
    feast_level: int
    feast_description: str
    feasts: tuple[str, ...]

    @property
    def is_fast(self) -> bool:
        # A seasonal fast can have a fast-free exception. Conversely, an
        # allowance attached to "No Fast" (e.g. June 29) is not a fast.
        return self.fast_level > 0 and bool(self.abstentions)

    @property
    def fasting_label(self) -> str:
        if not self.is_fast:
            return "No Fast"
        label = self.fast_description
        if self.fast_exception and self.fast_exception != "No overrides":
            allowance = self.fast_exception.removesuffix(" are Allowed").replace(" and ", " & ")
            label += f"\n{allowance}"
        return label


def _integer(item: dict, key: str, lower: int, upper: int) -> int:
    value = item.get(key)
    if type(value) is not int or not lower <= value <= upper:
        raise ValueError(f"Invalid Orthocal {key}: {value!r}.")
    return value


def _text(item: dict, key: str, *, empty: bool = False) -> str:
    value = item.get(key)
    if not isinstance(value, str) or (not empty and not value.strip()):
        raise ValueError(f"Invalid Orthocal {key}.")
    return value


def _texts(item: dict, key: str, *, nullable: bool = False) -> tuple[str, ...]:
    value = item.get(key)
    if nullable and value is None and key in item:
        return ()
    if not isinstance(value, list) or any(
        not isinstance(text, str) or not text.strip() for text in value
    ):
        raise ValueError(f"Invalid Orthocal {key}.")
    return tuple(value)


def fetch_liturgical_days(start: date, end: date) -> dict[date, LiturgicalDay]:
    """Fetch complete monthly responses for civil dates in [start, end).

    Month endpoints omit scripture passages and saint biographies. Fetch each
    intersecting month once, including adjacent grid dates, without per-day calls.
    """
    from . import fetch_public_bytes

    if not date(1583, 1, 1) <= start < end <= date(4100, 1, 1):
        raise ValueError("Orthocal supports dates from 1583 through 4099.")
    cursor = start.replace(day=1)
    result = {}
    while cursor < end:
        url = f"https://orthocal.info/api/gregorian/{cursor.year}/{cursor.month}/"
        try:
            payload = json.loads(fetch_public_bytes(url, limit=5 * 1024 * 1024))
        except (URLError, OSError, ValueError) as error:
            raise ValueError(f"Could not load Orthocal month {cursor:%Y-%m}: {error}") from error
        if not isinstance(payload, list):
            raise ValueError(f"Orthocal {cursor:%Y-%m} did not return a day list.")
        month_days = {}
        for item in payload:
            if not isinstance(item, dict):
                raise ValueError("Orthocal returned an invalid day record.")
            day = date(
                _integer(item, "year", 1583, 4099),
                _integer(item, "month", 1, 12),
                _integer(item, "day", 1, 31),
            )
            if day.replace(day=1) != cursor or day in month_days:
                raise ValueError(f"Orthocal returned a duplicate or unexpected date: {day}.")
            feast_level = _integer(item, "feast_level", -1, 8)
            feasts = _texts(item, "feasts", nullable=True)
            # A high-ranked commemoration may be named by summary_title rather
            # than feasts; never substitute an unrelated low-ranked saint list.
            if feast_level >= 6 and not feasts:
                feasts = (_text(item, "summary_title"),)
            info = LiturgicalDay(
                day, _integer(item, "fast_level", 0, 5),
                _text(item, "fast_level_desc"),
                _text(item, "fast_exception_desc", empty=True),
                _texts(item, "fast_abstentions"), feast_level,
                _text(item, "feast_level_description"), feasts,
            )
            if info.fast_level == 0 and info.abstentions:
                raise ValueError(f"Orthocal returned inconsistent fasting information for {day}.")
            month_days[day] = info
        expected = calendar.monthrange(cursor.year, cursor.month)[1]
        if len(month_days) != expected:
            raise ValueError(f"Orthocal {cursor:%Y-%m} is incomplete: expected {expected} dates.")
        result.update({day: info for day, info in month_days.items() if start <= day < end})
        cursor = cursor.replace(day=28) + timedelta(days=4)
        cursor = cursor.replace(day=1)
    return result


def with_liturgical_days(
    config: Presentation, days: dict[date, LiturgicalDay],
) -> Presentation:
    """Apply authoritative fasting shading after optional editorial backgrounds."""
    notes = []
    periods = []
    for day, info in sorted(days.items()):
        if info.day != day:
            raise ValueError("Liturgical metadata date does not match its day.")
        if info.feast_level >= 6:
            notes.append(Note(
                day, "High feast: " + "; ".join(info.feasts), config.feast, "high-feast",
            ))
        notes.append(Note(day, info.fasting_label, config.navy, "fasting"))
        periods.append(Period(
            day, day, config.fast_background if info.is_fast else config.background,
        ))
    attribution = (
        "Fasts & high feasts: orthocal.info (Gregorian, Slavic/OCA). "
        "Purple = fasting; red = high feast. Follow parish guidance."
    )
    return replace(
        config, notes=tuple(notes) + config.notes,
        periods=config.periods + tuple(periods),
        footer=f"{config.footer} | {attribution}" if config.footer else attribution,
    )
