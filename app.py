"""
SHADOW SELF APP — local dashboard + data input (built-in Python only, no installs)

Run:   python3 app.py          then open http://localhost:8000 (opens automatically)
Stop:  Ctrl + C

GET  /       dashboard (choose astronaut + day)
POST /add    check the reading (same ingestion as sensors) -> save to data/manual.csv -> re-run engine
POST /undo   remove the last manual entry -> re-run engine
POST /run    re-run the engine
POST /upload    CSV file -> every row checked by ingestion -> "add" (data/uploaded.csv)
                or "replace" (becomes data/mission.csv and/or data/preflight.csv) -> re-run engine
POST /generate  make fresh sample data (generate_sample_data.py) -> re-run engine
POST /clear     empty data/uploaded.csv + data/manual.csv -> re-run engine
GET  /template.csv   example file showing the exact columns

Fallbacks: bad input / bad CSV rows -> skipped with a message, good rows still taken in · engine fails -> error shown, old results kept
           page error -> simple error page · port busy -> try the next port
"""
import csv
import io
import json
import os
import subprocess
import sys
import webbrowser
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlencode, urlparse

from config.settings import LAUNCH_DATE, METRICS
from dashboard.page import LAST_RUN, MANUAL, page
from ingestion.ingest import ingest
from storage.db import ROOT

FIELDS = ["astronaut", "time", "metric", "value", "unit", "source", "quality", "detail"]
REQUIRED = ["astronaut", "time", "metric", "value", "unit"]
DATA = os.path.join(ROOT, "data")
UPLOADED = os.path.join(DATA, "uploaded.csv")
MAX_UPLOAD_MB = 60
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


def upload_csv(text, mode, name):
    """Check every row like a sensor reading. Good rows are kept; bad rows are skipped and counted."""
    reader = csv.DictReader(io.StringIO(text.lstrip("\ufeff")))
    cols = [c.strip() for c in (reader.fieldnames or [])]
    missing = [c for c in REQUIRED if c not in cols]
    if missing:
        return False, (f"{name}: missing column(s) {', '.join(missing)}. "
                       "Needed: astronaut,time,metric,value,unit (download the template).")
    log, keep, days, flagged = [], {"pre": [], "mission": []}, set(), 0
    for raw in reader:
        raw = {(k or "").strip(): (v or "").strip() for k, v in raw.items()}
        clean = ingest(raw, log)
        if clean is None:
            continue
        flagged += clean["quality"] == "bad"
        days.add(clean["day"])
        keep["pre" if clean["day"] <= 0 else "mission"].append({f: raw.get(f, "") for f in FIELDS})
    taken = len(keep["pre"]) + len(keep["mission"])
    rejected = sum(1 for l in log if l.startswith("rejected"))
    if taken == 0:
        return False, f"{name}: no usable rows ({rejected} rejected). First problem: {log[0][:120] if log else '-'}"

    if mode == "replace":
        if keep["mission"]:
            write_rows(os.path.join(DATA, "mission.csv"), keep["mission"])
            write_rows(UPLOADED, [])                  # old uploads would mix with the new mission
        if keep["pre"]:
            write_rows(os.path.join(DATA, "preflight.csv"), keep["pre"])
        what = " + ".join(w for w, rows in (("mission data", keep["mission"]), ("pre-mission data", keep["pre"])) if rows)
        action = f"replaced {what}"
    else:
        write_rows(UPLOADED, keep["pre"] + keep["mission"], append=True)
        action = "added to existing data"
    span = f"days {min(days)} to {max(days)}" if days else ""
    extra = f", {flagged:,} marked bad-quality" if flagged else ""
    skipped = f", {rejected:,} rows skipped" if rejected else ""
    return True, f"{name}: {taken:,} readings ({span}{extra}{skipped}) {action}."


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


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, kind="text/html; charset=utf-8"):
        data = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _redirect(self, astronaut, day, msg, kind):
        q = urlencode({k: v for k, v in {"a": astronaut, "day": day, "msg": msg, "kind": kind}.items() if v})
        self.send_response(303)
        self.send_header("Location", "/?" + q)
        self.end_headers()

    def do_GET(self):
        url = urlparse(self.path)
        if url.path == "/template.csv":
            self.send_response(200)
            self.send_header("Content-Type", "text/csv")
            self.send_header("Content-Disposition", "attachment; filename=shadow_self_template.csv")
            self.end_headers()
            return self.wfile.write(TEMPLATE.encode())
        if url.path != "/":
            return self._send(404, "Not found", "text/plain")
        q = {k: v[0] for k, v in parse_qs(url.query).items()}
        try:
            day = int(q["day"]) if q.get("day") else None
            self._send(200, page(q.get("a", ""), day, q.get("msg", ""), q.get("kind", "info")))
        except Exception as err:  # noqa: BLE001  fallback: simple error page, server keeps running
            self._send(500, f"<h1>Dashboard error</h1><p>{err}</p><p><a href='/'>Back</a></p>")

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        url = urlparse(self.path)
        if url.path == "/upload":
            return self._upload(url, length)
        form = {k: v[0] for k, v in parse_qs(self.rfile.read(length).decode()).items()}
        astronaut, day = form.get("astronaut", ""), form.get("day", "")
        try:
            if self.path == "/add":
                ok, msg = add_reading(form)
            elif self.path == "/undo":
                ok, msg = undo_last()
            elif self.path == "/run":
                ok, msg = True, ""
            elif self.path == "/generate":
                ok, msg = generate_data()
            elif self.path == "/clear":
                ok, msg = clear_dashboard_data()
            else:
                return self._send(404, "Not found", "text/plain")
            if ok:
                ran, run_msg = run_engine()
                ok, msg = ran, (msg + " " + run_msg).strip()
        except Exception as err:  # noqa: BLE001
            ok, msg = False, f"Something went wrong: {err}"
        self._redirect(astronaut, day, msg, "ok" if ok else "error")

    def _upload(self, url, length):
        """Browser sends the file's text; we answer with JSON {ok, msg}."""
        q = {k: v[0] for k, v in parse_qs(url.query).items()}
        name, mode = q.get("name", "upload.csv"), q.get("mode", "add")
        if length > MAX_UPLOAD_MB * 1024 * 1024:
            self.rfile.read(length)
            ok, msg = False, f"{name} is larger than {MAX_UPLOAD_MB} MB."
        else:
            try:
                text = self.rfile.read(length).decode("utf-8", errors="replace")
                ok, msg = upload_csv(text, mode, name)
                if ok:
                    ran, run_msg = run_engine()
                    ok, msg = ran, f"{msg} {run_msg}"
            except Exception as err:  # noqa: BLE001  fallback: report it, keep the server running
                ok, msg = False, f"Upload failed: {err}"
        self._send(200, json.dumps({"ok": ok, "msg": msg}), "application/json")

    def log_message(self, *args):
        pass                                              # keep the terminal quiet


def main():
    if not os.path.exists(os.path.join(ROOT, "shadow_self.db")):
        print("First run: processing data (a few seconds)...")
        run_engine()
    for port in range(8000, 8011):                        # fallback: port busy -> try the next one
        try:
            server = HTTPServer(("127.0.0.1", port), Handler)
            break
        except OSError:
            continue
    else:
        sys.exit("No free port between 8000 and 8010.")
    url = f"http://localhost:{port}"
    print(f"Shadow Self dashboard running at {url}   (Ctrl + C to stop)")
    if not os.environ.get("NO_BROWSER"):
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
