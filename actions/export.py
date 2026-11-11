"""
EXPORT — after every run, two simple spreadsheet files in outputs/ (open in Excel / Google Sheets).

outputs/alerts.csv   every warning the system raised
    astronaut, day, time, level (info / watch / act / urgent), system, message
outputs/checks.csv   every measurement check (the 7-step check for each metric each day)
    astronaut, day, system, metric, value, normal (personal baseline), change_pct,
    expected (what Shadow Self predicted; blank if that metric has no prediction), status, reason

Both are rewritten from the database each run, so they always match the latest results.
SORT ORDER
    alerts.csv : astronaut (A2 before A10), day, time of day (5-second alerts first, then the
                 end-of-day "daily" alerts), then most serious first (urgent, act, watch, info), system
    checks.csv : astronaut (A2 before A10), day, system (A-Z as shown), metric (A-Z)
"""
import csv
import os
import re

SYSTEM = {"radiation": "radiation", "muscle": "muscle", "bone": "bone", "sans": "eyes/brain", "cardio": "heart",
          "fusion": "cross-system"}
ALERT_FIELDS = ["astronaut", "day", "time", "level", "system", "message"]
CHECK_FIELDS = ["astronaut", "day", "system", "metric", "value", "normal", "change_pct", "expected", "status", "reason"]


LEVEL_ORDER = {"urgent": 0, "act": 1, "watch": 2, "info": 3}


def _who(astronaut):
    """Natural order for ids: A2 before A10."""
    return [int(p) if p.isdigit() else p for p in re.split(r"(\d+)", str(astronaut))]


def _num(v):
    return "" if v is None else f"{round(v, 3):g}"


def _write(path, fields, rows):
    with open(path + ".tmp", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(fields)
        w.writerows(rows)
    os.replace(path + ".tmp", path)          # never leaves a half-written file


def export_csv(db, out_dir):
    """Write alerts.csv and checks.csv. Returns (alert rows, check rows)."""
    os.makedirs(out_dir, exist_ok=True)
    alerts = [(a, d, (t or "")[11:19], tier, SYSTEM.get(dom, dom), msg) for a, d, t, tier, dom, msg in
              db.con.execute("SELECT astronaut, day, time, tier, domain, message FROM alerts").fetchall()]
    alerts.sort(key=lambda r: (_who(r[0]), r[1], r[2] == "", r[2], LEVEL_ORDER.get(r[3], 9), r[4]))
    _write(os.path.join(out_dir, "alerts.csv"), ALERT_FIELDS,
           [(a, d, t[:5] or "daily", tier, system, msg) for a, d, t, tier, system, msg in alerts])

    checks = [(a, d, SYSTEM.get(dom, dom), m, v, b, p, e, st, r) for a, d, dom, m, v, b, p, e, st, r in
              db.con.execute("SELECT astronaut, day, domain, metric, value, baseline, pct_change, predicted, "
                             "status, reason FROM results").fetchall()]
    checks.sort(key=lambda r: (_who(r[0]), r[1], r[2], r[3]))
    _write(os.path.join(out_dir, "checks.csv"), CHECK_FIELDS,
           [(a, d, system, m, _num(v), _num(b), _num(p), _num(e), st, r)
            for a, d, system, m, v, b, p, e, st, r in checks])
    return len(alerts), len(checks)
