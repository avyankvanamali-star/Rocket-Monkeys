"""
DASHBOARD PAGE (UI/page.py) — reads shadow_self.db (never writes it) and builds the whole website as one page.
HTML lives here; styles in UI/static/shadow.css; selection, day swaps, charts and drawer in UI/static/shadow.js
(app.py serves both at /static/...). The same rows are also embedded as JSON (#sd-data) so every panel stays in sync.

page(astronaut, day):
    open database (missing/empty? -> "no results yet" screen with Run / Generate / Upload)
    frame    : navy sidebar (crew with score + status + alert count, views, collapse) and a compact header
               (crew + day, day navigation, last engine run, Run engine). The only stars live here.
    tabs     : Overview  -> Shadow Score summary, system radar (0-100, Watch/Act zones), alerts + top 3 activities,
                            five system tiles, a trend linked to the selected system, 24 h heart rate + dose rate
               Systems   -> system list + one focused system: every check vs baseline, noise (MDC) and Shadow model
               Report    -> in-depth health report: summary, trend chart, alerts, plan, radiation budget, every check,
                            sensor doubts, print + Earth packet download
               Data      -> add a reading (validated), recent entries + undo, uploads, files, reset
               Engine    -> last run state + summary, searchable log
               How to use-> six steps, status meanings, a worked check from the chosen day
"""
import csv
import html
import json
import math
import os
import random
import re
import sqlite3
import threading
from datetime import datetime, timedelta

from config.settings import (CAREER_LIMIT_MSV, COUNTERMEASURES, EXERCISE, LAUNCH_DATE, METRICS, SLEEP,
                             STATUS_ORDER)
from storage.db import DB_PATH, ROOT

MANUAL = os.path.join(ROOT, "data", "manual.csv")
LAST_RUN = os.path.join(ROOT, "outputs", "last_run.txt")
BUILD = format(int(datetime.now().timestamp() * 1000) % 36 ** 6, "x")   # this server's code version (new on every restart)
STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")


def asset_v():
    """Version of the CSS + JS (UI/static/*.css, *.js) on disk right now. It is part of their URLs and of the page's build stamp, so the
    browser never pairs a page with styles or a script from a different version."""
    try:
        files = [f for f in os.listdir(STATIC_DIR) if f.endswith((".css", ".js"))]   # dashboard + landing
        return format(sum(os.stat(os.path.join(STATIC_DIR, f)).st_mtime_ns for f in files) // 10 ** 6 % 36 ** 6, "x")
    except OSError:
        return "0"
DOMAINS = ["radiation", "muscle", "bone", "sans", "cardio"]
NAMES = {"radiation": "Radiation", "muscle": "Muscle", "bone": "Bone", "sans": "Eyes / Brain",
         "cardio": "Heart", "overall": "Overall", "fusion": "Cross-system", "nutrition": "Nutrition",
         "context": "Habitat"}
LABEL = {"ok": "Nominal", "info": "Info", "watch": "Watch", "act": "Act", "urgent": "Urgent",
         "no data": "No data", "no baseline": "No baseline", "ignored": "Ignored"}
INPUT_GROUPS = ["cardio", "radiation", "muscle", "bone", "sans", "context", "nutrition"]
SKIP_INPUT = {"heart_rate", "dose_rate"}            # 5-second streams come from sensors, not typing
TABS = [("overview", "Overview"), ("systems", "Systems"), ("report", "Report"),
        ("data", "Data"), ("engine", "Engine"), ("guide", "How to use")]

# which system each countermeasure protects (so the top-3 list can rank plan items by how bad that system is)
CM_DOMAIN = {"missed_workouts": "muscle", "muscle_loss": "muscle", "stone_risk_high": "bone", "vitd_missed": "bone",
             "sans_watch": "sans", "schedule_oct": "sans", "cardio_drift": "cardio", "radiation_event": "radiation",
             "solar_storm": "radiation", "geomagnetic_storm": "radiation", "under_fueling": "muscle", "irregular_rhythm": "cardio"}
ACTION_DOMAIN = {COUNTERMEASURES[k][0]: v for k, v in CM_DOMAIN.items() if k in COUNTERMEASURES}
# everyday activity per system, used to fill the top-3 list when the engine planned fewer than 3 countermeasures
MAINTAIN = {
    "muscle": ("Resistance session at 10:00", "Keeps load at baseline to protect muscle area and strength."),
    "cardio": ("Aerobic intervals at 16:00 + 7.5 h sleep", "Holds heart-rate recovery and resting HR steady."),
    "bone": ("Drink 2.5 L + take vitamin D", "Keeps urine calcium low and bone loss slow."),
    "sans": ("Near-vision check + symptom log", "Earliest sign of eye / brain pressure change."),
    "radiation": ("Wear dosimeter, rehearse shelter route", "Fast response if a solar particle event starts."),
}

e = lambda x: html.escape("" if x is None else str(x))
st = lambda s: (s or "no data").lower().replace(" ", "-")

ICONS = {
    "overview": '<rect x="3" y="3" width="7.5" height="7.5" rx="2"/><rect x="13.5" y="3" width="7.5" height="7.5" rx="2"/>'
                '<rect x="3" y="13.5" width="7.5" height="7.5" rx="2"/><rect x="13.5" y="13.5" width="7.5" height="7.5" rx="2"/>',
    "systems": '<path d="M2 12h4l3-7 4 14 3-7h6"/>',
    "report": '<path d="M6 3h8l5 5v13H6z"/><path d="M14 3v5h5M9.5 13h6M9.5 17h6"/>',
    "data": '<ellipse cx="12" cy="5.5" rx="8" ry="2.8"/><path d="M4 5.5v6.5c0 1.6 3.6 2.8 8 2.8s8-1.2 8-2.8V5.5'
            'M4 12v6.5c0 1.6 3.6 2.8 8 2.8s8-1.2 8-2.8V12"/>',
    "engine": '<rect x="3" y="4" width="18" height="16" rx="2.5"/><path d="M7 9.5l3 2.5-3 2.5M13 15h4"/>',
    "guide": '<circle cx="12" cy="12" r="9"/><path d="M9.6 9.2a2.5 2.5 0 1 1 3.4 2.3c-.6.3-1 .8-1 1.5v.8M12 17v.01"/>',
    "radiation": '<path d="M12 3l7.5 3v6c0 4.4-3.2 7.9-7.5 9-4.3-1.1-7.5-4.6-7.5-9V6z"/><circle cx="12" cy="11.5" r="2.2"/>',
    "muscle": '<path d="M6.5 7v10M3.5 9.5v5M17.5 7v10M20.5 9.5v5M6.5 12h11"/>',
    "bone": '<path d="M8 4.5a2.4 2.4 0 0 0-3.4 3.4 2.4 2.4 0 0 0 1.9 3.6l6 6a2.4 2.4 0 0 0 3.6 1.9 2.4 2.4 0 0 0 3.4-3.4'
            ' 2.4 2.4 0 0 0-1.9-3.6l-6-6A2.4 2.4 0 0 0 8 4.5z"/>',
    "sans": '<path d="M2 12s3.6-6.5 10-6.5S22 12 22 12s-3.6 6.5-10 6.5S2 12 2 12z"/><circle cx="12" cy="12" r="2.8"/>',
    "cardio": '<path d="M12 20s-7.2-4.3-9-9.2A4.7 4.7 0 0 1 12 7a4.7 4.7 0 0 1 9 3.8C19.2 15.7 12 20 12 20z"/>',
    "overall": '<circle cx="12" cy="12" r="3"/><ellipse cx="12" cy="12" rx="10" ry="4.2" transform="rotate(-28 12 12)"/>',
    "fusion": '<circle cx="8.5" cy="12" r="5"/><circle cx="15.5" cy="12" r="5"/>',
    "warning": '<path d="M12 3.5 2.5 20h19z"/><path d="M12 10v4.5M12 17.2v.01"/>',
    "run": '<path d="M7 4.5v15l12-7.5z"/>',
    "print": '<path d="M7 9V3.5h10V9M7 17H4.5V10h15v7H17"/><rect x="7" y="14" width="10" height="6.5"/>',
    "download": '<path d="M12 4v11M7.5 10.5 12 15l4.5-4.5M4.5 19.5h15"/>',
    "upload": '<path d="M12 15V4M7.5 8.5 12 4l4.5 4.5M4.5 19.5h15"/>',
    "undo": '<path d="M9 14 4 9l5-5"/><path d="M4 9h10a6 6 0 0 1 0 12h-3"/>',
    "spark": '<path d="M12 3v4M12 17v4M3 12h4M17 12h4M5.6 5.6l2.8 2.8M15.6 15.6l2.8 2.8M5.6 18.4l2.8-2.8M15.6 8.4l2.8-2.8"/>',
    "clear": '<path d="M4 7h16M9.5 7V4.5h5V7M6.5 7l1 13h9l1-13"/>',
    "shadow": '<circle cx="10" cy="12" r="6"/><circle cx="14" cy="12" r="6" stroke-dasharray="2 2.5"/>',
    "clock": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    "x": '<path d="M6 6l12 12M18 6 6 18"/>',
    "sun": '<circle cx="12" cy="12" r="4"/><path d="M12 2.5v2M12 19.5v2M2.5 12h2M19.5 12h2M5.3 5.3l1.4 1.4M17.3 17.3l1.4 1.4'
           'M5.3 18.7l1.4-1.4M17.3 6.7l1.4-1.4"/>',
    "moon": '<path d="M20 14.5A8 8 0 0 1 9.5 4 8 8 0 1 0 20 14.5z"/>',
    "arrow": '<path d="M5 12h14M13 6l6 6-6 6"/>',
    "chev-l": '<path d="M14.5 6 8.5 12l6 6"/>',
    "chev-r": '<path d="M9.5 6l6 6-6 6"/>',
    "menu": '<path d="M4 7h16M4 12h16M4 17h16"/>',
    "collapse": '<rect x="3.5" y="4.5" width="17" height="15" rx="2.5"/><path d="M9.5 4.5v15M15.5 10l-2 2 2 2"/>',
    "panel": '<rect x="3.5" y="4.5" width="17" height="15" rx="2.5"/><path d="M14 4.5v15"/>',
    "search": '<circle cx="11" cy="11" r="6.5"/><path d="M16 16l4.5 4.5"/>',
}


def icon(name, cls="ic"):
    return f'<svg class="{cls}" viewBox="0 0 24 24" aria-hidden="true">{ICONS.get(name, "")}</svg>'


# ---------------- data ----------------
def _q(con, sql, args=()):
    try:
        return [dict(r) for r in con.execute(sql, args)]
    except sqlite3.Error:
        return []                                    # fallback: table missing -> empty section


def hourly(con, astronaut, day, metric):
    """Average of a 5-second stream per hour of the day (bad-quality samples left out)."""
    rows = _q(con, "SELECT CAST(substr(time, 12, 2) AS INTEGER) h, AVG(value) v, MIN(value) lo, MAX(value) hi "
                   "FROM measurements WHERE astronaut=? AND day=? AND metric=? AND COALESCE(quality, '')!='bad' "
                   "GROUP BY h ORDER BY h", (astronaut, day, metric))
    return {r["h"]: r for r in rows if r["h"] is not None and 0 <= r["h"] <= 23}


def earth_summary(astronaut, day):
    """outputs/earth_summary_<A>_day<N>.json (fallback: missing / unreadable -> None)."""
    if not re.fullmatch(r"[\w-]+", str(astronaut)):
        return None
    try:
        with open(os.path.join(ROOT, "outputs", f"earth_summary_{astronaut}_day{day}.json")) as f:
            s = json.load(f)
    except (OSError, ValueError):
        return None
    return s if isinstance(s, dict) and s.get("mission_day") == day else None


def load(astronaut, day):
    if not os.path.exists(DB_PATH):
        return None
    try:
        con = sqlite3.connect(DB_PATH)
    except sqlite3.Error:
        return None
    con.row_factory = sqlite3.Row
    try:
        con.execute("PRAGMA busy_timeout = 8000")         # engine writing right now -> wait for it, don't fail
        days = [r["day"] for r in _q(con, "SELECT DISTINCT day FROM daily_scores ORDER BY day")]
        crew = [r["astronaut"] for r in _q(con, "SELECT DISTINCT astronaut FROM daily_scores ORDER BY astronaut")]
        if not days or not crew:
            return None
        astronaut = astronaut if astronaut in crew else crew[0]
        day = day if day in days else days[-1]
        d = {
            "days": days, "day": day, "astronaut": astronaut, "crew": crew,
            "scores": {(r["astronaut"], r["day"], r["domain"]): r for r in _q(con, "SELECT * FROM daily_scores")},
            "alerts": _q(con, "SELECT * FROM alerts WHERE astronaut=? AND day=? ORDER BY "
                              "CASE tier WHEN 'urgent' THEN 0 WHEN 'act' THEN 1 WHEN 'watch' THEN 2 ELSE 3 END, time",
                         (astronaut, day)),
            "crew_alerts": _q(con, "SELECT astronaut, tier FROM alerts WHERE day=?", (day,)),
            "plans": _q(con, "SELECT * FROM plans WHERE astronaut=? AND made_on_day=? ORDER BY scheduled_day, id",
                        (astronaut, day)),
            "results": _q(con, "SELECT * FROM results WHERE astronaut=? AND day=? "
                               "ORDER BY flagged DESC, domain, metric", (astronaut, day)),
            "baselines": {r["metric"]: r["value"] for r in
                          _q(con, "SELECT metric, value FROM baselines WHERE astronaut=?", (astronaut,))},
            "history": _q(con, "SELECT day, domain, metric, value, baseline, mdc, status FROM results "
                               "WHERE astronaut=? ORDER BY day, id", (astronaut,)),
            "hr": hourly(con, astronaut, day, "heart_rate"),
            "dose": hourly(con, astronaut, day, "dose_rate"),
        }
    except sqlite3.Error:
        return None                                  # fallback: unreadable / corrupt database -> "no results" page
    finally:
        con.close()
    d["summary"] = earth_summary(astronaut, day)
    return d


def manual_entries():
    try:
        with open(MANUAL, newline="") as f:
            return list(csv.DictReader(f))[-8:][::-1]
    except OSError:
        return []


def last_run():
    try:
        with open(LAST_RUN) as f:
            return f.read()
    except OSError:
        return "No engine run yet."


_ROWS = {}                                           # path -> ((size, mtime), rows): recount only when the file changes
_ROWS_LOCK = threading.Lock()                        # many page loads at once -> one count, the rest reuse it


def count_rows(path):
    """Data rows in a CSV (header not counted), read in 1 MB blocks (fallback: missing file -> 0)."""
    try:
        with _ROWS_LOCK:
            return _count(path)
    except OSError:
        return 0


def _count(path):
    st = os.stat(path)
    key = (st.st_size, st.st_mtime_ns)
    if path in _ROWS and _ROWS[path][0] == key:
        return _ROWS[path][1]
    lines, last = 0, b"\n"
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            lines += block.count(b"\n")
            last = block[-1:]
    lines += last != b"\n"                             # last line without a newline still counts
    _ROWS[path] = (key, max(lines - 1, 0))
    return _ROWS[path][1]


def file_info():
    """Rows in each data file."""
    return [(label, name, count_rows(os.path.join(ROOT, "data", name)))
            for name, label in (("preflight.csv", "Pre-mission"), ("mission.csv", "Mission"),
                                ("uploaded.csv", "Uploaded"), ("manual.csv", "Typed in"))]


# ---------------- small helpers ----------------
def score_of(d, a, day, dom):
    return d["scores"].get((a, day, dom)) or {}


def score_txt(r):
    return "--" if not r or r.get("score") is None else f'{r["score"]:.0f}'


STATUS_ICON = {
    "ok": '<circle cx="12" cy="12" r="8.5"/><path d="M8.3 12.3l2.5 2.5 4.9-5.3"/>',
    "watch": '<circle cx="12" cy="12" r="8.5"/><path d="M12 7.6v5.2M12 16.3v.01"/>',
    "act": '<path d="M12 3.6 2.6 19.6h18.8z"/><path d="M12 9.8v4.4M12 17v.01"/>',
    "urgent": '<path d="M8.3 2.8h7.4l5.5 5.5v7.4l-5.5 5.5H8.3l-5.5-5.5V8.3z"/><path d="M12 7.6v5.2M12 16.3v.01"/>',
    "none": '<circle cx="12" cy="12" r="8.5"/><path d="M8.5 12h7"/>',
}


def status_icon(status):
    s = st(status)
    k = "ok" if s in ("ok", "info") else s if s in STATUS_ICON else "none"
    return f'<svg class="si" viewBox="0 0 24 24" aria-hidden="true">{STATUS_ICON[k]}</svg>'


def chip(status):
    s = (status or "no data").lower()
    return f'<span class="chip {st(s)}">{status_icon(s)}{e(LABEL.get(s, s.title()))}</span>'


def date_of(day):
    return (LAUNCH_DATE + timedelta(days=day - 1)).strftime("%a %d %b %Y")


def label_of(metric):
    return METRICS.get(metric, {}).get("label", metric)


def unit_of(metric):
    u = METRICS.get(metric, {}).get("unit", "")
    return "%" if u == "pct" else u


def num(x, digits=1):
    if x is None:
        return "—"
    return f"{x:,.{digits}f}".rstrip("0").rstrip(".") if isinstance(x, float) else e(x)


def clip(text, n=140):
    text = text or ""
    return text if len(text) <= n else text[:n].rsplit(" ", 1)[0] + "…"


def pct_txt(p):
    return "—" if p is None else f"{p:+.1f}%"


def link(a, day):
    return f"/app?a={e(a)}&amp;day={e(day)}"


def domain_note(d, domain):
    for a in d["alerts"]:
        if a["key"] == f"domain_{domain}":
            return a["message"].split(": ", 1)[-1]
    r = score_of(d, d["astronaut"], d["day"], domain)
    if r.get("score") is None:
        return "Nothing measured today"
    return "Behaving like their usual self"


def worst_tier(alerts):
    tiers = [a["tier"] for a in alerts]
    return max(tiers, key=lambda t: STATUS_ORDER.get(t, -1)) if tiers else None


# ---------------- top 3 activities ----------------
def top_activities(d):
    """Countermeasures planned today, ranked by how bad their system is; topped up with everyday activities."""
    a, day = d["astronaut"], d["day"]
    radiation_urgent = any(x["tier"] == "urgent" and x["domain"] == "radiation" for x in d["alerts"])
    items, seen = [], set()
    for p in d["plans"]:
        if p["action"] in seen:
            continue
        seen.add(p["action"])
        dom = ACTION_DOMAIN.get(p["action"], "")
        r = score_of(d, a, day, dom) if dom else {}
        status = r.get("status") or "watch"
        rank = STATUS_ORDER.get(status, 0) + (3 if dom == "radiation" and radiation_urgent else 0)
        why = f"{NAMES.get(dom, 'Crew')} at {score_txt(r)}/100" if r else "Cross-system rule"
        note = domain_note(d, dom) if dom else ""
        items.append({"title": p["action"], "domain": dom or "fusion", "status": status, "rank": rank,
                      "why": why, "detail": clip(p["note"] or note), "when": f"Day {p['scheduled_day']}",
                      "kind": "Countermeasure"})
    items.sort(key=lambda x: -x["rank"])
    items = items[:3]
    used = {x["domain"] for x in items}
    by_score = sorted(DOMAINS, key=lambda dom: (score_of(d, a, day, dom).get("score") is None,
                                                 score_of(d, a, day, dom).get("score") or 0))
    for dom in by_score:
        if len(items) >= 3:
            break
        if dom in used:
            continue
        r = score_of(d, a, day, dom)
        title, detail = MAINTAIN[dom]
        items.append({"title": title, "domain": dom, "status": r.get("status") or "no data", "rank": -1,
                      "why": f"{NAMES[dom]} at {score_txt(r)}/100" if r.get("score") is not None
                      else f"{NAMES[dom]}: no reading yet", "detail": detail, "when": "Today",
                      "kind": "Routine"})
    return items


def headline(d):
    a, day = d["astronaut"], d["day"]
    ov = score_of(d, a, day, "overall")
    scored = [(dom, score_of(d, a, day, dom).get("score")) for dom in DOMAINS]
    scored = [x for x in scored if x[1] is not None]
    if not ov or ov.get("score") is None:
        return "No overall score for this day yet. Add a reading or run the engine."
    status = ov.get("status") or "ok"
    lowest = min(scored, key=lambda x: x[1]) if scored else None
    if status in ("ok", "info"):
        return (f"All five systems are tracking {a}'s usual self. Lowest is {NAMES[lowest[0]]} at "
                f"{lowest[1]:.0f}." if lowest else "All systems nominal.")
    return (f"{NAMES[lowest[0]]} is pulling the score down to {ov['score']:.0f}. "
            f"Follow today's countermeasures and re-check tomorrow.")


# ---------------- SVG pieces ----------------
def ring(score, status, size=120, stroke=10, ticks=False, label=""):
    r = (size - stroke) / 2 - (10 if ticks else 0)
    c = size / 2
    v = 0 if score is None else max(0, min(100, score))
    return (f'<svg class="ring {st(status)}" viewBox="0 0 {size} {size}" role="img" '
            f'aria-label="{e(label)} score {e("no data" if score is None else round(score))} out of 100">'
            f'<circle class="ring-track" cx="{c}" cy="{c}" r="{r:.1f}" stroke-width="{stroke}"/>'
            f'<circle class="ring-arc" cx="{c}" cy="{c}" r="{r:.1f}" stroke-width="{stroke}" pathLength="100" '
            f'stroke-dasharray="100 100" style="stroke-dashoffset:{100 - v:.1f}" transform="rotate(-90 {c} {c})"/></svg>')


def sparkline(points, w=120, h=34):
    """points = [(day, score or None)] on a fixed 0-100 scale; a missing day breaks the line."""
    n = max(len(points) - 1, 1)
    segs, cur = [], []
    for i, (_, s) in enumerate(points):
        if s is None:
            if cur:
                segs.append(cur)
            cur = []
            continue
        cur.append((4 + i / n * (w - 8), 3 + (1 - s / 100) * (h - 6)))
    if cur:
        segs.append(cur)
    if not segs:
        return f'<svg class="spark" viewBox="0 0 {w} {h}" aria-hidden="true"></svg>'
    path = " ".join("M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in sg) for sg in segs)
    lx, ly = segs[-1][-1]
    return (f'<svg class="spark" viewBox="0 0 {w} {h}" aria-hidden="true"><path d="{path}"/>'
            f'<circle cx="{lx:.1f}" cy="{ly:.1f}" r="2.6"/></svg>')


def _bands(x_of, top, height):
    out = []
    s0, s1 = SLEEP
    for a, b in ((s0, 24), (0, s1)) if s0 > s1 else ((s0, s1),):
        out.append(f'<rect class="band sleep" x="{x_of(a):.1f}" y="{top}" width="{x_of(b) - x_of(a):.1f}" height="{height}"/>')
    for a, b, _ in EXERCISE:
        out.append(f'<rect class="band ex" x="{x_of(a):.1f}" y="{top}" width="{x_of(b) - x_of(a):.1f}" height="{height}"/>')
    return "".join(out)


def trace(series, baseline=None, unit="", cls="hr", w=640, h=170):
    """24-hour line chart of hourly averages with sleep / exercise bands and an optional baseline."""
    if not series:
        return '<div class="nodata">No stream data for this day.</div>'
    pl, pr, pt, pb = 36, 10, 12, 22
    vals = [r["v"] for r in series.values()] + ([baseline] if baseline is not None else [])
    lo, hi = min(vals), max(vals)
    pad = max((hi - lo) * 0.15, 1)
    lo, hi = lo - pad, hi + pad
    x_of = lambda hr: pl + hr / 24 * (w - pl - pr)
    y_of = lambda v: pt + (1 - (v - lo) / (hi - lo)) * (h - pt - pb)
    segs, cur = [], []
    for hr in range(24):
        if hr in series:
            cur.append((x_of(hr + 0.5), y_of(series[hr]["v"])))
        elif cur:
            segs.append(cur)
            cur = []
    if cur:
        segs.append(cur)
    line = " ".join("M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in s) for s in segs)
    area = " ".join(f"M{s[0][0]:.1f},{h - pb} " + " ".join(f"L{x:.1f},{y:.1f}" for x, y in s) +
                    f" L{s[-1][0]:.1f},{h - pb} Z" for s in segs)
    peak_h = max(series, key=lambda k: series[k]["v"])
    px, py = x_of(peak_h + 0.5), y_of(series[peak_h]["v"])
    grid = "".join(f'<text class="axis" x="{x_of(t):.1f}" y="{h - 6}" text-anchor="middle">{t:02d}:00</text>'
                   for t in (0, 6, 12, 18)) + f'<text class="axis" x="{x_of(24):.1f}" y="{h - 6}" text-anchor="end">24</text>'
    grid += (f'<text class="axis" x="{pl - 6}" y="{pt + 8}" text-anchor="end">{hi:.0f}</text>'
             f'<text class="axis" x="{pl - 6}" y="{h - pb}" text-anchor="end">{lo:.0f}</text>')
    base = ""
    if baseline is not None:
        by = y_of(baseline)
        base = (f'<line class="baseline" x1="{pl}" x2="{w - pr}" y1="{by:.1f}" y2="{by:.1f}"/>'
                f'<text class="axis base-l" x="{pl + 6}" y="{by - 4:.1f}">baseline {baseline:.0f}</text>')
    # hover / arrow-key readout: every hour's value + its point in viewBox units (read by shadow.js)
    pts = json.dumps([[hr, round(series[hr]["v"], 2), round(x_of(hr + 0.5), 1), round(y_of(series[hr]["v"]), 1)]
                      for hr in sorted(series)])
    return (f'<div class="trace-wrap" tabindex="0" data-pts="{e(pts)}" data-unit="{e(unit)}" data-w="{w}" data-h="{h}" '
            f'aria-label="24 hour trace in {e(unit)}. Use the left and right arrow keys to read each hour.">'
            f'<div class="readout" aria-live="polite" hidden><b></b><span></span></div>'
            f'<svg class="trace {cls}" viewBox="0 0 {w} {h}" aria-hidden="true">'
            f'<defs><linearGradient id="g-{cls}" x1="0" x2="0" y1="0" y2="1"><stop offset="0" class="g0"/>'
            f'<stop offset="1" class="g1"/></linearGradient></defs>'
            f'{_bands(x_of, pt, h - pt - pb)}{grid}{base}'
            f'<path class="area" d="{area}" fill="url(#g-{cls})"/><path class="line" d="{line}"/>'
            f'<circle class="peak" cx="{px:.1f}" cy="{py:.1f}" r="4"/>'
            f'<text class="axis peak-l" x="{px:.1f}" y="{max(py - 9, 10):.1f}" text-anchor="middle">'
            f'{series[peak_h]["v"]:.0f} {e(unit)}</text>'
            f'<line class="scan" x1="0" x2="0" y1="{pt}" y2="{h - pb}"/><circle class="probe" r="4.5"/></svg></div>')


# ---------------- shared bits ----------------
def prev_day(d):
    """The previous day that actually has results (None on the first day)."""
    earlier = [x for x in d["days"] if x < d["day"]]
    return earlier[-1] if earlier else None


def tri(kind):
    path = {"up": "M6 2.5l4.5 7h-9z", "down": "M6 9.5 1.5 2.5h9z", "flat": "M2 5h8v2H2z"}[kind]
    return f'<svg class="tri" viewBox="0 0 12 12" aria-hidden="true"><path d="{path}"/></svg>'


def delta(cur, prev, pday):
    """'▼ 31 vs day 2 (34)': only when both days have a score. Higher score = closer to usual self."""
    if cur is None or prev is None or pday is None:
        return '<span class="delta none">No earlier day to compare</span>'
    dv = cur - prev
    kind = "up" if dv >= 0.5 else "down" if dv <= -0.5 else "flat"
    word = {"up": "up", "down": "down", "flat": "no change"}[kind]
    return (f'<span class="delta {kind}"><b>{tri(kind)}<span class="sr">{word} </span>{abs(dv):.0f}</b>'
            f' vs day {pday} ({prev:.0f})</span>')


def stars(seed, w, h, n, orbit=None):
    """A sparse, static star field (+ one fine orbital line) for the navy frame only. Never behind data."""
    rnd = random.Random(seed)
    dots = "".join(f'<circle cx="{rnd.uniform(0, w):.0f}" cy="{rnd.uniform(0, h):.0f}" '
                   f'r="{rnd.choice((.5, .6, .7, .8, 1, 1.3)):.1f}" opacity="{rnd.uniform(.25, .85):.2f}"/>'
                   for _ in range(n))
    ring_ = (f'<ellipse class="orbit" cx="{orbit[0]}" cy="{orbit[1]}" rx="{orbit[2]}" ry="{orbit[3]}" '
             f'transform="rotate({orbit[4]} {orbit[0]} {orbit[1]})"/>' if orbit else "")
    return (f'<svg class="stars" viewBox="0 0 {w} {h}" preserveAspectRatio="xMidYMid slice" aria-hidden="true" '
            f'focusable="false">{ring_}{dots}</svg>')


def when_txt(ts):
    """'today 17:32' / 'yesterday 17:32' / 'Mon 09 Nov, 17:32' for a file time (local clock)."""
    t = datetime.fromtimestamp(ts)
    days = (datetime.now().date() - t.date()).days
    day = "today" if days == 0 else "yesterday" if days == 1 else t.strftime("%a %d %b")
    return f"{day} {t:%H:%M}" if days in (0, 1) else f"{day}, {t:%H:%M}"


def engine_info():
    """What the last main.py run left behind in outputs/last_run.txt (None before the first run)."""
    try:
        mtime = os.stat(LAST_RUN).st_mtime
        with open(LAST_RUN) as f:
            text = f.read()
    except OSError:
        return None
    lines = text.splitlines()
    grab = lambda prefix: next((ln.strip() for ln in lines if ln.strip().startswith(prefix)), "")
    try:
        with open(os.path.join(ROOT, "outputs", "errors.log")) as f:
            err_lines = sum(1 for ln in f if ln.strip())
    except OSError:
        err_lines = 0
    return {"when": when_txt(mtime), "failed": "--- errors ---" in text, "pre": grab("Pre-mission:"),
            "mission": grab("Mission data:"), "crew": grab("Astronauts:"),
            "rejected": sum(1 for ln in lines if "rejected" in ln), "converted": sum(1 for ln in lines if "converted" in ln),
            "err_lines": err_lines, "text": text}


# ---------------- frame: sidebar + header (navy, with the only stars) ----------------
def crew_note(d, a):
    tiers = [x["tier"] for x in d["crew_alerts"] if x["astronaut"] == a]
    hot = sum(1 for t in tiers if t in ("act", "urgent"))
    urgent = sum(1 for t in tiers if t == "urgent")
    watch = sum(1 for t in tiers if t == "watch")
    if urgent:
        return f"{urgent} urgent alert{'s' if urgent > 1 else ''}"
    if hot:
        return f"{hot} to act on"
    if watch:
        return f"{watch} to watch"
    return "No alerts today"


def sidebar(d):
    if d is None:
        crew = '<p class="side-empty">No crew yet. Run the engine or add data.</p>'
    else:
        day, cur = d["day"], d["astronaut"]
        crew = ""
        for a in d["crew"]:
            r = score_of(d, a, day, "overall")
            on = a == cur
            crew += (f'<a class="crew {st(r.get("status"))}{" on" if on else ""}" href="{link(a, day)}" data-nav '
                     f'aria-current="{"page" if on else "false"}" '
                     f'aria-label="{e(a)}, score {score_txt(r)} of 100, {e(LABEL.get(r.get("status") or "no data", ""))}, '
                     f'{e(crew_note(d, a))}">'
                     f'<span class="crew-id">{e(a)}</span>'
                     f'<span class="crew-score">{score_txt(r)}<small>/100</small></span>'
                     f'<span class="crew-st">{chip(r.get("status"))}</span>'
                     f'<span class="crew-note">{e(crew_note(d, a))}</span></a>')
    nav = "".join(f'<a class="tab" href="#{k}" role="tab" data-tab="{k}" id="tab-{k}" aria-controls="view-{k}" '
                  f'title="{e(v)}">{icon(k)}<span>{e(v)}</span></a>' for k, v in TABS)
    day_txt = f" · day {d['day']}" if d else ""
    return f"""<aside class="side" id="side" aria-label="Crew and views">
  {stars(11, 240, 900, 46, (40, 760, 260, 120, -18))}
  <a class="brand" href="/" aria-label="Shadow Self home">
    <svg class="mark" viewBox="0 0 40 40" aria-hidden="true"><circle class="m-shadow" cx="23" cy="21" r="11"/>
    <circle class="m-self" cx="17" cy="19" r="11"/><circle class="m-core" cx="17" cy="19" r="3.2"/></svg>
    <span class="brand-t"><b>Shadow Self</b><small>Crew health monitor</small></span></a>
  <div class="side-label">Crew{day_txt}</div><nav class="crewlist" aria-label="Crew">{crew}</nav>
  <div class="side-label">Views</div>
  <nav class="tabs" role="tablist" aria-label="Views"><span class="tab-ind" aria-hidden="true"></span>{nav}</nav>
  <button class="collapse" type="button" data-collapse aria-expanded="true" aria-controls="side">
    {icon("collapse")}<span>Collapse</span></button>
</aside>"""


def topbar(d):
    eng = engine_info()
    run_meta = (f'<span class="run-meta{" failed" if eng and eng["failed"] else ""}">'
                f'{"Last run failed" if eng and eng["failed"] else "Engine run"}<b>{e(eng["when"])}</b></span>'
                if eng else '<span class="run-meta">Engine<b>not run yet</b></span>')
    if d is None:
        title, daynav, a, day = '<h1>Awaiting first run</h1>', "", "", ""
    else:
        a, day = d["astronaut"], d["day"]
        title = (f'<h1>{e(a)}<span class="sep" aria-hidden="true">·</span>Mission day {day}</h1>'
                 f'<p>{e(date_of(day))}</p>')
        pills = ""
        for x in d["days"]:
            r = score_of(d, a, x, "overall")
            on = x == day
            pills += (f'<a class="day {st(r.get("status"))}{" on" if on else ""}" href="{link(a, x)}" data-nav data-day="{x}"'
                      f'{" aria-current=\"date\"" if on else ""} aria-label="Day {x}, score {score_txt(r)}, '
                      f'{e(LABEL.get(r.get("status") or "no data", ""))}"><span class="dot" aria-hidden="true"></span>'
                      f'<span class="d">Day {x}</span><span class="v">{score_txt(r)}</span></a>')
        i = d["days"].index(day)
        prv = d["days"][i - 1] if i > 0 else None
        nxt = d["days"][i + 1] if i + 1 < len(d["days"]) else None
        step = lambda x, cls, lab, ic: (f'<a class="day-step {cls}" href="{link(a, x)}" data-nav data-day="{x}" '
                                        f'aria-label="{lab} (day {x})" title="{lab} (←/→)">{icon(ic)}</a>' if x is not None else
                                        f'<span class="day-step {cls}" aria-disabled="true">{icon(ic)}</span>')
        daynav = (f'<nav class="daynav" aria-label="Mission day">{step(prv, "prev", "Previous day", "chev-l")}'
                  f'<div class="days">{pills}</div>{step(nxt, "next", "Next day", "chev-r")}</nav>')
    return f"""<header class="top">{stars(5, 1200, 64, 34, (980, 40, 420, 34, -4))}
  <button class="menu-btn" type="button" data-menu aria-label="Open crew and views" aria-controls="side" aria-expanded="false">{icon("menu")}</button>
  <div class="top-title">{title}</div>{daynav}
  <div class="top-run">{run_meta}
  <form method="post" action="/run" class="runform"><input type="hidden" name="astronaut" value="{e(a)}">
    <input type="hidden" name="day" value="{e(day)}"><input type="hidden" name="tab" value="">
    <button class="btn primary" data-busy="Re-running engine">{icon("run")}<span>Run engine</span></button></form></div>
</header>"""


# ---------------- overview: the main workspace ----------------
def radar(d):
    """Five real system scores on their shared 0-100 scale; Watch (<75) and Act (<50) zones from actions/act.py."""
    a, day = d["astronaut"], d["day"]
    pd = prev_day(d)
    W, H, cx, cy, R = 480, 384, 240, 200, 138
    ang = lambda i: math.radians(-90 + i * 72)
    pt = lambda i, v: (cx + R * v / 100 * math.cos(ang(i)), cy + R * v / 100 * math.sin(ang(i)))
    poly = lambda v: " ".join(f"{x:.1f},{y:.1f}" for x, y in (pt(i, v) for i in range(5)))
    cur = [score_of(d, a, day, dom).get("score") for dom in DOMAINS]
    prv = [score_of(d, a, pd, dom).get("score") for dom in DOMAINS] if pd is not None else None

    def shape(vals):
        if all(v is not None for v in vals):
            return "M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in (pt(i, v) for i, v in enumerate(vals))) + " Z"
        segs = []                                    # a missing system stays missing: only real neighbours connect
        for i in range(5):
            j = (i + 1) % 5
            if vals[i] is not None and vals[j] is not None:
                (x1, y1), (x2, y2) = pt(i, vals[i]), pt(j, vals[j])
                segs.append(f"M{x1:.1f},{y1:.1f} L{x2:.1f},{y2:.1f}")
        return " ".join(segs)

    closed = all(v is not None for v in cur)
    out = (f'<polygon class="zone watch" points="{poly(75)}"/><polygon class="zone act" points="{poly(50)}"/>' +
           "".join(f'<polygon class="grid g{v}" points="{poly(v)}"/>' for v in (25, 50, 75, 100)) +
           "".join(f'<line class="spoke" x1="{cx}" y1="{cy}" x2="{pt(i, 100)[0]:.1f}" y2="{pt(i, 100)[1]:.1f}"/>'
                   for i in range(5)) +
           # scale numbers sit between the Radiation and Muscle spokes, never on a data point
           "".join(f'<text class="scale" x="{cx + R * v / 100 * math.cos(math.radians(-54)):.1f}" '
                   f'y="{cy + R * v / 100 * math.sin(math.radians(-54)) + 3:.1f}" text-anchor="middle">{v}</text>'
                   for v in (25, 50, 75, 100)))
    if prv and any(v is not None for v in prv):
        out += f'<path class="prev" d="{shape(prv)}"/>'
    ov = score_of(d, a, day, "overall")
    out += (f'<path class="cur-f{"" if closed else " open"}" d="{shape(cur)}"/>'
            f'<text class="c-num" x="{cx}" y="{cy + 7}" text-anchor="middle">{score_txt(ov)}</text>'
            f'<text class="c-lab" x="{cx}" y="{cy + 22}" text-anchor="middle">Shadow Score</text>'
            f'<path class="cur-s" d="{shape(cur)}"/>')
    for i, (dom, v) in enumerate(zip(DOMAINS, cur)):
        if v is not None:
            x, y = pt(i, v)
            r = score_of(d, a, day, dom)
            out += f'<circle class="vx {st(r.get("status"))}" data-dom="{dom}" cx="{x:.1f}" cy="{y:.1f}" r="4.5"/>'
    labels = ""
    pos = ["p-top", "p-right", "p-right", "p-left", "p-left"]
    for i, dom in enumerate(DOMAINS):
        r = score_of(d, a, day, dom)
        x, y = pt(i, 100)
        lx, ly = cx + (x - cx) * 1.15, cy + (y - cy) * 1.15
        p = score_of(d, a, pd, dom).get("score") if pd is not None else None
        ch = (f", {'up' if r['score'] >= p else 'down'} {abs(r['score'] - p):.0f} from day {pd}"
              if p is not None and r.get("score") is not None else "")
        labels += (f'<button class="ax {pos[i]} {st(r.get("status"))}" type="button" data-select="{dom}" aria-pressed="false" '
                   f'style="left:{lx / W * 100:.2f}%;top:{ly / H * 100:.2f}%" '
                   f'aria-label="{e(NAMES[dom])}: {score_txt(r)} of 100, {e(LABEL.get(r.get("status") or "no data", ""))}{e(ch)}">'
                   f'<span class="ax-n">{icon(dom, "ic tiny")}{e(NAMES[dom])}</span>'
                   f'<span class="ax-v">{status_icon(r.get("status"))}{score_txt(r) if r.get("score") is not None else "No data"}</span></button>')
    summary = ", ".join(f"{NAMES[dom]} {score_txt(score_of(d, a, day, dom))}" for dom in DOMAINS)
    return (f'<figure class="radar" data-radar><svg viewBox="0 0 {W} {H}" role="img" '
            f'aria-label="System profile for day {day}, 0 to 100: {e(summary)}. Overall {score_txt(ov)}.">{out}</svg>'
            f'{labels}</figure>')


def overview(d):
    a, day = d["astronaut"], d["day"]
    pd = prev_day(d)
    ov = score_of(d, a, day, "overall")
    ovp = score_of(d, a, pd, "overall") if pd is not None else {}
    v = ov.get("score")
    lowest = min(((score_of(d, a, day, dom).get("score"), dom) for dom in DOMAINS
                  if score_of(d, a, day, dom).get("score") is not None), default=None)
    # A. summary + counts straight from today's rows
    zone = {"act": 0, "watch": 0, "ok": 0}
    for dom in DOMAINS:
        sc = score_of(d, a, day, dom).get("score")
        if sc is not None:
            zone["act" if sc < 50 else "watch" if sc < 75 else "ok"] += 1
    n_flag = sum(1 for x in d["results"] if x["flagged"])
    hot = sum(1 for x in d["alerts"] if x["tier"] in ("act", "urgent"))
    glance = "".join(f'<div><dt>{k}</dt><dd class="num">{v}</dd></div>' for k, v in (
        ("Systems under 50", f'{zone["act"]} of 5'), ("Systems 50 to 74", f'{zone["watch"]} of 5'),
        ("Checks flagged", f'{n_flag} of {len(d["results"])}'), ("Alerts to act on", f'{hot} of {len(d["alerts"])}')))
    summary = f"""<section class="tile t-summary" aria-labelledby="sum-h">
    <p class="cap">Day {day} · {e(date_of(day))}</p>
    <h2 class="t-title" id="sum-h">Shadow Score</h2>
    <div class="kpi"><b class="num">{score_txt(ov)}</b><span class="of">/100</span>{chip(ov.get("status"))}</div>
    <p class="kpi-d">{delta(v, ovp.get("score"), pd)}</p>
    <div class="meter {st(ov.get("status"))}" role="img" aria-label="Score {score_txt(ov)} on a 0 to 100 scale. Watch below 75, act below 50.">
      <span class="mz act"></span><span class="mz watch"></span><span class="mz ok"></span>
      <i style="left:{0 if v is None else max(0, min(100, v)):.1f}%"></i></div>
    <div class="meter-l" aria-hidden="true"><span>0</span><span style="left:50%">50</span><span style="left:75%">75</span><span>100</span></div>
    <p class="lede">{e(headline(d))}</p>
    <dl class="glance">{glance}</dl>
    <p class="fine">The Shadow Score is the lowest of the five system scores. Each system starts at 100 and loses points
      as readings drift past their measurement noise, and when cross-system rules fire. Demo thresholds, not medical standards.</p>
    <a class="link-btn" href="#report">Open the full report{icon("arrow", "ic tiny")}</a></section>"""
    # B. radar
    radar_tile = f"""<section class="tile t-radar" aria-labelledby="rad-h">
    <div class="tile-h"><div><p class="cap">Day {day}{f" vs day {pd}" if pd is not None else ""} · score 0 to 100</p>
      <h2 class="t-title" id="rad-h">System profile</h2></div>
      <button class="link-btn" type="button" data-select="" data-reset hidden>{icon("x", "ic tiny")}Show all systems</button></div>
    {radar(d)}
    <ul class="legend" aria-label="Legend">
      <li><i class="lg cur"></i>Day {day}</li>{f'<li><i class="lg prev"></i>Day {pd}</li>' if pd is not None else ''}
      <li><i class="lg zw"></i>Watch zone, under 75</li><li><i class="lg za"></i>Act zone, under 50</li></ul>
    <p class="radar-read" data-radar-read aria-live="polite">Choose a system name to inspect it{f". Lowest today: {NAMES[lowest[1]]} at {lowest[0]:.0f}" if lowest else ""}.</p></section>"""
    # C. priority: real alerts first, then the existing top-3 activities (countermeasures vs routine)
    alerts = "".join(
        f'<li class="al {st(x["tier"])}" data-dom="{e(x["domain"])}" data-tier="{st(x["tier"])}">'
        f'{chip(x["tier"])}<span class="al-dom">{e(NAMES.get(x["domain"], x["domain"]))}</span>'
        f'<span class="al-t">{e(x["time"][11:16] if x["time"] else "daily")}</span>'
        f'<p>{e(x["message"])}</p></li>' for x in d["alerts"])
    alerts_html = (f'<ol class="alist" data-alist>{alerts}</ol>'
                   f'<button class="more" type="button" data-more hidden></button>' if d["alerts"] else
                   f'<p class="quiet">{status_icon("ok")}No alerts for {e(a)} today.</p>')
    acts = ""
    for i, t in enumerate(top_activities(d), 1):
        acts += (f'<li class="act-card {st(t["status"])}" data-dom="{e(t["domain"])}"><span class="act-n">{i}</span>'
                 f'<div class="act-b"><p class="act-t">{e(t["title"])}</p>'
                 f'<p class="act-why">{icon(t["domain"], "ic tiny")}{e(t["why"])} · {e(t["detail"])}</p></div>'
                 f'<span class="tag {"cm" if t["kind"] == "Countermeasure" else "mt"}">{e(t["kind"])}</span></li>')
    prio = f"""<section class="tile t-prio" aria-labelledby="prio-h">
    <div class="tile-h"><div><p class="cap">Day {day} · most urgent first</p><h2 class="t-title" id="prio-h">Needs attention</h2></div>
      <p class="prio-filter" data-prio-filter hidden></p></div>
    <h3 class="sub-h alerts-h">Alerts <span class="count">{len(d["alerts"])}</span></h3>{alerts_html}
    <h3 class="sub-h acts-h">Top 3 activities <span class="muted">from the engine's plan</span></h3>
    <ol class="top3">{acts}</ol></section>"""
    # strip: the same five values as a list (the radar's accessible twin) + selection
    tiles = ""
    for dom in DOMAINS:
        r = score_of(d, a, day, dom)
        p = score_of(d, a, pd, dom) if pd is not None else {}
        spark = sparkline([(x, score_of(d, a, x, dom).get("score")) for x in d["days"]])
        tiles += (f'<button class="stile {st(r.get("status"))}" type="button" data-select="{dom}" aria-pressed="false">'
                  f'<span class="st-h">{icon(dom, "ic tiny")}{e(NAMES[dom])}</span>'
                  f'<span class="st-kpi"><b class="num">{score_txt(r)}</b><small>/100</small>{chip(r.get("status"))}</span>'
                  f'{delta(r.get("score"), p.get("score"), pd)}{spark}</button>')
    hr_base = d["baselines"].get("resting_hr")
    return f"""<section class="view" id="view-overview" data-view="overview" role="tabpanel" aria-labelledby="tab-overview">
  <h2 class="sr">Overview</h2>
  <div class="ov-top">{summary}{radar_tile}{prio}</div>
  <div class="strip" role="group" aria-label="Systems: select one to inspect">{tiles}</div>
  <section class="tile t-trend" aria-labelledby="trend-h" data-trend>
    <div class="tile-h"><div><p class="cap" data-trend-cap>Mission days {d["days"][0]} to {d["days"][-1]}</p>
      <h2 class="t-title" id="trend-h" data-trend-title>All systems · score by day</h2></div>
      <div class="tile-actions"><button class="btn" type="button" data-open-drawer hidden>{icon("panel")}<span>View system details</span></button></div></div>
    <div class="trend-body"><div class="trend-main" data-trend-chart><p class="muted">Loading trend…</p></div>
      <div class="trend-side" data-trend-side></div></div></section>
  <div class="grid2">
    <section class="tile"><div class="tile-h"><div><p class="cap">Day {day} · hourly mean · sleep and exercise shaded</p>
      <h2 class="t-title">{icon("cardio", "ic tiny")} Heart rate</h2></div>
      <span class="legend inline"><span><i class="lg sleep"></i>Sleep</span><span><i class="lg ex"></i>Exercise</span></span></div>
      {trace(d["hr"], hr_base, "bpm", "hr")}</section>
    <section class="tile"><div class="tile-h"><div><p class="cap">Day {day} · hourly mean, µSv/h</p>
      <h2 class="t-title">{icon("radiation", "ic tiny")} Dose rate</h2></div></div>
      {trace(d["dose"], None, "µSv/h", "dose")}</section>
  </div>
</section>"""


def client_data(d):
    """Everything the workspace needs to stay in sync on the client, from the same database rows."""
    a, day = d["astronaut"], d["day"]
    pd = prev_day(d)
    sysd = {}
    for dom in DOMAINS + ["overall"]:
        r = score_of(d, a, day, dom)
        p = score_of(d, a, pd, dom) if pd is not None else {}
        sysd[dom] = {"name": NAMES[dom], "score": r.get("score"), "status": st(r.get("status")),
                     "label": LABEL.get(r.get("status") or "no data", ""), "prev": p.get("score"),
                     "note": domain_note(d, dom) if dom != "overall" else headline(d),
                     "series": [[x, score_of(d, a, x, dom).get("score"), st(score_of(d, a, x, dom).get("status"))]
                                for x in d["days"]]}
    hist = {}
    for h in d["history"]:
        hist.setdefault(h["metric"], {})[h["day"]] = [h["day"], h["value"], h["baseline"], h["mdc"], st(h["status"])]
    checks = {}
    for r in d["results"]:
        dom = r["domain"] if r["domain"] in DOMAINS else "context"
        checks.setdefault(dom, []).append({
            "metric": r["metric"], "label": label_of(r["metric"]), "unit": unit_of(r["metric"]), "value": r["value"],
            "baseline": r["baseline"], "pct": r["pct_change"], "mdc": r["mdc"], "pred": r["predicted"],
            "unexp": bool(r["unexpected"]), "flagged": bool(r["flagged"]), "status": st(r["status"]),
            "label_s": LABEL.get(r["status"] or "no data", r["status"] or ""), "reason": r["reason"],
            "hist": sorted(hist.get(r["metric"], {}).values())})
    return {
        "astronaut": a, "day": day, "days": d["days"], "prevDay": pd, "domains": DOMAINS, "sys": sysd, "checks": checks,
        "alerts": [{"tier": st(x["tier"]), "label": LABEL.get(x["tier"], x["tier"]), "domain": x["domain"],
                    "dname": NAMES.get(x["domain"], x["domain"]), "time": x["time"][11:16] if x["time"] else "daily",
                    "msg": x["message"]} for x in d["alerts"]],
        "plans": [{"action": p["action"], "domain": ACTION_DOMAIN.get(p["action"], "fusion"), "day": p["scheduled_day"],
                   "note": p["note"]} for p in d["plans"]],
    }


# ---------------- systems: compact navigation + one focused system ----------------
def check_row(r):
    pct = r["pct_change"]
    bar = min(abs(pct or 0), 50) * 2
    shadow = (f'{num(r["predicted"], 2)}{"<span class=unexp>unexpected</span>" if r["unexpected"] else ""}'
              if r["predicted"] is not None else '<span class="muted">—</span>')
    return f"""<tr class="check {st(r['status'])}{' flagged' if r['flagged'] else ''}">
      <th scope="row"><b>{e(label_of(r['metric']))}</b><span class="reason">{e(r['reason'])}</span></th>
      <td class="n"><b>{num(r['value'], 2)}</b> <span class="unit">{e(unit_of(r['metric']))}</span></td>
      <td class="n">{num(r['baseline'], 2)}</td>
      <td class="n chg"><span>{pct_txt(pct)}</span><span class="bar" aria-hidden="true"><i style="width:{bar:.0f}%"></i></span></td>
      <td class="n">{num(r['mdc'], 2)}</td>
      <td class="n">{shadow}</td>
      <td>{chip(r['status'])}</td></tr>"""


def systems(d):
    a, day = d["astronaut"], d["day"]
    pd = prev_day(d)
    navs, arts = "", ""
    groups = [(dom, [x for x in d["results"] if x["domain"] == dom]) for dom in DOMAINS]
    other = [x for x in d["results"] if x["domain"] not in DOMAINS]
    if other:
        groups.append(("context", other))
    for dom, checks in groups:
        r = score_of(d, a, day, dom) if dom != "context" else {}
        n_flag = sum(1 for x in checks if x["flagged"])
        name = NAMES.get(dom, "Context + nutrition")
        navs += (f'<a class="sn {st(r.get("status")) if r else "no-data"}" href="#systems/{dom}" data-sys="{dom}">'
                 f'<span class="sn-n">{icon(dom if dom != "context" else "fusion", "ic tiny")}{e(name)}</span>'
                 f'<span class="sn-v">{score_txt(r) if r else ""}</span>'
                 f'<span class="sn-m">{chip(r.get("status")) if r else ""}<small>{n_flag} of {len(checks)} flagged</small></span></a>')
        rows = "".join(check_row(x) for x in checks)
        empty = ('<p class="quiet">No checks for this system today.</p>' if not checks else
                 f'<p class="quiet none-flagged">{status_icon("ok")}Nothing flagged in {e(name)} today.</p>' if not n_flag else "")
        plans = [p for p in d["plans"] if ACTION_DOMAIN.get(p["action"]) == dom]
        plan_html = ("".join(f'<li><span class="mono when">Day {p["scheduled_day"]}</span><b>{e(p["action"])}</b></li>'
                             for p in plans))
        head = ""
        if r:
            p = score_of(d, a, pd, dom) if pd is not None else {}
            head = (f'<div class="sa-kpi"><b class="num">{score_txt(r)}</b><small>/100</small>{chip(r.get("status"))}</div>'
                    f'<p class="kpi-d">{delta(r.get("score"), p.get("score"), pd)}</p>'
                    f'{sparkline([(x, score_of(d, a, x, dom).get("score")) for x in d["days"]], 200, 44)}')
        arts += f"""<article class="tile sys-art {st(r.get('status')) if r else ''}" id="sys-{dom}" data-sys="{dom}" aria-labelledby="sa-{dom}">
      <header class="sa-h"><div class="sa-t"><p class="cap">{e(name)} · day {day} · {len(checks)} check{'' if len(checks) == 1 else 's'}, {n_flag} flagged</p>
        <h3 id="sa-{dom}">{e(name)}</h3><p class="note">{e(domain_note(d, dom)) if r else 'Habitat and nutrition readings that feed the cross-system rules.'}</p></div>
        <div class="sa-side">{head}</div></header>
      {f'<div class="scroll"><table class="mtable"><thead><tr><th scope="col">Measurement</th><th scope="col" class="n">Today</th><th scope="col" class="n">Baseline</th><th scope="col" class="n">Change</th><th scope="col" class="n">Noise (MDC)</th><th scope="col" class="n">Shadow expected</th><th scope="col">Status</th></tr></thead><tbody>{rows}</tbody></table></div>' if checks else ''}
      {empty}
      {f'<h4 class="sub-h">Planned for {e(name)}</h4><ul class="plan">{plan_html}</ul>' if plans else ''}
      {f'<button class="btn" type="button" data-select="{dom}" data-open-drawer-for="{dom}">{icon("panel")}<span>Quick view with trends</span></button>' if r else ''}
    </article>"""
    total_flag = sum(1 for x in d["results"] if x["flagged"])
    return f"""<section class="view" id="view-systems" data-view="systems" role="tabpanel" aria-labelledby="tab-systems" hidden>
  <div class="view-h"><div><h2>Systems</h2>
    <p class="muted maxw">Each reading is compared to {e(a)}'s pre-flight baseline, its measurement noise (MDC) and the Shadow
      model's expected value. A check is flagged when it moves past the noise in the bad direction.</p></div>
    <div class="seg" role="group" aria-label="Which checks to show" data-filter-for="view-systems">
      <button type="button" aria-pressed="true" data-filter="all">All checks <span>{len(d["results"])}</span></button>
      <button type="button" aria-pressed="false" data-filter="flagged">Flagged <span>{total_flag}</span></button></div></div>
  <div class="sys-layout"><nav class="sys-nav tile" aria-label="Systems">{navs}</nav><div class="sys-detail">{arts}</div></div>
</section>"""


# ---------------- report ----------------
def radiation_budget(s):
    rb = (s or {}).get("radiation_budget") or {}
    if not rb:
        return '<p class="muted">No radiation budget in the Earth packet for this day.</p>'
    total, proj = rb.get("total_msv") or 0, rb.get("projected_msv") or 0
    used = min(total / CAREER_LIMIT_MSV * 100, 100)
    proj_pct = min(proj / CAREER_LIMIT_MSV * 100, 100)
    stats = "".join(f'<div class="stat"><span class="k">{k}</span><b class="num">{v}</b></div>' for k, v in (
        ("Today", f"{rb.get('today_msv', 0):.2f} mSv"), ("Mission total", f"{total:.2f} mSv"),
        ("Burn rate", f"{rb.get('burn_msv_day', 0):.2f} mSv/day"), ("Projected (end of mission)", f"{proj:.0f} mSv")))
    return f"""<div class="stats">{stats}</div>
    <div class="gauge" role="img" aria-label="{used:.1f}% of career limit used, {proj_pct:.0f}% projected">
      <div class="gauge-proj" style="width:{proj_pct:.1f}%"></div><div class="gauge-used" style="width:{max(used, .6):.1f}%"></div>
      <span class="gauge-mark" style="left:{proj_pct:.1f}%"><small>projected {proj_pct:.0f}%</small></span></div>
    <p class="muted small">{used:.2f}% of the {CAREER_LIMIT_MSV:.0f} mSv career limit used so far.</p>"""


def trend_chart(d, w=1000, h=280):
    """Every system's score on its real mission day (gaps stay gaps), Watch/Act zones, a legend that toggles series."""
    a, days = d["astronaut"], d["days"]
    pl, pr, pt, pb = 34, 100, 14, 28
    lo_d, hi_d = days[0], days[-1]
    x_of = lambda x: pl + ((x - lo_d) / (hi_d - lo_d) if hi_d > lo_d else 0.5) * (w - pl - pr)
    y_of = lambda v: pt + (1 - v / 100) * (h - pt - pb)
    out = (f'<rect class="zone watch" x="{pl}" y="{y_of(75):.1f}" width="{w - pl - pr}" height="{y_of(50) - y_of(75):.1f}"/>'
           f'<rect class="zone act" x="{pl}" y="{y_of(50):.1f}" width="{w - pl - pr}" height="{y_of(0) - y_of(50):.1f}"/>'
           f'<text class="zone-l" x="{pl + 6}" y="{y_of(75) + 13:.1f}">Watch zone, under 75</text>'
           f'<text class="zone-l" x="{pl + 6}" y="{y_of(50) + 13:.1f}">Act zone, under 50</text>')
    out += "".join(f'<line class="gridline" x1="{pl}" x2="{w - pr}" y1="{y_of(v):.1f}" y2="{y_of(v):.1f}"/>'
                   f'<text class="axis" x="{pl - 6}" y="{y_of(v) + 3:.1f}" text-anchor="end">{v}</text>'
                   for v in (0, 25, 50, 75, 100))
    out += "".join(f'<text class="axis{" on" if x == d["day"] else ""}" x="{x_of(x):.1f}" y="{h - 8}" '
                   f'text-anchor="middle">Day {x}</text>' for x in days)
    legend, ends = "", []
    for dom in DOMAINS + ["overall"]:
        pts = [(x, r) for x in days if (r := score_of(d, a, x, dom)) and r.get("score") is not None]
        if not pts:
            continue
        segs, cur, last = [], [], None
        for x, r in pts:                             # a skipped day number breaks the line: no invented readings
            if last is not None and x != last + 1 and cur:
                segs.append(cur)
                cur = []
            cur.append((x_of(x), y_of(r["score"])))
            last = x
        segs.append(cur)
        path = " ".join("M" + " L".join(f"{px:.1f},{py:.1f}" for px, py in sg) for sg in segs)
        dots = "".join(f'<circle class="{st(r.get("status"))}" cx="{x_of(x):.1f}" cy="{y_of(r["score"]):.1f}" r="4" '
                       f'data-tip="{e(NAMES[dom])} · day {x} · {r["score"]:.0f}/100 · {e(LABEL.get(r.get("status") or "no data", ""))}">'
                       f'<title>{e(NAMES[dom])}, day {x}: {r["score"]:.0f}</title></circle>' for x, r in pts)
        ends.append([dom, y_of(pts[-1][1]["score"])])
        out += f'<g class="series s-{dom}" data-series="{dom}"><path d="{path}"/>{dots}</g>'
        legend += (f'<button type="button" class="lgb s-{dom}" data-series-toggle="{dom}" aria-pressed="true">'
                   f'<i></i>{e(NAMES[dom])}</button>')
    ends.sort(key=lambda t: t[1])                    # end labels pushed apart (13px) so they never overlap
    for i in range(1, len(ends)):
        ends[i][1] = max(ends[i][1], ends[i - 1][1] + 13)
    out += "".join(f'<text class="end-l s-{dom}" data-series-label="{dom}" x="{w - pr + 8}" y="{y + 4:.1f}">{e(NAMES[dom])}</text>'
                   for dom, y in ends)
    return (f'<div class="trend-legend" role="group" aria-label="Show or hide a system">{legend}</div>'
            f'<div class="chart-wrap" data-tipchart><div class="tip" hidden></div>'
            f'<svg class="trend-chart" viewBox="0 0 {w} {h}" role="img" aria-label="Score per system by mission day; exact values in the table below">{out}</svg></div>')


def report(d):
    a, day = d["astronaut"], d["day"]
    ov = score_of(d, a, day, "overall")
    s = d["summary"]
    tier = (s or {}).get("tier") or ov.get("status")
    n = {t: sum(1 for x in d["alerts"] if x["tier"] == t) for t in ("urgent", "act", "watch", "info")}
    unexpected = sum(1 for x in d["results"] if x["unexpected"])
    flagged = sum(1 for x in d["results"] if x["flagged"])
    rules = (s or {}).get("rules_fired") or sorted({x["message"].split(":")[0] for x in d["alerts"]
                                                    if x["domain"] == "fusion"})
    scores_tbl = "".join(
        f'<tr class="{"on" if x == day else ""}"><th scope="row"><a href="{link(a, x)}" data-nav data-day="{x}">Day {x}</a></th>' +
        "".join(f'<td class="t {st(score_of(d, a, x, dom).get("status"))}">{score_txt(score_of(d, a, x, dom))}</td>'
                for dom in DOMAINS + ["overall"]) + "</tr>" for x in d["days"])
    head = "".join(f'<th scope="col">{e(NAMES[x])}</th>' for x in DOMAINS + ["overall"])
    timeline = "".join(
        f'<li class="{st(x["tier"])}"><span class="tl-dot"></span><span class="when mono">'
        f'{e(x["time"][11:16] if x["time"] else "daily")}</span>{chip(x["tier"])}'
        f'<span class="tl-dom">{e(NAMES.get(x["domain"], x["domain"]))}</span><p>{e(x["message"])}</p></li>'
        for x in d["alerts"]) or '<li class="muted">No alerts for this day.</li>'
    plan = "".join(f'<li><span class="mono when">Day {p["scheduled_day"]}</span><b>{e(p["action"])}</b>'
                   f'{"<span class=muted>" + e(p["note"]) + "</span>" if p["note"] else ""}</li>'
                   for p in d["plans"]) or '<li class="muted">Nothing scheduled.</li>'
    per_sys = ""
    for dom in DOMAINS + ["other"]:
        rows = [x for x in d["results"] if (x["domain"] == dom if dom != "other" else x["domain"] not in DOMAINS)]
        if not rows:
            continue
        r = score_of(d, a, day, dom) if dom != "other" else {}
        body = "".join(
            f'<tr class="{"flag" if x["flagged"] else ""}"><th scope="row">{e(label_of(x["metric"]))}</th>'
            f'<td class="n">{num(x["value"], 2)} <span class="unit">{e(unit_of(x["metric"]))}</span></td>'
            f'<td class="n">{num(x["baseline"], 2)}</td>'
            f'<td class="n">{pct_txt(x["pct_change"])}</td>'
            f'<td class="n">{num(x["mdc"], 2)}</td><td class="n">{num(x["predicted"], 2)}</td>'
            f'<td>{chip(x["status"])}</td><td class="reason">{e(x["reason"])}</td></tr>' for x in rows)
        title = NAMES.get(dom, "Context + nutrition")
        per_sys += f"""<div class="rep-sys"><h4>{icon(dom if dom != 'other' else 'fusion', 'ic tiny')} {e(title)}
        <span class="num">{score_txt(r) if r else ''}</span> {chip(r.get('status')) if r else ''}</h4>
        <div class="scroll"><table class="mtable results"><thead><tr><th scope="col">Metric</th><th scope="col" class="n">Value</th><th scope="col" class="n">Baseline</th><th scope="col" class="n">Change</th>
        <th scope="col" class="n">Noise (MDC)</th><th scope="col" class="n">Shadow expected</th><th scope="col">Status</th><th scope="col">Why</th></tr></thead><tbody>{body}</tbody></table></div></div>"""
    doubts = (s or {}).get("sensor_doubt") or []
    doubt_html = "".join(f"<li>{e(x if isinstance(x, str) else json.dumps(x))}</li>" for x in doubts) or \
        '<li class="muted">No sensor doubts for this day.</li>'
    lowest = sorted(((score_of(d, a, day, dom).get("score"), dom) for dom in DOMAINS
                     if score_of(d, a, day, dom).get("score") is not None))
    focus = ", ".join(f"{NAMES[dom]} ({sc:.0f})" for sc, dom in lowest[:2]) or "—"
    download = (f'<a class="btn" href="/report.json?a={e(a)}&amp;day={day}" download>{icon("download")}'
                f'<span>Earth packet (JSON)</span></a>' if s else "")
    return f"""<section class="view" id="view-report" data-view="report" role="tabpanel" aria-labelledby="tab-report" hidden>
  <article class="report tile">
    <header class="rep-h">
      <div><p class="cap">{e(a)} · mission day {day} · {e(date_of(day))}</p><h2>In-depth health report</h2>
        <p class="muted small">From shadow_self.db{" and the Earth packet" if s else ""}. Demo thresholds, not medical standards.</p></div>
      <div class="rep-actions"><button class="btn" type="button" data-print>{icon("print")}<span>Print / PDF</span></button>{download}</div>
    </header>
    <div class="rep-summary">
      <div class="rep-score"><p class="cap">Shadow Score</p><div class="kpi"><b class="num">{score_txt(ov)}</b><span class="of">/100</span></div>{chip(tier)}</div>
      <div class="kpis">
        <div class="kpi-c"><span class="k">Focus systems</span><b>{e(focus)}</b></div>
        <div class="kpi-c"><span class="k">Alerts</span><b class="num">{n["urgent"]} urgent, {n["act"]} act, {n["watch"]} watch</b></div>
        <div class="kpi-c"><span class="k">Checks flagged</span><b class="num">{flagged} of {len(d["results"])}</b></div>
        <div class="kpi-c"><span class="k">Unexpected by Shadow</span><b class="num">{unexpected}</b></div>
        <div class="kpi-c wide"><span class="k">Rules fired</span><b>{e(", ".join(rules) or "none")}</b></div>
      </div>
    </div>
    <p class="rep-lede">{e(headline(d))}</p>

    <h3 class="rep-sec">Score trend</h3>
    {trend_chart(d)}
    <div class="scroll"><table class="trend"><thead><tr><th scope="col">Day</th>{head}</tr></thead><tbody>{scores_tbl}</tbody></table></div>

    <div class="rep-2">
      <div><h3 class="rep-sec">Alerts timeline</h3><ol class="tl">{timeline}</ol></div>
      <div><h3 class="rep-sec">Countermeasure plan</h3><ul class="plan">{plan}</ul>
        <h3 class="rep-sec">Radiation budget</h3>{radiation_budget(s)}</div>
    </div>

    <h3 class="rep-sec">All checks by system</h3>
    {per_sys or '<p class="muted">No checks for this day.</p>'}

    <h3 class="rep-sec">Sensor doubts</h3><ul class="plan">{doubt_html}</ul>
  </article></section>"""


# ---------------- data ----------------
def metric_options():
    out = []
    for g in INPUT_GROUPS:
        opts = "".join(f'<option value="{m}" data-lo="{c["range"][0]}" data-hi="{c["range"][1]}" data-unit="{e(c["unit"])}">'
                       f'{e(c["label"])} ({e(c["unit"])})</option>'
                       for m, c in METRICS.items() if c["domain"] == g and m not in SKIP_INPUT and "range" in c)
        out.append(f'<optgroup label="{e(NAMES.get(g, g.capitalize()))}">{opts}</optgroup>')
    return "".join(out)


def data_view(d, astronaut, hidden=True):
    info = file_info()
    files = "".join(f'<li><span>{e(label)}</span><span class="mono muted">data/{e(name)}</span>'
                    f'<b class="num">{n:,}</b></li>' for label, name, n in info)
    add = ""
    if d is not None:
        day = d["day"]
        astro_opts = "".join(f'<option {"selected" if x == astronaut else ""}>{e(x)}</option>' for x in d["crew"])
        entries = "".join(f'<li><span class="mono">{e(m["astronaut"])}</span><span class="mono muted">'
                          f'{e(m["time"][:16].replace("T", " "))}</span><span>{e(label_of(m["metric"]))}</span>'
                          f'<b class="num">{e(m["value"])} <span class="unit">{e(m["unit"])}</span></b></li>' for m in manual_entries()) \
            or '<li class="quiet">No typed readings yet.</li>'
        add = f"""<section class="tile d-add" aria-labelledby="add-h"><div class="tile-h"><div><p class="cap">Saved to data/manual.csv, then the engine re-runs</p>
      <h3 class="t-title" id="add-h">Add a reading</h3></div></div>
      <form method="post" action="/add" class="form" data-busy-form data-validate novalidate>
        <input type="hidden" name="tab" value="data">
        <label>Astronaut<select name="astronaut">{astro_opts}</select></label>
        <label>Mission day<input type="number" name="day" value="{day}" min="-13" max="180" required></label>
        <label>Time<input type="time" name="time" value="21:00" required></label>
        <label class="wide">Measurement<select name="metric" data-metric>{metric_options()}</select></label>
        <label class="wide">Value<span class="field"><input name="value" inputmode="decimal" placeholder="e.g. 290" required
          aria-describedby="val-hint val-err" autocomplete="off"><span class="unit" data-unit-label></span></span>
          <span class="hint" id="val-hint" data-range></span><span class="field-err" id="val-err" role="alert" hidden></span></label>
        <button class="btn primary wide" data-busy="Saving + re-running engine">{icon("spark")}<span>Save and re-run engine</span></button>
      </form>
      <p class="fine">Checked exactly like a sensor reading. Use day {d["days"][-1] + 1} to start a new mission day.</p></section>
    <section class="tile d-recent" aria-labelledby="rec-h"><div class="tile-h"><div><p class="cap">Last 8 typed readings, newest first</p>
      <h3 class="t-title" id="rec-h">Recent entries</h3></div>
        <form method="post" action="/undo" data-busy-form><input type="hidden" name="astronaut" value="{e(astronaut)}">
          <input type="hidden" name="day" value="{day}"><input type="hidden" name="tab" value="data">
          <button class="btn small" data-busy="Undoing"{"" if manual_entries() else " disabled"}>{icon("undo")}<span>Undo last</span></button></form></div>
      <ul class="entries">{entries}</ul></section>"""
    counts = {name: n for _, name, n in info}
    boxes = upload_box("pre", astronaut, "Pre-mission data", "Baseline, day 0 and earlier", "preflight.csv",
                       counts.get("preflight.csv", 0),
                       "Sets each astronaut's normal. Rows dated day 1 or later are skipped here.",
                       [("add", "Add to existing pre-mission data"), ("replace", "Replace pre-mission data (preflight.csv)")]) + \
        upload_box("mission", astronaut, "Mission data", "In flight, day 1 onward", "mission.csv",
                   counts.get("mission.csv", 0),
                   "Daily logs, tests and sensor streams. Rows dated day 0 or earlier are skipped here.",
                   [("add", "Add to existing mission data (new days, readings, astronauts)"),
                    ("replace", "Replace mission data (mission.csv)")])
    return f"""<section class="view" id="view-data" data-view="data" role="tabpanel" aria-labelledby="tab-data"{" hidden" if hidden else ""}>
  <div class="view-h"><div><h2>Data</h2><p class="muted maxw">Type a reading, upload CSV files, or reset to sample data.
    Every change is checked like a sensor reading and the engine re-runs straight after.</p></div></div>
  <div class="data-grid">{add}
    <section class="tile d-files" aria-labelledby="files-h"><div class="tile-h"><div><p class="cap">Rows in each file</p>
      <h3 class="t-title" id="files-h">Files</h3></div><a class="link-btn" href="/template.csv">{icon("download", "ic tiny")}Template</a></div>
      <ul class="files">{files}</ul>
      <p class="fine">Columns: astronaut, time, metric, value, unit (optional: source, quality, detail). Bad rows are skipped and counted.</p></section>
    {boxes}
    <section class="tile d-danger" aria-labelledby="reset-h"><div class="tile-h"><div><p class="cap">These replace or remove data and ask first</p>
      <h3 class="t-title" id="reset-h">Reset</h3></div></div>
      <div class="danger-row">
        <form method="post" action="/generate" data-confirm="Make fresh sample data? This rewrites preflight.csv and mission.csv." data-busy-form>
          <input type="hidden" name="tab" value="data"><input type="hidden" name="astronaut" value="{e(astronaut)}">
          <button class="btn" data-busy="Generating sample data">{icon("spark")}<span>Generate sample data</span></button>
          <p class="fine">Rewrites preflight.csv and mission.csv with a 3-day demo.</p></form>
        <form method="post" action="/clear" data-confirm="Remove all uploaded and typed-in readings? This cannot be undone." data-busy-form>
          <input type="hidden" name="tab" value="data"><input type="hidden" name="astronaut" value="{e(astronaut)}">
          <button class="btn danger" data-busy="Clearing">{icon("clear")}<span>Clear uploads and typed readings</span></button>
          <p class="fine">Empties uploaded.csv and manual.csv. Sample files stay.</p></form>
      </div></section>
  </div></section>"""


def upload_box(section, astronaut, title, eyebrow, file_name, n, help_text, modes):
    """One upload box. section 'pre' only keeps day <= 0 rows, 'mission' only day >= 1 (checked again by app.py)."""
    opts = "".join(f'<option value="{v}">{e(t)}</option>' for v, t in modes)
    return f"""<section class="tile upbox {section}" id="box-{section}" aria-labelledby="up-{section}">
      <div class="tile-h"><div><p class="cap">{icon("clock" if section == "pre" else "spark", "ic tiny")} {e(eyebrow)}</p>
        <h3 class="t-title" id="up-{section}">{e(title)}</h3>
        <p class="upbox-n"><b class="num">{n:,}</b> rows in <span class="mono">data/{e(file_name)}</span></p></div></div>
      <form class="form upform" data-section="{section}" data-astronaut="{e(astronaut)}">
        <label class="drop wide">{icon("upload")}<span class="dropname">Drop a {e(title.lower())} CSV here or click to choose</span>
          <input type="file" class="file" name="file-{section}" accept=".csv,text/csv" required></label>
        <label class="wide">How to use it<select class="mode" name="mode-{section}">{opts}</select></label>
        <button class="btn primary wide upbtn">{icon("upload")}<span>Upload {e(title.lower())}</span></button></form>
      <div class="upresult" data-upresult></div>
      <p class="fine upstatus" aria-live="polite">{e(help_text)}</p></section>"""


# ---------------- engine ----------------
def engine_view(hidden=True):
    eng = engine_info()
    if eng is None:
        status = '<p class="quiet">The engine has not run yet. Run it to build shadow_self.db from the files in data/.</p>'
        log = ""
    else:
        cells = [("Last run", eng["when"], ""), ("Result", "Failed, previous results kept" if eng["failed"] else "Completed",
                                                  "urgent" if eng["failed"] else "ok"),
                 ("Pre-mission", eng["pre"].split(":", 1)[-1].strip() or "—", ""),
                 ("Mission data", eng["mission"].split(":", 1)[-1].strip() or "—", ""),
                 ("Rejected rows", f'{eng["rejected"]} in the log', ""),
                 ("Fallback errors", f'{eng["err_lines"]} lines in outputs/errors.log', "")]
        status = '<div class="eng-grid">' + "".join(
            f'<div class="eng-c"><span class="k">{k}</span><b>{status_icon(c) if c else ""}{e(v)}</b></div>'
            for k, v, c in cells) + "</div>"
        lines = "".join(f'<span class="ln{" err" if ("error" in ln.lower() or "rejected" in ln) else ""}">{e(ln) or " "}</span>'
                        for ln in eng["text"].splitlines())
        log = f"""<details class="tile log" data-log>
      <summary><span>{icon("engine", "ic tiny")} Engine log</span><span class="mono muted">outputs/last_run.txt · {len(eng["text"].splitlines())} lines</span></summary>
      <div class="log-tools"><label class="search">{icon("search", "ic tiny")}<input type="search" placeholder="Filter lines, e.g. A2 or rejected" data-log-filter aria-label="Filter log lines"></label>
        <span class="muted small" data-log-count></span></div>
      <pre class="mono" data-log-lines>{lines}</pre></details>"""
    return f"""<section class="view" id="view-engine" data-view="engine" role="tabpanel" aria-labelledby="tab-engine"{" hidden" if hidden else ""}>
  <div class="view-h"><div><h2>Engine</h2><p class="muted maxw">main.py reads data/, checks every reading, scores each system and writes
    shadow_self.db. A run takes a few seconds; only one runs at a time.</p></div>
    <form method="post" action="/run" data-busy-form><button class="btn primary" data-busy="Re-running engine">{icon("run")}<span>Run engine now</span></button></form></div>
  <section class="tile" aria-label="Last run">{status}</section>
  {log}</section>"""


STATUS_HELP = [
    ("ok", "Within measurement noise of the pre-flight baseline. Nothing to do."),
    ("watch", "A real change in the bad direction, or a system score under 75. Keep an eye on it."),
    ("act", "The same real change three checks in a row, or a score under 50. A countermeasure is planned."),
    ("urgent", "Only from hard rules: an irregular heartbeat or a radiation event. Deal with it now."),
    ("no data", "No usable readings. The score stays blank instead of looking healthy."),
]


def worked_example(d):
    """One real check from the chosen day, laid out step by step (falls back to a plain note)."""
    rows = (d or {}).get("results") or []
    pick = next((x for x in rows if x["flagged"] and x["predicted"] is not None), None) or \
        next((x for x in rows if x["flagged"]), None) or next((x for x in rows if x["baseline"] is not None), None)
    if pick is None:
        return '<p class="muted">Once the engine has run, a real check from the chosen day appears here.</p>'
    u = unit_of(pick["metric"])
    diff = None if pick["value"] is None or pick["baseline"] is None else abs(pick["value"] - pick["baseline"])
    beyond = diff is not None and pick["mdc"] is not None and diff > pick["mdc"]
    noise = ("—" if diff is None or pick["mdc"] is None else
             f'{num(diff, 2)} {"&gt;" if beyond else "&le;"} {num(pick["mdc"], 2)}')
    if pick["predicted"] is None:
        shadow, shadow_note = "—", "No Shadow model for this metric"
    else:
        shadow = num(pick["predicted"], 2)
        shadow_note = "Further off than usual: unexpected" if pick["unexpected"] else "Close to what the model expected"
    cells = [
        ("Reading", f'{num(pick["value"], 2)} <small>{e(u)}</small>', "Today's value"),
        ("Pre-flight baseline", num(pick["baseline"], 2), f'Change {pct_txt(pick["pct_change"])}'),
        ("Gap vs noise (MDC)", noise, "Real change" if beyond else "Within noise"),
        ("Shadow expected", shadow, shadow_note),
    ]
    out = "".join(f'<div class="ex-cell"><span class="k">{k}</span><b class="num">{v}</b>'
                  f'<span class="muted small">{n}</span></div>' for k, v, n in cells)
    return f"""<figure class="example">
      <figcaption><b>{e(label_of(pick["metric"]))}</b><span class="muted small">{e(d["astronaut"])}, mission day {d["day"]}</span>
        {chip(pick["status"])}</figcaption>
      <div class="ex-row">{out}</div>
      <p class="ex-why"><span class="muted">Engine's reason:</span> {e(pick["reason"])}</p></figure>"""


def guide_view(d=None):
    steps = [
        ("Choose a crew member", "The crew list in the navy sidebar shows each person's Shadow Score, status and alert "
         "count, so another crew member's alert is never hidden by the one you are looking at.", ""),
        ("Choose a mission day", "Use the day buttons in the header, or the arrows (← and → work too). The whole "
         "workspace updates in place and keeps the tab you are on.", ""),
        ("Understand the status", "The Shadow Score is the lowest of the five system scores. The system profile shows "
         "all five on one 0 to 100 scale, with the Watch (under 75) and Act (under 50) zones shaded.",
         '<a class="btn small" href="#overview">Open Overview</a>'),
        ("Inspect a system", "Choose a system name in the profile or a system tile. The alerts, trend and measurements "
         "follow your choice; View system details opens every measurement with its baseline and noise band.", ""),
        ("Review the evidence", "Systems lists every check behind each score. Report is the printable version, with the "
         "Earth packet download.",
         '<a class="btn small" href="#systems">Open Systems</a><a class="btn small" href="#report">Open Report</a>'),
        ("Add data and re-run", "Data takes a typed reading or a CSV upload, then re-runs the engine. Engine shows the "
         "last run and its log.", '<a class="btn small" href="#data">Open Data</a><a class="btn small" href="#engine">Open Engine</a>'),
    ]
    step_html = "".join(f'<li><span class="g-n">{i}</span><div class="g-b"><h4>{t}</h4><p class="muted">{p}</p>'
                        f'{f"<div class=g-links>{links}</div>" if links else ""}</div></li>'
                        for i, (t, p, links) in enumerate(steps, 1))
    status_html = "".join(f'<div><dt>{chip(s)}</dt><dd>{e(text)}</dd></div>' for s, text in STATUS_HELP)
    return f"""<section class="view" id="view-guide" data-view="guide" role="tabpanel" aria-labelledby="tab-guide" hidden>
  <div class="view-h"><div><h2>How to use Shadow Self</h2>
    <p class="muted maxw">Shadow Self compares each astronaut with two references: their own pre-flight baseline, and the
      Shadow model's estimate of what today's sleep, workload, CO&#8322; and radiation should do to them. It flags what has
      really changed and plans what to do about it.</p></div></div>
  <div class="guide-grid">
    <section class="tile"><h3 class="t-title">Six steps</h3><ol class="g-steps">{step_html}</ol></section>
    <div class="guide-side">
      <section class="tile"><h3 class="t-title">What the statuses mean</h3><dl class="g-dl status">{status_html}</dl></section>
      <section class="tile"><h3 class="t-title">How one check is decided</h3>
        <p class="muted">Compare the reading with the baseline, ask whether the gap is bigger than the measurement noise
          (MDC), compare it with the Shadow model, then see whether it happened three checks in a row. A real one:</p>
        {worked_example(d)}
        <p class="fine">A system's score starts at 100. It drops by 25 for each MDC of average drift and by 10 for each
          cross-system rule that fires. Everything runs on this computer; nothing is sent anywhere.</p></section>
    </div>
  </div></section>"""


def page(astronaut, day, msg="", msg_kind="info"):
    d = load(astronaut, day)
    kind = msg_kind if msg_kind in ("ok", "error", "info") else "info"
    banner = (f'<div class="toast {kind}" role="status"><span>{e(msg)}</span>'
              f'<button class="x" type="button" aria-label="Dismiss" data-dismiss>{icon("x")}</button></div>' if msg else "")
    if d is None:
        body = f"""{banner}<section class="view" id="view-overview" data-view="overview" role="tabpanel">
      <div class="empty-state tile"><svg class="empty-art" viewBox="0 0 200 140" aria-hidden="true">
        <circle class="m-shadow" cx="112" cy="72" r="38"/><circle class="m-self" cx="90" cy="66" r="38"/></svg>
      <h2>Waiting for the first engine run</h2>
      <p class="muted maxw">Upload a CSV, generate sample data, or run the engine on the files already in data/.</p>
      <form method="post" action="/run" data-busy-form><button class="btn primary" data-busy="Running engine">{icon("run")}
        <span>Run engine</span></button></form></div></section>
      {data_view(None, astronaut, hidden=True)}{engine_view()}{guide_view(None)}
      <section class="view" id="view-systems" data-view="systems" role="tabpanel" hidden><div class="empty-state tile"><h2>No systems yet</h2></div></section>
      <section class="view" id="view-report" data-view="report" role="tabpanel" hidden><div class="empty-state tile"><h2>No report yet</h2></div></section>"""
        return shell(body, None)

    body = f"""{banner}{overview(d)}{systems(d)}{report(d)}{data_view(d, d["astronaut"])}
    {engine_view()}{guide_view(d)}"""
    return shell(body, d)


def shell(body, d):
    title = f"{d['astronaut']} · Day {d['day']} · Shadow Self" if d else "Shadow Self"
    data = (json.dumps(client_data(d), separators=(",", ":")).replace("</", "<\\/") if d else "null")
    v = asset_v()
    return f"""<!doctype html><html lang="en" data-build="{BUILD}-{v}"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{e(title)}</title>
<meta name="color-scheme" content="light"><meta name="theme-color" content="#101827">
<script>try{{if(localStorage.getItem("shadow-side")==="collapsed")document.documentElement.classList.add("side-collapsed")}}catch(e){{}}</script>
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 40 40'%3E%3Ccircle cx='23' cy='21' r='11' fill='%235C6B76'/%3E%3Ccircle cx='17' cy='19' r='11' fill='%233459E6'/%3E%3C/svg%3E">
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Geist:wght@400;500;600&family=Geist+Mono:wght@400;500&display=swap" media="print" onload="this.media='all'">
<link rel="stylesheet" href="/static/shadow.css?v={v}">
<noscript><style>.view[hidden]{{display:block!important}}.sys-art{{display:block!important}}</style></noscript>
</head><body>
<a class="skip" href="#main">Skip to the workspace</a>
<div class="app">{sidebar(d)}
<main class="main" id="main">{topbar(d)}<div class="content">{body}</div></main></div>
<div class="scrim" data-scrim hidden></div>
<dialog class="drawer" id="drawer" aria-labelledby="drawer-h"><div class="drawer-in" data-drawer-body></div></dialog>
<script type="application/json" id="sd-data">{data}</script>
<div class="busy" id="busy" hidden><div class="busy-card"><div class="busy-orbit"><i></i></div>
  <p id="busy-t">Working…</p><small class="muted">Usually 2 to 5 seconds. Buttons stay disabled until it finishes.</small></div></div>
<script src="/static/shadow.js?v={v}" defer></script></body></html>"""
