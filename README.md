# Calendar

Export the **forthcoming calendar month** from a public Google Calendar to a
printable US Letter PDF agenda or landscape parish month grid. No Google account,
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

## Generate the parish publication locally

Install [uv](https://docs.astral.sh/uv/) and
[Task](https://taskfile.dev/installation/), then run:

```sh
task dev
# Select a month instead of the default next month:
CALENDAR_MONTH=2026-06 task dev
```

Both commands produce `dist/calendar.pdf` using `config/parish.toml` and the
parish's public Google Calendar. `GOOGLE_CALENDAR_URL` overrides that public
source. `CALENDAR_MONTH` also works with the CLI. Invalid dates, inaccessible
feeds, or invalid configuration fail the task; there is no sample-data fallback.

The supplied Google Calendar browser link's calendar ID maps to this public feed,
which was successfully fetched during implementation:

```text
https://calendar.google.com/calendar/ical/hardin.ws_fm73fv8u5c49ki9kc9infr3jic%40group.calendar.google.com/public/basic.ics
```

This is read-only and requires no credentials. The browser link itself is not
an iCal feed. Do not pass a private or secret iCal URL to this public exporter.

## Generate and download in GitHub Actions

Once the workflow is on the default branch, open **Actions > Generate parish
calendar PDF > Run workflow**. Leave `month` empty for next month in
`America/Los_Angeles`, or enter `YYYY-MM`. `calendar_url` defaults to the same
public parish feed used locally; use only a public HTTPS iCal URL.

The workflow runs `task test` and the identical `task dev` entry point, then
uploads `dist/calendar.pdf` as **parish-calendar-pdf**, retained for 30 days.
Download it from the completed run's **Artifacts** section. No repository
secrets or Google account permissions are required. A failed fetch fails the
run rather than publishing an empty/sample replacement.

## Presentation template

The `parish` layout follows the supplied June 2026 publication: landscape Letter,
Sunday-first grid with adjacent-month dates, a navy serif masthead, central parish
ornament, pale green days, pale blue adjacent dates, red all-day headings, and
bold local start times. It calculates four, five, or six calendar rows as needed.
Multi-day events appear on every overlapping day with exclusive end dates.
Crowded cells point to a readable appendix containing their complete event
details; events are never silently dropped or shrunk below the configured size.

The original publication uses Garamond and Perpetua. The portable template uses
built-in Times fonts instead of distributing those fonts. The ornament asset is
cropped from the supplied publication; see
[`src/newsletter_calendar/assets/README.md`](src/newsletter_calendar/assets/README.md).

```sh
uv run newsletter-calendar --config config/parish.toml \
  --calendar-url "$GOOGLE_CALENDAR_URL" --month 2026-06 --output june.pdf
```

Configuration paths for `logo` resolve relative to the TOML file. Supported keys:
`template` (`agenda` or `parish`), `title`, `address`, `logo`, `footer`,
`font_size` (8–12 points), and `navy`, `background`, `adjacent`, `feast`
(`#RRGGBB`). CLI `--title` and `--template` override configuration.
Without a config/template argument the original portrait agenda remains the
default; `--template parish` also works without branding.

Optional editorial `periods` shade inclusive date ranges, with later ranges
taking precedence. `notes` add colored day headings. For example:

```toml
[[periods]]
start = 2026-06-08
end = 2026-06-28
color = "#e4e4ff"

[[notes]]
day = 2026-06-09
text = "Wine & Oil"
color = "#002060"
```

These are editorial inputs, **not automatically inferred fasting rules**.
The production config contains no June dates or events. The optional
[`examples/june-2026.toml`](examples/june-2026.toml) adds only the Apostles'
Fast shading from the reference for comparison:

```sh
GOOGLE_CALENDAR_URL='https://calendar.google.com/calendar/ical/hardin.ws_fm73fv8u5c49ki9kc9infr3jic%40group.calendar.google.com/public/basic.ics' \
  uv run newsletter-calendar --month 2026-06 \
  --config examples/june-2026.toml --output june-comparison.pdf
```

This comparison fetches real events, including adjacent grid dates, and labels
the editorial shading in its footer. The current public feed differs from the
printed June publication; choir practice, meal teams, fasting allowances, and
other publication-only annotations are not invented or copied into event data.
All-day events are colored headings regardless of whether they are feast days.
Neither template includes event descriptions or attachments.

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
- `--config config/parish.toml`: load reusable presentation settings and assets.
- `--template agenda` or `--template parish`: override the configured layout.

The default agenda lists events chronologically with dates, local start/end times, titles,
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
task test
# Or, with the development dependencies installed:
uv run --locked python -m unittest discover -s tests -v
```
