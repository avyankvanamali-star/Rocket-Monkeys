"""
DASHBOARD PAGE — reads shadow_self.db and builds one HTML page.

page(astronaut, day):
    open database (missing/empty? -> "no results yet" page with a Run button)
    crew strip   : overall score per astronaut
    score cards  : 5 systems + overall for the chosen day
    trend table  : every day x every system
    alerts + plan for the chosen day
    input form   : add a reading -> saved to data/manual.csv -> engine re-runs
    data panel   : upload CSV (add / replace), generate sample data, clear uploads, file row counts
    results table: every 7-step check for the day (value, baseline, change, expected, reason)
"""
import csv
import html
import os
import sqlite3

from config.settings import ASTRONAUTS, METRICS
from storage.db import DB_PATH, ROOT

MANUAL = os.path.join(ROOT, "data", "manual.csv")
LAST_RUN = os.path.join(ROOT, "outputs", "last_run.txt")
DOMAINS = ["radiation", "muscle", "bone", "sans", "cardio"]
NAMES = {"radiation": "Radiation", "muscle": "Muscle", "bone": "Bone", "sans": "Eyes / Brain (SANS)",
         "cardio": "Heart", "overall": "Overall"}
INPUT_GROUPS = ["cardio", "radiation", "muscle", "bone", "sans", "context", "nutrition"]
SKIP_INPUT = {"heart_rate", "dose_rate"}            # 5-second streams come from sensors, not typing
e = lambda x: html.escape("" if x is None else str(x))


# ---------------- data ----------------
def _q(con, sql, args=()):
    try:
        return [dict(r) for r in con.execute(sql, args)]
    except sqlite3.Error:
        return []                                    # fallback: table missing -> empty section


def load(astronaut, day):
    if not os.path.exists(DB_PATH):
        return None
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    days = [r["day"] for r in _q(con, "SELECT DISTINCT day FROM daily_scores ORDER BY day")]
    crew = [r["astronaut"] for r in _q(con, "SELECT DISTINCT astronaut FROM daily_scores ORDER BY astronaut")]
    if not days:
        return None
    astronaut = astronaut if astronaut in crew else crew[0]
    day = day if day in days else days[-1]
    scores = _q(con, "SELECT * FROM daily_scores")
    d = {
        "days": days, "day": day, "astronaut": astronaut, "crew": crew,
        "scores": {(r["astronaut"], r["day"], r["domain"]): r for r in scores},
        "alerts": _q(con, "SELECT * FROM alerts WHERE astronaut=? AND day=? ORDER BY "
                          "CASE tier WHEN 'urgent' THEN 0 WHEN 'act' THEN 1 WHEN 'watch' THEN 2 ELSE 3 END, time",
                     (astronaut, day)),
        "plans": _q(con, "SELECT * FROM plans WHERE astronaut=? AND made_on_day=?", (astronaut, day)),
        "results": _q(con, "SELECT * FROM results WHERE astronaut=? AND day=? "
                           "ORDER BY flagged DESC, domain, metric", (astronaut, day)),
    }
    con.close()
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


# ---------------- pieces ----------------
def chip(status):
    s = (status or "no data").lower()
    return f'<span class="chip {s.replace(" ", "-")}">{e(s.upper())}</span>'


def score_txt(r):
    return "--" if not r or r["score"] is None else f'{r["score"]:.0f}'


def card(domain, r, note):
    status = r["status"] if r else "no data"
    return (f'<div class="card {e(status).replace(" ", "-")}"><div class="card-top"><span>{e(NAMES[domain])}</span>'
            f'{chip(status)}</div><div class="score">{score_txt(r)}</div><div class="note">{e(note)}</div></div>')


def domain_note(d, domain):
    for a in d["alerts"]:
        if a["key"] == f"domain_{domain}":
            return a["message"].split(": ", 1)[-1]
    r = d["scores"].get((d["astronaut"], d["day"], domain))
    if r and r["score"] is None:
        return "Nothing measured today"
    return "Normal — behaving like their usual self"


def metric_options():
    out = []
    for g in INPUT_GROUPS:
        opts = "".join(f'<option value="{m}">{e(c["label"])} ({e(c["unit"])})</option>'
                       for m, c in METRICS.items() if c["domain"] == g and m not in SKIP_INPUT)
        out.append(f'<optgroup label="{e(g.capitalize())}">{opts}</optgroup>')
    return "".join(out)


def link(a, day):
    return f"/?a={a}&day={day}"


# ---------------- page ----------------
def file_info():
    """Rows in each data file (fallback: missing file -> 0)."""
    out = []
    for name, label in (("preflight.csv", "Pre-mission (sample)"), ("mission.csv", "Mission (sample / replaced)"),
                        ("uploaded.csv", "Uploaded"), ("manual.csv", "Typed in")):
        try:
            with open(os.path.join(ROOT, "data", name)) as f:
                n = max(sum(1 for _ in f) - 1, 0)
        except OSError:
            n = 0
        out.append(f"<li><b>{e(label)}</b> · data/{e(name)} · {n:,} rows</li>")
    return "".join(out)


def data_panel(astronaut):
    return f"""<section class="panel" id="data"><h3>Data in</h3>
      <div class="grid2">
        <div><form id="up" class="form">
            <label class="wide">CSV file<input type="file" id="file" accept=".csv,text/csv" required></label>
            <label class="wide">How to use it<select id="mode">
              <option value="add">Add to existing data (new days, new readings, new astronauts)</option>
              <option value="replace">Replace mission data (and pre-mission data if the file has day 0 or earlier)</option>
            </select></label>
            <button class="wide" id="upbtn">Upload &amp; process</button></form>
          <p class="hint" id="upstatus">Columns: astronaut,time,metric,value,unit (+ optional source,quality,detail).
            Every row is checked; bad rows are skipped and counted. <a href="/template.csv">Download template</a></p></div>
        <div><ul class="list small">{file_info()}</ul>
          <div class="btnrow">
            <form method="post" action="/generate" onsubmit="return confirm('Make fresh sample data? This rewrites preflight.csv and mission.csv.')">
              <button>Generate sample data</button></form>
            <form method="post" action="/clear" onsubmit="return confirm('Remove all uploaded and typed-in readings?')">
              <button class="ghost">Clear uploads + typed</button></form>
          </div></div>
      </div></section>
    <script>
    document.getElementById('up').addEventListener('submit', async (ev) => {{
      ev.preventDefault();
      const f = document.getElementById('file').files[0], st = document.getElementById('upstatus'),
            btn = document.getElementById('upbtn');
      if (!f) return;
      btn.disabled = true; st.textContent = 'Uploading ' + f.name + ' and re-running the engine… (large files take ~10 s)';
      try {{
        const text = await f.text();
        const mode = document.getElementById('mode').value;
        const r = await fetch('/upload?mode=' + mode + '&name=' + encodeURIComponent(f.name),
                              {{method: 'POST', headers: {{'Content-Type': 'text/csv'}}, body: text}});
        const j = await r.json();
        location.href = '/?a={e(astronaut)}&kind=' + (j.ok ? 'ok' : 'error') + '&msg=' + encodeURIComponent(j.msg);
      }} catch (err) {{
        st.textContent = 'Upload failed: ' + err; btn.disabled = false;
      }}
    }});
    </script>"""


def page(astronaut, day, msg="", msg_kind="info"):
    d = load(astronaut, day)
    banner = f'<div class="banner {e(msg_kind)}">{e(msg)}</div>' if msg else ""

    if d is None:
        body = f"""{banner}<section class="empty"><h2>No results yet</h2>
        <p>Upload a CSV, generate sample data, or run the engine on the files already in data/.</p>
        <form method="post" action="/run"><button>Run engine</button></form></section>{data_panel(astronaut)}"""
        return shell(body, astronaut, None)

    day, astronaut = d["day"], d["astronaut"]
    crew = "".join(
        f'<a class="crew {"on" if a == astronaut else ""}" href="{link(a, day)}"><b>{a}</b>'
        f'<span>{score_txt(d["scores"].get((a, day, "overall")))}</span>'
        f'{chip((d["scores"].get((a, day, "overall")) or {}).get("status"))}</a>' for a in d["crew"])
    days = "".join(f'<a class="day {"on" if x == day else ""}" href="{link(astronaut, x)}">Day {x}</a>'
                   for x in d["days"])

    cards = card("overall", d["scores"].get((astronaut, day, "overall")),
                 "Lowest of the five systems") + "".join(
        card(dom, d["scores"].get((astronaut, day, dom)), domain_note(d, dom)) for dom in DOMAINS)

    head = "".join(f"<th>{e(NAMES[x])}</th>" for x in DOMAINS + ["overall"])
    trend_rows = ""
    for x in d["days"]:
        cells = ""
        for dom in DOMAINS + ["overall"]:
            r = d["scores"].get((astronaut, x, dom))
            cells += f'<td class="t {e((r or {}).get("status", "no data")).replace(" ", "-")}">{score_txt(r)}</td>'
        trend_rows += f'<tr class="{"on" if x == day else ""}"><td><a href="{link(astronaut, x)}">Day {x}</a></td>{cells}</tr>'

    alerts = "".join(
        f'<li>{chip(a["tier"])} <span class="when">{e(a["time"][11:16] if a["time"] else "daily")}</span> '
        f'{e(a["message"])}</li>' for a in d["alerts"]) or "<li>No alerts.</li>"
    plans = "".join(f'<li><b>Day {p["scheduled_day"]}:</b> {e(p["action"])}'
                    f'{" <i>(" + e(p["note"]) + ")</i>" if p["note"] else ""}</li>' for p in d["plans"]) \
        or "<li>Nothing scheduled.</li>"

    rows = ""
    for r in d["results"]:
        pct = "" if r["pct_change"] is None else f'{r["pct_change"]:+.1f}%'
        exp = "" if r["predicted"] is None else f'{r["predicted"]:g}'
        rows += (f'<tr><td>{e(METRICS.get(r["metric"], {}).get("label", r["metric"]))}</td><td>{e(r["domain"])}</td>'
                 f'<td>{e(r["value"])}</td><td>{e(r["baseline"])}</td><td>{e(pct)}</td><td>{e(exp)}</td>'
                 f'<td>{chip(r["status"])}</td><td class="reason">{e(r["reason"])}</td></tr>')

    entries = "".join(f'<li>{e(m["astronaut"])} · {e(m["time"][:16].replace("T", " "))} · '
                      f'{e(METRICS.get(m["metric"], {}).get("label", m["metric"]))} = {e(m["value"])} {e(m["unit"])}</li>'
                      for m in manual_entries()) or "<li>None yet.</li>"
    astro_opts = "".join(f'<option {"selected" if a == astronaut else ""}>{e(a)}</option>' for a in d["crew"])

    body = f"""{banner}
    <section class="crewbar">{crew}</section>
    <nav class="days">{days}</nav>
    <h2>{e(astronaut)} · Mission day {day}</h2>
    <section class="cards">{cards}</section>

    <section class="grid">
      <div class="panel"><h3>Alerts</h3><ul class="list">{alerts}</ul>
        <h3>Plan (countermeasures)</h3><ul class="list">{plans}</ul></div>

      <div class="panel"><h3>Add a reading</h3>
        <form method="post" action="/add" class="form">
          <label>Astronaut<select name="astronaut">{astro_opts}</select></label>
          <label>Mission day<input type="number" name="day" value="{day}" min="-13" max="180" required></label>
          <label>Time<input type="time" name="time" value="21:00" required></label>
          <label class="wide">Measurement<select name="metric">{metric_options()}</select></label>
          <label class="wide">Value<input name="value" inputmode="decimal" placeholder="e.g. 290" required></label>
          <button class="wide">Save &amp; re-run engine</button>
        </form>
        <p class="hint">Saved to data/manual.csv and checked like any sensor reading. Use the next day number
        (e.g. Day {d["days"][-1] + 1}) to add a new day. Re-running takes a few seconds.</p>
        <h3>Recent entries</h3><ul class="list small">{entries}</ul>
        <form method="post" action="/undo"><button class="ghost">Undo last entry</button></form>
      </div>
    </section>

    {data_panel(astronaut)}

    <section class="panel"><h3>Trend</h3>
      <div class="scroll"><table class="trend"><tr><th>Day</th>{head}</tr>{trend_rows}</table></div></section>

    <section class="panel"><h3>Every check for day {day}</h3><div class="scroll">
      <table class="results"><tr><th>Metric</th><th>System</th><th>Value</th><th>Baseline</th><th>Change</th>
      <th>Expected</th><th>Status</th><th>Why</th></tr>{rows or '<tr><td colspan="8">No checks.</td></tr>'}</table>
    </div></section>

    <details class="panel"><summary>Engine log (last run)</summary><pre>{e(last_run())}</pre></details>"""
    return shell(body, astronaut, day)


def shell(body, astronaut, day):
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Shadow Self</title>
<style>
:root{{--bg:#0b1020;--panel:#121a30;--line:#24304f;--text:#e6ebf7;--dim:#8f9bb8;--ok:#2fbf71;--watch:#f2b233;
--act:#f2683a;--urgent:#e5304f;--none:#59627a;--accent:#7aa2ff}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--text);font:15px/1.45 -apple-system,
BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}}main{{max-width:1180px;margin:0 auto;padding:16px}}
header{{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:14px 16px;
border-bottom:1px solid var(--line);background:#0e1528}}header h1{{font-size:18px;margin:0;letter-spacing:.5px}}
header small{{color:var(--dim)}}a{{color:var(--accent);text-decoration:none}}
button{{background:var(--accent);color:#0b1020;border:0;border-radius:8px;padding:9px 14px;font-weight:600;cursor:pointer}}
button.ghost{{background:transparent;color:var(--dim);border:1px solid var(--line)}}
h2{{margin:18px 0 10px;font-size:20px}}h3{{margin:4px 0 10px;font-size:15px;color:var(--dim);font-weight:600}}
.banner{{padding:10px 14px;border-radius:8px;margin-bottom:12px;background:#17325a}}.banner.error{{background:#5a1f2a}}
.banner.ok{{background:#173f2c}}
.crewbar{{display:flex;gap:10px;flex-wrap:wrap}}.crew{{display:flex;align-items:center;gap:10px;padding:10px 14px;
background:var(--panel);border:1px solid var(--line);border-radius:10px;color:var(--text)}}
.crew.on{{border-color:var(--accent)}}.crew span{{font-size:20px;font-weight:700}}
.days{{display:flex;gap:6px;margin-top:12px;flex-wrap:wrap}}.day{{padding:5px 12px;border-radius:20px;
border:1px solid var(--line);color:var(--dim)}}.day.on{{background:var(--accent);color:#0b1020;border-color:var(--accent)}}
.cards{{display:grid;grid-template-columns:repeat(auto-fill,minmax(170px,1fr));gap:10px}}
.card{{background:var(--panel);border:1px solid var(--line);border-left:4px solid var(--none);border-radius:10px;padding:12px}}
.card.ok{{border-left-color:var(--ok)}}.card.watch{{border-left-color:var(--watch)}}.card.act{{border-left-color:var(--act)}}
.card.urgent{{border-left-color:var(--urgent)}}.card-top{{display:flex;justify-content:space-between;gap:6px;
font-size:13px;color:var(--dim)}}.score{{font-size:34px;font-weight:700;margin:4px 0}}
.note{{font-size:12.5px;color:var(--dim);overflow-wrap:anywhere}}
.chip{{font-size:11px;font-weight:700;padding:2px 7px;border-radius:10px;background:var(--none);color:#fff;white-space:nowrap}}
.chip.ok,.chip.info{{background:var(--ok)}}.chip.watch{{background:var(--watch);color:#1b1300}}
.chip.act{{background:var(--act)}}.chip.urgent{{background:var(--urgent)}}
.grid{{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:12px}}
.panel{{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:14px;margin-top:12px}}
.grid .panel{{margin-top:0}}.list{{list-style:none;padding:0;margin:0 0 14px}}.list li{{padding:6px 0;
border-bottom:1px solid var(--line);font-size:13.5px}}.list.small li{{font-size:12.5px;color:var(--dim)}}
.when{{color:var(--dim);font-size:12px;margin:0 4px}}
.form{{display:grid;grid-template-columns:1fr 1fr 1fr;gap:10px}}.form label{{display:flex;flex-direction:column;
gap:4px;font-size:12.5px;color:var(--dim)}}.form .wide{{grid-column:1/-1}}
input,select{{background:#0b1020;color:var(--text);border:1px solid var(--line);border-radius:8px;padding:8px;font:inherit}}
.hint{{font-size:12px;color:var(--dim)}}.grid2{{display:grid;grid-template-columns:1fr 1fr;gap:16px}}
.btnrow{{display:flex;gap:8px;flex-wrap:wrap}}button:disabled{{opacity:.5}}.scroll{{overflow-x:auto}}table{{border-collapse:collapse;width:100%;font-size:13px}}
th,td{{padding:7px 8px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}}th{{color:var(--dim);font-weight:600}}
td.t{{text-align:center;font-weight:700}}td.ok{{color:var(--ok)}}td.watch{{color:var(--watch)}}td.act{{color:var(--act)}}
td.urgent{{color:var(--urgent)}}tr.on{{background:#18223d}}.reason{{color:var(--dim);min-width:260px}}
pre{{white-space:pre-wrap;font-size:12px;color:var(--dim);max-height:420px;overflow:auto}}
summary{{cursor:pointer;color:var(--dim);font-weight:600}}.empty{{text-align:center;padding:60px 0}}
@media (max-width:760px){{.grid,.grid2{{grid-template-columns:1fr}}.form{{grid-template-columns:1fr 1fr}}}}
</style></head><body>
<header><div><h1>🛰️ SHADOW SELF</h1><small>Astronaut health monitor · early warning</small></div>
<form method="post" action="/run"><input type="hidden" name="astronaut" value="{e(astronaut)}">
<input type="hidden" name="day" value="{e(day if day is not None else '')}"><button>Run engine</button></form></header>
<main>{body}</main></body></html>"""
