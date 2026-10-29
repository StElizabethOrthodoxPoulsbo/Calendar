import calendar
import contextlib
import io
import json
import tempfile
import unittest
from dataclasses import replace
from datetime import date
from pathlib import Path
from unittest.mock import patch
from urllib.error import URLError
from zoneinfo import ZoneInfo

from pypdf import PdfReader

from newsletter_calendar import Event, main, write_pdf
from newsletter_calendar.liturgical import fetch_liturgical_days, with_liturgical_days
from newsletter_calendar.presentation import Period, Presentation
from test_calendar import calendar_with


ZONE = ZoneInfo("America/Los_Angeles")


def month_payload(year=2026, month=6):
    """Synthetic complete month with selected documented Orthocal June examples."""
    records = [
        {
            "year": year, "month": month, "day": day,
            "fast_level": 0, "fast_level_desc": "No Fast",
            "fast_exception_desc": "", "fast_abstentions": [],
            "feast_level": 0, "feast_level_description": "Liturgy",
            "feasts": None, "summary_title": "Ordinary day",
        } for day in range(1, calendar.monthrange(year, month)[1] + 1)
    ]
    if (year, month) == (2026, 6):
        for day in range(8, 29):
            records[day - 1].update(
                fast_level=3, fast_level_desc="Apostles Fast",
                fast_abstentions=["meat", "fish", "dairy", "eggs", "wine", "oil"],
            )
        for day in (9, 11, 16, 18, 23, 25):
            records[day - 1].update(
                fast_exception_desc="Wine and Oil are Allowed",
                fast_abstentions=["meat", "fish", "dairy", "eggs"],
            )
        for day in (13, 14, 20, 21, 24, 27, 28):
            records[day - 1].update(
                fast_exception_desc="Fish, Wine and Oil are Allowed",
                fast_abstentions=["meat", "dairy", "eggs"],
            )
        for day, title in (
            (24, "Nativity of St John the Baptist"),
            (29, "Holy Apostles Peter and Paul"),
        ):
            records[day - 1].update(
                feast_level=6,
                feast_level_description="Red cross circle (great feast typikon symbol)",
                feasts=[title],
            )
        records[28]["fast_exception_desc"] = "Fish, Wine and Oil are Allowed"
        records[29].update(feast_level=4, feasts=["Synaxis of the Twelve Apostles"])
    return records


def payload_bytes(records):
    return json.dumps(records).encode()


class LiturgicalTests(unittest.TestCase):
    @patch("newsletter_calendar.fetch_public_bytes")
    def test_june_fasting_allowances_high_feasts_and_nonfast_exception(self, fetch):
        fetch.return_value = payload_bytes(month_payload())
        days = fetch_liturgical_days(date(2026, 6, 1), date(2026, 7, 1))
        fetch.assert_called_once_with(
            "https://orthocal.info/api/gregorian/2026/6/", limit=5 * 1024 * 1024,
        )
        self.assertEqual(days[date(2026, 6, 8)].fasting_label, "Apostles Fast")
        self.assertEqual(days[date(2026, 6, 9)].fasting_label,
                         "Apostles Fast\nWine & Oil")
        self.assertTrue(days[date(2026, 6, 13)].is_fast)
        self.assertEqual(days[date(2026, 6, 13)].fasting_label,
                         "Apostles Fast\nFish, Wine & Oil")
        self.assertEqual(days[date(2026, 6, 29)].fasting_label, "No Fast")
        config = with_liturgical_days(Presentation(), days)
        high = [note for note in config.notes if note.kind == "high-feast"]
        self.assertEqual([note.day.day for note in high], [24, 29])
        self.assertIn("Nativity of St John the Baptist", high[0].text)
        colors = {period.start: period.color for period in config.periods}
        self.assertEqual([day.day for day in days if colors[day] == config.fast_background],
                         list(range(8, 29)))

    @patch("newsletter_calendar.fetch_public_bytes")
    def test_adjacent_months_and_year_rollover_use_one_call_per_month(self, fetch):
        fetch.side_effect = [
            payload_bytes(month_payload(2026, 12)), payload_bytes(month_payload(2027, 1)),
            payload_bytes(month_payload(2027, 2)),
        ]
        days = fetch_liturgical_days(date(2026, 12, 27), date(2027, 2, 7))
        self.assertEqual(len(days), 42)
        self.assertEqual(fetch.call_count, 3)
        self.assertEqual(min(days), date(2026, 12, 27))
        self.assertEqual(max(days), date(2027, 2, 6))

    @patch("newsletter_calendar.fetch_public_bytes")
    def test_fast_free_exception_and_major_feast_summary(self, fetch):
        payload = month_payload()
        payload[0].update(
            fast_level=2, fast_level_desc="Lenten Fast",
            fast_exception_desc="Fast Free", fast_abstentions=[],
            feast_level=8, feast_level_description="Major feast Lord",
            summary_title="Great and Holy Pascha",
        )
        payload[1].update(
            feast_level=7, feast_level_description="Major feast Theotokos",
            feasts=["Annunciation"],
        )
        fetch.return_value = payload_bytes(payload)
        days = fetch_liturgical_days(date(2026, 6, 1), date(2026, 7, 1))
        self.assertFalse(days[date(2026, 6, 1)].is_fast)
        self.assertEqual(days[date(2026, 6, 1)].fasting_label, "No Fast")
        notes = with_liturgical_days(Presentation(), days).notes
        self.assertTrue(any("Great and Holy Pascha" in note.text for note in notes))
        self.assertTrue(any("Annunciation" in note.text for note in notes))

    @patch("newsletter_calendar.fetch_public_bytes")
    def test_incomplete_duplicate_unexpected_and_invalid_records_fail(self, fetch):
        missing = month_payload()[:-1]
        duplicate = month_payload() + [month_payload()[0]]
        wrong_month = month_payload()
        wrong_month[0]["month"] = 5
        invalid_level = month_payload()
        invalid_level[0]["fast_level"] = True
        inconsistent = month_payload()
        inconsistent[0]["fast_abstentions"] = ["meat"]
        no_abstentions = month_payload()
        del no_abstentions[0]["fast_abstentions"]
        for payload in (missing, duplicate, wrong_month, invalid_level,
                        inconsistent, no_abstentions, {}, ["invalid"]):
            with self.subTest(payload=type(payload)):
                fetch.return_value = payload_bytes(payload)
                with self.assertRaises(ValueError):
                    fetch_liturgical_days(date(2026, 6, 1), date(2026, 7, 1))

    @patch("newsletter_calendar.fetch_public_bytes")
    def test_network_and_invalid_json_fail_with_source_context(self, fetch):
        for error in (URLError("Unavailable"), ValueError("Oversized response")):
            fetch.side_effect = error
            with self.assertRaisesRegex(ValueError, "Orthocal month 2026-06"):
                fetch_liturgical_days(date(2026, 6, 1), date(2026, 7, 1))
        fetch.side_effect = None
        fetch.return_value = b"not json"
        with self.assertRaisesRegex(ValueError, "Orthocal month 2026-06"):
            fetch_liturgical_days(date(2026, 6, 1), date(2026, 7, 1))

    @patch("newsletter_calendar.fetch_public_bytes")
    def test_actual_pdf_fast_colors_high_feasts_and_google_events(self, fetch):
        fetch.return_value = payload_bytes(month_payload())
        days = fetch_liturgical_days(date(2026, 6, 1), date(2026, 7, 1))
        days[date(2026, 5, 31)] = replace(days[date(2026, 6, 1)], day=date(2026, 5, 31))
        for day in range(1, 5):
            source = days[date(2026, 6, 8)] if day in (1, 3) else days[date(2026, 6, 1)]
            days[date(2026, 7, day)] = replace(source, day=date(2026, 7, day))
        # A stale editorial purple mask must not override a sourced nonfast day.
        config = with_liturgical_days(Presentation(
            template="parish", periods=(Period(date(2026, 6, 1), date(2026, 6, 30),
                                                "#e4e4ff"),),
        ), days)
        events = [Event(date(2026, 6, 24), date(2026, 6, 25), "Parish meeting", "")]
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "calendar.pdf"
            for template in ("parish", "agenda"):
                write_pdf(events, output, date(2026, 6, 1), ZONE, "Parish",
                          replace(config, template=template))
                pdf = PdfReader(output)
                text = " ".join(" ".join(page.extract_text() for page in pdf.pages).split())
                self.assertIn("Nativity of St John the Baptist", text)
                self.assertIn("Holy Apostles Peter and Paul", text)
                self.assertIn("Parish meeting", text)
                self.assertIn("Wine & Oil", text)
                self.assertIn("orthocal.info", text)
                if template == "parish":
                    fills = []
                    color = None
                    for operands, operator in pdf.pages[0].get_contents().operations:
                        if operator == b"rg":
                            color = tuple(round(float(value), 4) for value in operands)
                        elif operator == b"re":
                            fills.append(color)
                    purple = (round(228 / 255, 4), round(228 / 255, 4), 1.0)
                    green = (round(239 / 255, 4), 1.0, round(232 / 255, 4))
                    blue = (round(228 / 255, 4), round(244 / 255, 4), 1.0)
                    self.assertEqual(fills.count(purple), 23)
                    self.assertEqual(fills[0], blue)  # May 31
                    self.assertEqual(fills[1], green)  # June 1
                    self.assertEqual(fills[29], green)  # June 29
                    self.assertEqual(fills[31], purple)  # July 1
                    self.assertEqual(fills[32], blue)  # July 2
                    self.assertEqual(fills[33], purple)  # July 3

    @patch("newsletter_calendar.urlopen")
    def test_oversized_orthocal_response_fails_before_json_parsing(self, urlopen):
        response = urlopen.return_value.__enter__.return_value
        response.url = "https://orthocal.info/api/gregorian/2026/6/"
        response.read.return_value = b"x" * (5 * 1024 * 1024 + 1)
        with self.assertRaisesRegex(ValueError, "Orthocal month 2026-06.*5 MiB"):
            fetch_liturgical_days(date(2026, 6, 1), date(2026, 7, 1))
        response.read.assert_called_once_with(5 * 1024 * 1024 + 1)

    @patch("newsletter_calendar.fetch_calendar")
    @patch("newsletter_calendar.fetch_liturgical_days")
    def test_cli_source_failure_does_not_replace_existing_pdf(self, liturgical, google):
        google.return_value = calendar_with()
        liturgical.side_effect = ValueError("Could not load Orthocal month 2026-06")
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "calendar.pdf"
            output.write_bytes(b"existing publication")
            with contextlib.redirect_stderr(io.StringIO()) as stderr:
                with self.assertRaises(SystemExit) as failure:
                    main(["--calendar-url", "https://example.org/public.ics",
                          "--config", "config/parish.toml", "--month", "2026-06",
                          "--output", str(output)])
            self.assertEqual(failure.exception.code, 1)
            self.assertIn("Orthocal", stderr.getvalue())
            self.assertEqual(output.read_bytes(), b"existing publication")


if __name__ == "__main__":
    unittest.main()
