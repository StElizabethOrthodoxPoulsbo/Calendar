import contextlib
import io
import os
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from icalendar import Calendar

from newsletter_calendar import (
    Event,
    event_label,
    events_for_month,
    fetch_calendar,
    main,
    month_bounds,
    write_pdf,
)


ZONE = ZoneInfo("America/Los_Angeles")


class YearEndClock(datetime):
    @classmethod
    def now(cls, tz=None):
        return datetime(2026, 12, 31, 23, tzinfo=ZONE).astimezone(tz)


def calendar_with(*events, timezone="America/Los_Angeles"):
    header = "BEGIN:VCALENDAR\nVERSION:2.0\nPRODID:-//Calendar tests//EN\n"
    if timezone:
        header += f"X-WR-TIMEZONE:{timezone}\n"
    return Calendar.from_ical(
        header
        + "".join(f"BEGIN:VEVENT\n{event}\nEND:VEVENT\n" for event in events)
        + "END:VCALENDAR\n"
    )


class CalendarTests(unittest.TestCase):
    def test_next_month_and_year_rollover(self):
        self.assertEqual(
            month_bounds(date(2026, 12, 31)), (date(2027, 1, 1), date(2027, 2, 1))
        )
        self.assertEqual(
            month_bounds(date(2028, 1, 31)), (date(2028, 2, 1), date(2028, 3, 1))
        )

    def test_recurrences_exclusions_overrides_cancellations_and_dst(self):
        calendar = calendar_with(
            "UID:weekly\nDTSTART;TZID=America/Los_Angeles:20261025T090000\n"
            "DTEND;TZID=America/Los_Angeles:20261025T100000\n"
            "RRULE:FREQ=WEEKLY;COUNT=7\n"
            "EXDATE;TZID=America/Los_Angeles:20261108T090000\nSUMMARY:Liturgy",
            "UID:weekly\nRECURRENCE-ID;TZID=America/Los_Angeles:20261115T090000\n"
            "DTSTART;TZID=America/Los_Angeles:20261115T110000\n"
            "DTEND;TZID=America/Los_Angeles:20261115T120000\nSUMMARY:Moved liturgy",
            "UID:weekly\nRECURRENCE-ID;TZID=America/Los_Angeles:20261122T090000\n"
            "DTSTART;TZID=America/Los_Angeles:20261122T090000\n"
            "DTEND;TZID=America/Los_Angeles:20261122T100000\nSTATUS:CANCELLED",
            "UID:cancelled\nDTSTART:20261103T170000Z\nSTATUS:CANCELLED",
        )
        events = events_for_month(calendar, date(2026, 11, 1), date(2026, 12, 1), ZONE)
        self.assertEqual([event.start.day for event in events], [1, 15, 29])
        self.assertEqual([event.start.hour for event in events], [9, 11, 9])
        self.assertEqual(events[1].summary, "Moved liturgy")
        self.assertEqual(events[0].start.utcoffset().total_seconds(), -8 * 3600)

    def test_boundaries_all_day_multiday_and_timezone_conversion(self):
        calendar = calendar_with(
            "UID:previous\nDTSTART:20261101T063000Z\nDTEND:20261101T070000Z",
            "UID:local-first\nDTSTART:20261101T073000Z\nSUMMARY:First",
            "UID:outside\nDTSTART:20261201T080000Z",
            "UID:local-last\nDTSTART:20261201T073000Z\nSUMMARY:Last",
            "UID:overlap\nDTSTART;VALUE=DATE:20261030\n"
            "DTEND;VALUE=DATE:20261103\nSUMMARY:Retreat",
            "UID:all-day\nDTSTART;VALUE=DATE:20261101\nSUMMARY:Feast",
        )
        events = events_for_month(calendar, date(2026, 11, 1), date(2026, 12, 1), ZONE)
        self.assertEqual(
            [event.summary for event in events], ["Retreat", "Feast", "First", "Last"]
        )
        self.assertEqual(event_label(events[0]), "All day, Oct 30 – Nov 02")
        self.assertEqual(event_label(events[1]), "All day")
        self.assertEqual(events[-1].start.date(), date(2026, 11, 30))

    def test_floating_times_without_feed_timezone_use_display_zone(self):
        calendar = calendar_with(
            "UID:floating\nDTSTART:20261101T003000\nSUMMARY:Midnight", timezone=None
        )
        events = events_for_month(calendar, date(2026, 11, 1), date(2026, 12, 1), ZONE)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].start.hour, 0)
        self.assertNotIn("X-WR-TIMEZONE", calendar)

    def test_timed_multiday_label(self):
        event = Event(
            datetime(2026, 11, 2, 18, tzinfo=ZONE),
            datetime(2026, 11, 3, 9, tzinfo=ZONE),
            "Retreat",
            "",
        )
        self.assertEqual(event_label(event), "Nov 02, 6:00 PM – Nov 03, 9:00 AM")

    @patch("newsletter_calendar.urlopen")
    def test_fetch_public_feed(self, urlopen):
        response = urlopen.return_value.__enter__.return_value
        response.url = "https://calendar.google.com/public/basic.ics"
        response.read.return_value = calendar_with().to_ical()
        self.assertEqual(fetch_calendar(response.url).name, "VCALENDAR")
        self.assertEqual(urlopen.call_args.kwargs["timeout"], 30)

    @patch("newsletter_calendar.urlopen")
    def test_reject_unsafe_urls_before_download(self, urlopen):
        for url in (
            "file:///etc/passwd",
            "http://example.org/calendar.ics",
            "******example.org/calendar.ics",
        ):
            with self.subTest(url=url), self.assertRaises(ValueError):
                fetch_calendar(url)
        urlopen.assert_not_called()

    @patch("newsletter_calendar.urlopen")
    def test_reject_non_calendar_response(self, urlopen):
        response = urlopen.return_value.__enter__.return_value
        response.url = "https://example.org/calendar.ics"
        response.read.return_value = b"<html>Not a calendar</html>"
        with self.assertRaises(ValueError):
            fetch_calendar(response.url)

    def test_pdf_empty_long_and_escaped_content(self):
        start = date(2026, 11, 1)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "calendar.pdf"
            write_pdf([], output, start, ZONE, "Parish")
            self.assertTrue(output.read_bytes().startswith(b"%PDF-"))
            events = [
                Event(
                    start,
                    date(2026, 11, 2),
                    f"Event {index}: <b>literal</b> & " + "Long title " * 25,
                    "<img src='file:///not-an-image'/> & Parish Hall",
                )
                for index in range(100)
            ]
            write_pdf(events, output, start, ZONE, "Saints <Peter & Paul>")
            self.assertGreater(output.stat().st_size, 5000)
            self.assertIn(b"/Type /Pages", output.read_bytes())

    @patch.dict(os.environ, {"GOOGLE_CALENDAR_URL": "https://example.org/public.ics"})
    @patch("newsletter_calendar.fetch_calendar")
    def test_cli_with_environment_url_and_explicit_month(self, fetch):
        fetch.return_value = calendar_with(
            "UID:feast\nDTSTART;VALUE=DATE:20261121\nSUMMARY:Feast"
        )
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "newsletter.pdf"
            with contextlib.redirect_stdout(io.StringIO()) as stdout:
                status = main(["--month", "2026-11", "--output", str(output)])
            self.assertEqual(status, 0)
            self.assertTrue(output.exists())
            self.assertIn("1 events for November 2026", stdout.getvalue())
        fetch.assert_called_once_with("https://example.org/public.ics")

    @patch("newsletter_calendar.fetch_calendar")
    @patch("newsletter_calendar.write_pdf")
    @patch("newsletter_calendar.datetime", YearEndClock)
    def test_cli_defaults_to_next_month_in_display_timezone(self, write, fetch):
        fetch.return_value = calendar_with()
        with contextlib.redirect_stdout(io.StringIO()):
            main(["--calendar-url", "https://example.org/public.ics"])
        self.assertEqual(write.call_args.args[1], Path("calendar-2027-01.pdf"))
        self.assertEqual(write.call_args.args[2], date(2027, 1, 1))
        self.assertEqual(write.call_args.args[3], ZONE)

    @patch("newsletter_calendar.fetch_calendar")
    def test_invalid_options_and_network_errors_fail_cleanly(self, fetch):
        for options in (["--month", "2026-13"], ["--timezone", "Not/AZone"]):
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                main(["--calendar-url", "https://example.org/public.ics", *options])
        fetch.assert_not_called()
        fetch.side_effect = OSError("Unable to download calendar")
        with contextlib.redirect_stderr(io.StringIO()) as stderr:
            with self.assertRaises(SystemExit) as failure:
                main(["--calendar-url", "https://example.org/public.ics"])
        self.assertEqual(failure.exception.code, 1)
        self.assertIn("Unable to download calendar", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
