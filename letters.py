"""Generate cover-letter drafts from verified facts + the listing.

Deliberately refuses to invent the "why this company" paragraph. That sentence
has to come from him, so it is emitted as a marked placeholder.

Usage:
    python3 letters.py <job_id>          # write all variants for one job
    python3 letters.py --top 5           # write all variants for the 5 best jobs
"""
import json
import os
import re
import sys
import time

import db

HERE = os.path.dirname(os.path.abspath(__file__))

# ---- Verified facts only. Do not add claims the repo cannot back. ----
FACTS = {
    "school": "Tufts University",
    "degree": "electrical engineering",
    "year": "sophomore",
    "gpa": "3.71",
}

RESEARCH = (
    "Over the summer I built a tested Python package for training and evaluating neural "
    "emulators of the Lorenz-63 chaotic system — about 6,700 lines, 106 tests, and eight "
    "diagnostics including Lyapunov spectra and correlation dimension. The part I am proudest "
    "of is unglamorous: I derived backpropagation by hand through a four-stage Runge-Kutta "
    "integrator and checked it against finite differences to 1e-10, because I did not want to "
    "trust a number I could not reproduce."
)

BUILDING = (
    "I also ship. I built an Android reader that reflows arXiv papers for phone screens — "
    "React Native and TypeScript, about 4,000 lines — where the interesting problem was "
    "restoring your reading position on a page whose height changes after it loads. I ended up "
    "storing a position and an anchor and re-applying the restore until the layout settled."
)

COMMUNICATING = (
    "I spend a lot of my time explaining technical things. I am a learning assistant for "
    "Physics 12 (electromagnetics), where I run small-group sessions and help redesign "
    "assessment. As a Career Center ambassador I grew event reach to over 600,000 impressions "
    "and advise students one-on-one on recruiting."
)

LIFE = (
    "Between high school and college I worked as an artisanal carpenter in Fiji, digitized a "
    "shipped library for students in Rwanda, and started a small bicycle business that I still "
    "run. I have used Linux since I was a child."
)

SIGNOFF = "\nSincerely,\nPeter Wiehler\npeter.wiehler@tufts.edu | (929) 216-8804\n"


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

    if variant == "technical":
        body = RESEARCH + "\n\n" + BUILDING
    elif variant == "builder":
        body = BUILDING + "\n\n" + RESEARCH
    else:
        body = COMMUNICATING + "\n\n" + RESEARCH

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

    return (
        f"Dear {company} Hiring Team,\n\n"
        f"I'm a {FACTS['year']} studying {FACTS['degree']} at {FACTS['school']}, and I'm "
        f"applying for the {title} role.\n\n"
        f"{hook_placeholder(job)}\n\n"
        f"{body}\n\n"
        f"{closer}\n\n"
        f"I'd welcome the chance to bring that to {company} this summer. Thank you for your "
        f"time and consideration.\n"
        f"{SIGNOFF}"
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
        path = os.path.join(db.LETTERS, f"{safe_name(job['company'])}--{safe_name(job['title'])}--{variant}.md")
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
