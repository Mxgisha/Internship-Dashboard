"""HTTP surface: routes, filters, pagination, posts, escaping."""
import http.client
import os
import sys
import threading
import unittest
import urllib.parse
from http.server import ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
for path in (os.path.dirname(HERE), HERE):
    if path not in sys.path:
        sys.path.insert(0, path)

import _bootstrap  # noqa: E402
import collect  # noqa: E402
import db  # noqa: E402
import server  # noqa: E402
from support import NOW, TempDB, make_job, silent  # noqa: E402


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.env = TempDB()
        self.env.__enter__()
        self.con = self.env.con
        self.old_page_size = server.PAGE_SIZE
        collect.collect(self.con, [
            make_job(1, company="Acme"),
            make_job(2, company="Beta", title="ASIC Design Intern"),
        ], now=NOW, fresh=True, log=silent)

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(2)
        server.PAGE_SIZE = self.old_page_size
        self.env.__exit__(None, None, None)

    def request(self, method, path, data=None):
        body = urllib.parse.urlencode(data) if data is not None else None
        headers = {"Content-Type": "application/x-www-form-urlencoded"} if data is not None else {}
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request(method, path, body=body, headers=headers)
        response = conn.getresponse()
        payload = response.read().decode("utf-8")
        result = (response.status, payload, response)
        conn.close()
        return result

    def get(self, path):
        return self.request("GET", path)

    def post(self, path, data):
        return self.request("POST", path, data)

    def test_feed(self):
        status, body, _ = self.get("/")
        self.assertEqual(status, 200)
        self.assertIn("Acme", body)
        self.assertIn("Beta", body)
        self.assertIn("Why this scored", self.get("/job/id-001")[1])

    def test_health_is_plain_text(self):
        status, body, response = self.get("/health")
        self.assertEqual(status, 200)
        self.assertEqual(response.getheader("Content-Type"), "text/plain; charset=utf-8")
        self.assertEqual(body.strip(), "ok")

    def test_unknown_job_is_404(self):
        status, body, _ = self.get("/job/nope")
        self.assertEqual(status, 404)
        self.assertIn("No such job", body)

    def test_unknown_route_is_404(self):
        self.assertEqual(self.get("/nope")[0], 404)

    def test_bad_min_fit_does_not_500(self):
        status, body, _ = self.get("/?min_fit=abc")
        self.assertEqual(status, 200)
        self.assertIn("Acme", body)

    def test_cache_control(self):
        _, _, response = self.get("/")
        self.assertEqual(response.getheader("Cache-Control"), "no-store")

    def test_pagination(self):
        server.PAGE_SIZE = 5
        extra = [make_job(100 + i, company=f"Company {i}", title=f"Embedded Firmware Intern {i}")
                 for i in range(10)]
        collect.collect(self.con, extra, now=NOW, fresh=True, log=silent)
        _, first, _ = self.get("/")
        self.assertIn("page 1 of 3", first)
        _, second, _ = self.get("/?page=2")
        self.assertIn("page 2 of 3", second)

    def test_closed_rows_are_hidden_by_default(self):
        self.con.execute("UPDATE jobs SET closed_at=? WHERE id='id-002'", (NOW,))
        self.con.commit()
        _, open_feed, _ = self.get("/")
        self.assertNotIn("Beta", open_feed)
        _, closed_feed, _ = self.get("/?show=closed")
        self.assertIn("Beta", closed_feed)
        self.assertIn("closed", closed_feed)

    def test_duplicates_are_hidden_by_default(self):
        collect.collect(self.con, [
            make_job(10, company="DupCo", title="Embedded Firmware Intern"),
            make_job(11, company="DupCo", title="Embedded Firmware Intern"),
        ], now=NOW, fresh=True, log=silent)
        _, open_feed, _ = self.get("/")
        self.assertIn("/job/id-010", open_feed)
        self.assertNotIn("/job/id-011", open_feed)
        _, dups, _ = self.get("/?show=duplicates")
        self.assertIn("/job/id-011", dups)

    def test_status_post(self):
        status, body, response = self.post("/update", {"id": "id-001", "status": "applied"})
        self.assertEqual(status, 303)
        self.assertEqual(response.getheader("Location"), "/job/id-001")
        row = self.con.execute(
            "SELECT status, status_changed_at FROM jobs WHERE id='id-001'").fetchone()
        self.assertEqual(row["status"], "applied")
        self.assertIsNotNone(row["status_changed_at"])

    def test_invalid_status_is_ignored(self):
        self.post("/update", {"id": "id-001", "status": "wizard"})
        row = self.con.execute("SELECT status FROM jobs WHERE id='id-001'").fetchone()
        self.assertEqual(row["status"], "new")

    def test_notes_post(self):
        status, _, _ = self.post("/notes", {"id": "id-001", "notes": "hello <world>"})
        self.assertEqual(status, 303)
        row = self.con.execute("SELECT notes FROM jobs WHERE id='id-001'").fetchone()
        self.assertEqual(row["notes"], "hello <world>")

    def test_summary_post_and_reset(self):
        self.post("/summary", {"id": "id-001", "summary": "My own company note"})
        row = self.con.execute(
            "SELECT summary, summary_edited FROM jobs WHERE id='id-001'").fetchone()
        self.assertEqual(row["summary"], "My own company note")
        self.assertEqual(row["summary_edited"], 1)

        self.post("/summary", {"id": "id-001", "action": "reset"})
        row = self.con.execute(
            "SELECT summary, summary_edited FROM jobs WHERE id='id-001'").fetchone()
        self.assertEqual(row["summary_edited"], 0)
        self.assertIn("No profile on file for Acme", row["summary"])

    def test_post_unknown_job_is_404(self):
        self.assertEqual(self.post("/update", {"id": "nope", "status": "applied"})[0], 404)

    def test_html_is_escaped(self):
        collect.collect(self.con, [make_job(20, company="<script>alert(1)</script>")],
                        now=NOW, fresh=True, log=silent)
        _, body, _ = self.get("/")
        self.assertNotIn("<script>alert(1)</script>", body)
        self.assertIn("&lt;script&gt;", body)

    def test_status_filter(self):
        self.post("/update", {"id": "id-001", "status": "applied"})
        _, applied, _ = self.get("/?status=applied")
        self.assertIn("Acme", applied)
        _, rejected, _ = self.get("/?status=rejected")
        self.assertNotIn("Acme", rejected)

    def test_search(self):
        _, body, _ = self.get("/?q=Beta")
        self.assertIn("Beta", body)
        self.assertNotIn("Acme", body)

    def test_log_page(self):
        self.assertEqual(self.get("/log")[0], 200)

    def test_runs_page(self):
        self.con.execute("INSERT INTO runs (started, finished, fetched, active, matched) "
                         "VALUES (?,?,?,?,?)", (NOW, NOW + 1, 10, 5, 2))
        self.con.commit()
        status, body, _ = self.get("/runs")
        self.assertEqual(status, 200)
        self.assertIn("collection runs", body)


if __name__ == "__main__":
    unittest.main()
