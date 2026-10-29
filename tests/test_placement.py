import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from pypdf import PdfReader

from newsletter_calendar import Event, write_pdf
from newsletter_calendar.presentation import (
    Note, Presentation, is_calendar_observance, is_calendar_service,
)


ZONE = ZoneInfo("America/Los_Angeles")
MONTH = date(2026, 6, 1)


def event(summary, day=14, hour=10, location=""):
    start = datetime(2026, 6, day, hour, tzinfo=ZONE)
    return Event(start, start + timedelta(hours=1), summary, location)


def normalized(text):
    return " ".join(text.split())


def surfaces(pdf):
    calendar = []
    appendix = []
    for page in pdf.pages:
        target = calendar if float(page.mediabox.width) == 792 else appendix
        target.append(page.extract_text())
    return normalized(" ".join(calendar)), normalized(" ".join(appendix))


class PlacementTests(unittest.TestCase):
    def test_regular_services_and_community_classification(self):
        for title in (
            "Divine Liturgy", "Liturgy of the Presanctified Gifts",
            "Great Vespers", "Reader's Vespers", "Resurrectional Vigil",
            "Third and Sixth Hours", "3rd & 6th Hour", "Royal Hours",
            "Matins", "Moleben of Healing", "Akathist", "Small Compline",
            "Vespers with Orthodox Discussions Following",
            "Divine Liturgy followed by a Baptism",
        ):
            with self.subTest(title=title):
                self.assertTrue(is_calendar_service(event(title)))
        for title in (
            "Baptism", "Crowning", "Panakhida", "Panikhida", "Pannikhida",
            "Baptism after Vespers", "Fellowship after Divine Liturgy",
            "Discussion of the Divine Liturgy", "Parish Council Meeting",
            "Homeless Ministry", "Choir Practice", "Sacrament of Healing",
            "Office Hours",
        ):
            with self.subTest(title=title):
                self.assertFalse(is_calendar_service(event(title)))

    def test_all_day_feast_and_fast_notices_are_not_community_events(self):
        for title in ("All Saints Sunday", "All Saints of America Sunday",
                      "Holy Spirit Day", "Beginning of the Apostles Fast"):
            notice = Event(date(2026, 6, 14), date(2026, 6, 15), title, "")
            self.assertTrue(is_calendar_observance(notice), title)
        for title in ("All Saints Parish Picnic", "Baptism on Pentecost"):
            notice = Event(date(2026, 6, 14), date(2026, 6, 15), title, "")
            self.assertFalse(is_calendar_observance(notice), title)

    def test_mixed_crowded_day_places_each_entry_on_only_one_surface(self):
        notes = (
            Note(date(2026, 6, 14), "High feast: Test High Feast", "#cc0000", "high-feast"),
            Note(date(2026, 6, 14), "Apostles Fast\nWine & Oil", "#002060", "fasting"),
        )
        events = [
            Event(date(2026, 6, 14), date(2026, 6, 15),
                  "Baptism OverflowMarker " + "Long community detail " * 20, "Parish Hall"),
            event("Divine Liturgy WorshipMarker", hour=10),
            event("Great Vespers EveningMarker", hour=18),
            event("Crowning CrowningMarker", hour=12),
            event("Panakhida MemorialMarker", hour=13),
            event("Crowning FitsOnCalendar", day=15, hour=12),
        ]
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "calendar.pdf"
            write_pdf(events, output, MONTH, ZONE, "Parish",
                      Presentation(template="parish", notes=notes))
            pdf = PdfReader(output)
            main, appendix = surfaces(pdf)
            self.assertIn("WorshipMarker", main)
            self.assertIn("EveningMarker", main)
            self.assertIn("10-11am", main)
            self.assertIn("6-7pm", main)
            self.assertIn("Test High Feast", main)
            self.assertIn("Apostles Fast", main)
            self.assertIn("Wine & Oil", main)
            self.assertIn("FitsOnCalendar", main)
            self.assertNotIn("OverflowMarker", main)
            self.assertIn("OverflowMarker", appendix)
            self.assertIn("Sunday, June 14, 2026", appendix)
            self.assertIn("Parish Hall", appendix)
            self.assertIn("event(s) in appendix", main)
            for name in (
                "WorshipMarker", "EveningMarker", "Test High Feast", "Apostles Fast",
                "Wine & Oil", "FitsOnCalendar",
            ):
                self.assertNotIn(name, appendix)
            for name in ("OverflowMarker", "WorshipMarker", "EveningMarker",
                         "CrowningMarker", "MemorialMarker", "FitsOnCalendar"):
                self.assertEqual(main.count(name) + appendix.count(name), 1, name)

    def test_june_required_content_fits_one_calendar_page_with_community_overflow(self):
        events = []
        notes = []
        for day in (date(2026, 5, 31), *(date(2026, 6, n) for n in (7, 14, 21, 28))):
            for hour, minute, end_hour, title in (
                (9, 40, 10, "Third and Sixth Hours"),
                (10, 0, 12, "Divine Liturgy"),
                (12, 0, 14, "Fellowship Meal"),
            ):
                events.append(Event(
                    datetime(day.year, day.month, day.day, hour, minute, tzinfo=ZONE),
                    datetime(day.year, day.month, day.day, end_hour, tzinfo=ZONE),
                    title, "",
                ))
        for day in range(8, 29):
            notes.append(Note(
                date(2026, 6, day), "Apostles Fast\nFish, Wine & Oil",
                "#002060", "fasting",
            ))
        for day, title in ((7, "All Saints Sunday"), (14, "All Saints of America Sunday")):
            events.append(Event(date(2026, 6, day), date(2026, 6, day + 1), title, ""))
        for day, title in (
            (date(2026, 5, 31), "Holy Pentecost"),
            (date(2026, 6, 24), "Nativity of St John the Baptist"),
            (date(2026, 6, 29), "Holy Apostles Peter and Paul"),
        ):
            notes.append(Note(day, f"High feast: {title}", "#cc0000", "high-feast"))
            events.append(Event(day, day + timedelta(days=1), title, ""))
        events.extend([
            Event(datetime(2026, 5, 31, 13, tzinfo=ZONE),
                  datetime(2026, 5, 31, 14, tzinfo=ZONE),
                  "Vespers with Kneeling Prayers", ""),
            event("Vespers with Orthodox Discussions Following", day=24, hour=18),
            event("Great Vespers", day=28, hour=18),
            event("Divine Liturgy", day=29, hour=10),
            event("Baptism OverflowMarker", day=14, location="Details " * 50),
        ])
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "calendar.pdf"
            write_pdf(events, output, MONTH, ZONE, "Parish",
                      Presentation(template="parish", notes=tuple(notes)))
            pdf = PdfReader(output)
            self.assertEqual(sum(float(page.mediabox.width) == 792 for page in pdf.pages), 1)
            main, appendix = surfaces(pdf)
            for name in ("All Saints Sunday", "All Saints of America Sunday",
                         "Holy Pentecost", "Holy Apostles Peter and Paul"):
                self.assertEqual(main.count(name), 1, name)
                self.assertNotIn(name, appendix)
            self.assertNotIn("OverflowMarker", main)
            self.assertEqual(appendix.count("OverflowMarker"), 1)

    def test_required_content_grows_calendar_instead_of_entering_appendix(self):
        events = [event(f"Divine Liturgy Service{index:03d}") for index in range(40)]
        notes = (
            Note(date(2026, 6, 14), "High feast: Always On Calendar", "#cc0000", "high-feast"),
            Note(date(2026, 6, 14), "Apostles Fast\nWine & Oil", "#002060", "fasting"),
        )
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "calendar.pdf"
            write_pdf(events, output, MONTH, ZONE, "Parish",
                      Presentation(template="parish", notes=notes))
            pdf = PdfReader(output)
            self.assertGreater(len(pdf.pages), 1)
            self.assertTrue(all(float(page.mediabox.width) == 792 for page in pdf.pages))
            main, appendix = surfaces(pdf)
            self.assertEqual(appendix, "")
            self.assertIn("Calendar continues >", main)
            self.assertEqual(main.count("Always On Calendar"), 1)
            self.assertEqual(main.count("Wine & Oil"), 1)
            for index in range(40):
                self.assertEqual(main.count(f"Service{index:03d}"), 1)

    def test_very_long_required_entry_splits_only_across_calendar_pages(self):
        service = event("Great Vespers LongServiceMarker",
                        location="Service details " * 400 + "ENDDETAILS")
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "calendar.pdf"
            write_pdf([service], output, MONTH, ZONE, "Parish",
                      Presentation(template="parish"))
            pdf = PdfReader(output)
            main, appendix = surfaces(pdf)
            self.assertGreater(len(pdf.pages), 2)
            self.assertEqual(appendix, "")
            self.assertEqual(main.count("LongServiceMarker"), 1)
            self.assertEqual(main.split().count("Service"), 400)
            self.assertEqual(main.split().count("details"), 400)
            self.assertEqual(main.count("ENDDETAILS"), 1)

    def test_long_community_entry_does_not_block_a_smaller_entry_that_fits(self):
        events = [
            Event(date(2026, 6, 14), date(2026, 6, 15),
                  "Baptism TooLongForGrid " + "Long community detail " * 20, ""),
            event("Crowning FitsSmall", hour=9),
            event("Great Vespers", hour=18),
        ]
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "calendar.pdf"
            write_pdf(events, output, MONTH, ZONE, "Parish",
                      Presentation(template="parish"))
            main, appendix = surfaces(PdfReader(output))
            self.assertIn("FitsSmall", main)
            self.assertIn("Great Vespers", main)
            self.assertIn("9-10am", main)
            self.assertLess(main.index("FitsSmall"), main.index("Great Vespers"))
            self.assertNotIn("FitsSmall", appendix)
            self.assertNotIn("TooLongForGrid", main)
            self.assertEqual(appendix.count("TooLongForGrid"), 1)

    def test_multi_day_overflow_occurs_once_and_never_on_both_surfaces(self):
        retreat = Event(
            date(2026, 6, 1), date(2026, 6, 4),
            "Community Retreat MultiDayMarker " + "Retreat details " * 80, "Retreat Center",
        )
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "calendar.pdf"
            write_pdf([retreat], output, MONTH, ZONE, "Parish",
                      Presentation(template="parish"))
            main, appendix = surfaces(PdfReader(output))
            self.assertNotIn("MultiDayMarker", main)
            self.assertEqual(appendix.count("MultiDayMarker"), 1)
            self.assertIn("All day, Jun 01", appendix)
            self.assertIn("Jun 03", appendix)

    def test_matching_google_high_feast_stays_on_calendar_when_day_is_crowded(self):
        notes = (
            Note(date(2026, 6, 14), "High feast: Holy Apostles Peter and Paul",
                 "#cc0000", "high-feast"),
        )
        feast = Event(date(2026, 6, 14), date(2026, 6, 15), "Apostles Peter and Paul", "")
        events = [event(f"Divine Liturgy Service{index:03d}") for index in range(15)]
        events.append(feast)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "calendar.pdf"
            write_pdf(events, output, MONTH, ZONE, "Parish",
                      Presentation(template="parish", notes=notes))
            main, appendix = surfaces(PdfReader(output))
            self.assertIn("Apostles Peter and Paul", main)
            self.assertEqual(main.count("Apostles Peter and Paul"), 1)
            self.assertEqual(appendix, "")


if __name__ == "__main__":
    unittest.main()
