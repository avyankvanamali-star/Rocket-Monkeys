"""
UI TESTS (UI/test_ui.py) — built-in Python only. Never changes data/ or shadow_self.db.

Run (from the shadow_self folder):   python3 -m unittest UI.test_ui -v

1. page() renders every astronaut x day, plus junk input, an empty database, a missing database
2. the live server (started on a free port): every GET route, path-escape attempts, junk query strings,
   POST validation failures (bad value / bad CSV) that must NOT write anything
"""
import os
import re
import shutil
import socket
import time
import sqlite3
import sys
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, build_opener, HTTPRedirectHandler, urlopen

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from UI import app, page as pg  # noqa: E402

DATA_FILES = ["manual.csv", "uploaded.csv", "mission.csv", "preflight.csv"]
TAB_IDS = ["overview", "systems", "report", "data", "engine", "guide"]


def snapshot():
    out = {}
    for name in DATA_FILES:
        try:
            out[name] = os.path.getmtime(os.path.join(ROOT, "data", name))
        except OSError:
            out[name] = None
    return out


def balanced(html):
    """Cheap structure check: every <section>, <div>, <ul>, <svg> opened is closed."""
    for tag in ("section", "div", "ul", "ol", "svg", "table", "form", "a"):
        opened = len(re.findall(rf"<{tag}[\s>]", html))
        closed = html.count(f"</{tag}>")
        if opened != closed:
            return f"<{tag}> opened {opened}, closed {closed}"
    return ""


class PageRender(unittest.TestCase):
    def test_every_astronaut_and_day(self):
        d = pg.load("", None)
        self.assertIsNotNone(d, "run main.py first so shadow_self.db has results")
        for a in d["crew"]:
            for day in d["days"]:
                h = pg.page(a, day)
                self.assertIn(f"{a} · Day {day}", h)
                for t in TAB_IDS:
                    self.assertIn(f'id="view-{t}"', h, t)
                self.assertEqual(balanced(h), "", f"{a} day {day}")
                self.assertIn("Top 3 activities", h)
                self.assertEqual(h.count('class="act-card'), 3, "always exactly 3 activities")
                self.assertIn("In-depth health report", h)
                self.assertIn('id="box-pre"', h)
                self.assertIn('id="box-mission"', h)

    def test_top3_always_three(self):
        d = pg.load("", None)
        for a in d["crew"]:
            for day in d["days"]:
                d2 = pg.load(a, day)
                acts = pg.top_activities(d2)
                self.assertEqual(len(acts), 3)
                ranks = [x["rank"] for x in acts]
                self.assertEqual(ranks, sorted(ranks, reverse=True), "ranked worst first")

    def test_junk_input_is_escaped_and_falls_back(self):
        h = pg.page("<script>alert(1)</script>", 99999, "<img src=x onerror=alert(1)>", "\"><b>")
        self.assertNotIn("<script>alert", h)
        self.assertNotIn("<img src=x", h)
        self.assertIn("&lt;img src=x", h)
        self.assertNotIn('class="toast "><b>', h)

    def test_scores_stay_in_ring_range(self):
        for v in (None, -20, 0, 50, 100, 140):
            svg = pg.ring(v, "ok", 100, 8)
            off = float(re.search(r"stroke-dashoffset:([\d.]+)", svg).group(1))
            self.assertTrue(0 <= off <= 100, (v, off))

    def test_trace_handles_empty_and_flat(self):
        self.assertIn("No stream data", pg.trace({}))
        flat = {h: {"v": 70.0} for h in range(24)}
        self.assertIn("<path", pg.trace(flat, 70.0, "bpm"))
        gap = {h: {"v": 60.0 + h} for h in (0, 1, 2, 10, 11)}
        self.assertEqual(pg.trace(gap).count("M"), 4)      # two line segments + two area segments

    def _with_db(self, path):
        old = pg.DB_PATH
        pg.DB_PATH = path
        try:
            return pg.page("", None)
        finally:
            pg.DB_PATH = old

    def test_missing_database(self):
        h = self._with_db(os.path.join(tempfile.gettempdir(), "does_not_exist_shadow.db"))
        self.assertIn("Waiting for the first engine run", h)
        self.assertEqual(balanced(h), "")

    def test_empty_database(self):
        tmp = tempfile.mkdtemp()
        try:
            path = os.path.join(tmp, "empty.db")
            sqlite3.connect(path).close()
            h = self._with_db(path)
            self.assertIn("Waiting for the first engine run", h)
        finally:
            shutil.rmtree(tmp)


class UploadSections(unittest.TestCase):
    """The Pre-mission and Mission boxes, run against a temporary data folder (real data/ untouched)."""
    CSV = ("astronaut,time,metric,value,unit\n"
           "A2,2027-02-20T07:00:00,resting_hr,57,bpm\n"       # day -8  (pre-mission)
           "A2,2027-02-28T07:00:00,resting_hr,56,bpm\n"       # day 0   (pre-mission)
           "A2,2027-03-04T07:00:00,resting_hr,63,bpm\n"       # day 4   (mission)
           "A2,nope,resting_hr,x,bpm\n")                       # broken

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.old = app.DATA, app.UPLOADED
        app.DATA, app.UPLOADED = self.tmp, os.path.join(self.tmp, "uploaded.csv")

    def tearDown(self):
        app.DATA, app.UPLOADED = self.old
        shutil.rmtree(self.tmp)

    def rows(self, name):
        try:
            with open(os.path.join(self.tmp, name)) as f:
                return max(sum(1 for _ in f) - 1, 0)
        except OSError:
            return 0

    def test_pre_box_keeps_only_pre_rows(self):
        ok, msg = app.upload_csv(self.CSV, "replace", "t.csv", "pre")
        self.assertTrue(ok, msg)
        self.assertEqual(self.rows("preflight.csv"), 2)
        self.assertEqual(self.rows("mission.csv"), 0)
        self.assertIn("1 mission (day 1 or later) rows skipped", msg)

    def test_mission_box_keeps_only_mission_rows(self):
        ok, msg = app.upload_csv(self.CSV, "replace", "t.csv", "mission")
        self.assertTrue(ok, msg)
        self.assertEqual(self.rows("mission.csv"), 1)
        self.assertEqual(self.rows("preflight.csv"), 0)
        self.assertIn("2 pre-mission (day 0 or earlier) rows skipped", msg)

    def test_wrong_box_only_is_refused_with_hint(self):
        pre_only = "\n".join(self.CSV.splitlines()[:3]) + "\n"
        ok, msg = app.upload_csv(pre_only, "add", "t.csv", "mission")
        self.assertFalse(ok)
        self.assertIn("use the Pre-mission box", msg)
        self.assertEqual(self.rows("uploaded.csv"), 0)

    def test_add_then_mission_replace_keeps_pre_uploads(self):
        app.upload_csv(self.CSV, "add", "t.csv", "pre")
        app.upload_csv(self.CSV, "add", "t.csv", "mission")
        self.assertEqual(self.rows("uploaded.csv"), 3)
        app.upload_csv(self.CSV, "replace", "t.csv", "mission")
        self.assertEqual(self.rows("uploaded.csv"), 2, "pre-mission uploads survive a mission replace")

    def test_no_section_still_splits_like_before(self):
        ok, _ = app.upload_csv(self.CSV, "replace", "t.csv")
        self.assertTrue(ok)
        self.assertEqual((self.rows("preflight.csv"), self.rows("mission.csv")), (2, 1))


class RowCount(unittest.TestCase):
    def test_count_rows_edge_cases(self):
        tmp = tempfile.mkdtemp()
        try:
            cases = {"lf.csv": b"h\n1\n2\n", "crlf.csv": b"h\r\n1\r\n2\r\n", "nolast.csv": b"h\n1\n2",
                     "header.csv": b"h\n", "empty.csv": b""}
            want = {"lf.csv": 2, "crlf.csv": 2, "nolast.csv": 2, "header.csv": 0, "empty.csv": 0}
            for name, data in cases.items():
                with open(os.path.join(tmp, name), "wb") as f:
                    f.write(data)
                self.assertEqual(pg.count_rows(os.path.join(tmp, name)), want[name], name)
            self.assertEqual(pg.count_rows(os.path.join(tmp, "missing.csv")), 0)
            path = os.path.join(tmp, "lf.csv")                # file changes -> recounted, not stale
            with open(path, "ab") as f:
                f.write(b"3\n")
            os.utime(path, ns=(time.time_ns(), time.time_ns() + 10**9))
            self.assertEqual(pg.count_rows(path), 3)
        finally:
            shutil.rmtree(tmp)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kw):
        return None


class LiveServer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = app.Server(("127.0.0.1", 0), app.Handler)
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.before = snapshot()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def get(self, path):
        try:
            with urlopen(self.base + path, timeout=30) as r:
                return r.status, r.read().decode(), r.headers
        except HTTPError as err:
            return err.code, err.read().decode(), err.headers

    def post(self, path, data, ctype="application/x-www-form-urlencoded"):
        req = Request(self.base + path, data=data.encode(), headers={"Content-Type": ctype})
        try:
            r = build_opener(NoRedirect).open(req, timeout=60)
            return r.status, r.read().decode(), r.headers
        except HTTPError as err:
            return err.code, err.read().decode(), err.headers

    def test_get_routes(self):
        for path, code in [("/", 200), ("/?a=A2&day=3", 200), ("/?a=A2&day=xyz", 200), ("/?day=-5", 200),
                           ("/?a=%00&day=", 200), ("/template.csv", 200), ("/static/shadow.css", 200),
                           ("/static/shadow.js", 200), ("/nope", 404), ("/static/nope.css", 404),
                           ("/static/../app.py", 404), ("/static/%2e%2e/app.py", 404), ("/static/..%2fpage.py", 404),
                           ("/static/../../shadow_self.db", 404), ("/report.json?a=../config&day=1", 404),
                           ("/report.json?a=A2&day=abc", 404), ("/report.json", 404)]:
            status, _, _ = self.get(path)
            self.assertEqual(status, code, path)

    def test_static_types(self):
        self.assertIn("text/css", self.get("/static/shadow.css")[2]["Content-Type"])
        self.assertIn("javascript", self.get("/static/shadow.js")[2]["Content-Type"])

    def test_report_json_when_packet_exists(self):
        d = pg.load("", None)
        for a in d["crew"]:
            if pg.earth_summary(a, d["days"][-1]):
                status, body, headers = self.get(f"/report.json?a={a}&day={d['days'][-1]}")
                self.assertEqual(status, 200)
                self.assertIn("attachment", headers["Content-Disposition"])
                self.assertIn('"mission_day"', body)

    def test_bad_typed_reading_is_refused_and_keeps_tab(self):
        for value in ("abc", "", "99999"):
            form = urlencode({"astronaut": "A2", "day": "3", "time": "21:00", "metric": "resting_hr",
                              "value": value, "tab": "data"})
            status, _, headers = self.post("/add", form)
            self.assertEqual(status, 303)
            self.assertIn("kind=error", headers["Location"])
            self.assertTrue(headers["Location"].endswith("#data"))
        status, _, headers = self.post("/add", urlencode({"day": "x", "time": "zz", "value": "1", "tab": "<x>"}))
        self.assertNotIn("#", headers["Location"].split("?", 1)[-1].replace("%23", ""))  # unknown tab dropped

    def test_bad_uploads_are_refused(self):
        cases = ["", "foo,bar\n1,2\n", "astronaut,time,metric,value,unit\nA2,nope,resting_hr,abc,bpm\n",
                 "﻿astronaut,time,metric,value,unit\nA2,2027-03-03T07:00:00,not_a_metric,5,x\n"]
        for body in cases:
            status, out, _ = self.post("/upload?mode=add&name=t.csv", body, "text/csv")
            self.assertEqual(status, 200)
            self.assertIn('"ok": false', out, body)

    def raw(self, data):
        with socket.create_connection(("127.0.0.1", self.server.server_port), timeout=20) as sock:
            sock.sendall(data)
            out = b""
            while chunk := sock.recv(65536):
                out += chunk
        return out.split(b"\r\n", 1)[0]

    def test_malformed_requests_never_crash(self):
        for data in (b"POST /add HTTP/1.1\r\nContent-Length: abc\r\n\r\n",
                     b"POST /add HTTP/1.1\r\nContent-Length: -5\r\n\r\n",
                     b"POST /add HTTP/1.1\r\nContent-Length: 8\r\n\r\nvalue=\xff\xfe",
                     b"POST /add HTTP/1.1\r\nContent-Length: 300000\r\n\r\n" + b"a" * 300000,
                     b"POST /upload?section=pre HTTP/1.1\r\nContent-Length: 0\r\n\r\n",
                     b"POST /upload?section=x&mode=zap HTTP/1.1\r\nContent-Length: 4\r\n\r\n\x00\xff\x00\xff",
                     b"\x00\x01 nonsense\r\n\r\n"):
            self.assertTrue(self.raw(data), data[:40])
        self.assertEqual(self.get("/?a=A2&day=3")[0], 200, "still serving after abuse")

    def test_parallel_page_loads(self):
        codes, threads = [], [threading.Thread(target=lambda p=p: codes.append(self.get(p)[0]))
                              for p in ["/?a=A1&day=1", "/?a=A2&day=3", "/static/shadow.css"] * 8]
        t0 = time.time()
        [t.start() for t in threads]
        [t.join() for t in threads]
        self.assertEqual(set(codes), {200})
        self.assertLess(time.time() - t0, 10)

    def test_page_waits_for_running_engine(self):
        with app.WORK:                                       # pretend the engine is mid-run for 1 s
            t = threading.Thread(target=lambda: self.__dict__.setdefault("r", self.get("/?a=A2&day=3")))
            t0 = time.time()
            t.start()
            self.assertEqual(self.get("/static/shadow.css")[0], 200)   # static never waits
            self.assertLess(time.time() - t0, 0.5)
            time.sleep(1)
        t.join()
        self.assertEqual(self.r[0], 200)
        self.assertGreaterEqual(time.time() - t0, 1)

    def test_unknown_post_is_404(self):
        self.assertEqual(self.post("/delete-everything", "")[0], 404)

    def test_zz_nothing_written(self):
        self.assertEqual(snapshot(), self.before, "tests must not touch data/")


if __name__ == "__main__":
    unittest.main(verbosity=2)
