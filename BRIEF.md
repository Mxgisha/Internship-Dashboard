# Internship Dashboard — Brief

**What it is.** A local tool that turns one public internship feed into a scored, filterable
shortlist with company notes, application tracking, and cover-letter drafts. One SQLite file, one
Python process, standard library only.

**The problem.** Job boards optimize for volume, not fit. Scrolling 17,000 listings produces
anxiety, not a pipeline. This reduces that feed to roughly 400 defensible candidates and keeps a
record of what happened to each.

**Core mechanics.** Four stages, about 830 lines of standard-library Python:

1. **Ingest** — one JSON request to Simplify's internship index, which aggregates Greenhouse,
   Lever, and Workday boards. 17,373 records, no auth, no scraping.
2. **Score** — rules in `profile.py` produce 0–100 from season, category, title keywords, degree,
   location, and recency. Every term is recorded, so any score can be explained.
3. **Store** — SQLite upsert keyed on listing id. `status` and `notes` are human fields and are
   never overwritten by a re-collect; machine fields always are.
4. **Surface** — `server.py` serves the dashboard; `letters.py` writes three letter variants per
   job from verified facts.

**The design decision.** No scraping. LinkedIn and Indeed block it, and Handshake is auth-gated to
a university account. ATS endpoints and the Simplify index are public JSON meant to be read — so
one request replaces thousands and the URLs point at the real posting.

**Honest limits.**

- The fit score is keyword overlap, not evidence. The top scorer in the database is an ASIC role
  with no RTL project behind it; `GAP_WARNINGS` flags this per job, but it is a heuristic.
- Company summaries are a hand-written dict for 14 targets, stubs otherwise.
- Letters refuse to write the "why this company" sentence — it is emitted as a placeholder,
  because that sentence is the letter.
- Personal data is hardcoded: weights in `profile.py`, biography in `letters.py`. Until that is
  extracted, this is one person's tool rather than a tool.

**Paths forward.**

- **P0 — De-personalize.** Weights and biography into `config.toml`; everything else gets cheaper.
- **P1 — Posting text.** Fetch the real description when a URL matches a supported ATS. This is
  what turns generic drafts into per-posting tailoring, and it removes a tab-switch per application.
- **P2 — Second feed.** A ~50-company ATS watchlist removes the single-source risk of depending on
  one GitHub index.
- **P2 — Outcomes.** Statuses are recorded; outcomes are not. A rejection log with a reason would
  tune the scorer better than any further keyword work.
- **P3 — Package.** `pyproject.toml`, a console entry point, tests for the scorer and parser.

**Out of scope:** auto-apply, LLM-generated letters, hosting, multi-user. Volume isn't the
problem; defensibility is.
