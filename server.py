"""Local dashboard. Standard library only — no Flask, no build step.

    python3 server.py        ->  http://127.0.0.1:8099
"""
import html
import json
import os
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import config
import db

try:
    import letters as L
    import profile as P
except config.ConfigError as exc:  # a missing config should read as advice, not a traceback
    raise SystemExit(f"jobhunt: {exc}")

PORT = 8099
PAGE_SIZE = 50
HERE = os.path.dirname(os.path.abspath(__file__))

SORTS = {
    "fit": "fit DESC, date_posted DESC",
    "new": "date_posted DESC, fit DESC",
    "company": "company COLLATE NOCASE ASC, fit DESC",
}
SHOWS = {
    "open": "open",
    "closed": "closed",
    "duplicates": "duplicates",
    "all": "everything",
}

CSS = """
:root{--bg:#14161a;--panel:#1c1f26;--line:#2b3038;--tx:#e6e8ec;--dim:#8b93a1;--acc:#6ea8fe;--ok:#4ade80;--warn:#fbbf24}
*{box-sizing:border-box}
body{margin:0;font:14px/1.5 ui-sans-serif,system-ui,-apple-system,Segoe UI,Roboto,sans-serif;background:var(--bg);color:var(--tx)}
a{color:var(--acc);text-decoration:none}a:hover{text-decoration:underline}
header{padding:14px 20px;border-bottom:1px solid var(--line);display:flex;gap:18px;align-items:baseline;flex-wrap:wrap}
h1{font-size:15px;margin:0;font-weight:600;letter-spacing:.02em}
.wrap{padding:18px 20px;max-width:1400px}
.stats{display:flex;gap:16px;flex-wrap:wrap;margin-bottom:14px;color:var(--dim);font-size:13px}
.stats b{color:var(--tx)}
form.filters{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:16px}
input,select,textarea,button{background:var(--panel);color:var(--tx);border:1px solid var(--line);border-radius:6px;padding:7px 9px;font:inherit}
button{cursor:pointer}button:hover{border-color:var(--acc)}
button.primary{background:var(--acc);color:#0b1020;border-color:var(--acc);font-weight:600}
table{width:100%;border-collapse:collapse}
th{text-align:left;font-size:11px;text-transform:uppercase;letter-spacing:.06em;color:var(--dim);padding:6px 8px;border-bottom:1px solid var(--line);font-weight:600}
td{padding:8px;border-bottom:1px solid #22262d;vertical-align:top}
tr:hover td{background:#181b21}
.fit{font-variant-numeric:tabular-nums;font-weight:600;width:46px}
.bar{height:5px;background:#2b3038;border-radius:3px;width:70px;overflow:hidden;margin-top:3px}
.bar i{display:block;height:100%;background:var(--acc)}
.chip{display:inline-block;padding:1px 7px;border-radius:99px;font-size:11px;border:1px solid var(--line);color:var(--dim)}
.chip.applied{color:var(--ok);border-color:#27503a}.chip.shortlisted{color:var(--acc);border-color:#2b4a7a}
.chip.rejected{color:#ef4444;border-color:#5b2222}.chip.interviewing{color:var(--warn);border-color:#5c4a1a}
.chip.offer{color:var(--ok);border-color:#27503a}.chip.closed{color:#9aa4b2;border-color:#3a4048}
.chip.dup{color:var(--dim);border-style:dashed}
.dim{color:var(--dim)}.small{font-size:12px}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:16px;margin-bottom:16px}
.panel h2{font-size:12px;text-transform:uppercase;letter-spacing:.07em;color:var(--dim);margin:0 0 10px}
pre{white-space:pre-wrap;font:13px/1.6 ui-monospace,SFMono-Regular,Menlo,monospace;background:#111318;border:1px solid var(--line);border-radius:8px;padding:14px;margin:0}
ul.reasons{margin:0;padding-left:18px;color:var(--dim)}
ul.reasons li{font-size:12.5px}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:16px}
@media(max-width:1000px){.grid{grid-template-columns:1fr}}
.tag{font-size:11px;color:var(--dim);border:1px solid var(--line);border-radius:4px;padding:1px 6px;margin-right:4px}
.pager{display:flex;gap:12px;align-items:center;margin-top:14px;font-size:13px;color:var(--dim)}
"""


def esc(x):
    return html.escape(str(x if x is not None else ""))


def rget(row, key, default=""):
    try:
        value = row[key]
    except (IndexError, KeyError):
        return default
    return default if value is None else value


def _int_param(q, key, default, low=None, high=None):
    try:
        value = int(q.get(key, [default])[0])
    except (TypeError, ValueError):
        value = default
    if low is not None:
        value = max(low, value)
    if high is not None:
        value = min(high, value)
    return value


def _like(value):
    return "%" + value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def warnings_for(job):
    """Flag where a high-scoring job would still be hard to defend."""
    keys = job.keys()
    cat = (job["category"] if "category" in keys else "") or ""
    detail = (job["detail"] if "detail" in keys else "") or ""
    blob = f"{job['title']} {cat} {detail[:6000]}".lower()
    hits = [msg for kw, msg in P.GAP_WARNINGS.items() if kw in blob]
    return hits[:3]


def age(ts):
    if not ts:
        return "?"
    d = (time.time() - ts) / 86400
    if d >= 1:
        return f"{d:.0f}d"
    return f"{max(0, d * 24):.0f}h"


def page(title, body):
    return (f"<!doctype html><meta charset=utf-8><title>{esc(title)}</title>"
            f"<style>{CSS}</style>"
            f"<header><h1>job hunt</h1>"
            f"<a href='/'>feed</a><a href='/log'>log</a><a href='/runs'>runs</a>"
            f"<span class=dim style='margin-left:auto;font-size:12px'>{time.strftime('%b %d, %H:%M')}</span>"
            f"</header><div class=wrap>{body}</div>")


def _query(params, **overrides):
    values = dict(params)
    values.update(overrides)
    values = {k: v for k, v in values.items() if v not in (None, "")}
    return urllib.parse.urlencode(values)


def _pager(params, page_no, pages):
    if pages <= 1:
        return ""
    if page_no > 1:
        prev = f"<a href='?{_query(params, page=page_no - 1)}'>&larr; prev</a>"
    else:
        prev = "<span>&larr; prev</span>"
    if page_no < pages:
        nxt = f"<a href='?{_query(params, page=page_no + 1)}'>next &rarr;</a>"
    else:
        nxt = "<span>next &rarr;</span>"
    return (f"<div class=pager>{prev}<span>page {page_no} of {pages}</span>{nxt}</div>")


def list_page(con, q):
    needle = q.get("q", [""])[0].strip()
    status = q.get("status", [""])[0]
    if status not in db.STATUSES:
        status = ""
    cat = q.get("cat", [""])[0]

    show = q.get("show", ["open"])[0]
    if show not in SHOWS:
        show = "open"
    default_min = 0 if show != "open" else P.MIN_FIT
    min_fit = _int_param(q, "min_fit", default_min, 0, 100)
    sort = q.get("sort", ["fit"])[0]
    if sort not in SORTS:
        sort = "fit"
    page_no = _int_param(q, "page", 1, 1, 10**6)

    where, args = ["1=1"], []
    if show == "closed":
        where.append("closed_at IS NOT NULL")
    elif show == "duplicates":
        where.append("duplicate_of IS NOT NULL")
    elif show == "all":
        pass
    else:
        where.append("closed_at IS NULL")
        where.append("duplicate_of IS NULL")
    where.append("fit >= ?")
    args.append(min_fit)
    if status:
        where.append("status=?")
        args.append(status)
    if cat:
        where.append("category=?")
        args.append(cat)
    if needle:
        where.append("(company LIKE ? ESCAPE '\\' OR title LIKE ? ESCAPE '\\')")
        args += [_like(needle), _like(needle)]

    clauses = " AND ".join(where)
    total = con.execute(f"SELECT COUNT(*) FROM jobs WHERE {clauses}", args).fetchone()[0]
    pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    page_no = min(page_no, pages)
    offset = (page_no - 1) * PAGE_SIZE
    rows = con.execute(
        f"SELECT * FROM jobs WHERE {clauses} ORDER BY {SORTS[sort]} LIMIT ? OFFSET ?",
        args + [PAGE_SIZE, offset],
    ).fetchall()

    c = db.counts(con)
    cats = [r["category"] for r in con.execute(
        "SELECT category, COUNT(*) n FROM jobs GROUP BY category ORDER BY n DESC") if r["category"]]

    stat_line = " · ".join(
        f"<b>{esc(label)}</b> {esc(value)}" for label, value in [
            ("open", c.get("open", 0)),
            ("new", c.get("new", 0)),
            ("shortlisted", c.get("shortlisted", 0)),
            ("applied", c.get("applied", 0)),
            ("closed", c.get("closed", 0)),
            ("letters", c["letters"]),
        ])

    last = con.execute(
        "SELECT * FROM runs WHERE finished IS NOT NULL ORDER BY id DESC LIMIT 1").fetchone()
    last_line = (f"last collect {age(last['started'])} ago · {last['matched']} kept"
                 if last else "no successful collection yet")

    def opt(value, current, label=None):
        selected = " selected" if str(current) == str(value) else ""
        return f"<option value='{esc(value)}'{selected}>{esc(label or value)}</option>"

    cat_opts = "<option value=''>all categories</option>" + "".join(
        opt(x, cat) for x in cats)
    status_opts = "<option value=''>all statuses</option>" + "".join(
        opt(s, status) for s in db.STATUSES)
    sort_opts = "".join(opt(k, sort, k) for k in SORTS)
    show_opts = "".join(opt(k, show, label) for k, label in SHOWS.items())

    trs = []
    for r in rows:
        locs = json.loads(r["locations"] or "[]")
        loc = ", ".join(locs[:2]) + (" +" + str(len(locs) - 2) if len(locs) > 2 else "")
        chips = f"<span class='chip {esc(r['status'])}'>{esc(r['status'])}</span>"
        if rget(r, "closed_at"):
            chips += " <span class='chip closed'>closed</span>"
        if rget(r, "duplicate_of"):
            chips += f" <a class='chip dup' href='/job/{urllib.parse.quote(rget(r, 'duplicate_of'))}'>duplicate</a>"
        trs.append(
            f"<tr><td class=fit>{r['fit']}<div class=bar><i style='width:{r['fit']}%'></i></div></td>"
            f"<td><a href='/job/{urllib.parse.quote(r['id'])}'>{esc(r['company'])}</a>"
            f"<div class=dim small>{esc(r['category'])}</div></td>"
            f"<td>{esc(r['title'])}</td>"
            f"<td class=dim small>{esc(loc)}</td>"
            f"<td class=dim small>{age(r['date_posted'])}</td>"
            f"<td>{chips}</td>"
            f"<td><a href='{esc(r['url'])}' target=_blank rel=noopener>open</a></td></tr>")

    if rows:
        showing = f"showing {offset + 1}&ndash;{offset + len(rows)} of {total}"
    elif show == "closed":
        showing = "no closed postings match"
    elif show == "duplicates":
        showing = "no duplicate postings match"
    else:
        showing = "no jobs match; run <code>python3 collect.py</code> or widen the filters"

    params = {"q": needle, "cat": cat, "status": status, "min_fit": min_fit,
              "sort": sort, "show": show}

    body = f"""
<div class=stats>{stat_line}</div>
<div class=dim small style="margin-bottom:10px">{esc(last_line)} · {showing}</div>
<form class=filters method=get>
  <input name=q placeholder="company or title" value="{esc(needle)}">
  <select name=cat>{cat_opts}</select>
  <select name=status>{status_opts}</select>
  <select name=show>{show_opts}</select>
  <select name=sort>{sort_opts}</select>
  <input name=min_fit type=number min=0 max=100 value="{esc(min_fit)}" style="width:90px" title="min fit">
  <button>filter</button>
</form>
<table><thead><tr><th>fit</th><th>company</th><th>role</th><th>location</th><th>posted</th><th>status</th><th></th></tr></thead>
<tbody>{''.join(trs) or '<tr><td colspan=7 class=dim>' + showing + '</td></tr>'}</tbody></table>
{_pager(params, page_no, pages)}
"""
    return page("feed", body)


def job_page(con, job_id):
    j = con.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    if not j:
        return page("missing", "<p>No such job. <a href='/'>back</a></p>"), 404

    reasons = json.loads(j["reasons"] or "[]")
    locs = json.loads(j["locations"] or "[]")
    terms = json.loads(j["terms"] or "[]")
    lets = con.execute("SELECT variant, body, created FROM letters WHERE job_id=? ORDER BY variant",
                       (job_id,)).fetchall()

    opts = "".join(
        f"<option value='{s}'{' selected' if s == j['status'] else ''}>{s}</option>"
        for s in db.STATUSES)

    letter_html = ""
    for letter in lets:
        letter_html += (f"<h3 class=small style='margin:14px 0 6px;color:var(--dim)'>"
                        f"{esc(letter['variant'])}</h3><pre>{esc(letter['body'])}</pre>")
    if not lets:
        letter_html = "<p class=dim small>No drafts yet. Generate them below.</p>"

    hits = warnings_for(j)
    warn_html = ("<div class=panel style='border-color:#5c4a1a'><h2 style='color:var(--warn)'>"
                 "Defend this before you apply</h2><ul class=reasons>"
                 + "".join(f"<li>{esc(h)}</li>" for h in hits) + "</ul></div>") if hits else ""

    badges = f"<span class='chip {esc(j['status'])}'>{esc(j['status'])}</span>"
    if rget(j, "closed_at"):
        badges += " <span class='chip closed'>closed " + esc(age(j["closed_at"])) + " ago</span>"
    duplicate_of = rget(j, "duplicate_of")
    if duplicate_of:
        badges += (f" <span class='chip dup'>duplicate of "
                   f"<a href='/job/{urllib.parse.quote(duplicate_of)}'>the representative</a></span>")
    edited = rget(j, "summary_edited", 0)

    body = f"""
<p class=small><a href='/'>&larr; feed</a></p>
<div class=panel>
  <h2>{esc(j['company'])}</h2>
  <div style="font-size:17px;font-weight:600;margin-bottom:6px">{esc(j['title'])}</div>
  <div class=stats style="margin:0 0 12px">
    <span>fit <b>{j['fit']}</b></span><span>category <b>{esc(j['category'])}</b></span>
    <span>posted <b>{age(j['date_posted'])}</b> ago</span><span>terms <b>{esc(', '.join(terms))}</b></span>
    <span>sponsorship <b>{esc(j['sponsorship'])}</b></span>
    <span>source <b>{esc(rget(j, 'source', 'simplify'))}</b></span>
  </div>
  <div class=small style="margin-bottom:10px">{badges}</div>
  <div class=small><span class=tag>locations</span>{esc(', '.join(locs))}</div>
  <p><a href='{esc(j['url'])}' target=_blank rel=noopener>Open original posting &rarr;</a></p>
  <form method=post action='/update' style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
    <input type=hidden name=id value="{esc(j['id'])}">
    <select name=status>{opts}</select>
    <button class=primary>save status</button>
    <span class=dim small>changed {esc(age(rget(j, 'status_changed_at', 0)))} ago</span>
  </form>
</div>

{warn_html}
<div class=grid>
  <div class=panel><h2>Why this scored {j['fit']}</h2><ul class=reasons>{''.join(f'<li>{esc(r)}</li>' for r in reasons)}</ul></div>
  <div class=panel>
    <h2>Company summary</h2>
    <p class=small>{esc(j['summary'])}</p>
    <form method=post action='/summary'>
      <input type=hidden name=id value="{esc(j['id'])}">
      <textarea name=summary rows=4 style="width:100%">{esc(j['summary'])}</textarea>
      <div style="margin-top:8px;display:flex;gap:8px;align-items:center">
        <button class=primary>save summary</button>
        <button name=action value=reset>reset to auto</button>
        <span class=dim small>{'edited by you' if edited else 'auto-generated'}</span>
      </div>
    </form>
  </div>
</div>

<div class=panel>
  <h2>Cover letter drafts</h2>
  <form method=post action='/letter' style="margin-bottom:10px">
    <input type=hidden name=id value="{esc(j['id'])}">
    <button class=primary>generate / refresh 3 variants</button>
    <span class=dim small>&nbsp;saved to letters/</span>
  </form>
  {letter_html}
</div>

<div class=panel>
  <h2>Notes</h2>
  <form method=post action='/notes'>
    <input type=hidden name=id value="{esc(j['id'])}">
    <textarea name=notes rows=5 style="width:100%">{esc(j['notes'])}</textarea>
    <div style="margin-top:8px"><button class=primary>save notes</button></div>
  </form>
</div>
"""
    return page(j["company"], body), 200


def log_page(con):
    path = os.path.join(db.LOGS, "collect.log")
    if os.path.exists(path):
        with open(path) as fh:
            text = fh.read()[-40000:]
    else:
        text = "no log yet"
    return page("log", f"<div class=panel><h2>collect.log</h2><pre>{esc(text)}</pre></div>")


def runs_page(con):
    rows = con.execute("SELECT * FROM runs ORDER BY id DESC LIMIT 30").fetchall()
    trs = []
    for r in rows:
        duration = (r["finished"] - r["started"]) if r["finished"] and r["started"] else 0
        trs.append(
            f"<tr><td>{r['id']}</td>"
            f"<td class=dim>{time.strftime('%Y-%m-%d %H:%M', time.localtime(r['started'] or 0))}</td>"
            f"<td>{rget(r, 'fetched', '')}</td><td>{rget(r, 'active', '')}</td>"
            f"<td>{rget(r, 'matched', '')}</td><td>{rget(r, 'inserted', '')}</td>"
            f"<td>{rget(r, 'updated', '')}</td><td>{rget(r, 'duplicates', '')}</td>"
            f"<td>{rget(r, 'closed', '')}</td><td class=dim>{duration}s</td>"
            f"<td class=dim small>{esc(rget(r, 'note', ''))}</td></tr>")
    body = ("<div class=panel><h2>collection runs</h2><table><thead><tr><th>#</th><th>when</th>"
            "<th>fetched</th><th>active</th><th>kept</th><th>new</th><th>upd</th><th>dup</th>"
            "<th>closed</th><th>dur</th><th>note</th>"
            f"</tr></thead><tbody>{''.join(trs) or '<tr><td colspan=11 class=dim>no runs</td></tr>'}</tbody></table>"
            f"</div>")
    return page("runs", body)


class Handler(BaseHTTPRequestHandler):
    def _send(self, body, code=200, ctype="text/html; charset=utf-8"):
        data = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):
        pass

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(u.query)
        con = db.connect()
        try:
            if u.path == "/":
                self._send(list_page(con, q))
            elif u.path.startswith("/job/"):
                body, code = job_page(con, urllib.parse.unquote(u.path[5:]))
                self._send(body, code)
            elif u.path == "/log":
                self._send(log_page(con))
            elif u.path == "/runs":
                self._send(runs_page(con))
            elif u.path == "/health":
                self._send("ok\n", ctype="text/plain; charset=utf-8")
            else:
                self._send(page("404", "<p>Not found. <a href='/'>feed</a></p>"), 404)
        finally:
            con.close()

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0) or 0)
        form = urllib.parse.parse_qs(self.rfile.read(n).decode("utf-8", "replace"))
        job_id = form.get("id", [""])[0]
        con = db.connect()
        try:
            row = con.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            if not row:
                self._send(page("missing", "<p>No such job. <a href='/'>back</a></p>"), 404)
                return

            if self.path == "/update":
                status = form.get("status", ["new"])[0]
                if status in db.STATUSES and status != row["status"]:
                    con.execute("UPDATE jobs SET status=?, status_changed_at=? WHERE id=?",
                                (status, int(time.time()), job_id))
                    con.commit()
                    db.log(f"status {row['status']} -> {status}: {job_id}")
                self._redirect(f"/job/{urllib.parse.quote(job_id)}")
            elif self.path == "/notes":
                con.execute("UPDATE jobs SET notes=? WHERE id=?",
                            (form.get("notes", [""])[0][:20000], job_id))
                con.commit()
                self._redirect(f"/job/{urllib.parse.quote(job_id)}")
            elif self.path == "/summary":
                if form.get("action", ["save"])[0] == "reset":
                    count = con.execute(
                        "SELECT COUNT(*) FROM jobs WHERE company=? AND closed_at IS NULL",
                        (row["company"],)).fetchone()[0]
                    con.execute("UPDATE jobs SET summary=?, summary_edited=0 WHERE id=?",
                                (P.company_summary(row["company"], count), job_id))
                    db.log(f"summary reset to auto: {job_id}")
                else:
                    con.execute("UPDATE jobs SET summary=?, summary_edited=1 WHERE id=?",
                                (form.get("summary", [""])[0][:5000], job_id))
                    db.log(f"summary edited: {job_id}")
                con.commit()
                self._redirect(f"/job/{urllib.parse.quote(job_id)}")
            elif self.path == "/letter":
                L.write_letters(con, job_id)
                self._redirect(f"/job/{urllib.parse.quote(job_id)}")
            else:
                self._send("bad request", 400)
        finally:
            con.close()

    def _redirect(self, to):
        self.send_response(303)
        self.send_header("Location", to)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()


if __name__ == "__main__":
    con = db.connect()
    c = db.counts(con)
    con.close()
    print(f"jobhunt dashboard -> http://127.0.0.1:{PORT}")
    print(f"database: {db.DB_PATH} ({c['total']} jobs, {c['open']} open, {c['letters']} letters)")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
