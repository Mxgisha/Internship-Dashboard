"""Local dashboard. Standard library only — no Flask, no build step.

    python3 server.py        ->  http://127.0.0.1:8099
"""
import html
import json
import os
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import db
import letters as L
import profile as P

PORT = 8099
HERE = os.path.dirname(os.path.abspath(__file__))

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
.dim{color:var(--dim)}.small{font-size:12px}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:16px;margin-bottom:16px}
.panel h2{font-size:12px;text-transform:uppercase;letter-spacing:.07em;color:var(--dim);margin:0 0 10px}
pre{white-space:pre-wrap;font:13px/1.6 ui-monospace,SFMono-Regular,Menlo,monospace;background:#111318;border:1px solid var(--line);border-radius:8px;padding:14px;margin:0}
ul.reasons{margin:0;padding-left:18px;color:var(--dim)}
ul.reasons li{font-size:12.5px}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:16px}
@media(max-width:1000px){.grid{grid-template-columns:1fr}}
.tag{font-size:11px;color:var(--dim);border:1px solid var(--line);border-radius:4px;padding:1px 6px;margin-right:4px}
"""


def esc(x):
    return html.escape(str(x if x is not None else ""))


def warnings_for(job):
    """Flag where a high-scoring job would still be hard to defend."""
    keys = job.keys()
    cat = (job["category"] if "category" in keys else "") or ""
    blob = f"{job['title']} {cat}".lower()
    hits = [msg for kw, msg in P.GAP_WARNINGS.items() if kw in blob]
    return hits[:3]


def age(ts):
    if not ts:
        return "?"
    d = (time.time() - ts) / 86400
    return f"{d:.0f}d" if d >= 1 else f"{d * 24:.0f}h"


def page(title, body):
    return (f"<!doctype html><meta charset=utf-8><title>{esc(title)}</title>"
            f"<style>{CSS}</style>"
            f"<header><h1>job hunt</h1>"
            f"<a href='/'>feed</a><a href='/log'>log</a><a href='/runs'>runs</a>"
            f"<span class=dim style='margin-left:auto;font-size:12px'>{time.strftime('%b %d, %H:%M')}</span>"
            f"</header><div class=wrap>{body}</div>")


def list_page(con, q):
    status = q.get("status", [""])[0]
    cat = q.get("cat", [""])[0]
    needle = q.get("q", [""])[0].strip()
    min_fit = q.get("min_fit", ["45"])[0] or 45

    sql = "SELECT * FROM jobs WHERE fit >= ?"
    args = [int(min_fit)]
    if status:
        sql += " AND status=?"
        args.append(status)
    if cat:
        sql += " AND category=?"
        args.append(cat)
    if needle:
        sql += " AND (company LIKE ? OR title LIKE ?)"
        args += [f"%{needle}%", f"%{needle}%"]
    sql += " ORDER BY fit DESC, date_posted DESC LIMIT 300"
    rows = con.execute(sql, args).fetchall()

    c = db.counts(con)
    cats = [r["category"] for r in con.execute(
        "SELECT category, COUNT(*) n FROM jobs GROUP BY category ORDER BY n DESC")]

    stat_line = " · ".join(f"<b>{esc(k)}</b> {esc(v)}" for k, v in
                           [("jobs", c["total"]), ("new", c.get("new", 0)),
                            ("shortlisted", c.get("shortlisted", 0)),
                            ("applied", c.get("applied", 0)),
                            ("letters", c["letters"])])

    def opt(val, cur, label=None):
        sel = " selected" if str(cur) == str(val) else ""
        return f"<option value='{esc(val)}'{sel}>{esc(label or val)}</option>"

    cat_opts = "<option value=''>all categories</option>" + "".join(
        opt(x, cat) for x in cats if x)
    status_opts = "<option value=''>all statuses</option>" + "".join(
        opt(s, status) for s in db.STATUSES)

    trs = []
    for r in rows:
        locs = json.loads(r["locations"] or "[]")
        loc = ", ".join(locs[:2]) + (" +" + str(len(locs) - 2) if len(locs) > 2 else "")
        trs.append(
            f"<tr><td class=fit>{r['fit']}<div class=bar><i style='width:{r['fit']}%'></i></div></td>"
            f"<td><a href='/job/{esc(r['id'])}'>{esc(r['company'])}</a><div class=dim small>{esc(r['category'])}</div></td>"
            f"<td>{esc(r['title'])}</td>"
            f"<td class=dim small>{esc(loc)}</td>"
            f"<td class=dim small>{age(r['date_posted'])}</td>"
            f"<td><span class='chip {esc(r['status'])}'>{esc(r['status'])}</span></td>"
            f"<td><a href='{esc(r['url'])}' target=_blank rel=noopener>open</a></td></tr>")

    body = f"""
<div class=stats>{stat_line}</div>
<form class=filters method=get>
  <input name=q placeholder="company or title" value="{esc(needle)}">
  <select name=cat>{cat_opts}</select>
  <select name=status>{status_opts}</select>
  <input name=min_fit type=number min=0 max=100 value="{esc(min_fit)}" style="width:90px" title="min fit">
  <button>filter</button>
</form>
<table><thead><tr><th>fit</th><th>company</th><th>role</th><th>location</th><th>posted</th><th>status</th><th></th></tr></thead>
<tbody>{''.join(trs) or '<tr><td colspan=7 class=dim>No jobs match. Run <code>python3 collect.py</code>.</td></tr>'}</tbody></table>
"""
    return page("feed", body)


def job_page(con, job_id, msg=""):
    j = con.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    if not j:
        return page("missing", "<p>No such job. <a href='/'>back</a></p>")
    reasons = json.loads(j["reasons"] or "[]")
    locs = json.loads(j["locations"] or "[]")
    terms = json.loads(j["terms"] or "[]")
    lets = con.execute("SELECT variant, body, created FROM letters WHERE job_id=? ORDER BY variant",
                       (job_id,)).fetchall()

    opts = "".join(
        f"<option value='{s}'{' selected' if s == j['status'] else ''}>{s}</option>"
        for s in db.STATUSES)

    letter_html = ""
    for l in lets:
        letter_html += (f"<h3 class=small style='margin:14px 0 6px;color:var(--dim)'>"
                        f"{esc(l['variant'])}</h3><pre>{esc(l['body'])}</pre>")
    if not lets:
        letter_html = "<p class=dim small>No drafts yet. Generate them below.</p>"

    hits = warnings_for(j)
    warn_html = ("<div class=panel style='border-color:#5c4a1a'><h2 style='color:var(--warn)'>"
                 "Defend this before you apply</h2><ul class=reasons>"
                 + "".join(f"<li>{esc(h)}</li>" for h in hits) + "</ul></div>") if hits else ""

    body = f"""
<p class=small><a href='/'>&larr; feed</a></p>
<div class=panel>
  <h2>{esc(j['company'])}</h2>
  <div style="font-size:17px;font-weight:600;margin-bottom:6px">{esc(j['title'])}</div>
  <div class=stats style="margin:0 0 12px">
    <span>fit <b>{j['fit']}</b></span><span>category <b>{esc(j['category'])}</b></span>
    <span>posted <b>{age(j['date_posted'])}</b> ago</span><span>terms <b>{esc(', '.join(terms))}</b></span>
    <span>sponsorship <b>{esc(j['sponsorship'])}</b></span>
  </div>
  <div class=small><span class=tag>locations</span>{esc(', '.join(locs))}</div>
  <p><a href='{esc(j['url'])}' target=_blank rel=noopener>Open original posting &rarr;</a></p>
  <form method=post action='/update' style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
    <input type=hidden name=id value="{esc(j['id'])}">
    <select name=status>{opts}</select>
    <button class=primary>save status</button>
  </form>
</div>

{warn_html}
<div class=grid>
  <div class=panel><h2>Why this scored {j['fit']}</h2><ul class=reasons>{''.join(f'<li>{esc(r)}</li>' for r in reasons)}</ul></div>
  <div class=panel><h2>Company summary</h2><p class=small>{esc(j['summary'])}</p></div>
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
{('<div class=panel><b>'+esc(msg)+'</b></div>') if msg else ''}
"""
    return page(j["company"], body)


def log_page(con):
    path = os.path.join(db.LOGS, "collect.log")
    text = open(path).read()[-40000:] if os.path.exists(path) else "no log yet"
    return page("log", f"<div class=panel><h2>collect.log</h2><pre>{esc(text)}</pre></div>")


def runs_page(con):
    rows = con.execute("SELECT * FROM runs ORDER BY id DESC LIMIT 30").fetchall()
    trs = []
    for r in rows:
        dur = (r["finished"] - r["started"]) if r["finished"] and r["started"] else 0
        trs.append(f"<tr><td>{r['id']}</td><td class=dim>{time.strftime('%Y-%m-%d %H:%M', time.localtime(r['started'] or 0))}</td>"
                   f"<td>{r['fetched']}</td><td>{r['active']}</td><td>{r['matched']}</td>"
                   f"<td>{r['inserted']}</td><td>{r['updated']}</td><td class=dim>{dur}s</td>"
                   f"<td class=dim small>{esc(r['note'])}</td></tr>")
    body = ("<div class=panel><h2>collection runs</h2><table><thead><tr><th>#</th><th>when</th>"
            "<th>fetched</th><th>active</th><th>matched</th><th>new</th><th>upd</th><th>dur</th><th>note</th>"
            f"</tr></thead><tbody>{''.join(trs) or '<tr><td colspan=9 class=dim>no runs</td></tr>'}</tbody></table>"
            f"</div>")
    return page("runs", body)


class Handler(BaseHTTPRequestHandler):
    def _send(self, body, code=200):
        data = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
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
                self._send(job_page(con, u.path[5:]))
            elif u.path == "/log":
                self._send(log_page(con))
            elif u.path == "/runs":
                self._send(runs_page(con))
            elif u.path == "/health":
                self._send("ok")
            else:
                self._send(page("404", "<p>Not found. <a href='/'>feed</a></p>"), 404)
        finally:
            con.close()

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        form = urllib.parse.parse_qs(self.rfile.read(n).decode())
        job_id = form.get("id", [""])[0]
        con = db.connect()
        try:
            if self.path == "/update":
                st = form.get("status", ["new"])[0]
                if st in db.STATUSES:
                    con.execute("UPDATE jobs SET status=? WHERE id=?", (st, job_id))
                    con.commit()
                    db.log(f"status -> {st}: {job_id}")
                self._redirect(f"/job/{job_id}")
            elif self.path == "/notes":
                con.execute("UPDATE jobs SET notes=? WHERE id=?", (form.get("notes", [""])[0], job_id))
                con.commit()
                self._redirect(f"/job/{job_id}")
            elif self.path == "/letter":
                L.write_letters(con, job_id)
                self._redirect(f"/job/{job_id}")
            else:
                self._send("bad request", 400)
        finally:
            con.close()

    def _redirect(self, to):
        self.send_response(303)
        self.send_header("Location", to)
        self.end_headers()


if __name__ == "__main__":
    con = db.connect()
    c = db.counts(con)
    con.close()
    print(f"jobhunt dashboard -> http://127.0.0.1:{PORT}")
    print(f"database: {db.DB_PATH} ({c['total']} jobs, {c['letters']} letters)")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
