"""
SHADOW SELF APP — local dashboard + data input (built-in Python only, no installs)

Run:   python3 UI/app.py       (from the shadow_self folder) -> opens http://localhost:8002 (landing page; dashboard at /app)
       works from inside UI/ too:  cd UI && python3 app.py
       python3 UI/app.py --port 8100   (a different address)
Stop:  Ctrl + C

One copy, always current: running it again while it is already running just opens the running copy, and the
running copy restarts itself on the same address when its Python code changes (CSS / JS are read fresh on
every request), so the page, its styles and its script always come from the same version.

GET  /       landing page: the idea, then the live dashboard as a read-only demo (UI/landing.py)
             old dashboard links (/?a=..&day=..) -> redirected to /app with the same query
GET  /app    dashboard (choose astronaut + day)
GET  /landing   -> redirected to /
POST /add    check the reading (same ingestion as sensors) -> save to data/manual.csv -> re-run engine
POST /undo   remove the last manual entry -> re-run engine
POST /run    re-run the engine
POST /upload    CSV file (?section=pre or mission keeps only that phase's rows) -> every row checked by ingestion -> "add" (data/uploaded.csv)
                or "replace" (becomes data/mission.csv and/or data/preflight.csv) -> re-run engine
POST /generate  make fresh sample data (generate_sample_data.py) -> re-run engine
POST /clear     empty data/uploaded.csv + data/manual.csv -> re-run engine
GET  /template.csv   example file showing the exact columns
GET  /report.json    the day's Earth packet (outputs/earth_summary_<A>_day<N>.json) as a download
GET  /static/...     the page's CSS + JavaScript (UI/static/)
GET  /health         {"app": "shadow-self", "root", "build", "pid"} (lets a second launch find this one)

Fallbacks: bad input / bad CSV rows -> skipped with a message, good rows still taken in · engine fails -> error shown, old results kept
           page error -> simple error page · port busy -> try the next port
           code edit with a syntax error -> keeps running the last good code and says so in the terminal
"""
import csv
import html
import io
import json
import os
import subprocess
import time
import sys
import threading
import webbrowser
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import urlopen

# The UI lives in shadow_self/UI/ but uses the engine's folders (config, ingestion, storage),
# so put the main project folder on Python's search path first.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from config.settings import LAUNCH_DATE, METRICS  # noqa: E402
from ingestion.ingest import ingest  # noqa: E402
from UI.landing import landing  # noqa: E402
from UI.page import BUILD, LAST_RUN, MANUAL, earth_summary, page  # noqa: E402

FIELDS = ["astronaut", "time", "metric", "value", "unit", "source", "quality", "detail"]
REQUIRED = ["astronaut", "time", "metric", "value", "unit"]
DATA = os.path.join(ROOT, "data")
UPLOADED = os.path.join(DATA, "uploaded.csv")
MAX_UPLOAD_MB = 60
STATIC = os.path.realpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "static"))
STATIC_TYPES = {".css": "text/css; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".svg": "image/svg+xml"}
PORT = 8002                                               # preferred address; busy -> the next free one
PORTS = range(8000, 8011)
TABS = {"overview", "systems", "report", "data", "engine", "guide"}
MAX_FORM_KB = 256
# One change at a time: typed entries, uploads, generate, clear and engine runs queue up behind this lock,
# so two clicks can never run two engines at once. Page loads wait for it too (the engine rebuilds the
# database tables while it runs); CSS / JS / template never wait.
WORK = threading.Lock()
WAIT_FOR_ENGINE_S = 300
TEMPLATE = """astronaut,time,metric,value,unit,source,quality,detail
A2,2027-03-04T07:00:00,resting_hr,63,bpm,manual,good,
A2,2027-03-04T09:30:00,urine_calcium,305,mg/day,urine_test,good,
A2,2027-03-04T09:30:00,knee_torque,85,Nm,force_sensor,good,
A2,2027-03-04T21:00:00,fluids,1.7,L,daily_log,good,
A2,2027-03-04T21:00:00,sodium,4200,mg,daily_log,good,
A3,2027-02-28T21:00:00,resting_hr,58,bpm,preflight,good,
"""


def write_rows(path, rows, append=False):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    new = not append or not os.path.exists(path) or os.path.getsize(path) == 0
    with open(path, "a" if append else "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        if new:
            w.writeheader()
        w.writerows(rows)


def upload_csv(text, mode, name, section=""):
    """Check every row like a sensor reading. Good rows are kept; bad rows are skipped and counted.
    section "pre"     -> pre-mission box: only day <= 0 rows; replace = becomes data/preflight.csv
    section "mission" -> mission box:     only day >= 1 rows; replace = becomes data/mission.csv
    section ""        -> old single upload (both kinds, replace splits them by day)"""
    reader = csv.DictReader(io.StringIO(text.lstrip("\ufeff")))
    cols = [c.strip() for c in (reader.fieldnames or [])]
    missing = [c for c in REQUIRED if c not in cols]
    if missing:
        return False, (f"{name}: missing column(s) {', '.join(missing)}. "
                       "Needed: astronaut,time,metric,value,unit (download the template).")
    log, keep, days, flagged, wrong = [], {"pre": [], "mission": []}, set(), 0, 0
    for raw in reader:
        raw = {(k or "").strip(): (v or "").strip() for k, v in raw.items()}
        clean = ingest(raw, log)
        if clean is None:
            continue
        kind = "pre" if clean["day"] <= 0 else "mission"
        if section in keep and kind != section:
            wrong += 1                                     # belongs in the other box
            continue
        flagged += clean["quality"] == "bad"
        days.add(clean["day"])
        keep[kind].append({f: raw.get(f, "") for f in FIELDS})
    taken = len(keep["pre"]) + len(keep["mission"])
    rejected = sum(1 for l in log if l.startswith("rejected"))
    other = {"pre": "mission (day 1 or later)", "mission": "pre-mission (day 0 or earlier)"}.get(section, "")
    if taken == 0:
        if wrong:
            box = "Mission" if section == "pre" else "Pre-mission"
            what = "the only usable row is" if wrong == 1 else f"all {wrong:,} usable rows are"
            return False, f"{name}: {what} {other} data — use the {box} box."
        return False, f"{name}: no usable rows ({rejected} rejected). First problem: {log[0][:120] if log else '-'}"

    if mode == "replace":
        if keep["mission"]:
            write_rows(os.path.join(DATA, "mission.csv"), keep["mission"])
            write_rows(UPLOADED, uploaded_pre_rows())  # old mission uploads would mix with the new mission;
                                                       # pre-mission uploads (Pre-mission box) are kept
        if keep["pre"]:
            write_rows(os.path.join(DATA, "preflight.csv"), keep["pre"])
        what = " + ".join(w for w, rows in (("mission data", keep["mission"]), ("pre-mission data", keep["pre"])) if rows)
        action = f"replaced {what}"
    else:
        write_rows(UPLOADED, keep["pre"] + keep["mission"], append=True)
        action = {"pre": "added to pre-mission data", "mission": "added to mission data"}.get(section, "added to existing data")
    span = f"days {min(days)} to {max(days)}" if days else ""
    extra = f", {flagged:,} marked bad-quality" if flagged else ""
    skipped = f", {rejected:,} rows skipped" if rejected else ""
    elsewhere = f", {wrong:,} {other} rows skipped (other box)" if wrong else ""
    return True, f"{name}: {taken:,} readings ({span}{extra}{skipped}{elsewhere}) {action}."


def uploaded_pre_rows():
    """Rows already in data/uploaded.csv that are pre-mission (day 0 or earlier)."""
    try:
        with open(UPLOADED, newline="") as f:
            rows = list(csv.DictReader(f))
    except OSError:
        return []
    keep = []
    for raw in rows:
        clean = ingest(dict(raw), [])
        if clean is not None and clean["day"] <= 0:
            keep.append(raw)
    return keep


def generate_data():
    try:
        p = subprocess.run([sys.executable, "generate_sample_data.py"], cwd=ROOT, capture_output=True,
                           text=True, timeout=300)
        return p.returncode == 0, ("Fresh sample data generated." if p.returncode == 0 else
                                   "Generator failed: " + p.stderr[-200:])
    except (OSError, subprocess.TimeoutExpired) as err:
        return False, f"Generator failed: {err}"


def clear_dashboard_data():
    write_rows(UPLOADED, [])
    write_rows(MANUAL, [])
    return True, "Cleared uploaded and typed-in readings."


def run_engine():
    """Re-run main.py in its own process. Returns (ok, message)."""
    try:
        p = subprocess.run([sys.executable, "main.py"], cwd=ROOT, capture_output=True, text=True, timeout=300)
        output = p.stdout + (("\n--- errors ---\n" + p.stderr) if p.stderr else "")
        os.makedirs(os.path.dirname(LAST_RUN), exist_ok=True)
        with open(LAST_RUN, "w") as f:
            f.write(output)
        if p.returncode != 0:
            return False, "Engine stopped with an error — previous results kept. See the engine log."
        return True, "Engine re-run complete."
    except (OSError, subprocess.TimeoutExpired) as err:
        return False, f"Could not run the engine: {err}"


def add_reading(form):
    """Validate one typed reading exactly like a sensor reading, then append it to data/manual.csv."""
    metric = form.get("metric", "")
    try:
        float(form.get("value", "").strip())
    except ValueError:
        return False, "Not saved: the value must be a number (e.g. 2.4)."
    try:
        day = int(form.get("day", ""))
        hh, mm = (int(x) for x in form.get("time", "21:00").split(":")[:2])
    except ValueError:
        return False, "Day and time must be numbers."
    stamp = datetime.combine(LAUNCH_DATE + timedelta(days=day - 1), datetime.min.time()) + timedelta(hours=hh, minutes=mm)
    raw = {"astronaut": form.get("astronaut", ""), "time": stamp.isoformat(), "metric": metric,
           "value": form.get("value", "").strip(), "unit": METRICS.get(metric, {}).get("unit", ""),
           "source": "manual_entry", "quality": "good", "detail": ""}
    log = []
    clean = ingest(raw, log)
    if clean is None:
        return False, "Not saved: " + (log[-1] if log else "invalid reading")
    if clean["quality"] == "bad":
        lo, hi = METRICS[metric]["range"]
        return False, f"Not saved: {METRICS[metric]['label']} must be between {lo} and {hi} {raw['unit']}."
    new_file = not os.path.exists(MANUAL)
    with open(MANUAL, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if new_file:
            w.writeheader()
        w.writerow(raw)
    return True, f"Saved {METRICS[metric]['label']} = {raw['value']} {raw['unit']} for {raw['astronaut']} day {day}."


def undo_last():
    try:
        with open(MANUAL, newline="") as f:
            rows = list(csv.DictReader(f))
    except OSError:
        return False, "No manual entries to undo."
    if not rows:
        return False, "No manual entries to undo."
    last = rows.pop()
    with open(MANUAL, "w", newline="") as f:          # rewrite the file without the last row
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    return True, f"Removed {last['metric']} = {last['value']} ({last['astronaut']})."


class Server(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 128                                  # default 5 -> a burst of loads waits 1-3 s in the OS


class Handler(BaseHTTPRequestHandler):
    timeout = 30                                              # a stalled / half-sent request is dropped after 30 s

    def _send(self, code, body, kind="text/html; charset=utf-8"):
        data = body.encode()
        try:
            self.send_response(code)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(data)))
            if kind.startswith(("text/css", "text/javascript")):
                self.send_header("Cache-Control", "no-cache")    # always fresh after an edit, 304-free and cheap
            self.end_headers()
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass                                              # browser left before the answer -> nothing to do

    def _moved(self, location):
        self.send_response(301)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _length(self):
        try:
            return max(int(self.headers.get("Content-Length", 0) or 0), 0)
        except ValueError:
            return 0

    def _redirect(self, astronaut, day, msg, kind, tab=""):
        msg = msg[:600]                                       # keep the URL a sane length
        q = urlencode({k: v for k, v in {"a": astronaut, "day": day, "msg": msg, "kind": kind}.items() if v})
        self.send_response(303)
        self.send_header("Location", "/app?" + q + (f"#{tab}" if tab in TABS else ""))   # back to the same tab
        self.end_headers()

    def _static(self, path):
        """UI/static/<file> only (fallback: anything else, or a path escaping the folder -> 404)."""
        full = os.path.realpath(os.path.join(STATIC, path[len("/static/"):]))
        kind = STATIC_TYPES.get(os.path.splitext(full)[1])
        if not kind or not full.startswith(STATIC + os.sep) or not os.path.isfile(full):
            return self._send(404, "Not found", "text/plain")
        with open(full, encoding="utf-8") as f:
            self._send(200, f.read(), kind)

    def _report_json(self, q):
        s = earth_summary(q.get("a", ""), int(q["day"]) if q.get("day", "").lstrip("-").isdigit() else None)
        if s is None:
            return self._send(404, "No Earth packet for that astronaut and day.", "text/plain")
        data = json.dumps(s, indent=2).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Disposition",
                         f"attachment; filename=earth_summary_{s.get('astronaut', 'crew')}_day{s.get('mission_day', '')}.json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        url = urlparse(self.path)
        if url.path == "/template.csv":
            self.send_response(200)
            self.send_header("Content-Type", "text/csv")
            self.send_header("Content-Disposition", "attachment; filename=shadow_self_template.csv")
            self.end_headers()
            return self.wfile.write(TEMPLATE.encode())
        if url.path.startswith("/static/"):
            return self._static(url.path)
        q = {k: v[0] for k, v in parse_qs(url.query).items()}
        if url.path == "/report.json":
            return self._report_json(q)
        if url.path == "/health":
            return self._send(200, json.dumps({"app": "shadow-self", "root": ROOT, "build": BUILD, "pid": os.getpid()}),
                              "application/json")
        if url.path == "/landing":                          # old address of the landing page
            return self._moved("/")
        if url.path == "/" and set(q) & {"a", "day", "msg", "kind"}:   # old dashboard link -> same view at /app
            return self._moved("/app?" + url.query)
        if url.path == "/":
            try:
                return self._send(200, landing())
            except Exception as err:  # noqa: BLE001  fallback: simple error page
                return self._send(500, f"<h1>Landing page error</h1><p>{html.escape(str(err))}</p><p><a href='/app'>Dashboard</a></p>")
        if url.path != "/app":
            return self._send(404, "Not found", "text/plain")
        if WORK.acquire(timeout=WAIT_FOR_ENGINE_S):           # engine mid-run -> wait, then show fresh results
            WORK.release()
        try:
            day = int(q["day"]) if q.get("day", "").lstrip("-").isdigit() else None   # junk day -> latest day
            self._send(200, page(q.get("a", ""), day, q.get("msg", ""), q.get("kind", "info")))
        except Exception as err:  # noqa: BLE001  fallback: simple error page, server keeps running
            self._send(500, f"<h1>Dashboard error</h1><p>{html.escape(str(err))}</p><p><a href='/app'>Back</a></p>")

    def _drain(self, length):
        """Read and throw away a body we won't use, in blocks (never holds a huge body in memory)."""
        while length > 0:
            got = self.rfile.read(min(length, 1 << 20))
            if not got:
                break
            length -= len(got)

    def do_POST(self):
        length, url = self._length(), urlparse(self.path)
        if url.path == "/upload":
            return self._upload(url, length)
        if url.path not in ("/add", "/undo", "/run", "/generate", "/clear"):
            self._drain(length)
            return self._send(404, "Not found", "text/plain")
        if length > MAX_FORM_KB * 1024:
            self._drain(length)
            return self._redirect("", "", "Form too large.", "error")
        try:
            form = {k: v[0] for k, v in parse_qs(self.rfile.read(length).decode("utf-8", errors="replace")).items()}
        except (OSError, ValueError):
            form = {}
        astronaut, day = form.get("astronaut", ""), form.get("day", "")
        try:
            with WORK:                                        # one change + engine run at a time
                ok, msg = {"/add": lambda: add_reading(form), "/undo": undo_last, "/run": lambda: (True, ""),
                           "/generate": generate_data, "/clear": clear_dashboard_data}[url.path]()
                if ok:
                    ran, run_msg = run_engine()
                    ok, msg = ran, (msg + " " + run_msg).strip()
        except Exception as err:  # noqa: BLE001
            ok, msg = False, f"Something went wrong: {err}"
        try:
            self._redirect(astronaut, day, msg, "ok" if ok else "error", form.get("tab", ""))
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _upload(self, url, length):
        """Browser sends the file's text; we answer with JSON {ok, msg}."""
        q = {k: v[0] for k, v in parse_qs(url.query).items()}
        name, mode = q.get("name", "upload.csv")[:120], q.get("mode", "add")
        mode = mode if mode in ("add", "replace") else "add"
        section = q.get("section", "") if q.get("section") in ("pre", "mission") else ""
        if length > MAX_UPLOAD_MB * 1024 * 1024:
            self._drain(length)
            ok, msg = False, f"{name} is larger than {MAX_UPLOAD_MB} MB."
        elif length == 0:
            ok, msg = False, f"{name} is empty."
        else:
            try:
                text = self.rfile.read(length).decode("utf-8", errors="replace")
                with WORK:
                    ok, msg = upload_csv(text, mode, name, section)
                    if ok:
                        ran, run_msg = run_engine()
                        ok, msg = ran, f"{msg} {run_msg}"
            except Exception as err:  # noqa: BLE001  fallback: report it, keep the server running
                ok, msg = False, f"Upload failed: {err}"
        self._send(200, json.dumps({"ok": ok, "msg": msg}), "application/json")

    def log_message(self, *args):
        pass                                              # keep the terminal quiet


def running_copy():
    """Port of a Shadow Self server for this same folder that is already running, or None."""
    for port in PORTS:
        try:
            with urlopen(f"http://127.0.0.1:{port}/health", timeout=0.4) as r:
                info = json.loads(r.read().decode())
            if info.get("app") == "shadow-self" and info.get("root") == ROOT:
                return port
        except (OSError, ValueError):
            continue
    return None


def code_files():
    """Every Python file of this project the server has loaded (page.py, settings, ingestion, ...)."""
    files = {os.path.abspath(__file__)}
    for m in list(sys.modules.values()):
        f = getattr(m, "__file__", None)
        if f and f.endswith(".py") and os.path.abspath(f).startswith(ROOT + os.sep):
            files.add(os.path.abspath(f))
    return files


def stamp(files):
    out = {}
    for f in files:
        try:
            out[f] = os.stat(f).st_mtime_ns
        except OSError:
            out[f] = None
    return out


def watch_code(port):
    """Restart this server in place (same address) when its Python code changes, so a page built by old code
    is never paired with new CSS / JS. A change that does not compile is reported and the old code keeps running."""
    files = code_files()
    seen = stamp(files)
    while True:
        time.sleep(1)
        now = stamp(files)
        if now == seen:
            continue
        changed = [f for f in files if now[f] != seen[f]]
        seen = now
        bad = []
        for f in changed:
            try:
                with open(f, encoding="utf-8") as fh:
                    compile(fh.read(), f, "exec")
            except (OSError, SyntaxError, ValueError) as err:
                bad.append(f"{os.path.relpath(f, ROOT)}: {err}")
        if bad:
            print("Code change not loaded (fix it and save again):\n  " + "\n  ".join(bad), flush=True)
            continue
        time.sleep(0.3)                                   # editors often save in two steps
        with WORK:                                        # never restart in the middle of a change / engine run
            print(f"Code changed ({', '.join(os.path.relpath(f, ROOT) for f in changed)}) -> restarting on the same address",
                  flush=True)
            env = dict(os.environ, SHADOW_PORT=str(port), NO_BROWSER="1")
            os.execve(sys.executable, [sys.executable, os.path.abspath(__file__)] + sys.argv[1:], env)


def serve_online(port):
    """ONLINE MODE: used when a hosting service (e.g. Render) starts the site and gives it a PORT.
    Listens on every address (0.0.0.0) so people on the internet can reach it, makes the sample data
    and database on first start (data/ and shadow_self.db are not on GitHub), and skips the
    laptop-only extras (opening a browser, restarting on code changes)."""
    if not os.path.exists(os.path.join(DATA, "mission.csv")):
        print("Online first start: making sample data...", flush=True)
        print(generate_data()[1], flush=True)
    if not os.path.exists(os.path.join(ROOT, "shadow_self.db")):
        print("Online first start: processing data...", flush=True)
        print(run_engine()[1], flush=True)
    server = Server(("0.0.0.0", port), Handler)
    print(f"Shadow Self online on port {port}", flush=True)
    server.serve_forever()


def main():
    hosted_port = os.environ.get("PORT")                 # set by the hosting service when the site is online
    if hosted_port:
        serve_online(int(hosted_port))
        return
    args = sys.argv[1:]
    want = PORT
    if "--port" in args:
        try:
            want = int(args[args.index("--port") + 1])
        except (IndexError, ValueError):
            sys.exit("Usage: python3 UI/app.py [--port 8002]")
    restarted = os.environ.pop("SHADOW_PORT", None)
    if restarted:
        want = int(restarted)
    else:
        port = running_copy()
        if port:                                          # fallback: already running -> use that copy, never a second one
            url = f"http://localhost:{port}"
            print(f"Shadow Self is already running at {url} (it reloads itself when the code changes). Opening it.")
            if not os.environ.get("NO_BROWSER"):
                webbrowser.open(url)
            return
    if not os.path.exists(os.path.join(ROOT, "shadow_self.db")):
        print("First run: processing data (a few seconds)...")
        run_engine()
    order = [want] + [p for p in PORTS if p != want]
    server = None
    for attempt in range(20 if restarted else 1):         # a restart waits for its own address to free up
        for port in ([want] if restarted else order):     # fallback: port busy -> try the next one
            try:
                server = Server(("127.0.0.1", port), Handler)    # threaded: a slow request never blocks the rest
                break
            except OSError:
                continue
        if server:
            break
        time.sleep(0.1)
    if not server:
        sys.exit(f"Port {want} is busy." if restarted else "No free port between 8000 and 8010.")
    url = f"http://localhost:{port}"
    if restarted:
        print(f"Restarted with the new code at {url}", flush=True)
    else:
        moved = f"   (port {want} was busy)" if port != want else ""
        print(f"Shadow Self dashboard running at {url}{moved}   (Ctrl + C to stop)", flush=True)
        if not os.environ.get("NO_BROWSER"):
            webbrowser.open(url)
    threading.Thread(target=watch_code, args=(port,), daemon=True).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
