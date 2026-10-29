"""Export public iCalendar events as a monthly newsletter PDF."""

import argparse
import os
from copy import deepcopy
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from xml.sax.saxutils import escape
from zoneinfo import ZoneInfo

import recurring_ical_events
from icalendar import Calendar
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

from .presentation import Presentation, grid_bounds, load_presentation, write_parish_pdf


@dataclass(frozen=True)
class Event:
    start: date | datetime
    end: date | datetime
    summary: str
    location: str


def month_bounds(today: date) -> tuple[date, date]:
    """Return the first day of next month and its exclusive end."""
    start = (today.replace(day=28) + timedelta(days=4)).replace(day=1)
    end = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
    return start, end


def fetch_calendar(url: str) -> Calendar:
    """Download a public HTTPS iCalendar feed without credentials."""
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Use a public HTTPS iCal URL without credentials.")
    request = Request(url, headers={"User-Agent": "newsletter-calendar/0.1"})
    limit = 20 * 1024 * 1024
    with urlopen(request, timeout=30) as response:
        if urlparse(response.url).scheme != "https":
            raise ValueError("Calendar feed redirected to a non-HTTPS URL.")
        data = response.read(limit + 1)
    if len(data) > limit:
        raise ValueError("Calendar feed exceeds the 20 MiB size limit.")
    calendar = Calendar.from_ical(data)
    if calendar.name != "VCALENDAR":
        raise ValueError("The URL did not return an iCalendar calendar.")
    return calendar


def local_datetime(value: date | datetime, zone: ZoneInfo) -> datetime:
    if not isinstance(value, datetime):
        return datetime.combine(value, time.min, zone)
    if value.tzinfo is None:
        return value.replace(tzinfo=zone)
    return value.astimezone(zone)


def events_for_month(
    calendar: Calendar, start: date, end: date, zone: ZoneInfo
) -> list[Event]:
    """Expand recurrence exceptions and select events overlapping [start, end)."""
    lower = local_datetime(start, zone)
    upper = local_datetime(end, zone)
    calendar = deepcopy(calendar)
    floating_zone = ZoneInfo(str(calendar.pop("X-WR-TIMEZONE", zone.key)))

    def localize_floating(value):
        if isinstance(value, datetime) and value.tzinfo is None:
            return value.replace(tzinfo=floating_zone)
        if isinstance(value, tuple):
            return tuple(localize_floating(part) for part in value)
        return value

    # The library's X-WR-TIMEZONE conversion also rewrites UTC recurrences.
    # Localize only floating values, preserving explicit UTC and TZID semantics.
    for component in calendar.walk("VEVENT"):
        for name, value in component.property_items(recursive=False):
            if name in ("DTSTART", "DTEND", "RECURRENCE-ID", "RDATE", "EXDATE"):
                for item in getattr(value, "dts", [value]):
                    localized = localize_floating(item.dt)
                    if localized != item.dt:
                        item.dt = localized
                        item.params["TZID"] = floating_zone.key
    occurrences = recurring_ical_events.of(calendar).between(lower, upper)
    events = []
    for component in occurrences:
        if str(component.get("STATUS", "")).upper() == "CANCELLED":
            continue
        begin = component.decoded("DTSTART")
        finish = component.decoded("DTEND", begin)
        if isinstance(begin, datetime):
            begin = local_datetime(begin, zone)
            finish = local_datetime(finish, zone)
        begin_time = local_datetime(begin, zone)
        finish_time = local_datetime(finish, zone)
        if begin_time >= upper or (
            finish_time <= lower and not (begin_time == finish_time >= lower)
        ):
            continue
        events.append(
            Event(
                begin,
                finish,
                str(component.get("SUMMARY", "(Untitled event)")),
                str(component.get("LOCATION", "")),
            )
        )
    return sorted(
        events,
        key=lambda event: (
            local_datetime(event.start, zone),
            isinstance(event.start, datetime),
            event.summary.casefold(),
        ),
    )


def clock(value: datetime) -> str:
    return value.strftime("%I:%M %p").lstrip("0")


def event_label(event: Event) -> str:
    """Format all-day exclusive ends and timed multi-day events."""
    if not isinstance(event.start, datetime):
        last_day = max(event.start, event.end - timedelta(days=1))
        if last_day == event.start:
            return "All day"
        return f"All day, {event.start:%b %d} – {last_day:%b %d}"
    if event.end <= event.start:
        return clock(event.start)
    if event.start.date() == event.end.date():
        return f"{clock(event.start)} – {clock(event.end)}"
    return (
        f"{event.start:%b %d}, {clock(event.start)} – "
        f"{event.end:%b %d}, {clock(event.end)}"
    )


def write_pdf(
    events: list[Event],
    output: Path,
    start: date,
    zone: ZoneInfo,
    title: str,
    presentation: Presentation | None = None,
) -> None:
    """Write a printable US Letter agenda, automatically spanning pages."""
    if presentation and presentation.template == "parish":
        write_parish_pdf(events, output, start, zone, title, presentation)
        return
    styles = getSampleStyleSheet()
    styles["Heading2"].keepWithNext = True
    styles["BodyText"].spaceAfter = 8
    document = SimpleDocTemplate(
        str(output),
        pagesize=letter,
        rightMargin=0.65 * inch,
        leftMargin=0.65 * inch,
        topMargin=0.65 * inch,
        bottomMargin=0.65 * inch,
        title=f"{title} — {start:%B %Y}",
        author="Newsletter Calendar",
    )
    story = [
        Paragraph(escape(title), styles["Title"]),
        Paragraph(start.strftime("%B %Y"), styles["Heading1"]),
        Paragraph(f"Times shown in {escape(zone.key)}", styles["Normal"]),
        Spacer(1, 12),
    ]
    previous_day = None
    for event in events:
        day = event.start.date() if isinstance(event.start, datetime) else event.start
        # Events already underway appear under the first day of this month.
        day = max(day, start)
        if day != previous_day:
            story.append(Paragraph(day.strftime("%A, %B %d"), styles["Heading2"]))
            previous_day = day
        text = f"<b>{escape(event.summary)}</b><br/>{escape(event_label(event))}"
        if event.location:
            text += f"<br/>{escape(event.location)}"
        story.append(Paragraph(text, styles["BodyText"]))
    if not events:
        story.append(Paragraph("No events scheduled this month.", styles["BodyText"]))

    def page_footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 9)
        canvas.setFillColor(colors.grey)
        canvas.drawRightString(
            letter[0] - doc.rightMargin, 0.35 * inch, f"Page {doc.page}"
        )
        canvas.restoreState()

    document.build(story, onFirstPage=page_footer, onLaterPages=page_footer)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Export next month's public Google Calendar events to a newsletter PDF."
    )
    parser.add_argument(
        "--calendar-url",
        default=os.environ.get("GOOGLE_CALENDAR_URL"),
        help="Public iCal URL (or set GOOGLE_CALENDAR_URL).",
    )
    parser.add_argument(
        "--timezone",
        help="IANA display timezone; defaults to the calendar timezone, then UTC.",
    )
    parser.add_argument(
        "--month", default=os.environ.get("CALENDAR_MONTH") or None,
        help="Export YYYY-MM instead of next month (or set CALENDAR_MONTH).",
    )
    parser.add_argument("--output", type=Path, help="Defaults to calendar-YYYY-MM.pdf.")
    parser.add_argument("--title", help="PDF heading; defaults to the calendar name.")
    parser.add_argument("--config", type=Path, help="Presentation TOML configuration.")
    parser.add_argument("--template", choices=("agenda", "parish"), help="Override the PDF layout.")
    args = parser.parse_args(argv)
    if not args.calendar_url:
        parser.error("Provide --calendar-url or set GOOGLE_CALENDAR_URL.")
    try:
        # Validate explicit options before accessing the network.
        presentation = load_presentation(args.config) if args.config else Presentation()
        if args.template:
            from dataclasses import replace

            presentation = replace(presentation, template=args.template)
        zone = ZoneInfo(args.timezone) if args.timezone else None
        if args.month:
            selected = datetime.strptime(args.month, "%Y-%m").date()
            if selected.strftime("%Y-%m") != args.month:
                raise ValueError("--month must use YYYY-MM format.")
            start, end = selected, month_bounds(selected)[0]
        calendar = fetch_calendar(args.calendar_url)
        zone = zone or ZoneInfo(str(calendar.get("X-WR-TIMEZONE", "UTC")))
        if not args.month:
            start, end = month_bounds(datetime.now(zone).date())
        lower, upper = grid_bounds(start) if presentation.template == "parish" else (start, end)
        events = events_for_month(calendar, lower, upper, zone)
        output = args.output or Path(f"calendar-{start:%Y-%m}.pdf")
        title = args.title or presentation.title or str(calendar.get("X-WR-CALNAME", "Parish Calendar"))
        write_pdf(events, output, start, zone, title, presentation)
    except Exception as error:
        parser.exit(1, f"Could not export calendar: {error}\n")
    print(f"Wrote {output} ({len(events)} events for {start:%B %Y}"
          f"{', including adjacent grid dates' if presentation.template == 'parish' else ''}).")
    return 0
