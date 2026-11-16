# jobhunt — internship dashboard

A local dashboard for a focused internship search: a scored feed of real postings, per-company
notes, application status tracking, and cover-letter drafts. Runs on the Python standard library —
no dependencies, no build step, no accounts.

> New here? Read **[BRIEF.md](BRIEF.md)** first — one page on what this is and where it's going.
> This file is the mechanics.

---

## Quick start

```bash
cp config.example.toml config.toml   # once; edit identity, letters, and targets
python3 collect.py --refresh         # download the feed, score it, populate the database
python3 server.py                    # dashboard at http://127.0.0.1:8099
```

Inspect a run without writing to the database:

```bash
python3 collect.py --dry-run    # score the cached feed, print what would change
```

Run the tests (standard library `unittest`, no network, no writes to `data/`):

```bash
python3 -m unittest discover -s tests -v
```

Requires Python 3.11+. Nothing else. No `pip install`, no virtualenv, no Node.

Generate letter drafts from the CLI:

```bash
python3 letters.py --top 5      # three variants for the five highest-scoring jobs
python3 letters.py <job-id>     # one job
```

Keep the feed fresh with cron (once a day is plenty):

```
0 8 * * * cd /path/to/internship-dashboard && /usr/bin/python3 collect.py --refresh
```

---

## Architecture

Six modules, one direction of data flow. Nothing imports upward.

```
feed URL
   │
   ▼
collect.py ──► profile.py ──► config.toml   weights, identity, prose
   │
   ▼
  db.py ──────► data/jobhunt.db  SQLite: jobs, letters, runs
   │
   ├──► server.py ──► http://127.0.0.1:8099   dashboard
   └──► letters.py ─► letters/*.md            drafts
```

| File | Role |
|---|---|
| `collect.py` | Fetch → score → upsert → log a run. The only module that touches the network. |
| `config.py` | Loads and validates `config.toml`; the error message tells you to copy the example. |
| `profile.py` | Non-personal location vocabulary plus the scoring, company, and gap settings loaded from config. |
| `db.py` | Schema, in-place migrations, connection, counts, text log, JSON snapshot. |
| `server.py` | Stdlib `http.server` app: feed, detail, log, runs. |
| `letters.py` | Three letter variants from the config's identity and verified prose. |
| `tests/` | 120 stdlib tests: scoring, locations, dedupe, lifecycle, config, migrations, HTTP routes. |

**Why no framework.** The whole app is ~1,600 lines, plus the tests. A web framework would add a dependency tree
larger than the program, and the dashboard is a form-to-table view over one SQLite file.

---

## Data model

**`jobs`** — one row per posting, keyed on the feed's listing id.

| Column | Notes |
|---|---|
| `id`, `company`, `title`, `category`, `url` | from the feed |
| `locations`, `terms`, `degrees` | JSON-encoded arrays |
| `fit`, `reasons` | score 0–100 and the itemised contributions that produced it |
| `summary` | company note — seeded from `config.toml`, editable; re-collect refreshes it until you edit it |
| `status`, `notes` | **human fields; never overwritten by a re-collect** |
| `closed_at` | set when a listing leaves the feed; kept and hidden, not deleted |
| `duplicate_of` | representative id when the same company + role is posted more than once |
| `summary_edited`, `status_changed_at`, `source` | provenance for the UI and the lifecycle |
| `first_seen`, `last_seen` | unix timestamps of the first and most recent run that saw it |

`status` ∈ `new`, `shortlisted`, `applied`, `interviewing`, `offer`, `rejected`, `archived`.

A re-collect re-scores every row it has already stored, including rows that have dropped below
`MIN_FIT`, and closes rows that are no longer active. A closed row is not deleted: it keeps its
notes and status and is reachable at `/?show=closed`. If the representative copy of a role
disappears while another copy remains, the status, notes, and edited summary move to the new
representative instead of being stranded on the closed row.

**`letters`** — `(job_id, variant)` unique, `variant` ∈ `technical`, `builder`, `consulting`.

**`runs`** — one row per collection: fetched / active / matched / inserted / updated / duplicates /
closed / duration. This is the process log, visible at `/runs` and `/log`.

---

## How scoring works

`score()` in `collect.py` sums contributions and clamps to 0–100. Every term is recorded in
`reasons`, which is shown on the job page — so a score is always explainable.

| Signal | Effect |
|---|---|
| Season matches a targeted term | +25 (Summer), +10 (Winter), +8 (Fall); **−15** if no match |
| Category: Hardware / AI-ML / Software / Quant | +20 / +18 / +15 / +12 |
| Title keyword hits | +6 to +18 each (`fpga`, `asic`, `embedded`, `simulation`, …) |
| Accepts bachelor's | +10; **−10** if it lists degrees that exclude it |
| US location | +10, **+8 more** for preferred metros/remote; **−15** if non-US; **0** if unknown |
| Posted < 7 days / < 21 days | +10 / +5 |
| Negative keyword (`phd`, `sales`, `senior`, …) | −15 to −30 |

Then: merge duplicate company + title listings, drop everything below `MIN_FIT` (70), sort
descending, and keep the top `MAX_JOBS` (400) distinct roles. Duplicates are stored with
`duplicate_of` set and hidden from the feed, so the same role does not consume two slots.

`MAX_JOBS` caps how many roles are selected on each run. A role you have already stored stays visible
while it is still active and above the threshold, even if it has slipped past rank 400; this is what
keeps shortlisted and applied rows from disappearing. `--dry-run` reports the effect before writing.

**Tune by editing `config.toml`, not the code.** Re-run `collect.py` without `--refresh` to
re-score from the cached feed in a few seconds. A cached run does not close or reopen anything,
because it cannot know what has left the feed.

### Location parsing

`classify_location()` is deliberately evidence-based and returns **us**, **foreign**, or
**unknown**. US state names and city aliases are checked as whole words and before country words,
so `New Mexico` is not Mexico, `Indianapolis, IN` is not India, and `LA`, `SF`, `Boston`, and bare
state names are recognised. State codes count only in a `City, XX` position; `Remote in UK` is
foreign, while bare `Remote` is treated as US. An unknown location scores 0 rather than −15:
missing evidence is not evidence of a foreign posting. The full matrix lives in
`tests/test_locations.py`; the whole suite has 120 tests.

---

## Dashboard

| Route | Purpose |
|---|---|
| `/` | Filterable feed: search, category, status, show, sort, min fit, page |
| `/job/<id>` | Detail: score breakdown, editable company summary, gap warnings, letters, notes, status |
| `/log` | Tail of `logs/collect.log` |
| `/runs` | Collection history table |
| `/health` | Plain `ok`, for a cron check |

The feed defaults to open, non-duplicate rows at or above `MIN_FIT`, 50 per page. `show=closed`
lists postings that left the feed, `show=duplicates` lists the collapsed repeats, and `show=all`
combines everything; `sort` is `fit`, `new`, or `company`.

Two features exist because the score alone is misleading:

- **"Why this scored N"** — the itemised `reasons` list.
- **"Defend this before you apply"** — fires on `asic`, `fpga`, `analog`, `spice`, `rf`,
  `clearance`, `phd`, `sales` and says what the posting expects that the résumé cannot show yet.

---

## Cover letters

`letters.py` composes from the **verified facts in `config.toml`** — the research numbers, the
shipped app, the teaching and advising history. It writes three variants per job so you can pick a
register rather than rewrite from scratch.

It does **not** invent the "why this company" paragraph. That line is emitted as a marked
`[HOOK — …]` placeholder, because it is the only sentence in the letter that has to come from you
and it is the one that decides whether the letter reads as real.

---

## Configuration

Personal data and preferences live in `config.toml` (gitignored). Start from `config.example.toml`:

| Section | Holds |
|---|---|
| `[scoring]` | `min_fit`, `max_jobs`, accepted degrees |
| `[scoring.seasons]` / `.categories` / `.title_keywords` / `.title_penalties` | the weights |
| `[locations].preferred` | metros that earn the +8 location bonus |
| `[identity]` | name, school, degree, year, GPA, email, phone |
| `[letters]` | the four verified paragraphs used to assemble drafts |
| `[companies."Name"]` | `aliases` and a `summary` for a target company |
| `[gaps]` | evidence-gap flags shown per job |

`profile.py` keeps only the non-personal location vocabulary (`US_STATE_NAMES`, `US_CITY_WORDS`,
`NON_US_WORDS`, state codes). `JOBHUNT_CONFIG` points at a different config; `JOBHUNT_DATA_DIR`
moves the database and snapshot. A missing or malformed config stops `collect.py`, `server.py`, and
`letters.py` with a one-line message instead of a traceback.

---

## Extending

**Add a keyword or penalty** — one line in `config.toml` under
`[scoring.title_keywords]` / `[scoring.title_penalties]`, then re-score.

**Add a company note** — a `[companies."Name"]` table with a `summary` and, if the feed uses a
different name, `aliases` (for example `["RTX"]`). Re-collect. Rows whose summary you have not
edited are refreshed; edited summaries are never overwritten.

**Add an evidence gap** — one line under `[gaps]`; the key is matched against title, category, and
the posting text when it is available.

**Add a feed** — `collect.py`'s `fetch()` returns a list of dicts; `collect()` normalises, scores,
dedupes, and applies the lifecycle. A second source needs a small adapter producing the same keys
(`id`, `company_name`, `title`, `category`, `url`, `locations`, `terms`, `degrees`, `date_posted`,
`active`, `is_visible`).

**Add a status** — extend `db.STATUSES`; the UI selects from it automatically.

**Rebuild the brief PDF** — edit `BRIEF.md`, then `python3 tools/md2pdf.py BRIEF.md`.
The converter handles the subset of Markdown these docs use and prints via headless Chromium.

---

## Troubleshooting

**Dashboard is empty** — run `collect.py`. It creates the schema on first connect.

**Feed download fails** — the raw file is cached at `data/listings_raw.json`; drop the flag to
work offline, or check the URL at the top of `collect.py`.

**Everything scores 0** — `MIN_FIT` is probably above the best achievable score for your filters.
Run `python3 collect.py --all --dry-run` to see the unfiltered distribution without writing it.

**A job I applied to disappeared** — it probably left the feed. Closed rows are kept; visit
`/?show=closed` or `/job/<id>`. Status and notes are intact, and if another copy of the same role
is still listed, they move to that copy automatically.

**The feed shows more than `MAX_JOBS`** — `MAX_JOBS` caps the roles selected per run. Previously
seen roles stay visible while they are still active and above `MIN_FIT`, so a shortlisted row does
not vanish when it slips down the ranking. Inactive rows appear only under `show=closed` or `show=all`.

**A role appears twice** — same company + title listings are merged. The representative keeps the
union of locations and the best ATS URL; the others are hidden and listed at `/?show=duplicates`.

**Letter output looks like a résumé** — the four prose blocks live in `config.toml` under
`[letters]`. Replace them with facts you can defend in an interview; `letters.py` only assembles
them and builds the signature from `[identity]`.

---

## Status

Working, used daily, single-user, one machine. 120 tests cover scoring, location parsing, dedupe,
the lifecycle, configuration, migration, and the HTTP surface; run them with `make check` or
`python3 -m unittest discover -s tests -v`. The repository is de-personalized: the only personal
data is `config.toml`, which is gitignored and checked by `tests/test_depersonalized.py`.

The lifecycle is now explicit: a fresh collect re-scores stored rows, closes rows that left the
feed, reopens rows that return, and leaves status, notes, and edited summaries alone. Known
limitations and the roadmap are in [BRIEF.md](BRIEF.md). The standing caveat remains: **the score
measures keyword overlap, not your competitiveness for the role** — which is what the gap warnings
are for.
