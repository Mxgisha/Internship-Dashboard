"""Collect listings, score them against profile.py, write to SQLite.

Usage:
    python3 collect.py             # use cached raw file
    python3 collect.py --refresh   # re-download the listings feed first
    python3 collect.py --all       # ignore MIN_FIT / MAX_JOBS
"""
import json
import os
import re
import sys
import time
import urllib.request

import db
import profile as P

HERE = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(HERE, "data", "listings_raw.json")
FEED = "https://raw.githubusercontent.com/SimplifyJobs/Summer2027-Internships/dev/.github/scripts/listings.json"


def fetch(refresh):
    os.makedirs(os.path.dirname(RAW), exist_ok=True)
    if refresh or not os.path.exists(RAW):
        db.log(f"fetching feed: {FEED}")
        req = urllib.request.Request(FEED, headers={"User-Agent": "jobhunt/0.1 (personal use)"})
        with urllib.request.urlopen(req, timeout=60) as r:
            data = r.read()
        with open(RAW, "wb") as fh:
            fh.write(data)
        db.log(f"downloaded {len(data) / 1e6:.1f} MB")
    else:
        db.log("using cached listings_raw.json (pass --refresh to update)")
    with open(RAW) as fh:
        return json.load(fh)


def as_list(v):
    if v is None:
        return []
    return v if isinstance(v, list) else [v]


def is_us(locations):
    """Deliberately strict. 'San Jose, CA' is US; 'Toronto, ON, Canada' is not;
    a bare 'SF' is US because it never carries a state code."""
    joined = " | ".join(locations)
    low = joined.lower()
    if any(w in low for w in P.NON_US_WORDS):
        return False
    if "remote" in low or "united states" in low or "usa" in low:
        return True
    for code in re.findall(r",\s*([A-Z]{2})\b", joined):
        if code in P.US_STATES:
            return True
    if re.search(r"\b(sf|nyc|bay area|silicon valley)\b", low):
        return True
    return False


def score(job):
    """Return (fit 0-100, list of human-readable reasons)."""
    pts, reasons = 0, []
    title = (job.get("title") or "").lower()
    terms = as_list(job.get("terms"))
    degrees = [d.lower() for d in as_list(job.get("degrees"))]
    locs = as_list(job.get("locations"))

    # Season
    best = None
    for t in terms:
        for season, w in P.SEASONS.items():
            if t.lower() == season.lower() and (best is None or w > best[1]):
                best = (t, w)
    if best:
        pts += best[1]
        reasons.append(f"+{best[1]} season {best[0]}")
    else:
        reasons.append("+0 season not targeted")
        pts -= 15

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
    if is_us(locs):
        pts += 10
        blob = " ".join(locs).lower()
        if any(p in blob for p in P.PREFERRED_LOCATIONS):
            pts += 8
            reasons.append("+18 US + near Boston/remote")
        else:
            reasons.append("+10 US")
    else:
        pts -= 15
        reasons.append("-15 outside US")

    # Freshness
    posted = job.get("date_posted") or 0
    age_days = (time.time() - posted) / 86400 if posted else 999
    if age_days < 7:
        pts += 10
        reasons.append("+10 posted <7d")
    elif age_days < 21:
        pts += 5
        reasons.append("+5 posted <21d")

    return max(0, min(100, pts)), reasons


def summary_for(company, active_roles):
    known = P.COMPANY_PROFILES.get(company)
    if known:
        return known
    return (f"No profile on file for {company}. {active_roles} active role(s) in this feed. "
            f"Edit this field to write your own summary.")


def main(argv):
    refresh = "--refresh" in argv
    show_all = "--all" in argv
    started = int(time.time())
    con = db.connect()
    cur = con.cursor()
    cur.execute("INSERT INTO runs (started) VALUES (?)", (started,))
    run_id = cur.lastrowid
    con.commit()

    raw = fetch(refresh)
    db.log(f"loaded {len(raw)} records", run_id)

    active = [j for j in raw if j.get("active")]
    db.log(f"{len(active)} active listings", run_id)

    # Count active roles per company for the auto summary.
    per_company = {}
    for j in active:
        per_company[j.get("company_name")] = per_company.get(j.get("company_name"), 0) + 1

    scored = []
    for j in active:
        fit, reasons = score(j)
        if not show_all and fit < P.MIN_FIT:
            continue
        scored.append((fit, reasons, j))
    scored.sort(key=lambda t: -t[0])
    db.log(f"{len(scored)} cleared MIN_FIT={P.MIN_FIT}", run_id)

    if not show_all:
        scored = scored[: P.MAX_JOBS]
        db.log(f"capped at MAX_JOBS={P.MAX_JOBS}", run_id)

    now = int(time.time())
    inserted = updated = 0
    for fit, reasons, j in scored:
        company = j.get("company_name") or "?"
        row = con.execute("SELECT id, status FROM jobs WHERE id=?", (j["id"],)).fetchone()
        payload = (
            company,
            j.get("title"),
            j.get("category"),
            j.get("url"),
            json.dumps(as_list(j.get("locations"))),
            json.dumps(as_list(j.get("terms"))),
            json.dumps(as_list(j.get("degrees"))),
            j.get("sponsorship"),
            j.get("date_posted") or 0,
            j.get("date_updated") or 0,
            fit,
            json.dumps(reasons),
            summary_for(company, per_company.get(company, 0)),
            now,
        )
        if row:
            con.execute(
                """UPDATE jobs SET company=?, title=?, category=?, url=?, locations=?, terms=?,
                   degrees=?, sponsorship=?, date_posted=?, date_updated=?, fit=?, reasons=?,
                   summary=CASE WHEN summary IS NULL OR summary='' THEN ? ELSE summary END,
                   last_seen=?
                   WHERE id=?""",
                payload + (j["id"],),
            )
            updated += 1
        else:
            con.execute(
                """INSERT INTO jobs (company, title, category, url, locations, terms, degrees,
                   sponsorship, date_posted, date_updated, fit, reasons, summary, first_seen, last_seen, id)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                payload[:-1] + (now, now, j["id"]),
            )
            inserted += 1
    con.commit()

    cur.execute(
        "UPDATE runs SET finished=?, fetched=?, active=?, matched=?, inserted=?, updated=?, note=? WHERE id=?",
        (int(time.time()), len(raw), len(active), len(scored), inserted, updated,
         "all" if show_all else f"MIN_FIT={P.MIN_FIT} MAX={P.MAX_JOBS}", run_id),
    )
    con.commit()

    db.log(f"inserted {inserted}, updated {updated}", run_id)
    c = db.counts(con)
    db.log(f"database now holds {c['total']} jobs, {c['letters']} letters", run_id)
    db.log(f"run {run_id} complete", run_id)
    db.dump_json(con)
    db.log("wrote data/snapshot.json")
    con.close()


if __name__ == "__main__":
    main(sys.argv[1:])
