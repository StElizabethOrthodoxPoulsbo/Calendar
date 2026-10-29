import contextlib
import io
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from pypdf import PdfReader

from newsletter_calendar import Event, main, write_pdf
from newsletter_calendar.presentation import (
    Presentation, events_on_day, grid_bounds, load_presentation, month_weeks,
)
from test_calendar import calendar_with


ZONE = ZoneInfo("America/Los_Angeles")


class PresentationTests(unittest.TestCase):
    def test_sunday_first_four_five_six_week_and_year_boundaries(self):
        for month, rows in ((date(2026, 2, 1), 4), (date(2026, 6, 1), 5),
                            (date(2026, 8, 1), 6)):
            with self.subTest(month=month):
                weeks = month_weeks(month)
                self.assertEqual(len(weeks), rows)
                self.assertTrue(all(week[0].weekday() == 6 for week in weeks))
                self.assertEqual(grid_bounds(month)[1], weeks[-1][-1] + timedelta(days=1))
        self.assertEqual(grid_bounds(date(2027, 1, 1))[0], date(2026, 12, 27))

    def test_multiday_exclusive_ends_and_instants(self):
        events = [
            Event(date(2026, 5, 31), date(2026, 6, 3), "Retreat", ""),
            Event(datetime(2026, 6, 1, 23, tzinfo=ZONE),
                  datetime(2026, 6, 2, 0, tzinfo=ZONE), "Midnight end", ""),
            Event(datetime(2026, 6, 2, 9, tzinfo=ZONE),
                  datetime(2026, 6, 2, 9, tzinfo=ZONE), "Instant", ""),
        ]
        self.assertEqual([e.summary for e in events_on_day(events, date(2026, 6, 2), ZONE)],
                         ["Retreat", "Instant"])
        self.assertEqual(events_on_day(events, date(2026, 6, 3), ZONE), [])

    def test_config_assets_and_invalid_settings(self):
        config = load_presentation(Path("config/parish.toml"))
        self.assertTrue(config.logo.is_file())
        self.assertEqual(config.template, "parish")
        reference = load_presentation(Path("examples/june-2026.toml"))
        self.assertTrue(reference.orthocal)
        self.assertEqual(reference.periods, ())
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.toml"
            for content in (
                'template = "unknown"', 'background = "red"', 'font_size = 3',
                'logo = "missing.png"', 'unknown = true', 'title = 3',
                'orthocal = "yes"', 'fast_background = "purple"',
                '[[periods]]\nstart = 2026-06-08\nend = 2026-06-01\ncolor = "#000000"',
                '[[notes]]\nday = "2026-06-01"\ntext = "No fast"\ncolor = "#000000"',
            ):
                with self.subTest(content=content):
                    path.write_text(content)
                    with self.assertRaises(ValueError):
                        load_presentation(path)

    def test_pdf_dimensions_empty_month_and_six_week_month(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "calendar.pdf"
            for month in (date(2026, 2, 1), date(2026, 6, 1), date(2026, 8, 1)):
                write_pdf([], output, month, ZONE, "Saints <Peter & Paul>",
                          Presentation(template="parish"))
                pdf = PdfReader(output)
                self.assertEqual(len(pdf.pages), 1)
                self.assertEqual(tuple(pdf.pages[0].mediabox), (0, 0, 792, 612))
                text = pdf.pages[0].extract_text()
                self.assertIn("No events scheduled", text)
                self.assertIn("Saints <Peter & Paul>", text)
                self.assertIn(month.strftime("%B %Y").upper(), text)

    def test_crowded_cells_preserve_every_event_in_appendix(self):
        events = [
            Event(date(2026, 6, 1), date(2026, 6, 2),
                  f"Unique event {i:03d} <literal> & " + "Long title " * 20,
                  "Parish <Hall>") for i in range(35)
        ]
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "calendar.pdf"
            write_pdf(events, output, date(2026, 6, 1), ZONE, "Parish",
                      Presentation(template="parish"))
            pdf = PdfReader(output)
            self.assertGreater(len(pdf.pages), 2)
            self.assertIn("Full day: see appendix", pdf.pages[0].extract_text())
            text = "\n".join(page.extract_text() for page in pdf.pages[1:])
            for i in range(35):
                self.assertIn(f"Unique event {i:03d} <literal> &", text)
            self.assertIn("Parish <Hall>", text)

    def test_editorial_notes_and_very_long_events_are_not_lost(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "notes.toml"
            config.write_text(
                'template = "parish"\n[[notes]]\nday = 2026-06-01\n'
                'text = "Wine & <Oil>"\ncolor = "#002060"\n'
            )
            output = Path(directory) / "calendar.pdf"
            event = Event(date(2026, 6, 1), date(2026, 6, 2),
                          "Long event " * 2000 + "END OF EVENT", "")
            write_pdf([event], output, date(2026, 6, 1), ZONE, "Parish",
                      load_presentation(config))
            pdf = PdfReader(output)
            self.assertGreater(len(pdf.pages), 2)
            text = "\n".join(page.extract_text() for page in pdf.pages[1:])
            self.assertIn("Wine & <Oil>", text)
            self.assertIn("END OF EVENT", text)

    @patch("newsletter_calendar.fetch_calendar")
    @patch("newsletter_calendar.fetch_liturgical_days", return_value={})
    def test_cli_loads_config_and_fetches_adjacent_grid_events(self, liturgical, fetch):
        fetch.return_value = calendar_with(
            "UID:previous\nDTSTART;VALUE=DATE:20260531\nSUMMARY:Previous month",
            "UID:next\nDTSTART;VALUE=DATE:20260704\nSUMMARY:Next month",
        )
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "calendar.pdf"
            with contextlib.redirect_stdout(io.StringIO()):
                main(["--calendar-url", "https://example.org/public.ics",
                      "--month", "2026-06", "--config", "config/parish.toml",
                      "--output", str(output)])
            text = PdfReader(output).pages[0].extract_text()
            self.assertIn("Previous month", text)
            self.assertIn("Next month", text)
            self.assertIn("St. Elizabeth Orthodox Church", text)
            liturgical.assert_called_once_with(date(2026, 5, 31), date(2026, 7, 5))

    @patch("newsletter_calendar.fetch_calendar")
    def test_invalid_config_fails_before_network(self, fetch):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            main(["--calendar-url", "https://example.org/public.ics",
                  "--config", "missing.toml"])
        fetch.assert_not_called()

    @patch("newsletter_calendar.fetch_calendar")
    @patch("newsletter_calendar.fetch_liturgical_days", return_value={})
    def test_agenda_override_and_environment_month(self, liturgical, fetch):
        fetch.return_value = calendar_with()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "calendar.pdf"
            with patch.dict("os.environ", {"CALENDAR_MONTH": "2026-06"}):
                with contextlib.redirect_stdout(io.StringIO()):
                    main(["--calendar-url", "https://example.org/public.ics",
                          "--config", "config/parish.toml", "--template", "agenda",
                          "--output", str(output)])
            pdf = PdfReader(output)
            self.assertEqual(tuple(pdf.pages[0].mediabox), (0, 0, 612, 792))
            self.assertIn("June 2026", pdf.pages[0].extract_text())
            liturgical.assert_called_once_with(date(2026, 6, 1), date(2026, 7, 1))


if __name__ == "__main__":
    unittest.main()
