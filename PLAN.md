# Implementation Plan — jobhunt / internship dashboard

Reviewed **2026-11-09** against commit `699b2ef` (initial commit). The database in `data/jobhunt.db`
is from the single collection run of **2026-11-02**, seven days before this review. A fresh copy of
the upstream feed was downloaded for comparison (17,427 records, 13.1 MB).

This plan keeps the brief's constraints — standard library only, one SQLite file, one process, no
scraping, no auto-apply — and keeps its direction. It inserts **one phase before the brief's P0**,
because the review found that the shortlist already on screen is materially out of date. Fixing
that is cheaper and more valuable than making the tool portable.

> **Status 2026-11-10:** Phases 0 and 1 are implemented. The database was migrated in place, a
> fresh collection closed stale rows and added new ones, and 120 tests pass. Phase 0 added the
> lifecycle, filters, and `--dry-run`; Phase 1 moved weights, identity, letters, company notes,
> and gaps into `config.toml` (gitignored) with a tracked `config.example.toml`, and raised the
> floor to Python 3.11. See [README.md](README.md). Phase 2 (posting text) is next.

---

## 1. Baseline — what actually works

Everything runs on Python 3.14.7 with no installed dependencies.

| Check | Result |
|---|---|
| `python3 -m py_compile collect.py profile.py db.py server.py letters.py tools/md2pdf.py` | clean |
| `curl http://127.0.0.1:8099/{,/runs,/log,/health}` | 200, 200, 200, `ok` |
| `/job/<id>` | 200, score breakdown renders |
| `/job/does-not-exist` | **200** with "No such job" (should be 404) |
| Upstream feed | live, `HTTP 200`, 13,082,571 bytes, 0.64 s |
| Database | 400 jobs, 6 letters, 1 run; 399 `new`, 1 `shortlisted` |
| Feed page | 154 KB for 300 rows, no pagination |
| Code size | 930 lines across the five modules (README says ~830) |
| Tests | **none** |

Reproduce the baseline:

```bash
python3 -m py_compile *.py tools/*.py
python3 server.py &                    # then curl the routes
python3 - <<'PY'                       # counts
import sqlite3; c=sqlite3.connect('data/jobhunt.db')
print(c.execute('select count(*) from jobs').fetchone())
PY
```

The architecture is sound: `collect → db ← server`, no upward imports, parameterised SQL, HTML
escaping on output, loopback-only bind. The score breakdown and the `[HOOK — …]` placeholder in
letters are the two best decisions in the repo and should survive every phase below.

---

## 2. What the feed comparison measured

Active listings today: **5,277**. Listings that would clear `MIN_FIT = 70` today: **594**. The DB
holds the top **400** from seven days ago.

| Measurement | Value |
|---|---|
| Stored `fit` values that differ from a re-score at today's clock | **148 / 400** |
| Stored rows that would now fall below `MIN_FIT = 70` but remain in the DB | **21** |
| Stored rows no longer `active` in today's feed | **58 / 400** |
| Today's top-400 postings that are **not in the DB** | **112** |
| Duplicate rows in today's top 400 (same company + title) | **43** |
| Jobs affected by the location bug (prototype reclassification) | **133 active** |
| Location mentions a word-boundary prototype reclassifies as US | **447** |
| Jobs with an auto-generated stub company summary | **390 / 400** |
| Curated `COMPANY_PROFILES` keys that match a company in the DB | **4 / 14** |

The headline: **28% of today's best matches are missing, 14% of what is shown is dead, and 37% of
the scores are stale.** The brief's honest limits are accurate; the dashboard's freshness is the
limit it does not mention.

---

## 3. Defects found, ranked

### D1 — The database is a fossil, not a live view (high)

`collect.py` only ever upserts. There is no lifecycle:

- A listing that disappears from the feed is never marked closed. 58/400 rows are dead today.
- A row whose score falls below `MIN_FIT` keeps its old score, because it is not re-scored. 148/400
  scores are stale; 21 would now fail the threshold.
- The DB is a union of historical runs, not a snapshot of today. New postings are only seen if a
  run happens; 112 of today's top 400 are absent because no run since 2 Nov has re-evaluated the
  pool.
- `/` hard-caps at `LIMIT 300`, so even the 400 rows that are stored are not all reachable.
- `is_visible` (1 active-but-invisible listing today) is ignored.

The brief promises "a scored, filterable shortlist"; after a week of not running the collector, it
is a historical record. This is not fixed by cron: cron alone still leaves closed rows and stale
scores.

### D2 — `is_us()` produces false negatives on real feed strings (high)

The classifier is substring-based and runs the country blocklist before the US checks. Concrete
misses in today's feed:

| Location (mentions) | Why it fails | Current verdict |
|---|---|---|
| `LA` (73) | city alias list has `sf`, `nyc`, not `la` | non-US: −15 |
| `Indianapolis, IN` (22) | `"india" in "indianapolis"` triggers the blocklist | non-US: −15 |
| `California` (16), `Texas` (12), `Massachusetts` (11), `Washington` (10) | state **names** are not recognised, only two-letter codes after a comma | non-US: −15 |
| `New Mexico` (6), `Indiana` (7) | `"mexico"`, `"india"` substrings | non-US: −15 |
| `Remote in UK` (2) | `"uk"` is not in `NON_US_WORDS`; the `remote` shortcut returns US | US: +10/+18 |

A word-boundary reclassification prototype flips **52 distinct location strings, 447 mentions, and
133 active jobs**; the true number needs the test suite in §12. The swing per job is 25–33 points,
which is larger than most keyword weights. `profile.US_CITY_WORDS` already encodes the intended
aliases but is never used.

### D3 — Company summaries cannot be updated (medium-high)

Three separate problems around the same feature:

1. `collect.py` updates a summary only when it is `NULL`/empty:
   `CASE WHEN summary IS NULL OR summary='' THEN ? ELSE summary END`. So adding a key to
   `COMPANY_PROFILES` and re-collecting does **not** update rows already in the DB — the documented
   workflow in README ("Add a company note — one entry in `COMPANY_PROFILES`") only works for
   postings seen for the first time.
2. The stub says "Edit this field to write your own summary", but the job page has no summary edit
   control — only notes. README repeats that it is "editable" and "editable in the UI".
3. Profile keys are exact company names. The top job in the DB is **RTX**; `COMPANY_PROFILES` has
   **"Raytheon"**. Four of fourteen profiles match anything at all, and 390/400 jobs show a stub.

### D4 — No tests, and the docs claim there are (medium)

README line 113: "Twelve cases are covered in the module docstring's tests." `collect.py`'s
docstring contains no tests. There is no `tests/` directory and no CI. This matters because the
scorer is the product: every phase below changes it, and there is currently no way to tell a
deliberate ranking change from a regression.

### D5 — Duplicate roles consume shortlist slots (medium)

Same company + title posted to multiple locations or boards appears as separate rows: **43
duplicates in today's top 400**. Each consumes a slot and shows the same role twice. `location`
lists are not merged, so the "also available in" information is scattered.

### D6 — Score is not reproducible from the stored row (medium)

`score()` reads `time.time()` internally. The README recommends re-scoring from cache in under a
second, but the result changes with the wall clock, so a stored `fit` cannot be verified later and
tests would be flaky. Injecting a clock is a small refactor that unlocks D1's "re-score every row"
and the whole test suite.

### D7 — Unused data already in the feed (low-medium)

The feed carries `source`, `company_url`, `is_visible`, `sponsorship`, and `degrees`. The DB stores
`sponsorship` but never scores or displays it in any useful way; `company_url`, `source`, and
`is_visible` are dropped. `sponsorship == "U.S. Citizenship is Required"` is exactly the kind of
eligibility fact the gap warnings exist for.

### D8 — Smaller defects (low)

- No schema migrations. `CREATE TABLE IF NOT EXISTS` silently does nothing when a column is added to
  an existing DB. `jobs.detail` exists but is never read or written.
- Letter filenames can collide: `company--title--variant.md`, truncated at 60 chars, with no job id.
- `int(min_fit)` raises on a non-numeric query string → 500.
- `/health` returns `text/html`; `/job/unknown` returns 200.
- `server.log_page` reads the log without closing the file.
- README says "Everything lives in `profile.py`", but letter facts and prose live in `letters.py`.
- README says Python 3.10+, but `config.toml` (P0) needs `tomllib` (3.11+). 3.10 is EOL as of
  Oct 2026, so raising the floor is reasonable — but it should be a stated decision, not a surprise.

---

## 4. Recommended priority

The brief's P0 is de-personalization. I recommend doing it **second**: it is about who can use the
tool, while D1/D2 are about whether the tool is telling the truth today. Phase 0 also makes every
later phase cheaper, because config extraction and ATS fetching both need tests and stable scoring.

| This plan | Brief mapping | Theme | Why here |
|---|---|---|---|
| **Phase 0** | *(new)* | Stabilise: tests, clock, location, lifecycle, summary edit, dedupe, pagination | The current view is 7 days stale and 133 jobs are mis-scored; every later change needs tests |
| Phase 1 | P0 | De-personalize into `config.toml` | Unblocks Phase 2 (letter tailoring needs a user's facts) and makes the repo shareable |
| Phase 2 | P1 | Posting text + role-specific letters + description-based gap warnings | Highest user-visible value after Phase 0; turns generic drafts into per-posting drafts |
| Phase 3 | P2 | Second feed + ATS watchlist | Removes single-source risk; reuses the Phase 2 adapters |
| Phase 4 | P2 | Outcomes, status history, funnel | Makes the recorded statuses useful; do after the pipeline is trustworthy |
| Phase 5 | P3 | `pyproject.toml`, console entry point, CI | Packaging is a day of work once the interfaces stop moving |

If you prefer to keep the brief's order exactly, Phase 1 can move first; nothing in Phase 0 depends
on it. I would still do the test harness (0.1) and the location fix (0.2) before anything else.

---

## 5. Phase 0 — Stabilise (≈4 focused days)

### 0.1 Test harness and an injectable clock

- `collect.score(job, now=None)`; default `now = time.time()`. Use it for freshness.
- `tests/` with stdlib `unittest` only:
  - `tests/test_score.py` — weights, seasons, degrees, clamping, reasons sum to fit.
  - `tests/test_locations.py` — the matrix in §0.2 and §3.
  - `tests/test_lifecycle.py` — close/reopen/threshold.
  - `tests/test_config.py` — Phase 1 loader (written early against defaults).
  - `tests/test_server.py` — routes, 404, form validation, escaping.
- `tests/fixtures/` — a 20-record slice of the real feed with expected scores, plus synthetic edge
  cases (future date, missing date, empty locations).
- `Makefile` (or `justfile`): `test`, `check`, `serve`, `collect`, `docs`.
- Fix the README test claim as part of this item.

**Acceptance:** `python3 -m unittest discover -s tests -v` runs with no network, no writes to
`data/`, and fails if any weight in `profile.py` changes without a corresponding expected value.

### 0.2 Location classifier v2

Replace substring matching with tokenised matching, and make ambiguity explicit:

- Normalise the location string (casefold, collapse punctuation).
- Check **US-positive** evidence first: full state names, `, XX` state codes, `US`/`USA`/`U.S.`,
  and city aliases (`sf`, `nyc`, `la`, `boston`, `bay area`, …) as whole words.
- Then **foreign-positive** evidence: countries and regions with word boundaries, including `uk`,
  and Canadian provinces (`on`, `bc`, `qc`, `ab`) only in a `City, XX` position.
- Return a **three-valued** result: `us`, `foreign`, `unknown`. Score `unknown` as 0, not −15:
  absent evidence is not evidence of a foreign posting. `score()` then records
  `+10/+18 US`, `+0 location unknown`, or `−15 outside US` in `reasons`, so the change stays
  explainable.
- Keep `is_us()` as a thin boolean wrapper if other code needs it.
- Add the 52 reclassified strings (and the cases that must stay foreign) to
  `tests/fixtures/locations.txt`; assert both kinds.

**Acceptance:** `Indianapolis, IN`, `New Mexico`, `California`, `LA`, `Boston`, `Remote, US` → US;
`Toronto, ON, Canada`, `Vancouver, BC`, `Remote in UK`, `Zürich, Switzerland` → foreign; a score
diff of the top 50 before/after is reviewed and attached to the commit message.

### 0.3 Job lifecycle and current scores

- Migration (see §6): `closed_at`, `last_seen`, `status_changed_at`, `summary_edited`,
  `duplicate_of`, `source`.
- On a **fresh** run (feed actually downloaded): score every active listing, upsert the top
  `MAX_JOBS` **plus** any row already in the DB that is still active, so its score stays current.
- After the upsert: `UPDATE jobs SET closed_at = :run_start WHERE closed_at IS NULL AND last_seen <
  :run_start`. Reopen (`closed_at = NULL`) any row seen again.
- On an **offline** run (cached feed), do not touch `closed_at`; log "offline: lifecycle unchanged".
- Re-score every open row at read time is *not* the plan; one re-score per run is enough.
- New `--dry-run`: fetch/cache, score, print counts, write nothing. New run columns: `duplicates`,
  `closed`, `errors`, and a one-line summary per source.

**Acceptance:** immediately after a fresh collect, this returns 0:

```sql
SELECT COUNT(*) FROM jobs
WHERE closed_at IS NULL AND last_seen < (SELECT MAX(started) FROM runs);
```

and every open row's `fit` equals `score(row, now=run_start)`. Feed hides `closed_at IS NOT NULL`
by default; `?show=closed` reveals them with a `closed` chip. Status and notes survive a re-collect
(regression test).

### 0.4 Summary: editable, refreshable, alias-aware

- Add `summary_edited INTEGER DEFAULT 0`.
- On upsert: update the summary when `summary_edited = 0` **or** the row is new; never otherwise.
- Add `POST /summary` and a textarea on the job page. Saving sets `summary_edited = 1`. Offer "reset
  to auto" for a single row.
- Add `COMPANY_ALIASES` in `profile.py` (`{"RTX": "Raytheon"}`) and resolve profile keys through it.
  Consider a one-to-many `aliases` list in the eventual config.
- Rewrite the stub to state the truth ("Auto summary — edit below").

**Acceptance:** add a profile for a company already in the DB, re-collect without `--refresh`, and
its non-edited rows update; edit one row, re-collect, and the edit survives.

### 0.5 De-duplicate roles

- Group by `(normalised company, normalised title)` — optionally `+ category`; measure both.
- Representative: the member with the **lowest listing id** (stable across runs), or a
  `job_groups` table if status churn becomes a problem.
- Merge `locations`, `terms`, and `degrees` into the representative; keep the best URL by host
  preference (employer ATS > aggregator) and the earliest `date_posted`.
- Mark the rest with `duplicate_of = representative.id`; hide them from the feed by default, keep
  them in the DB for provenance.
- Apply `MAX_JOBS` **after** dedupe, so the cap counts distinct roles rather than repeat postings.
- Re-score after merging, since location affects fit.

**Acceptance:** today's pool yields 400 distinct roles in the top page (no same company+title
repeats); a representative change does not orphan a shortlisted status (test).

### 0.6 Feed view: pagination, sort, freshness

- Page size 50, `?page=`; sorts by `fit`, `date_posted`, `company`; keep filters in the query string.
- Remove the hard `LIMIT 300`; show "N of M matches".
- Show the last successful run time and the count of new postings since it in the header.
- Default `min_fit` becomes `profile.MIN_FIT` (70), not 45; the control stays for deliberately
  looking below the threshold.
- Fix `/job/<unknown>` → 404; validate `min_fit`; add `Cache-Control: no-store`; `/health` as
  `text/plain`.
- Check the table at 900 px: it currently has no horizontal scroll or column hiding.

**Acceptance:** every stored match is reachable by paging; the page shows when the data is from.

### 0.7 Documentation truth pass

- README: remove or satisfy the "12 tests" claim; correct the line count; correct "everything lives
  in profile.py"; document `--dry-run`, `?show=closed`, pagination.
- BRIEF: add the freshness caveat to "Honest limits" if Phase 0 slips; once Phase 0 ships, the
  remaining caveat is simply that the data is as fresh as the last run.
- Regenerate `BRIEF.pdf` with `python3 tools/md2pdf.py BRIEF.md` (and gitignore `BRIEF.html`).

---

## 6. Data model changes and migrations

`db.py` currently runs `CREATE TABLE IF NOT EXISTS` on every connect. Adding a column to `SCHEMA`
does nothing for an existing file. Introduce a tiny migration runner:

```python
MIGRATIONS = [
    # v1 — lifecycle + summary provenance + dedupe + sources
    """ALTER TABLE jobs ADD COLUMN closed_at INTEGER;
       ALTER TABLE jobs ADD COLUMN summary_edited INTEGER DEFAULT 0;
       ALTER TABLE jobs ADD COLUMN duplicate_of TEXT;
       ALTER TABLE jobs ADD COLUMN source TEXT;
       ALTER TABLE jobs ADD COLUMN detail_fetched_at INTEGER;
       ALTER TABLE jobs ADD COLUMN detail_status TEXT;
       ALTER TABLE jobs ADD COLUMN status_changed_at INTEGER;""",
    # v2 — status history / outcomes (Phase 4)
    """CREATE TABLE status_events (...);""",
]

def migrate(con):
    v = con.execute("PRAGMA user_version").fetchone()[0]
    for i, sql in enumerate(MIGRATIONS[v:], start=v + 1):
        con.executescript(sql)
        con.execute(f"PRAGMA user_version = {i}")
    con.commit()
```

Notes:

- Use `PRAGMA table_info(jobs)` in the migration to stay idempotent if a column already exists
  (`jobs.detail` already does).
- Backfill `status_changed_at` from `last_seen` for existing rows.
- `runs` gains `duplicates INTEGER`, `closed INTEGER`, `errors TEXT`, and a `sources` summary.
- `status_events` (Phase 4):

```sql
CREATE TABLE status_events (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  job_id      TEXT NOT NULL,
  from_status TEXT,
  to_status   TEXT NOT NULL,
  at          INTEGER NOT NULL,
  note        TEXT DEFAULT ''
);
CREATE INDEX idx_events_job ON status_events(job_id, at);
```

- Test migration both ways: empty file → current, and a copy of the current `jobhunt.db` → current,
  with all 400 rows and the 1 `shortlisted` status intact.

---

## 7. Phase 1 — De-personalize (brief P0, ≈1.5 days)

`config.toml` (gitignored) + `config.example.toml` (tracked) + `config.py` loader.

```toml
[scoring]
min_fit = 70
max_jobs = 400

[scoring.seasons]           # exact term -> points
"Summer 2027" = 25

[scoring.categories]
Hardware = 20

[scoring.title_keywords]
fpga = 18

[scoring.title_penalties]
phd = 25

[locations]
preferred = ["medford", "boston", "cambridge", "somerville", "remote"]

[identity]
name = "Your Name"
school = "..."
degree = "..."
year = "..."
gpa = "..."
email = "..."
phone = "..."

[letters]
research = """..."""
building = """..."""
communicating = """..."""
life = """..."""
signoff = """Sincerely,\n..."""

[companies.RTX]
aliases = ["Raytheon"]
summary = "..."

[gaps]
asic = "..."
clearance = "..."
```

`GAP_WARNINGS` moves under `[gaps]`, and `[companies.*]` replaces `COMPANY_PROFILES` with an alias
list, which is the fix for D3's RTX/Raytheon mismatch.

- `config.py`: `load(path=None)` using `tomllib`; `JOBHUNT_CONFIG` env override; validate types and
  ranges; a clear error telling the user to copy the example. `profile.py` keeps only the
  non-personal taxonomy (`US_STATES`, `NON_US_WORDS`, degree spellings, feed categories); every
  preference and every word about you moves out. `config.example.toml` carries the documented
  defaults, so an omitted section is never silently filled from a personal constant.
- `letters.py`: `FACTS` and the four prose blocks move to config; `SIGNOFF` too. Letter templates
  stay in code; prose leaves.
- `db.py`: allow `JOBHUNT_DATA_DIR` so tests use a temp database.
- First run: `collect.py` and `server.py` refuse to start with a missing config and print the exact
  `cp` command. A `/setup` page is optional; a message is enough for a local tool.
- Add `config.toml` to `.gitignore`; keep `config.example.toml` free of real personal data.

**Python floor:** raise to **3.11** (`tomllib`), update README. 3.10 is EOL; 3.11 is four years old
at the time of writing.

**Acceptance:**

```bash
git clone … && cp config.example.toml config.toml
python3 collect.py --refresh && python3 server.py
```

works with no code edits. Search the source and docs for your name, school, email, and phone and
confirm they appear only in `config.toml`; the test suite enforces this. Decide separately whether
the tracked `BRIEF.pdf` should be regenerated (it contains no personal data today).

---

## 8. Phase 2 — Posting text and tailored letters (brief P1, ≈3 days)

The feed has **no description field** (confirmed against today's 17,427 records). Posting text must
be fetched from the employer's ATS.

### 8.1 Adapters

New `postings.py` (or `sources/ats.py` if Phase 3 lands first):

| ATS | URL shape | Public endpoint |
|---|---|---|
| Greenhouse | `boards.greenhouse.io/{board}/jobs/{id}`, `job-boards.greenhouse.io/…` | `boards-api.greenhouse.io/v1/boards/{board}/jobs/{id}?content=true` |
| Lever | `jobs.lever.co/{board}/{id}` | `api.lever.co/v0/postings/{board}/{id}` (`descriptionPlain`, `lists`) |
| Ashby | `jobs.ashbyhq.com/{board}/{id}` | `api.ashbyhq.com/posting-api/job-board/{board}?includeCompensation=true` |
| SmartRecruiters | `jobs.smartrecruiters.com/{company}/{id}` | `api.smartrecruiters.com/v1/companies/{company}/postings/{id}` |
| Workday | `{tenant}.wdN.myworkdayjobs.com/…/{title}_{req}` | JSON POST to `/wday/cxs/{tenant}/{site}/job/{req}` — later, fragile |

- `resolve(url) -> (ats, board, posting_id) | None`; unknown hosts return `unsupported`, not an error.
- HTML → text with `html.parser` (stdlib); keep bullet structure, drop scripts/nav.
- Fetch policy: on demand from the job page ("Fetch description"), plus
  `python3 postings.py --top 50`; 0.5–1 s between requests, 10 s timeout, one retry, honest
  User-Agent; cache in `jobs.detail` + `detail_fetched_at` + `detail_status` (`ok`/`unsupported`/
  `error`). Never fetch on page load.
- Coverage estimate from today's active feed: Greenhouse ~537 + Lever ~156 + Ashby ~354 ≈ 20% of
  listings outright, more in the hardware/software slice after the top-400 cut. Measure before
  promising a percentage.

### 8.2 Use the text

- **Job page:** "What the posting asks for" — extracted requirement bullets, plus the gap warnings
  now searching `title + category + detail` (the current version only sees title/category, so
  "clearance" in the body is missed).
- **Letters:** replace one generic paragraph with a role-specific one built from 2–3 requirement
  bullets mapped to verified facts via a config-driven `[evidence]` table. If a requirement has no
  verified fact, emit a `[GAP — …]` placeholder, never a fabricated claim. Keep the `[HOOK — …]`
  exactly as is.
- **Scoring:** do **not** add description keywords to `fit` in this phase. Show a separate "evidence
  overlap" panel and collect outcomes first; changing weights and adding text matches at the same
  time makes the ranking unexplainable.

**Acceptance:** for the top 20 supported URLs, the job page shows a cached description and at least
one posting-specific line in the letter; the letter contains no claim absent from the config; an
unsupported/offline URL degrades to the current generic draft; no network call happens during a
plain page load.

---

## 9. Phase 3 — Second feed and watchlist (brief P2, ≈1.5 days)

- Normalised `Job` dataclass/schema: `id, source, company, title, category, url, locations, terms,
  degrees, sponsorship, date_posted, active, detail`.
- `sources/simplify.py` wraps today's `fetch()`; `sources/ats.py` polls a `watchlist.toml` of ~50
  companies with their boards. Each source logs its own counts; one failing source does not abort a
  run.
- Cross-source dedupe by canonical URL and `(company, title)`; `source` is stored, and the row keeps
  the best URL.
- CLI: `collect.py --source simplify|watchlist|all` (default `all` once the watchlist exists).
- Keep the Simplify feed behind a flag/config key rather than deleting it: it is the only source
  with 17k records and near-zero maintenance.

**Acceptance:** with the watchlist empty, behaviour is unchanged; with 50 boards, the feed grows and
the run log shows per-source counts; setting `sources.simplify = false` still produces a usable
shortlist; a dead board logs `error` and the run exits 0.

---

## 10. Phase 4 — Outcomes and pipeline (brief P2, ≈1.5 days)

- Write a `status_events` row on every status change (including back to `new`), with the old value.
- `applications`-level facts can stay in `status_events` plus a `rejected_reason` field; do not add
  a second source of truth for the current status.
- `/pipeline`: counts per stage, conversion rates, median days in stage, and a table of rejections
  with reason.
- `/export.csv`: one row per job with `fit`, key reasons, status, dates, notes.
- Rejection reason taxonomy: `no_response`, `skill_gap`, `timing`, `visa`, `role_filled`,
  `withdrew`, `other` + free text.
- Report conversion by score band, with **n** and a warning when n is small. Do not auto-tune the
  scorer from a handful of outcomes; use the report to edit weights deliberately.

**Acceptance:** the event log replays to the current status for every row; funnel counts match a
manual recount on the existing 400 rows; CSV opens in a spreadsheet with stable columns.

---

## 11. Phase 5 — Package (brief P3, ≈1 day)

- `pyproject.toml`, no runtime dependencies, `requires-python = ">=3.11"`.
- Console script `jobhunt` with subcommands: `collect`, `serve`, `letters`, `fetch-details`,
  `export`, `check`. Keep `python3 collect.py` etc. as thin wrappers so existing cron lines and the
  README keep working.
- `python3 -m unittest discover -s tests` + `python3 -m compileall -q .` as `jobhunt check` /
  `make check`.
- Optional dev extra: `ruff` only, no pytest, no framework. CI is optional for a local tool; a
  pre-commit hook running `make check` is the cheaper win.

**Acceptance:** `pip install -e .` then `jobhunt collect --dry-run` works from any directory;
`jobhunt serve` finds the repo's `data/` by config/`JOBHUNT_DATA_DIR`, not by CWD; `make check` is
green and is what the pre-commit hook runs.

---

## 12. Test plan (the part that keeps the rest honest)

| Suite | Cases |
|---|---|
| `test_score` | each season (best-of, unknown term → −15), each category, keyword and penalty hits, degree accepted/rejected/empty, freshness at 6.9/7/20.9/21 days, future date, missing date, clamp at 0 and 100, `sum(reasons) == fit` |
| `test_locations` | the matrix in §0.2 and §3, `Remote`/`Remote in UK`/`Remote, US`, Canadian provinces, `Indianapolis`/`New Mexico`, bare state names, `LA`/`SF`/`NYC`, unknown → 0 not −15 |
| `test_dedupe` | merge key, merged locations/terms, URL host preference, stable representative, copy isolation |
| `test_lifecycle` | close on disappearance, reopen, threshold drop, offline run leaves lifecycle alone, status/notes survive |
| `test_config` | missing file message, invalid TOML, out-of-range `min_fit`, defaults when sections omitted, example config loads |
| `test_server` | `/`, `/runs`, `/log`, `/health`, 404, POST status validation, notes round-trip, HTML escaping, bad `min_fit` |
| `test_letters` | three variants, hook placeholder present, no unverified text, gap placeholder when evidence missing, filename uniqueness |

Determinism rules: no network, no wall clock (`now` injected), no writes into `data/`; every test
gets a temp DB through `support.TempDB`, which overrides `db.DB_PATH`.

Golden fixture: commit a 20-record JSON slice **including** the expected `fit` and reasons, so a
weight change fails loudly. Regenerate deliberately with a script, not by hand.

---

## 13. Decisions needed before implementation

1. **Order.** Resolved: Phase 0 then Phase 1 shipped; Phase 2 is next.
2. **Config location.** Resolved: `config.toml` is gitignored; `config.example.toml` is tracked.
3. **Python floor.** Resolved: 3.11, for `tomllib`.
4. **ATS scope.** On-demand + top 50 per run (recommended), or fetch every supported posting (≈1,000
   requests/day, unnecessary)?
5. **Shortlist size.** Today 594 clear 70; 400 are kept; rank 400 sits at 73. After dedupe and the
   location fix the pool grows. Keep 400 and page the rest, or raise `MAX_JOBS`? Recommend: keep
   `MIN_FIT = 70`, dedupe first, then measure before tuning. Do not tune weights and fix the
   classifier in the same commit.
6. **BRIEF.pdf.** Keep committing it (it makes the repo pleasant to skim) and regenerate on doc
   changes, or drop it as a build artifact? Today it contains no personal data; that changes only
   if the brief itself gains a name.

---

## 14. First week — concrete sequence

1. **Day 1:** 0.1 tests + injected clock + `--dry-run`; correct README's test claim. Run the
   current suite against the existing DB; capture the baseline ranking.
2. **Day 2:** 0.2 location classifier + tests; re-score; diff the top 50 and attach the diff to the
   commit. Expect a meaningful reshuffle.
3. **Day 3:** 0.3 migration + lifecycle + re-score + closed filter; verify the acceptance SQL and
   that the 58 dead rows are hidden from the feed.
4. **Day 4:** 0.4 summary edit/refresh + aliases; 0.5 dedupe; 0.6 pagination and 404.
5. **Day 5:** 0.7 docs + BRIEF.pdf; run `collect.py --refresh` end-to-end; review the feed by hand
   for the first time in a week; only then start Phase 1.

**Do not batch 0.2 and 0.5 into one release without keeping the before/after ranking diff.** Both
change which jobs appear; if the diff is not reviewed, a bug becomes the new normal.

---

## 15. Definition of done for Phase 0

- `python3 -m unittest discover -s tests` is green; `python3 -m compileall -q .` clean.
- After a fresh collect: every open row's `last_seen` equals the run start and every open row's
  `fit` equals a fresh score; the feed shows only rows at or above the default threshold, and
  closed rows appear only behind `?show=closed`.
- The feed shows today's top roles, not a seven-day-old top; closed rows are hidden; all stored
  matches are reachable.
- Status and notes survive a re-collect; company summaries can be edited and refreshed.
- The job page, README, and BRIEF agree about what is editable, how fresh the data is, and how
  many tests exist.
- One command (`--dry-run`) tells you fetched/active/matched/duplicates/closed/new before writing.

## 16. Non-goals (unchanged from the brief)

Auto-apply, LLM-written letters, hosting, multi-user. The scorer remains keyword overlap and stays
explainable; description text is shown as evidence, not folded into the score until outcomes justify
it.

---

## Appendix — commands used for this review

```bash
python3 -m py_compile *.py tools/*.py
python3 server.py & curl -s -o /dev/null -w '%{http_code}\n' \
  http://127.0.0.1:8099/ http://127.0.0.1:8099/job/<id> \
  http://127.0.0.1:8099/log http://127.0.0.1:8099/runs
curl -sL -o data/listings_raw.json \
  https://raw.githubusercontent.com/SimplifyJobs/Summer2027-Internships/dev/.github/scripts/listings.json
# then: rescore the DB with collect.score, compare with today's active set,
# count duplicates, probe is_us on the 826 distinct location strings.
```

The downloaded feed is left in `data/listings_raw.json` (gitignored, 13 MB) so the next run can work
offline. The database was not modified by this review.
