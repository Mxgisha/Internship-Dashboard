"""Collect listings, score them against profile.py, write to SQLite.

Usage:
    python3 collect.py             # use cached raw file
    python3 collect.py --refresh   # re-download the listings feed first
    python3 collect.py --all       # ignore MIN_FIT / MAX_JOBS
    python3 collect.py --dry-run   # score and report, write nothing
"""
import json
import os
import re
import sys
import time
import urllib.request
from urllib.parse import urlparse

import config
import db

try:
    import profile as P
except config.ConfigError as exc:  # a missing config should read as advice, not a traceback
    raise SystemExit(f"jobhunt: {exc}")

HERE = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(HERE, "data", "listings_raw.json")
FEED = "https://raw.githubusercontent.com/SimplifyJobs/Summer2027-Internships/dev/.github/scripts/listings.json"

# Human fields follow a role only while the previous listing is recent. This
# covers a representative vanishing between runs without moving a rejection
# from last season onto a newly reposted role.
INHERIT_DAYS = 30

# Employer ATS links are more durable than aggregator links.
AGGREGATOR_HOSTS = ("simplify.jobs", "linkedin.com", "indeed.com", "handshake.com", "jobright.ai")
ATS_HOSTS = ("greenhouse.io", "lever.co", "ashbyhq.com", "smartrecruiters.com",
             "myworkdayjobs.com", "workday.com", "icims.com", "successfactors.com")


def fetch(refresh):
    """Return (records, freshly_downloaded)."""
    os.makedirs(os.path.dirname(RAW), exist_ok=True)
    fresh = False
    if refresh or not os.path.exists(RAW):
        db.log(f"fetching feed: {FEED}")
        req = urllib.request.Request(FEED, headers={"User-Agent": "jobhunt/0.1 (personal use)"})
        with urllib.request.urlopen(req, timeout=60) as r:
            data = r.read()
        with open(RAW, "wb") as fh:
            fh.write(data)
        db.log(f"downloaded {len(data) / 1e6:.1f} MB")
        fresh = True
    else:
        db.log("using cached listings_raw.json (pass --refresh to update)")
    with open(RAW) as fh:
        return json.load(fh), fresh


def as_list(v):
    if v is None:
        return []
    return v if isinstance(v, list) else [v]


def _norm(text):
    """Lowercase and reduce punctuation to single spaces."""
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def _has_word(haystack, needle):
    """Whole-word/phrase match against an already-normalised string."""
    if not needle:
        return False
    return re.search(r"(?<![a-z0-9])" + re.escape(needle) + r"(?![a-z0-9])", haystack) is not None


def classify_location(location):
    """Return 'us', 'foreign', or 'unknown' for one location string.

    Deliberately evidence-based: a missing country is not evidence of a foreign
    posting, so unknown locations cost nothing. Order matters — US state names
    must win over country words ("New Mexico" vs "Mexico").
    """
    text = str(location or "")
    low = text.lower()
    norm = _norm(low)

    if any(_has_word(norm, state) for state in P.US_STATE_NAMES):
        return "us"

    codes = {c.upper() for c in re.findall(r",\s*([A-Za-z]{2})\b", text)}
    if codes & P.US_STATES:
        return "us"

    if any(_has_word(norm, word) for word in P.NON_US_WORDS):
        return "foreign"

    if codes & P.CANADIAN_PROVINCES:
        return "foreign"

    if any(_has_word(norm, word) for word in P.US_COUNTRY_WORDS):
        return "us"
    if _has_word(norm, "u s") or _has_word(norm, "u s a"):
        return "us"

    if any(_has_word(norm, city) for city in P.US_CITY_WORDS):
        return "us"

    return "unknown"


def location_verdict(locations):
    """Combine a location list: any US evidence wins, then any foreign evidence."""
    verdicts = [classify_location(l) for l in as_list(locations)]
    if "us" in verdicts:
        return "us"
    if "foreign" in verdicts:
        return "foreign"
    return "unknown"


def is_us(locations):
    """Boolean compatibility wrapper. Unknown is not US."""
    return location_verdict(locations) == "us"


def _preferred(locations):
    blob = _norm(" ".join(str(l) for l in as_list(locations)))
    return any(_has_word(blob, place) for place in P.PREFERRED_LOCATIONS)


def score(job, now=None):
    """Return (fit 0-100, list of human-readable reasons). `now` is injectable."""
    now = time.time() if now is None else now
    pts, reasons = 0, []
    title = (job.get("title") or "").lower()
    terms = as_list(job.get("terms"))
    degrees = [d.lower() for d in as_list(job.get("degrees"))]
    locs = as_list(job.get("locations"))

    # Season
    best = None
    for t in terms:
        for season, w in P.SEASONS.items():
            if str(t).lower() == season.lower() and (best is None or w > best[1]):
                best = (t, w)
    if best:
        pts += best[1]
        reasons.append(f"+{best[1]} season {best[0]}")
    else:
        pts -= 15
        reasons.append("-15 season not targeted")

    # Category
    cat = job.get("category") or ""
    cw = P.CATEGORIES.get(cat, 0)
    if cw:
        pts += cw
        reasons.append(f"+{cw} category {cat}")
    else:
        reasons.append(f"+0 category {cat or 'none'}")

    # Title keywords
    for kw, w in P.TITLE_KEYWORDS.items():
        if kw in title:
            pts += w
            reasons.append(f"+{w} '{kw.strip()}'")

    # Penalties
    for kw, w in P.TITLE_PENALTIES.items():
        if kw in title:
            pts -= w
            reasons.append(f"-{w} '{kw.strip()}'")

    # Degree
    if any(d in degrees for d in P.ACCEPTED_DEGREES):
        pts += 10
        reasons.append("+10 accepts bachelor's")
    elif degrees:
        pts -= 10
        reasons.append(f"-10 degrees {','.join(degrees)}")

    # Location
    verdict = location_verdict(locs)
    if verdict == "us":
        pts += 10
        reasons.append("+10 US location")
        if _preferred(locs):
            pts += 8
            reasons.append("+8 preferred location")
    elif verdict == "foreign":
        pts -= 15
        reasons.append("-15 outside US")
    else:
        reasons.append("+0 location unknown")

    # Freshness. Future-dated records get no bonus rather than a fake one.
    posted = job.get("date_posted") or 0
    if posted:
        age_days = (now - posted) / 86400
        if 0 <= age_days < 7:
            pts += 10
            reasons.append("+10 posted <7d")
        elif 0 <= age_days < 21:
            pts += 5
            reasons.append("+5 posted <21d")

    return max(0, min(100, pts)), reasons


def summary_for(company, active_roles):
    return P.company_summary(company, active_roles)


def _merge_lists(values):
    out, seen = [], set()
    for value in values:
        value = str(value or "").strip()
        if value and value.casefold() not in seen:
            seen.add(value.casefold())
            out.append(value)
    return out


def url_rank(url):
    """Lower is better: employer ATS, then anything else, then aggregators."""
    host = (urlparse(url or "").netloc or "").lower()
    if not host:
        return 3
    if any(h in host for h in AGGREGATOR_HOSTS):
        return 2
    if any(h in host for h in ATS_HOSTS):
        return 0
    return 1


def _group_key(job):
    """The identity of a role across feed copies: normalised company + title."""
    return (_norm(job.get("company_name")), _norm(job.get("title")))


def dedupe(scored, now=None):
    """Collapse duplicate (company, title) listings and merge their fields.

    Returns (representatives, {rep_id: [duplicate jobs]}). The representative is
    the lowest listing id; its fields are merged and re-scored because location
    and freshness affect fit.
    """
    groups = {}
    for fit, reasons, job in scored:
        groups.setdefault(_group_key(job), []).append((fit, reasons, job))

    reps, members = [], {}
    for key, items in groups.items():
        items.sort(key=lambda t: str(t[2].get("id")))
        base = items[0][2]
        merged = dict(base)
        merged["locations"] = _merge_lists(
            list(as_list(base.get("locations")))
            + [loc for _, _, j in items[1:] for loc in as_list(j.get("locations"))])
        merged["terms"] = _merge_lists(
            list(as_list(base.get("terms")))
            + [t for _, _, j in items[1:] for t in as_list(j.get("terms"))])
        merged["degrees"] = _merge_lists(
            list(as_list(base.get("degrees")))
            + [d for _, _, j in items[1:] for d in as_list(j.get("degrees"))])
        urls = [j.get("url") for _, _, j in items if j.get("url")]
        if urls:
            merged["url"] = min(urls, key=url_rank)
        posted = [j.get("date_posted") or 0 for _, _, j in items if j.get("date_posted")]
        merged["date_posted"] = min(posted) if posted else 0
        fit, reasons = score(merged, now)
        reps.append((fit, reasons, merged))
        copies = []
        for _, _, job in items[1:]:
            copy = dict(job)
            copy["locations"] = list(as_list(job.get("locations")))
            copy["terms"] = list(as_list(job.get("terms")))
            copy["degrees"] = list(as_list(job.get("degrees")))
            copies.append(copy)
        members[base["id"]] = copies

    reps.sort(key=lambda t: -t[0])
    return reps, members


def _json(value):
    return json.dumps(value)


def collect(con, raw, *, now=None, show_all=False, fresh=True, dry_run=False, log=None):
    """Plan and apply one collection. Returns run statistics.

    On a fresh feed, rows that were not seen are closed and seen rows are
    reopened. On a cached feed, lifecycle fields are left alone.
    """
    now = int(now if now is not None else time.time())
    log = log or (lambda *a, **k: None)

    active = [j for j in raw if j.get("active") and j.get("is_visible", True) and j.get("id")]
    all_scored = []
    for job in active:
        fit, reasons = score(job, now)
        all_scored.append((fit, reasons, job))

    score_by_id = {job["id"]: (fit, reasons) for fit, reasons, job in all_scored}
    active_by_id = {job["id"]: job for job in active}
    per_company = {}
    for job in active:
        company = job.get("company_name") or "?"
        per_company[company] = per_company.get(company, 0) + 1

    # Merge first, then apply the threshold: a duplicate pair can clear the bar
    # together (e.g. one location earns the preferred-city bonus) even when
    # neither listing would alone.
    reps, members_by_rep = dedupe(all_scored, now)
    candidates = len(reps)
    if not show_all:
        reps = [rep for rep in reps if rep[0] >= P.MIN_FIT]
        reps = reps[: P.MAX_JOBS]

    selected = {rep["id"] for _, _, rep in reps}
    rep_by_member = {dup["id"]: rep_id
                     for rep_id in selected
                     for dup in members_by_rep.get(rep_id, [])}
    duplicate_count = sum(len(members_by_rep.get(rep_id, [])) for rep_id in selected)

    existing = {row["id"]: dict(row) for row in con.execute(
        "SELECT id, company, title, status, notes, summary, summary_edited, "
        "status_changed_at, closed_at FROM jobs")}
    existing_ids = set(existing)
    active_ids = set(score_by_id)
    existing_groups = {}
    for row in existing.values():
        key = (_norm(row.get("company")), _norm(row.get("title")))
        existing_groups.setdefault(key, []).append(row)

    stats = {
        "fetched": len(raw),
        "active": len(active),
        "matched": len(reps),
        "candidates": candidates,
        "inserted": 0,
        "updated": 0,
        "duplicates": duplicate_count,
        "closed": 0,
        "inherited": 0,
    }

    if dry_run:
        stats["would_insert"] = len(selected - existing_ids)
        stats["would_update"] = len(selected & existing_ids) + len(
            (existing_ids & active_ids) - selected)
        stats["would_close"] = len(existing_ids - active_ids) if fresh else 0
        bands = {}
        for fit, _, _ in all_scored:
            band = (fit // 10) * 10
            bands[band] = bands.get(band, 0) + 1
        log("score bands: " + ", ".join(
            f"{band}-{band + 9}: {bands[band]}" for band in sorted(bands, reverse=True)))
        log(f"{len(active)} active; {stats['matched']} kept of {candidates} distinct; "
            f"dry run, nothing written")
        return stats

    def human_status(row):
        return bool(row) and ((row.get("status") or "new") != "new"
                              or bool(row.get("notes")))

    def edited_summary(row):
        return bool(row) and bool(row.get("summary_edited"))

    def inheritance_for(job):
        """Keep human fields on the role when its representative listing changes.

        A shortlisted posting can disappear while another copy of the same role
        remains. The copies are one role, so the status, notes, and an edited
        company summary move to the new representative instead of being stranded
        on a closed row.
        """
        rep_row = existing.get(job["id"])
        cutoff = now - INHERIT_DAYS * 86400
        donors = [row for row in existing_groups.get(_group_key(job), [])
                  if row["id"] != job["id"]
                  and (row.get("closed_at") is None or row["closed_at"] >= cutoff)
                  and (human_status(row) or edited_summary(row))]
        if not donors:
            return None
        donors.sort(key=lambda row: (row.get("status_changed_at") or 0, str(row["id"])),
                    reverse=True)
        donor = donors[0]
        move_status = not human_status(rep_row) and human_status(donor)
        move_summary = not edited_summary(rep_row) and edited_summary(donor)
        if not (move_status or move_summary):
            return None
        return {
            "from": donor["id"],
            "status": donor["status"] if move_status else (rep_row["status"] if rep_row else "new"),
            "notes": donor["notes"] if move_status else (rep_row["notes"] if rep_row else ""),
            "status_changed_at": ((donor.get("status_changed_at") or now) if move_status
                                  else ((rep_row or {}).get("status_changed_at") or now)),
            "summary": donor.get("summary") if move_summary else None,
            "move_summary": move_summary,
        }

    def upsert(job, fit, reasons, duplicate_of):
        nonlocal stats
        job_id = job["id"]
        company = job.get("company_name") or "?"
        row = existing.get(job_id)
        if row and row.get("summary_edited"):
            summary = row.get("summary") or ""
        else:
            summary = P.company_summary(company, per_company.get(company, 0))
        closed_at = None if fresh or not row else row.get("closed_at")
        machine = (
            company,
            job.get("title"),
            job.get("category"),
            job.get("url"),
            _json(as_list(job.get("locations"))),
            _json(as_list(job.get("terms"))),
            _json(as_list(job.get("degrees"))),
            job.get("sponsorship"),
            job.get("date_posted") or 0,
            job.get("date_updated") or 0,
            fit,
            _json(reasons),
            summary,
            job.get("source") or "simplify",
        )
        if row:
            con.execute(
                """UPDATE jobs SET company=?, title=?, category=?, url=?, locations=?, terms=?,
                   degrees=?, sponsorship=?, date_posted=?, date_updated=?, fit=?, reasons=?,
                   summary=?, source=?, last_seen=?, closed_at=?, duplicate_of=?
                   WHERE id=?""",
                machine + (now, closed_at, duplicate_of, job_id),
            )
            stats["updated"] += 1
        else:
            con.execute(
                """INSERT INTO jobs (id, company, title, category, url, locations, terms, degrees,
                   sponsorship, date_posted, date_updated, fit, reasons, summary, source, status,
                   notes, first_seen, last_seen, closed_at, duplicate_of, summary_edited,
                   status_changed_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'new','',?,?,?,?,0,?)""",
                (job_id,) + machine + (now, now, closed_at, duplicate_of, now),
            )
            stats["inserted"] += 1

    written = set()
    for fit, reasons, rep in reps:
        upsert(rep, fit, reasons, None)
        inherited = inheritance_for(rep)
        if inherited:
            con.execute(
                """UPDATE jobs SET status=?, notes=?, status_changed_at=?,
                   summary=CASE WHEN ? THEN ? ELSE summary END,
                   summary_edited=CASE WHEN ? THEN 1 ELSE summary_edited END
                   WHERE id=?""",
                (inherited["status"], inherited["notes"], inherited["status_changed_at"],
                 1 if inherited["move_summary"] else 0, inherited["summary"] or "",
                 1 if inherited["move_summary"] else 0, rep["id"]),
            )
            stats["inherited"] += 1
            log(f"inherited status/notes for {rep['id']} from {inherited['from']}")
        written.add(rep["id"])
        for dup in members_by_rep.get(rep["id"], []):
            dup_fit, dup_reasons = score_by_id[dup["id"]]
            upsert(dup, dup_fit, dup_reasons, rep["id"])
            written.add(dup["id"])

    # Existing rows that are still active but were not selected (below the
    # threshold, outside the cap, or an unselected duplicate) still get current
    # machine fields. Status, notes, and edited summaries are untouched.
    for job_id, row in existing.items():
        if job_id in written or job_id not in active_by_id:
            continue
        fit, reasons = score_by_id[job_id]
        upsert(active_by_id[job_id], fit, reasons, rep_by_member.get(job_id))

    if fresh:
        stats["closed"] = con.execute(
            "UPDATE jobs SET closed_at=? WHERE closed_at IS NULL "
            "AND COALESCE(last_seen, 0) < ?", (now, now)).rowcount
    con.commit()

    log(f"{stats['active']} active; {stats['matched']} kept of {candidates} distinct "
        f"({stats['duplicates']} duplicate listings); {stats['inserted']} new, "
        f"{stats['updated']} updated, {stats['closed']} closed, "
        f"{stats['inherited']} human fields carried")
    return stats


def main(argv):
    refresh = "--refresh" in argv
    show_all = "--all" in argv
    dry_run = "--dry-run" in argv
    started = int(time.time())
    con = db.connect()

    run_id = None
    if not dry_run:
        cur = con.execute("INSERT INTO runs (started) VALUES (?)", (started,))
        run_id = cur.lastrowid
        con.commit()

    raw, fresh = fetch(refresh)
    db.log(f"loaded {len(raw)} records", run_id)
    if not fresh:
        db.log("cached feed: lifecycle fields left unchanged", run_id)

    stats = collect(
        con, raw, now=started, show_all=show_all, fresh=fresh, dry_run=dry_run,
        log=lambda msg: db.log(msg, run_id),
    )

    if dry_run:
        print(f"dry run: {stats['active']} active, {stats['candidates']} distinct candidates, "
              f"would insert {stats.get('would_insert', 0)}, "
              f"update {stats.get('would_update', 0)}, "
              f"close {stats.get('would_close', 0)}")
        con.close()
        return

    con.execute(
        """UPDATE runs SET finished=?, fetched=?, active=?, matched=?, inserted=?, updated=?,
           duplicates=?, closed=?, errors=?, note=? WHERE id=?""",
        (int(time.time()), stats["fetched"], stats["active"], stats["matched"],
         stats["inserted"], stats["updated"], stats["duplicates"], stats["closed"], "",
         "all" if show_all else f"MIN_FIT={P.MIN_FIT} MAX={P.MAX_JOBS}", run_id),
    )
    con.commit()

    c = db.counts(con)
    db.log(f"database now holds {c['total']} jobs ({c['open']} open, {c['closed']} closed, "
           f"{c['duplicates']} duplicates), {c['letters']} letters", run_id)
    db.log(f"run {run_id} complete", run_id)
    db.dump_json(con)
    db.log("wrote data/snapshot.json")
    con.close()


if __name__ == "__main__":
    main(sys.argv[1:])
