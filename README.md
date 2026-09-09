# vinted-scanner

Watches Vinted (and Shopify storefronts) for things you want, and emails you when
they turn up. It runs on a GitHub Actions schedule, so there is no server to pay
for and nothing to keep running on your laptop.

A React page on GitHub Pages lets you manage watches from your phone.

## How it works

Every 15 minutes, a scheduled workflow asks each enabled watch's source what it
can see right now. It compares that against an append-only log committed to this
repository, and emails a digest of whatever is genuinely new. When nothing is
new, no email is sent, so a message in your inbox always means something
happened.

The log is the point. It records only appearances and changes, never every
sighting, which keeps it small enough to live in git and makes price history a
side effect rather than a feature to build. Two things follow from that:

- **A new listing appeared** is an `appeared` event.
- **A price dropped**, or **something came back in stock**, is a `changed` event
  carrying the before and after.

Both come out of one pipeline. Adding a rule means writing a predicate over
events, not another scanner.

```
watches.yaml ──> Source.fetch() ──> diff against log ──> events
                 (vinted,                                  │
                  shopify)                                 ├─> append to JSONL
                                                           └─> rules ──> email
```

## Setting it up

You need a Gmail address and an [app password](https://myaccount.google.com/apppasswords).
Ordinary Gmail passwords will not work over SMTP.

In **Settings → Secrets and variables → Actions**, add a repository *secret*:

| Secret | What it is |
| --- | --- |
| `GMAIL_APP_PASSWORD` | The 16-character app password |

and these repository *variables*:

| Variable | What it is |
| --- | --- |
| `GMAIL_ADDRESS` | The Gmail address that sends the mail |
| `RECIPIENT_EMAIL` | Where alerts go. Comma-separated for several. Defaults to the sender |
| `HEARTBEAT_WEEKDAY` | Day for the "still alive" email, 0 = Monday. Leave unset to disable |

Then enable GitHub Pages under **Settings → Pages**, with **GitHub Actions** as
the source, and the UI will deploy on the next push to `main`.

The scan workflow re-enables itself on every run. GitHub disables scheduled
workflows after 60 days without repository activity, and that step resets the
timer.

## Adding a watch

The quickest way is to search on Vinted until the results look right, then paste
the URL. The scanner parses it into structured fields and stores those, not the
URL, so you can adjust the maximum price later without going back to Vinted.

From the UI, paste it into **Add from a Vinted search URL**. From a terminal:

```bash
uv run python -m scanner import-url \
  "https://www.vinted.co.uk/catalog?search_text=patagonia%20fleece&price_to=60"
```

That prints a block to paste into `watches.yaml`. Editing the file by hand is
equally fine; the UI and your text editor write the same thing.

Each watch chooses what it wants to hear about:

| `notify_on` | Fires when |
| --- | --- |
| `new_listing` | The item has never been seen before |
| `price_drop` | The price fell |
| `back_in_stock` | Availability went from false to true |
| `went_on_sale` | A Shopify compare-at price appeared above the price |

## Running it locally

```bash
uv sync --extra dev
uv run python -m scanner scan --dry-run   # prints the digest, writes nothing
uv run python -m scanner list             # show configured watches
uv run pytest -q
```

`--dry-run` works against a scratch copy of the log, so you can try a new watch
without polluting the history or emailing yourself.

To query the archive, derive a SQLite database from the log:

```bash
uv run python -m scanner rebuild-db
sqlite3 data/scanner.db "SELECT title, price, at FROM price_history LIMIT 20"
```

That database is deliberately not committed. It is a cache built from the log,
so a schema change is a rebuild rather than a migration, and you can delete it
whenever you like.

## Adding a source

A source is a pure function of its query. It reports what it can currently see
and owns no state at all, which means it has no cursor and therefore cannot get
cursor handling wrong. The core does every bit of the diffing.

```python
class MySource:
    name = "mysource"

    def fetch(self, query: dict, session: requests.Session) -> list[Observation]:
        ...
```

Register it in `src/scanner/sources/__init__.py`, record a fixture under
`tests/fixtures/`, and write tests against that fixture. The suite never opens a
socket, so it cannot fail because a retailer is having a bad day.

Put anything volatile in `extra` rather than `attributes`. Only `attributes` are
diffed. Vinted photo URLs carry a rotating signature and favourite counts move
constantly, so diffing either would manufacture change events forever.

## Layout

```
src/scanner/          scan logic, sources, storage, notifiers
  sources/            one module per site, plus the shared Vinted field table
  notify/             email and console adapters
ui/                   React page deployed to GitHub Pages
data/observations/    the event log, one JSONL file per month
tests/                fixtures recorded from the real APIs
docs/SPEC.md          why it is built this way
watches.yaml          what is being watched
```

## Notes and limits

Real latency is nearer 15 to 25 minutes than 15. GitHub's scheduler runs late
under load and occasionally skips. This is a digest of what appeared recently,
not a sniping tool.

Vinted's API is undocumented and will break sooner or later. A failing watch
fails alone and the others still report, so a broken source degrades the
scanner rather than stopping it.

Dedup is on `(source, item id)`. Sellers relist constantly and a relisted item
gets a fresh id, so you will occasionally see the same garment twice. That is
the deliberate trade: better a duplicate than a listing you never hear about.

Two of the retailers worth watching are stock Shopify and serve an
unauthenticated product feed, which is why the Shopify source needs no scraping
at all. Patagonia runs Salesforce Commerce Cloud and Lululemon sits behind bot
protection, so both will need adapters of their own.

## Prior art

[Fuyucch1/Vinted-Notifications](https://github.com/Fuyucch1/Vinted-Notifications)
solves the same problem as a long-running Docker service with Telegram and RSS
output. It is worth reading, and it is where the approach to Vinted's API came
from. No code is taken from it: it is AGPL-3.0, and this project is not.
