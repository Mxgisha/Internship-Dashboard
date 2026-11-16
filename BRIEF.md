# Internship Dashboard — Brief

**What it is.** A local tool that turns one public internship feed into a scored, filterable
shortlist with company notes, application tracking, and cover-letter drafts. One SQLite file, one
Python process, standard library only.

**The problem.** Job boards optimize for volume, not fit. Scrolling 17,000 listings produces
anxiety, not a pipeline. This reduces that feed to roughly 400 defensible candidates and keeps a
record of what happened to each.

**Core mechanics.** Four stages, about 1,600 lines of standard-library Python:

1. **Ingest** — one JSON request to Simplify's internship index, which aggregates Greenhouse,
   Lever, and Workday boards. 17,373 records, no auth, no scraping.
2. **Score** — rules in `config.toml` produce 0–100 from season, category, title keywords, degree,
   location, and recency. Every term is recorded, so any score can be explained.
3. **Store** — SQLite upsert keyed on listing id. `status`, `notes`, and an edited company summary
   are human fields and are never overwritten by a re-collect; machine fields always are. A fresh
   run re-scores stored rows, merges duplicate postings, and marks rows that left the feed as
   closed instead of deleting them.
4. **Surface** — `server.py` serves the dashboard; `letters.py` writes three letter variants per
   job from the verified facts in `config.toml`.

**The design decision.** No scraping. LinkedIn and Indeed block it, and Handshake is auth-gated to
a university account. ATS endpoints and the Simplify index are public JSON meant to be read — so
one request replaces thousands and the URLs point at the real posting.

**Honest limits.**

- The fit score is keyword overlap, not evidence. The top scorer in the database is an ASIC role
  with no RTL project behind it; the `[gaps]` config flags this per job, but it is a heuristic.
- Company summaries are hand-written notes for a handful of targets, stubs otherwise.
- Letters refuse to write the "why this company" sentence — it is emitted as a placeholder,
  because that sentence is the letter.
- The shortlist is only as fresh as the last run. A cached run re-scores but cannot detect postings
  that have left the feed; only `--refresh` closes them.

**Paths forward.**

- **P0 — De-personalize.** Done. Weights, identity, letters, company notes, and evidence gaps
  live in `config.toml`; `config.example.toml` is the tracked template.
- **P1 — Posting text.** Fetch the real description when a URL matches a supported ATS. This is
  what turns generic drafts into per-posting tailoring, and it removes a tab-switch per application.
- **P2 — Second feed.** A ~50-company ATS watchlist removes the single-source risk of depending on
  one GitHub index.
- **P2 — Outcomes.** Statuses are recorded; outcomes are not. A rejection log with a reason would
  tune the scorer better than any further keyword work.
- **P3 — Package.** `pyproject.toml`, a console entry point, and CI around the existing tests.

**Out of scope:** auto-apply, LLM-generated letters, hosting, multi-user. Volume isn't the
problem; defensibility is.
