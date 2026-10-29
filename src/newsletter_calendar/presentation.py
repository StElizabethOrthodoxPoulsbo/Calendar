"""Reusable parish month-grid presentation, independent of event sources."""

import calendar
import re
import tomllib
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import TYPE_CHECKING
from xml.sax.saxutils import escape
from zoneinfo import ZoneInfo

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import landscape, letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import Paragraph

if TYPE_CHECKING:
    from . import Event


@dataclass(frozen=True)
class Period:
    start: date
    end: date
    color: str


@dataclass(frozen=True)
class Note:
    day: date
    text: str
    color: str


@dataclass(frozen=True)
class Presentation:
    template: str = "agenda"
    title: str | None = None
    address: str = ""
    logo: Path | None = None
    footer: str = ""
    navy: str = "#002060"
    background: str = "#efffe8"
    adjacent: str = "#e4f4ff"
    feast: str = "#cc0000"
    font_size: float = 9
    periods: tuple[Period, ...] = field(default_factory=tuple)
    notes: tuple[Note, ...] = field(default_factory=tuple)


def _color(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", value):
        raise ValueError(f"Expected a #RRGGBB color, got {value!r}.")
    return value


def load_presentation(path: Path) -> Presentation:
    """Load strict TOML configuration; resolve asset paths beside the config."""
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    allowed = set(Presentation.__dataclass_fields__)
    unknown = set(data) - allowed
    if unknown:
        raise ValueError(f"Unknown presentation settings: {', '.join(sorted(unknown))}.")
    if data.get("template", "agenda") not in ("agenda", "parish"):
        raise ValueError("template must be 'agenda' or 'parish'.")
    for key in ("title", "address", "footer", "logo"):
        if key in data and not isinstance(data[key], str):
            raise ValueError(f"{key} must be a string.")
    size = data.get("font_size", 9)
    if isinstance(size, bool) or not isinstance(size, (int, float)) or not 8 <= size <= 12:
        raise ValueError("font_size must be between 8 and 12 points.")
    for key in ("navy", "background", "adjacent", "feast"):
        if key in data:
            _color(data[key])
    if data.get("logo"):
        data["logo"] = (path.parent / data["logo"]).resolve()
        if not data["logo"].is_file():
            raise ValueError(f"Logo does not exist: {data['logo']}")
    elif "logo" in data:
        data["logo"] = None
    periods = []
    for item in data.pop("periods", []):
        if set(item) != {"start", "end", "color"}:
            raise ValueError("Each period requires exactly start, end, color.")
        start, end = item["start"], item["end"]
        if type(start) is not date or type(end) is not date or end < start:
            raise ValueError("Period start/end must be TOML dates in ascending order.")
        periods.append(Period(start, end, _color(item["color"])))
    notes = []
    for item in data.pop("notes", []):
        if set(item) != {"day", "text", "color"}:
            raise ValueError("Each note requires exactly day, text, color.")
        if type(item["day"]) is not date or not isinstance(item["text"], str):
            raise ValueError("Notes require a TOML date and string text.")
        notes.append(Note(item["day"], item["text"], _color(item["color"])))
    return Presentation(**data, periods=tuple(periods), notes=tuple(notes))


def month_weeks(start: date) -> list[list[date]]:
    return calendar.Calendar(firstweekday=6).monthdatescalendar(start.year, start.month)


def grid_bounds(start: date) -> tuple[date, date]:
    weeks = month_weeks(start)
    return weeks[0][0], weeks[-1][-1] + timedelta(days=1)


def events_on_day(events: list["Event"], day: date, zone: ZoneInfo) -> list["Event"]:
    """Respect exclusive ends, midnight boundaries, and instantaneous events."""
    lower = datetime.combine(day, time.min, zone)
    upper = datetime.combine(day + timedelta(days=1), time.min, zone)

    def local(value):
        if not isinstance(value, datetime):
            return datetime.combine(value, time.min, zone)
        return value.replace(tzinfo=zone) if value.tzinfo is None else value.astimezone(zone)

    return [
        event for event in events
        if local(event.start) < upper
        and (local(event.end) > lower or lower <= local(event.start) == local(event.end))
    ]


def write_parish_pdf(
    events: list["Event"], output: Path, start: date, zone: ZoneInfo,
    title: str, config: Presentation,
) -> None:
    """Draw a bounded grid; preserve crowded cells in a readable appendix."""
    from . import clock

    width, height = landscape(letter)
    canvas = Canvas(str(output), pagesize=(width, height))
    canvas.setTitle(f"{title} - {start:%B %Y}")
    canvas.setAuthor("Newsletter Calendar")
    margin, grid_top, grid_bottom = 37, 470, 38
    cell_width = (width - 2 * margin) / 7
    weeks = month_weeks(start)
    cell_height = (grid_top - grid_bottom) / len(weeks)
    body = ParagraphStyle(
        "Grid", fontName="Times-Roman", fontSize=config.font_size,
        leading=config.font_size + 1,
    )
    heading = ParagraphStyle("Heading", parent=body, alignment=TA_RIGHT)
    overflow: list[tuple[date, list["Event"], list[Note]]] = []

    def paragraph(text, style, x, top, available_width):
        item = Paragraph(text, style)
        _, h = item.wrap(available_width, height)
        item.drawOn(canvas, x, top - h)
        return h

    canvas.setFillColor(colors.HexColor(config.navy))
    canvas.setFont("Times-Roman", 34)
    canvas.drawString(margin + 4, height - 76, start.strftime("%B %Y").upper())
    if config.logo:
        canvas.drawImage(
            str(config.logo), 345, height - 92, width=78, height=60,
            preserveAspectRatio=True, anchor="c", mask="auto",
        )
    brand = ParagraphStyle(
        "Brand", fontName="Times-Bold", fontSize=19, leading=21,
        alignment=TA_CENTER, textColor=colors.HexColor(config.navy),
    )
    brand_height = paragraph(escape(title), brand, 457, height - 43, 298)
    address = ParagraphStyle(
        "Address", parent=brand, fontName="Times-Roman", fontSize=10.5, leading=12,
    )
    paragraph(escape(config.address), address, 457, height - 49 - brand_height, 298)
    canvas.setStrokeColor(colors.HexColor("#555555"))
    canvas.setLineWidth(0.45)
    canvas.line(margin, 497, width - margin, 497)
    canvas.setFillColor(colors.black)
    canvas.setFont("Times-Roman", 12)
    for column, name in enumerate(
        ("Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday")
    ):
        canvas.drawCentredString(margin + (column + 0.5) * cell_width, 481, name)

    for row, week in enumerate(weeks):
        for column, day in enumerate(week):
            x = margin + column * cell_width
            top = grid_top - row * cell_height
            outside = day.month != start.month
            fill = config.background
            for period in config.periods:
                if period.start <= day <= period.end:
                    fill = period.color
            canvas.setFillColor(colors.HexColor(config.adjacent if outside else fill))
            canvas.rect(x, top - cell_height, cell_width, cell_height, stroke=1, fill=1)
            ink = colors.HexColor("#737d82") if outside else colors.black
            canvas.setFillColor(ink)
            canvas.setFont("Times-Bold", 11)
            number = f"{day:%B} 1" if day.day == 1 else str(day.day)
            canvas.drawString(x + 5, top - 12, number)
            day_events = events_on_day(events, day, zone)
            notes = [note for note in config.notes if note.day == day]
            remaining_top = top - 19
            available_width = cell_width - 10
            entries = []
            for note in notes:
                entries.append((
                    f'<font color="{note.color}">{escape(note.text)}</font>', heading
                ))
            for event in day_events:
                if isinstance(event.start, datetime):
                    local = event.start.astimezone(zone) if event.start.tzinfo else event.start
                    label = (
                        f"<b>{clock(local).replace(' ', '').lower()}</b> "
                        if local.date() == day else "<i>Continued:</i> "
                    )
                    text = label + escape(event.summary)
                    if event.location:
                        text += f"<br/><i>{escape(event.location)}</i>"
                    entries.append((text, body))
                else:
                    entries.append((
                        f'<font color="{config.feast}">{escape(event.summary)}</font>',
                        heading,
                    ))
            measured = []
            for text, style in entries:
                style = ParagraphStyle("Cell", parent=style, textColor=ink)
                item = Paragraph(text, style)
                _, h = item.wrap(available_width, height)
                measured.append((item, h))
            total = sum(h + 2 for _, h in measured)
            available = cell_height - 24
            crowded = total > available
            if crowded:
                overflow.append((day, day_events, notes))
                available -= 12
            for item, h in measured:
                if h + 2 > available:
                    break
                item.drawOn(canvas, x + 5, remaining_top - h)
                remaining_top -= h + 2
                available -= h + 2
            if crowded:
                canvas.setFillColor(colors.HexColor(config.navy))
                canvas.setFont("Times-Italic", 8)
                canvas.drawString(x + 5, top - cell_height + 5, "Full day: see appendix")

    footer = f"Times: {zone.key}"
    if not events:
        footer += " | No events scheduled in the displayed dates."
    if config.footer:
        footer += f" | {config.footer}"
    paragraph(
        escape(footer), ParagraphStyle("Footer", fontName="Times-Roman", fontSize=8,
                                       leading=9, alignment=TA_CENTER),
        margin, 29, width - 2 * margin,
    )
    canvas.showPage()
    if overflow:
        from . import event_label

        canvas.setPageSize(letter)
        y = 750

        def appendix_line(text, style):
            nonlocal y
            item = Paragraph(text, style)
            fragments = [item]
            while fragments:
                item = fragments.pop(0)
                _, h = item.wrap(538, 700)
                if h > y - 45:
                    parts = item.split(538, y - 45)
                    if parts:
                        item, *rest = parts
                        fragments = rest + fragments
                        _, h = item.wrap(538, 700)
                    else:
                        canvas.showPage()
                        y = 750
                        fragments.insert(0, item)
                        continue
                item.drawOn(canvas, 37, y - h)
                y -= h + 7

        appendix_line(f"<b>{escape(title)} - {start:%B %Y}: full days</b>", body)
        for day, day_events, notes in overflow:
            appendix_line(f"<b>{day:%A, %B %d, %Y}</b>", body)
            for note in notes:
                appendix_line(escape(note.text), body)
            for event in day_events:
                text = f"<b>{escape(event.summary)}</b><br/>{escape(event_label(event))}"
                if event.location:
                    text += f"<br/>{escape(event.location)}"
                appendix_line(text, body)
        canvas.showPage()
    canvas.save()
