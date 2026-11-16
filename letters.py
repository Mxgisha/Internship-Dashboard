"""Generate cover-letter drafts from verified facts + the listing.

Deliberately refuses to invent the "why this company" paragraph. That sentence
has to come from you, so it is emitted as a marked placeholder.

Usage:
    python3 letters.py <job_id>          # write all variants for one job
    python3 letters.py --top 5           # write all variants for the 5 best jobs
"""
import os
import re
import sys
import time

import config
import db

try:
    import profile as P
except config.ConfigError as exc:  # a missing config should read as advice, not a traceback
    raise SystemExit(f"jobhunt: {exc}")

HERE = os.path.dirname(os.path.abspath(__file__))


def classify(job):
    """Pick which body paragraphs suit this listing."""
    blob = (job["title"] + " " + (job["category"] or "")).lower()
    if any(k in blob for k in ("consult", "product", "strategy", "analyst")):
        return "consulting"
    if any(k in blob for k in ("hardware", "electrical", "fpga", "asic", "embedded",
                               "firmware", "analog", "rf", "dsp", "silicon", "validation")):
        return "hardware"
    return "software"


def hook_placeholder(job):
    return (
        f"[HOOK — one sentence, delete the brackets: why {job['company']} specifically, and "
        f"why this role. Name something real: a product line, a talk, a paper, a person you "
        f"spoke to. This is the only sentence in the letter I cannot write for you.]"
    )


def build(job, variant):
    company = job["company"]
    title = job["title"]
    style = classify(job)

    text = P.LETTER_TEXT
    if variant == "technical":
        body = text["research"] + "\n\n" + text["building"]
    elif variant == "builder":
        body = text["building"] + "\n\n" + text["research"]
    else:
        body = text["communicating"] + "\n\n" + text["research"]

    if style == "hardware" and variant == "technical":
        closer = (
            "That habit of testing a model against the thing it replaces is the same one I would "
            "bring to silicon: a block is only correct if it matches the reference, and the job "
            "is finding where it does not."
        )
    elif style == "consulting":
        closer = (
            "What I would bring is comfort with an underspecified problem: I have started from a "
            "vague brief in a carpentry workshop, in a research group, and in my own codebase, "
            "and the useful skill in all three was breaking it into pieces I could test."
        )
    else:
        closer = (
            "What I care about is understanding why a system fails rather than getting it to "
            "compile, and that is the part of an internship I would want to spend the summer on."
        )

    identity = P.IDENTITY
    signoff = (f"\nSincerely,\n{identity['name']}\n"
               f"{identity['email']} | {identity['phone']}\n")
    return (
        f"Dear {company} Hiring Team,\n\n"
        f"I'm a {identity['year']} studying {identity['degree']} at {identity['school']}, and "
        f"I'm applying for the {title} role.\n\n"
        f"{hook_placeholder(job)}\n\n"
        f"{body}\n\n"
        f"{closer}\n\n"
        f"I'd welcome the chance to bring that to {company} this summer. Thank you for your "
        f"time and consideration.\n"
        f"{signoff}"
    )


def safe_name(s):
    return re.sub(r"[^A-Za-z0-9]+", "-", s).strip("-")[:60]


def write_letters(con, job_id):
    job = con.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    if not job:
        print(f"no job {job_id}")
        return 0
    os.makedirs(db.LETTERS, exist_ok=True)
    made = 0
    for variant in ("technical", "builder", "consulting"):
        text = build(job, variant)
        con.execute(
            """INSERT INTO letters (job_id, variant, body, created) VALUES (?,?,?,?)
               ON CONFLICT(job_id, variant) DO UPDATE SET body=excluded.body, created=excluded.created""",
            (job_id, variant, text, int(time.time())),
        )
        path = os.path.join(
            db.LETTERS,
            f"{safe_name(job['company'])}--{safe_name(job['title'])}--{variant}"
            f"--{safe_name(str(job['id']))[:8]}.md")
        with open(path, "w") as fh:
            fh.write(f"# {job['company']} — {job['title']}\n\n"
                     f"Fit {job['fit']} · {job['category']} · {job['url']}\n\n---\n\n{text}")
        made += 1
    con.commit()
    db.log(f"wrote {made} letter variants for {job['company']} — {job['title']}")
    return made


if __name__ == "__main__":
    con = db.connect()
    args = sys.argv[1:]
    if not args:
        print(__doc__)
    elif args[0] == "--top":
        n = int(args[1]) if len(args) > 1 else 5
        rows = con.execute("SELECT id FROM jobs ORDER BY fit DESC LIMIT ?", (n,)).fetchall()
        for r in rows:
            write_letters(con, r["id"])
    else:
        write_letters(con, args[0])
    con.close()
