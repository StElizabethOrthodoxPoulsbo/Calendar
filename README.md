# Calendar

Export the **forthcoming calendar month** from a public Google Calendar to a
printable US Letter PDF agenda for a monthly newsletter. No Google account,
API key, or service credentials are needed to run the exporter.

## Install

Requires Python 3.12 or newer.

```sh
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
python -m pip install .
```

Alternatively, with [uv](https://docs.astral.sh/uv/), run `uv sync --locked`
and prefix the commands below with `uv run`.

## Point at a public Google Calendar

1. In Google Calendar, open the calendar's **Settings and sharing**.
2. Under **Access permissions for events**, enable **Make available to public**
   and allow event details to be visible. Only publish calendars whose events
   are intended to be public.
3. Under **Integrate calendar**, copy **Public address in iCal format**.
   Use the iCal URL, not the browser/embed URL or the secret iCal address.

Run this each month, replacing the example URL with your calendar's public URL:

```sh
newsletter-calendar \
  --calendar-url 'https://calendar.google.com/calendar/ical/YOUR_CALENDAR_ID/public/basic.ics' \
  --timezone America/Los_Angeles \
  --output newsletter-calendar.pdf
```

The default period is the entire next calendar month in the display timezone
(including December-to-January rollover), not the next 30 days. The default
filename is `calendar-YYYY-MM.pdf`. Calendar events must expose their details
publicly; otherwise Google may return only busy blocks.

To avoid repeating the URL, set the `GOOGLE_CALENDAR_URL` environment variable:

```sh
export GOOGLE_CALENDAR_URL='https://calendar.google.com/calendar/ical/YOUR_CALENDAR_ID/public/basic.ics'
newsletter-calendar --title 'St. Elizabeth Orthodox Church'
```

Optional arguments:

- `--month 2026-12`: export a specific month, useful when preparing ahead.
- `--timezone America/Los_Angeles`: override the feed's timezone. Without this,
  the calendar's `X-WR-TIMEZONE` is used, or UTC if it is absent. Floating event
  times follow the feed timezone, or the selected timezone if none is declared.
- `--title 'Parish Events'`: override the heading (otherwise the calendar name).
- `--output path/to/calendar.pdf`: choose the destination; its directory must
  already exist. An existing file is replaced.

The PDF lists events chronologically with dates, local start/end times, titles,
and locations. It handles recurring events and exceptions, excludes cancelled
events, labels all-day events, and includes multi-day events that overlap the
month. All-day end dates are exclusive, as in Google Calendar. Long lists
automatically continue onto additional numbered pages; an empty month is
explicitly labelled. The PDF uses standard fonts suited to Western European
text. Event descriptions and attachments are not included.

Network, invalid calendar, and output errors exit with a nonzero status and a
message on stderr. The feed must be available via HTTPS; downloads time out
after 30 seconds and are limited to 20 MiB.

## Checks

```sh
python -m unittest discover -s tests -v
```
