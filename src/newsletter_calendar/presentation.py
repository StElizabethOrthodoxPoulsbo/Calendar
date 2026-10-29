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
    kind: str = "editorial"


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
    orthocal: bool = False
    fast_background: str = "#e4e4ff"
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
    if type(data.get("orthocal", False)) is not bool:
        raise ValueError("orthocal must be true or false.")
    for key in ("title", "address", "footer", "logo"):
        if key in data and not isinstance(data[key], str):
            raise ValueError(f"{key} must be a string.")
    size = data.get("font_size", 9)
    if isinstance(size, bool) or not isinstance(size, (int, float)) or not 8 <= size <= 12:
        raise ValueError("font_size must be between 8 and 12 points.")
    for key in ("navy", "background", "adjacent", "feast", "fast_background"):
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


_COMMUNITY_EVENT = re.compile(
    r"\b(?:baptis\w*|christen\w*|crownings?|weddings?|pann?[aiy]khid\w*|"
    r"memorials?|funerals?|fellowship|meals?|potlucks?|potucks?|receptions?|"
    r"picnics?|meetings?|classes?|discussions?|study|lunch|dinner|"
    r"breakfast|celebrations?)\b",
    re.IGNORECASE,
)


def is_calendar_service(event: "Event") -> bool:
    """Keep regular worship on the grid, not events merely held after it."""
    service = re.search(
        r"\b(?:liturg(?:y|ies)|vespers?|vigils?|matins|orthros|molebens?|"
        r"akathists?|compline|presanctified|midnight office)\b|"
        r"\b(?:first|third|sixth|ninth|royal|1st|3rd|6th|9th)\b.*?\bhours?\b",
        event.summary, re.IGNORECASE,
    )
    community = _COMMUNITY_EVENT.search(event.summary)
    return service is not None and (community is None or service.start() < community.start())


def is_calendar_observance(event: "Event") -> bool:
    """All-day feast/fast notices are not community overflow entries."""
    return (
        not isinstance(event.start, datetime)
        and _COMMUNITY_EVENT.search(event.summary) is None
        and re.search(
            r"\b(?:feasts?|all saints|pentecost|pascha|nativity|theophany|"
            r"annunciation|ascension|transfiguration|dormition|holy spirit|"
            r"(?:apostles|lenten|dormition|nativity)\W+fast)\b",
            event.summary, re.IGNORECASE,
        ) is not None
    )


def _is_high_feast_event(event: "Event", notes: list[Note]) -> bool:
    if isinstance(event.start, datetime):
        return False

    def normalized(text):
        return re.sub(r"\W+", " ", text.casefold()).strip().removeprefix("holy ")

    name = normalized(event.summary)
    return bool(name) and any(
        name == normalized(feast)
        for note in notes if note.kind == "high-feast"
        for feast in note.text.removeprefix("High feast: ").split("; ")
    )


@dataclass
class _GridEntry:
    paragraph: Paragraph
    height: float
    order: int
    event: "Event | None" = None


@dataclass
class _DayCell:
    day: date
    number: str
    header: _GridEntry | None
    header_width: float
    required: list[_GridEntry]
    community: list[_GridEntry]


@dataclass
class _PlacedCell:
    cell: _DayCell
    entries: list[_GridEntry]
    header: bool
    continues: bool
    appendix_count: int


def write_parish_pdf(
    events: list["Event"], output: Path, start: date, zone: ZoneInfo,
    title: str, config: Presentation,
) -> None:
    """Keep worship/annotations on calendar pages; overflow only community events."""
    from . import Event, clock, event_label, local_datetime

    width, height = landscape(letter)
    canvas = Canvas(str(output), pagesize=(width, height))
    canvas.setTitle(f"{title} - {start:%B %Y}")
    canvas.setAuthor("Newsletter Calendar")
    margin, grid_top, grid_bottom = 37, 484, 38
    cell_width = (width - 2 * margin) / 7
    weeks = month_weeks(start)
    grid_height = grid_top - grid_bottom
    marker_space = 10
    available_width = cell_width - 10
    body = ParagraphStyle(
        "Grid", fontName="Times-Roman", fontSize=config.font_size,
        leading=config.font_size,
    )
    heading = ParagraphStyle("Heading", parent=body, alignment=TA_RIGHT)
    annotation = ParagraphStyle(
        "Annotation", parent=heading, fontSize=8, leading=9,
    )
    high_feast_notes = [note for note in config.notes if note.kind == "high-feast"]
    overflow: dict[date, list[Event]] = {}

    def measure(text, style, order, event=None, wrap_width=available_width):
        item = Paragraph(text, style)
        _, h = item.wrap(wrap_width, height)
        return _GridEntry(item, h, order, event)

    def event_text(event):
        if isinstance(event.start, datetime):
            event = Event(
                local_datetime(event.start, zone), local_datetime(event.end, zone),
                event.summary, event.location,
            )
        return (
            f"<b>{escape(event.summary)}</b><br/>{escape(event_label(event))}"
            + (f"<br/>{escape(event.location)}" if event.location else "")
        )

    def compact_clock(value):
        return clock(value).replace(":00", "").replace(" ", "").lower()

    def make_cell(day):
        outside = day.month != start.month
        ink = colors.HexColor("#737d82") if outside else colors.black
        notes = [note for note in config.notes if note.day == day]
        sourced = any(note.kind == "fasting" for note in notes)
        number = f"{day:%B} 1" if day.day == 1 else str(day.day)
        header_width = cell_width - canvas.stringWidth(number, "Times-Bold", 11) - 15
        header = None
        required = []
        community = []
        for index, note in enumerate(notes):
            text = escape(note.text).replace("\n", "<br/>")
            if note.kind == "fasting" and header is None:
                candidate = measure(
                    f'<font color="{note.color}">{text}</font>',
                    annotation, index - len(notes), wrap_width=header_width,
                )
                if candidate.height <= 36:
                    header = candidate
                    continue
            if note.kind == "high-feast":
                text = f"<b>{text.removeprefix('High feast: ')}</b>"
            required.append(measure(
                f'<font color="{note.color}">{text}</font>',
                annotation, index - len(notes),
            ))
        for index, event in enumerate(events_on_day(events, day, zone)):
            # One-day feast notices without extra details are already
            # represented by the equivalent sourced high-feast heading.
            if (
                not isinstance(event.start, datetime)
                and event.end == event.start + timedelta(days=1)
                and not event.location
                and _is_high_feast_event(event, notes)
            ):
                continue
            style = body
            if isinstance(event.start, datetime):
                local = Event(
                    local_datetime(event.start, zone), local_datetime(event.end, zone),
                    event.summary, event.location,
                )
                if local.start.date() == local.end.date():
                    label = compact_clock(local.start)
                    if local.end > local.start:
                        finish = compact_clock(local.end)
                        if label[-2:] == finish[-2:]:
                            label = label[:-2]
                        label += f"-{finish}"
                else:
                    label = event_label(local).replace(" AM", "am").replace(" PM", "pm")
                    label = label.replace(":00", "").replace(" \u2013 ", "-")
                text = f"<b>{escape(label)}</b> {escape(event.summary)}"
                if event.location:
                    text += f"<br/><i>{escape(event.location)}</i>"
            else:
                color = ("#737d82" if outside else "#000000") if sourced else config.feast
                text = f'<font color="{color}">{escape(event.summary)}</font>'
                if event.location:
                    text += f"<br/><i>{escape(event.location)}</i>"
                style = heading
            entry = measure(
                text, ParagraphStyle("Cell", parent=style, textColor=ink), index, event,
            )
            target = required if (
                is_calendar_service(event) or is_calendar_observance(event)
                or _is_high_feast_event(event, high_feast_notes)
            ) else community
            target.append(entry)
        return _DayCell(day, number, header, header_width, required, community)

    def top_offset(cell, show_header=True):
        return max(19, cell.header.height + 6) if show_header and cell.header else 19

    def minimum_height(cells):
        return max(
            32,
            max(top_offset(cell) + sum(entry.height + 1 for entry in cell.required)
                + 5 + (marker_space if cell.community else 0) for cell in cells),
        )

    def place_week(cells, row_height, pending, first=True):
        placed = []
        remaining = []
        for cell, queue in zip(cells, pending):
            queue = list(queue)
            available = row_height - top_offset(cell, first) - 5
            reserved = (
                marker_space
                if cell.community or sum(e.height + 1 for e in queue) > available
                else 0
            )
            available -= reserved
            entries = []
            while queue:
                entry = queue[0]
                if entry.height + 1 <= available + 1e-6:
                    entries.append(queue.pop(0))
                    available -= entry.height + 1
                elif entry.height + 1 > grid_height - 24 - marker_space:
                    parts = entry.paragraph.split(available_width, max(0, available - 1))
                    if not parts:
                        break
                    queue[:1] = [
                        _GridEntry(part, part.wrap(available_width, height)[1],
                                   entry.order, entry.event) for part in parts
                    ]
                else:
                    break
            deferred = []
            if not queue:
                # Reclaim the marker's space when every community entry fits.
                if sum(entry.height + 1 for entry in cell.community) <= available + reserved + 1e-6:
                    available += reserved
                for entry in cell.community:
                    if entry.height + 1 <= available + 1e-6:
                        entries.append(entry)
                        available -= entry.height + 1
                    elif entry.event is not None:
                        deferred.append(entry.event)
                cell.community = []
                if deferred:
                    overflow.setdefault(cell.day, []).extend(deferred)
            placed.append(_PlacedCell(
                cell, sorted(entries, key=lambda entry: entry.order),
                first, bool(queue), len(deferred),
            ))
            remaining.append(queue)
        return placed, remaining

    pages: list[list[tuple[float, list[_PlacedCell]]]] = []
    regular_weeks = []
    regular_heights = []

    def finish_regular_page():
        if not regular_weeks:
            return
        # Water-fill row heights: grow a crowded week without shrinking any
        # week's required content below its measured size.
        heights = list(regular_heights)
        flexible = set(range(len(heights)))
        space = grid_height
        while flexible:
            share = space / len(flexible)
            fixed = {index for index in flexible if heights[index] > share}
            if not fixed:
                for index in flexible:
                    heights[index] = share
                break
            for index in fixed:
                space -= heights[index]
            flexible -= fixed
        page = []
        for cells, row_height in zip(regular_weeks, heights):
            placed, pending = place_week(cells, row_height, [cell.required for cell in cells])
            if any(pending):
                raise ValueError("Measured calendar row did not fit its required content.")
            page.append((row_height, placed))
        pages.append(page)
        regular_weeks.clear()
        regular_heights.clear()

    for week in weeks:
        cells = [make_cell(day) for day in week]
        required_height = minimum_height(cells)
        if required_height > grid_height:
            finish_regular_page()
            pending = [cell.required for cell in cells]
            first = True
            while True:
                placed, remaining = place_week(cells, grid_height, pending, first)
                pages.append([(grid_height, placed)])
                if not any(remaining):
                    break
                if not first and not any(panel.entries for panel in placed):
                    raise ValueError("Could not split required calendar content into readable pages.")
                pending = remaining
                first = False
        else:
            if sum(regular_heights) + required_height > grid_height:
                finish_regular_page()
            regular_weeks.append(cells)
            regular_heights.append(required_height)
    finish_regular_page()

    # A multi-day occurrence belongs to one surface, not the calendar on one
    # date and repeated in the appendix on another. Keep its full range once.
    deferred_ids = {id(event) for day_events in overflow.values() for event in day_events}
    for page in pages:
        for _, panels in page:
            for panel in panels:
                moved = [
                    entry for entry in panel.entries
                    if entry.event is not None and id(entry.event) in deferred_ids
                ]
                panel.entries = [entry for entry in panel.entries if entry not in moved]
                panel.appendix_count += len(moved)
    if deferred_ids:
        overflow.clear()
        for event in events:
            if id(event) not in deferred_ids:
                continue
            day = local_datetime(event.start, zone).date()
            overflow.setdefault(max(day, weeks[0][0]), []).append(event)
            deferred_ids.remove(id(event))

    def paragraph(text, style, x, top, available_width):
        item = Paragraph(text, style)
        _, h = item.wrap(available_width, height)
        item.drawOn(canvas, x, top - h)
        return h

    brand = ParagraphStyle(
        "Brand", fontName="Times-Bold", fontSize=19, leading=21,
        alignment=TA_CENTER, textColor=colors.HexColor(config.navy),
    )
    address = ParagraphStyle(
        "Address", parent=brand, fontName="Times-Roman", fontSize=10.5, leading=12,
    )
    for page_number, page in enumerate(pages, 1):
        canvas.setFillColor(colors.HexColor(config.navy))
        canvas.setFont("Times-Roman", 34)
        canvas.drawString(margin + 4, height - 76, start.strftime("%B %Y").upper())
        if config.logo:
            canvas.drawImage(
                str(config.logo), 345, height - 92, width=78, height=60,
                preserveAspectRatio=True, anchor="c", mask="auto",
            )
        brand_height = paragraph(escape(title), brand, 457, height - 43, 298)
        paragraph(escape(config.address), address, 457, height - 49 - brand_height, 298)
        canvas.setStrokeColor(colors.HexColor("#555555"))
        canvas.setLineWidth(0.45)
        canvas.line(margin, grid_top + 27, width - margin, grid_top + 27)
        canvas.setFillColor(colors.black)
        canvas.setFont("Times-Roman", 12)
        for column, name in enumerate(
            ("Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday")
        ):
            canvas.drawCentredString(
                margin + (column + 0.5) * cell_width, grid_top + 11, name,
            )
        top = grid_top
        for cell_height, panels in page:
            for column, panel in enumerate(panels):
                cell = panel.cell
                day = cell.day
                x = margin + column * cell_width
                outside = day.month != start.month
                fill = config.background
                for period in config.periods:
                    if period.start <= day <= period.end:
                        fill = period.color
                sourced = any(note.day == day and note.kind == "fasting" for note in config.notes)
                background = (
                    config.adjacent
                    if outside and not (sourced and fill == config.fast_background)
                    else fill
                )
                canvas.setFillColor(colors.HexColor(background))
                canvas.rect(x, top - cell_height, cell_width, cell_height, stroke=1, fill=1)
                ink = colors.HexColor("#737d82") if outside else colors.black
                canvas.setFillColor(ink)
                canvas.setFont("Times-Bold", 11)
                canvas.drawString(x + 5, top - 12, cell.number)
                remaining_top = top - top_offset(cell, panel.header)
                if panel.header and cell.header:
                    cell.header.paragraph.drawOn(
                        canvas, x + cell_width - cell.header_width - 5,
                        top - 3 - cell.header.height,
                    )
                for entry in panel.entries:
                    entry.paragraph.drawOn(canvas, x + 5, remaining_top - entry.height)
                    remaining_top -= entry.height + 1
                if panel.continues or panel.appendix_count:
                    canvas.setFillColor(colors.HexColor(config.navy))
                    canvas.setFont("Times-Italic", 8)
                    marker = (
                        "Calendar continues >" if panel.continues
                        else f"{panel.appendix_count} event(s) in appendix"
                    )
                    canvas.drawString(x + 5, top - cell_height + 3, marker)
            top -= cell_height
        footer = f"Calendar {page_number}/{len(pages)} | Times: {zone.key}"
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

        appendix_line(
            f"<b>{escape(title)} - {start:%B %Y}: community events not on calendar</b>", body,
        )
        for day, day_events in sorted(overflow.items()):
            if y < 150:
                canvas.showPage()
                y = 750
            appendix_line(f"<b>{day:%A, %B %d, %Y}</b>", body)
            for event in day_events:
                appendix_line(event_text(event), body)
        canvas.showPage()
    canvas.save()
