"""Minimal Markdown -> HTML -> PDF, for BRIEF.md and any other project doc.

    python3 tools/md2pdf.py BRIEF.md

Supports headings, tables (with \\| escapes), bold/italic/code, fenced code, ordered and
unordered lists **with lazy continuation lines**, blockquotes, rules, and task checkboxes.
Unicode math passes through untouched.

Requires Chromium for the PDF step; skips the PDF if Chromium is absent.
"""
import html
import os
import re
import shutil
import subprocess
import sys

CSS = """
@page { size: Letter; margin: 0.62in 0.68in; }
body { font-family: "Helvetica Neue", Helvetica, Arial, "Liberation Sans", sans-serif;
       font-size: 9.4pt; line-height: 1.38; color: #111; margin: 0; }
h1 { font-size: 17pt; margin: 0 0 5pt; border-bottom: 2px solid #111; padding-bottom: 3pt; }
h2 { font-size: 11.4pt; margin: 13pt 0 4pt; padding-bottom: 2pt; border-bottom: 1px solid #bbb; }
h3 { font-size: 10pt; margin: 10pt 0 3pt; }
p { margin: 0 0 5pt; }
ul, ol { margin: 2pt 0 6pt; padding-left: 18pt; }
li { margin-bottom: 2.2pt; }
table { border-collapse: collapse; width: 100%; margin: 5pt 0 8pt; font-size: 8.9pt; }
th, td { border: 1px solid #c9c9c9; padding: 3pt 5pt; text-align: left; vertical-align: top; }
th { background: #eee; font-weight: 700; }
code { font-family: "DejaVu Sans Mono", monospace; font-size: 8.7pt; background: #f2f2f2;
       padding: 0 2pt; border-radius: 2px; }
pre { font-family: "DejaVu Sans Mono", monospace; font-size: 8.3pt; background: #f6f6f6;
      border: 1px solid #ddd; padding: 6pt 8pt; white-space: pre-wrap; }
hr { border: none; border-top: 1px solid #ccc; margin: 9pt 0; }
blockquote { margin: 5pt 0; padding: 4pt 9pt; border-left: 3px solid #bbb; background: #fafafa; }
.chk { list-style: none; margin-left: -13pt; }
"""

BULLET = re.compile(r"^(\s*)([-*+])\s+(.*)$")
ORDERED = re.compile(r"^(\s*)(\d+)[.)]\s+(.*)$")
STOP = re.compile(r"^(#{1,6}\s|\s*(---|\*\*\*|___)\s*$|>|\s*```)")


def inline(t):
    t = html.escape(t, quote=False)
    t = re.sub(r"`([^`]+)`", r"<code>\1</code>", t)
    t = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", t)
    t = re.sub(r"(?<![\w*])\*([^*\n]+)\*(?![\w*])", r"<em>\1</em>", t)
    return t


def split_row(line):
    line = line.strip().strip("|")
    cells, buf, esc = [], "", False
    for ch in line:
        if esc:
            buf += ch
            esc = False
        elif ch == "\\":
            esc = True
        elif ch == "|":
            cells.append(buf.strip())
            buf = ""
        else:
            buf += ch
    cells.append(buf.strip())
    return cells


def gather(lines, i, first, regex):
    """Collect one list item plus its lazy continuation lines."""
    text = regex.match(first).group(3).strip()
    i += 1
    while i < len(lines):
        nxt = lines[i]
        if not nxt.strip() or STOP.match(nxt) or BULLET.match(nxt) or ORDERED.match(nxt):
            break
        if "|" in nxt and nxt.strip().startswith("|"):
            break
        text += " " + nxt.strip()
        i += 1
    return text, i


def convert(md):
    out, lines, i = [], md.split("\n"), 0
    while i < len(lines):
        ln = lines[i]

        if ln.strip().startswith("```"):
            i += 1
            buf = []
            while i < len(lines) and not lines[i].strip().startswith("```"):
                buf.append(lines[i])
                i += 1
            i += 1
            out.append("<pre>" + html.escape("\n".join(buf)) + "</pre>")
            continue

        m = re.match(r"^(#{1,6})\s+(.*)$", ln)
        if m:
            n = len(m.group(1))
            out.append(f"<h{n}>{inline(m.group(2))}</h{n}>")
            i += 1
            continue

        if re.match(r"^\s*(---|\*\*\*|___)\s*$", ln):
            out.append("<hr>")
            i += 1
            continue

        if "|" in ln and i + 1 < len(lines) and re.match(
                r"^\s*\|?[\s:|-]*-{2,}[\s:|-]*\|?\s*$", lines[i + 1]):
            head = split_row(ln)
            i += 2
            body = []
            while i < len(lines) and lines[i].strip() and "|" in lines[i]:
                body.append(split_row(lines[i]))
                i += 1
            t = ["<table><thead><tr>", *[f"<th>{inline(c)}</th>" for c in head],
                 "</tr></thead><tbody>"]
            for r in body:
                t.append("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in r) + "</tr>")
            t.append("</tbody></table>")
            out.append("".join(t))
            continue

        if BULLET.match(ln):
            items = []
            while i < len(lines) and BULLET.match(lines[i]):
                txt, i = gather(lines, i, lines[i], BULLET)
                if txt.startswith("[ ]"):
                    items.append(f'<li class="chk">☐ {inline(txt[3:].strip())}</li>')
                elif txt.startswith("[x]"):
                    items.append(f'<li class="chk">☑ {inline(txt[3:].strip())}</li>')
                else:
                    items.append(f"<li>{inline(txt)}</li>")
            out.append("<ul>" + "".join(items) + "</ul>")
            continue

        if ORDERED.match(ln):
            items = []
            while i < len(lines) and ORDERED.match(lines[i]):
                txt, i = gather(lines, i, lines[i], ORDERED)
                items.append(f"<li>{inline(txt)}</li>")
            out.append("<ol>" + "".join(items) + "</ol>")
            continue

        if ln.strip().startswith(">"):
            buf = []
            while i < len(lines) and lines[i].strip().startswith(">"):
                buf.append(lines[i].strip().lstrip(">").strip())
                i += 1
            out.append("<blockquote>" + inline(" ".join(buf)) + "</blockquote>")
            continue

        if not ln.strip():
            i += 1
            continue

        buf = [ln.strip()]
        i += 1
        while i < len(lines) and lines[i].strip() and not STOP.match(lines[i]) \
                and not BULLET.match(lines[i]) and not ORDERED.match(lines[i]) \
                and not (lines[i].strip().startswith("|") and "|" in lines[i]):
            buf.append(lines[i].strip())
            i += 1
        out.append("<p>" + inline(" ".join(buf)) + "</p>")

    return "<!doctype html><meta charset='utf-8'><style>" + CSS + "</style>" + "\n".join(out)


def build(path):
    base = os.path.splitext(path)[0]
    hp = base + ".html"
    open(hp, "w").write(convert(open(path).read()))
    pdf = base + ".pdf"
    prof = os.path.join(os.path.dirname(os.path.abspath(__file__)) or ".", ".chromium")
    if shutil.which("chromium"):
        os.makedirs(prof, exist_ok=True)
        subprocess.run(["chromium", "--headless", "--disable-gpu", "--no-sandbox",
                        "--no-pdf-header-footer", f"--user-data-dir={prof}",
                        f"--print-to-pdf={pdf}", "file://" + os.path.abspath(hp)],
                       capture_output=True)
        shutil.rmtree(prof, ignore_errors=True)
        print(f"{os.path.basename(pdf)}  {os.path.getsize(pdf)}b")
    else:
        print(f"{os.path.basename(hp)}  (no chromium — HTML only)")


if __name__ == "__main__":
    for f in sys.argv[1:]:
        build(f)
