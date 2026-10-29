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

Both commands produce `dist/calendar.pdf` using `config/parish.toml`, the
parish's public Google Calendar, and [Orthocal](https://orthocal.info/) fasting
and high-feast data. `GOOGLE_CALENDAR_URL` overrides the public event
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
secrets or Google account permissions are required. A failed Google Calendar
or Orthocal fetch fails the run rather than publishing an empty/sample replacement.

## Presentation template

The `parish` layout follows the supplied June 2026 publication: landscape Letter,
Sunday-first grid with adjacent-month dates, a navy serif masthead, central parish
ornament, pale green nonfasting days, **purple fasting days**, pale blue
nonfasting adjacent dates, red high-feast headings, and bold local time ranges.
Adjacent-month fasting dates stay purple, with muted dates/event text.
It calculates four, five, or six calendar rows as needed.
Multi-day events appear on every overlapping day with exclusive end dates.
High-feast and fasting annotations and regular worship services stay on the
calendar. Liturgies, vespers, vigils, hours, matins, molebens, akathists, and
compline receive space before optional community entries. Matching all-day
Google feast/fast notices also remain on the calendar, including lower-ranked
observances such as All Saints Sunday. An equivalent one-day Google high-feast
notice without additional details is represented once by the sourced heading.
A combined event such
as "Vespers with Orthodox Discussions Following" remains intact as a service;
"Fellowship after Divine Liturgy" is a community event.

Baptisms, crownings, panakhidas, and other community events appear on the
calendar when they fit. **Only unplaced community events** go to the appendix:
calendar entries and liturgical annotations are not copied there. A small
`N event(s) in appendix` marker is a pointer, not a duplicate event. Multi-day
community occurrences are either on the calendar or listed once in the
appendix with their full date range, not on both surfaces. A long optional entry
does not block a later, smaller community entry that fits.

Calendar rows expand to fit required content at the configured font size.
If necessary, the month uses additional landscape **calendar pages**, with
dated calendar continuation cells for exceptionally long services. Worship
and high-feast/fasting information never spill into the community appendix,
and content is never silently dropped. Event text retains the configured size.
Timed events retain their local start/end times and locations.

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
`font_size` (8–12 points for events), `orthocal` (boolean), and `navy`,
`background`, `adjacent`, `feast`, `fast_background` (`#RRGGBB`).
Source annotations use 8-point text to keep the grid readable.
CLI `--title` and `--template` override configuration.
Without a config/template argument the original portrait agenda remains the
default; `--template parish` also works without branding.

### Fasting days and high feasts

The parish configuration enables `orthocal = true`. Both `task dev` and Actions
fetch the documented [Orthocal monthly API](https://orthocal.info/api/docs/)
using `https://orthocal.info/api/gregorian/YEAR/MONTH/`. This is the **Gregorian
(New Calendar), Slavic/OCA** convention: the supplied publication places the
Nativity of St John the Baptist on June 24 and Apostles Peter and Paul on June 29,
matching this convention rather than the Old Calendar.

The generator fetches each intersecting month once (including adjacent grid
dates). A fasting day is determined from Orthocal's `fast_level` and
`fast_abstentions`, not from a fixed June range or whether it is Wednesday/Friday.
Fish/wine/oil allowances do not turn a fasting day into a nonfasting day.
Fast-free exceptions are nonfasting; an allowance attached to `No Fast` is not
mistaken for a fast. Every displayed date gets a fasting label, including the
season and allowance when applicable. Both remain on calendar pages; no
fasting annotations are copied to the community appendix.

High-feast names come from Orthocal's `feasts` (or its `summary_title` for a
high-ranked day without a feast list). Ranks 6–8 are shown: great feast, major
feast of the Theotokos, and major feast of the Lord, as defined in Orthocal's
[rank definitions](https://github.com/brianglass/orthocal-python/blob/main/calendarium/datetools.py).
Lower-ranked saints/commemorations are not all labeled as high feasts. Other
parish Google Calendar entries retain their own titles and times; with Orthocal
enabled, ordinary all-day parish events are not automatically colored as high feasts.

Purple (`fast_background`) and nonfasting backgrounds are driven by source
data, taking precedence over editorial `periods`. Red headings identify
high feasts. A high feast can still be a fasting day (for example June 24);
June 29 is nonfasting. Orthocal attribution and the calendar convention are
printed in the PDF, including when using the agenda layout.

Per [Orthocal's guidance](https://orthocal.info/about/), these fasting indications
are not an authoritative pastoral rule: **follow parish guidance**. No fasting
guidance is invented when a source is missing. Timeouts, malformed JSON,
incomplete months, duplicate dates, and invalid fasting data fail generation
before the output PDF is replaced. Orthocal requests time out after 30 seconds,
are limited to 5 MiB each, and require no credentials. Scripture passages,
saint biographies, and readings are not copied into the PDF.

Optional editorial `periods` shade inclusive date ranges, with later ranges
taking precedence when Orthocal is disabled. `notes` add colored parish
annotations independently of sourced liturgical data. For example:

```toml
[[periods]]
start = 2026-06-08
end = 2026-06-28
color = "#e4e4ff"

[[notes]]
day = 2026-06-09
text = "Parish picnic"
color = "#002060"
```

These are optional editorial inputs, not a substitute for Orthocal fasting data.
The production config contains no month-specific dates or events. The
[`examples/june-2026.toml`](examples/june-2026.toml) comparison configuration now
uses the same two live sources, with no reference-derived fasting mask:

```sh
GOOGLE_CALENDAR_URL='https://calendar.google.com/calendar/ical/hardin.ws_fm73fv8u5c49ki9kc9infr3jic%40group.calendar.google.com/public/basic.ics' \
  uv run newsletter-calendar --month 2026-06 \
  --config examples/june-2026.toml --output june-comparison.pdf
```

This comparison fetches real parish events and real date-specific liturgical
information, including adjacent grid dates. The current public event feed
differs from the printed June publication; choir practice, meal teams, and
other publication-only parish annotations are not invented or copied into data.
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
