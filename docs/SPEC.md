# Spec: multi-source watch-and-notify scanner

> Synthesised from the `/grill-me` session. No issue tracker is configured for this
> repo, so the spec lives here rather than being published as an issue.

## Problem Statement

I want to know when something I care about appears or changes price on a shopping
site, without checking by hand. Vinted is the immediate case: good secondhand
clothing sells within hours, and by the time I remember to search, it is gone.

The same shape of problem exists on retailer sites — a specific item coming back
into stock, or a brand starting a sale — so whatever I build for Vinted should not
have to be thrown away to cover those.

I do not want to run or pay for a server.

## Solution

A Python scanner that runs on a GitHub Actions schedule. Each run asks every
enabled watch's source for what it can see right now, compares that against an
append-only history committed to this repo, and emails me a digest of what is
genuinely new. A static React UI on GitHub Pages lets me manage watches from my
phone by committing to this repo through the GitHub API.

The unit of storage is an **event log**, not a snapshot. That single decision is
what makes price-drop and back-in-stock alerting fall out later for free, rather
than requiring a rewrite.

## User Stories

1. As a bargain hunter, I want to paste a Vinted search URL and have it become a watch, so that I do not have to learn what `brand_ids[]=53` means.
2. As a bargain hunter, I want that pasted URL turned into editable fields, so that I can tweak the maximum price later without going back to Vinted.
3. As a bargain hunter, I want an email when a listing matching a watch first appears, so that I can act while it is still available.
4. As a bargain hunter, I want one email per scan containing everything new, so that a busy search does not flood my inbox.
5. As a bargain hunter, I want no email at all when nothing is new, so that a message in my inbox always means something happened.
6. As a bargain hunter, I want the email to show a thumbnail, price and size, so that I can triage from my phone without opening every link.
7. As a bargain hunter, I want each item in the email to link straight to the listing, so that buying is one tap away.
8. As a bargain hunter, I want to be told about a given listing exactly once, so that I am not re-alerted about something I already dismissed.
9. As a cautious operator, I want a weekly heartbeat email, so that silence tells me "nothing found" rather than "the scanner has been broken for a month".
10. As a cautious operator, I want the scheduled workflow to re-enable itself each run, so that GitHub's 60-day inactivity disable does not silently stop everything.
11. As a cautious operator, I want a failed email send to leave the notification pending, so that a transient SMTP error does not lose an alert.
12. As a cautious operator, I want one scan at a time, so that two runs cannot race to commit the same history file.
13. As a cautious operator, I want a scan of a broken source to fail that watch alone, so that one dead site does not stop the others reporting.
14. As a repo owner, I want history stored as line-oriented text, so that git can delta-compress it and the repo does not grow without bound.
15. As a repo owner, I want history partitioned by month, so that a single file never becomes unwieldy.
16. As a data magpie, I want every price change recorded, so that I can later ask what something actually sold for.
17. As a data magpie, I want to rebuild a queryable SQLite database from the log on demand, so that I can run real SQL without the database being a committed artefact.
18. As a data magpie, I want the database to be disposable, so that a schema change is a re-derive rather than a migration.
19. As a phone user, I want to add, edit, enable, disable and delete watches from a web page, so that I can manage them from anywhere.
20. As a phone user, I want to see recent finds in that web page, so that I can check what the scanner has been doing.
21. As a phone user, I want to paste a GitHub token once and have it remembered, so that I am not re-authenticating constantly.
22. As a security-conscious user, I want that token scoped to this one repository's contents, so that its blast radius is a repo whose contents are already public.
23. As a developer, I want sources to be pure functions of configuration, so that I can test them against recorded fixtures with no network.
24. As a developer, I want the whole scan driveable through one function, so that end-to-end tests need exactly one seam.
25. As a developer, I want CI to never touch the network, so that tests do not fail because Vinted is having a bad day.
26. As a developer, I want to add a source without editing the core, so that a new site is one new module plus a registry entry.
27. As a future me, I want to watch a specific product for a price drop, so that I can buy the thing I already know I want at the right moment.
28. As a future me, I want to watch a retailer for anything newly discounted, so that I catch a sale on its first day.
29. As a future me, I want a second notification channel without touching the scan logic, so that adding Telegram is a new adapter.

## Implementation Decisions

### Latency and hosting

Scans run on a GitHub Actions `schedule` at 15-minute intervals, accepting that
real-world latency is nearer 15–25 minutes under runner contention. This is a
"what appeared lately" digest, not a sniping tool. The repository is public, so
Actions minutes are free and the watch list is public — both accepted.

A spike confirmed Vinted's undocumented JSON API answers from a datacenter IP
with no proxy: fetch the locale homepage to pick up `access_token_web` and
`anon_id` cookies, then call `/api/v2/catalog/items`. No proxy pool is needed,
unlike the reference implementation.

The workflow re-enables itself on every run, defeating GitHub's 60-day
inactivity disable. A `concurrency` group prevents two runs racing to commit.

### The domain model

One concept, `Observation`: a sighting of an entity by a source, carrying a
stable `entity_key`, a URL, a title, a bag of **material attributes** and a bag
of **informational extras**. Material attributes are diffed between runs;
extras are recorded but never diffed.

That distinction is load-bearing. Vinted photo URLs carry a rotating `?s=`
signature and `favourite_count` moves constantly; diffing either would generate
a permanent stream of spurious change events. Image URLs and counters are extras.

Comparing a run's observations against the current state of the log yields
**events**, of which there are exactly two kinds:

- `appeared` — this `(source, entity_key)` has never been seen before.
- `changed` — it has, and at least one material attribute differs. The event
  records the before/after of each changed attribute.

"New listing", "price drop" and "back in stock" are then **rules over events**,
not separate pipelines. This is what keeps case (b) and (c) unblocked while only
case (a) ships.

### Storage

Append-only JSONL at `data/observations/YYYY-MM.jsonl`, one event per line, keys
sorted, committed to the repo. Git delta-compresses appended text well, where a
committed SQLite file would carry a near-full binary copy per commit — at ~2,900
runs a month that difference is a gigabyte-scale repo versus a megabyte-scale one.

Critically, an observation is only written when it is *new or changed*. Logging
every sighting every run would be ~9,600 lines a day; logging only changes is a
few dozen. The log is small precisely because it is a change log.

SQLite is a derived read model, built on demand by `rebuild-db` and
`.gitignore`d. It is a cache, never a source of truth.

`data/state.json` holds a `notified_through` timestamp and the last heartbeat
date. Notification advances that timestamp only after a successful send, so a
failed SMTP call re-sends next run rather than losing the alert.

### Watch definition

A watch is stored as structured fields, never as a URL. A pasted Vinted search
URL is an *import affordance*: it is parsed into those fields at import time.

The URL-parameter-to-field mapping lives in a single JSON table consumed by both
the Python parser and the TypeScript UI, so the two cannot drift.

### Module seams

Three seams, each with at least two adapters — no speculative abstraction:

- **`Source`** — `fetch(query, session) -> list[Observation]`. Deliberately
  stateless: the source always returns what it can currently see, and the core
  does all diffing and owns all durable state. A source cannot get cursor
  handling wrong because it has no cursor. Adapters: `vinted`, `shopify`.
- **`Notifier`** — `send(digest) -> None`. Adapters: `email`, `console`.
- **HTTP** — sources are handed a `requests.Session`. Tests inject a
  fixture-backed fake; CI never opens a socket.

The highest seam, and the one end-to-end tests drive, is `run_scan(...)`: config
in, events appended and a digest sent out, with store, notifier, clock and
session all injected.

### Sources

**Vinted** seeds cookies from the locale homepage, then calls
`/api/v2/catalog/items`. `entity_key` is the item id. Material attributes:
title, price, currency, brand, size, condition, seller. Extras: image URL,
favourite count, total price including buyer protection.

**Shopify** calls `/collections/{collection}/products.json`, which two of the
four retailers named (Private White V.C., Derek Rose) serve unauthenticated.
Observations are emitted **per variant**, not per product, because price and
availability live on the variant. `entity_key` is `{product_id}:{variant_id}`.
Material attributes: price, compare-at price, availability, titles.

Patagonia (Salesforce Commerce Cloud, 404s on that path) and Lululemon (403s
behind bot protection) will need their own adapters later; the seam is sized for
them but they are not built.

### Notification

One digest email per run, suppressed entirely when empty, sent via Gmail SMTP
over SSL with an app password — the same mechanism as the `nightjet-ticket-checker`
repo, including the `HEARTBEAT_WEEKDAY` liveness email. Multipart alternative:
plain text plus HTML with thumbnails.

Dedup is on `(source, entity_key)` globally, not per watch. An item matching two
watches notifies once. Relisted Vinted items get new ids and will notify again;
content fingerprinting is deliberately deferred until there is an archive to
validate it against.

### UI

Vite + React + TypeScript, built to static files and deployed to GitHub Pages.
It reads `watches.yaml` and the current month's JSONL through the GitHub
Contents API and writes `watches.yaml` back the same way, using a fine-grained
PAT held in `localStorage` and scoped to this repository's contents.

## Testing Decisions

A good test here exercises externally observable behaviour through a seam and
would survive the implementation being rewritten. Tests assert on emitted
events, digest content and log contents — never on private helpers.

- **Sources** are tested against recorded HTTP fixtures captured from the real
  APIs, through a fake session. This is the prior art the reference repo lacks
  entirely, and it is why CI needs no network.
- **The store** is tested for append/replay round-tripping, month partitioning,
  and the change-only invariant (an unchanged observation must write nothing).
- **Rules** are tested as pure functions over synthetic events.
- **`run_scan`** is tested end-to-end through its single seam: fake session, temp
  store, capturing notifier, frozen clock. These are the tests that matter most
  — first run notifies, second identical run is silent, changed price emits a
  `changed` event, a failing notifier leaves `notified_through` unmoved.
- **URL parsing** is tested against real pasted Vinted URLs.

## Out of Scope

- Multi-user support, authentication, and anything hosted.
- Sub-15-minute latency and self-hosted runners.
- Patagonia and Lululemon adapters; browser-driven scraping generally.
- Telegram, Discord, RSS. The `Notifier` seam exists; the adapters do not.
- Content-fingerprint dedup of relisted items.
- Automatic buying, watchlisting, or any authenticated action on Vinted.

## Further Notes

The reference repository (`Fuyucch1/Vinted-Notifications`) is AGPL-3.0. No code
is taken from it; it was read for its approach to Vinted's API only. Its
`pyVintedVN` module must not be vendored unless this project goes AGPL.

Vinted's API is undocumented and unstable by nature. Source adapters are
expected to break; failing one watch must never stop the others, and fixtures
should be re-recorded when a break is diagnosed.
