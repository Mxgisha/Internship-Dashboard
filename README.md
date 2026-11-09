# jobhunt — internship dashboard

A local dashboard for a focused internship search: a scored feed of real postings, per-company
notes, application status tracking, and cover-letter drafts. Runs on the Python standard library —
no dependencies, no build step, no accounts.

> New here? Read **[BRIEF.md](BRIEF.md)** first — one page on what this is and where it's going.
> This file is the mechanics.

---

## Quick start

```bash
python3 collect.py --refresh    # download the feed, score it, populate the database (~30 s)
python3 server.py               # dashboard at http://127.0.0.1:8099
```

Requires Python 3.10+. Nothing else. No `pip install`, no virtualenv, no Node.

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

Five modules, one direction of data flow. Nothing imports upward.

```
feed URL
   │
   ▼
collect.py ──► profile.py        scoring rules (weights, keywords, thresholds)
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
| `profile.py` | All tuning: seasons, categories, keyword weights, penalties, thresholds, company notes, gap warnings. |
| `db.py` | Schema, connection, counts, text log, JSON snapshot. |
| `server.py` | Stdlib `http.server` app: feed, detail, log, runs. |
| `letters.py` | Three letter variants per job from hardcoded verified facts. |

**Why no framework.** The whole app is ~830 lines. A web framework would add a dependency tree
larger than the program, and the dashboard is a form-to-table view over one SQLite file.

---

## Data model

**`jobs`** — one row per posting, keyed on the feed's listing id.

| Column | Notes |
|---|---|
| `id`, `company`, `title`, `category`, `url` | from the feed |
| `locations`, `terms`, `degrees` | JSON-encoded arrays |
| `fit`, `reasons` | score 0–100 and the itemised contributions that produced it |
| `summary` | company note — seeded from `profile.py`, editable |
| `status`, `notes` | **human fields; never overwritten by a re-collect** |
| `first_seen`, `last_seen` | unix timestamps |

`status` ∈ `new`, `shortlisted`, `applied`, `interviewing`, `offer`, `rejected`, `archived`.

**`letters`** — `(job_id, variant)` unique, `variant` ∈ `technical`, `builder`, `consulting`.

**`runs`** — one row per collection: fetched / active / matched / inserted / updated / duration.
This is the process log, visible at `/runs` and `/log`.

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
| US location | +10, **+8 more** for preferred metros/remote; **−15** if non-US |
| Posted < 7 days / < 21 days | +10 / +5 |
| Negative keyword (`phd`, `sales`, `senior`, …) | −15 to −30 |

Then: drop everything below `MIN_FIT` (70), sort descending, keep the top `MAX_JOBS` (400).

**Tune by editing `profile.py`, not the code.** Re-run `collect.py` without `--refresh` to
re-score from the cached feed in under a second.

### Location parsing

`is_us()` is deliberately strict and was written after a bug: a naive two-letter-state check
classified `SF` (San Francisco) as foreign and `Toronto, ON` as domestic. It now matches state
codes only when they follow a comma, checks a `NON_US_WORDS` blocklist first, and accepts a small
set of bare city aliases. Twelve cases are covered in the module docstring's tests.

---

## Dashboard

| Route | Purpose |
|---|---|
| `/` | Filterable feed: search, category, status, min fit |
| `/job/<id>` | Detail: score breakdown, company summary, gap warnings, letters, notes, status |
| `/log` | Tail of `logs/collect.log` |
| `/runs` | Collection history table |
| `/health` | Plain `ok`, for a cron check |

Two features exist because the score alone is misleading:

- **"Why this scored N"** — the itemised `reasons` list.
- **"Defend this before you apply"** — fires on `asic`, `fpga`, `analog`, `spice`, `rf`,
  `clearance`, `phd`, `sales` and says what the posting expects that the résumé cannot show yet.

---

## Cover letters

`letters.py` composes from **verified facts only** — the research numbers, the shipped app, the
teaching and advising history. It writes three variants per job so you can pick a register rather
than rewrite from scratch.

It does **not** invent the "why this company" paragraph. That line is emitted as a marked
`[HOOK — …]` placeholder, because it is the only sentence in the letter that has to come from you
and it is the one that decides whether the letter reads as real.

---

## Configuration

Everything lives in `profile.py`:

| Constant | Meaning |
|---|---|
| `SEASONS` | targeted terms and their weights |
| `CATEGORIES` | category weights |
| `TITLE_KEYWORDS` / `TITLE_PENALTIES` | substring boosts and penalties |
| `PREFERRED_LOCATIONS` | metros that earn the location bonus |
| `MIN_FIT` / `MAX_JOBS` | how selective the feed is |
| `COMPANY_PROFILES` | hand-written company notes |
| `GAP_WARNINGS` | evidence-gap flags shown per job |

---

## Extending

**Add a keyword or penalty** — one line in `TITLE_KEYWORDS` / `TITLE_PENALTIES`, then re-score.

**Add a company note** — one entry in `COMPANY_PROFILES`, keyed on the exact `company_name` from
the feed.

**Add a feed** — `collect.py`'s `fetch()` returns a list of dicts; `main()` normalises and scores.
A second source needs a small adapter producing the same keys (`id`, `company_name`, `title`,
`category`, `url`, `locations`, `terms`, `degrees`, `date_posted`, `active`).

**Add a status** — extend `db.STATUSES`; the UI selects from it automatically.

**Rebuild the brief PDF** — edit `BRIEF.md`, then `python3 tools/md2pdf.py BRIEF.md`.
The converter handles the subset of Markdown these docs use and prints via headless Chromium.

---

## Troubleshooting

**Dashboard is empty** — run `collect.py`. It creates the schema on first connect.

**Feed download fails** — the raw file is cached at `data/listings_raw.json`; drop the flag to
work offline, or check the URL at the top of `collect.py`.

**Everything scores 0** — `MIN_FIT` is probably above the best achievable score for your filters.
Run `collect.py --all` to see the unfiltered distribution.

**Letter output looks like a résumé** — the templates live in `letters.py` (`RESEARCH`, `BUILDING`,
`COMMUNICATING`, `LIFE`); they are deliberately personal and need rewriting for anyone else.

---

## Status

Working, used daily, single-user, one machine. Known limitations and the roadmap are in
[BRIEF.md](BRIEF.md). The standing caveat: **the score measures keyword overlap, not your
competitiveness for the role** — which is what the gap warnings are for.
