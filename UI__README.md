# Shadow Self — UI (website)

Everything the user sees in the browser lives in this folder. The engine (main.py, modules/, etc.)
stays in the main project folder; the UI only reads its database and calls it.

| File | What it is |
|---|---|
| app.py | The local web server: routes, typed entry, CSV upload, generate, clear, template + report download |
| page.py | The page itself (HTML): sidebar, warning strip and the 6 tabs below |
| static/shadow.css | All styles + motion (locked tokens, tablet + phone layouts, print layout for the report) |
| DESIGN.md | The design system: colour, type, 4px spacing grid and motion rules |
| static/shadow.js | Shared selection, in-place crew/day swaps, radar morph, trend + measurement charts, drawer, tabs, validation, upload, log filter, print |
| test_ui.py | Tests: `python3 -m unittest UI.test_ui -v` (never changes data/) |
| _backup_v1/ | The previous app.py + page.py, untouched |

## Layout
- Frame (navy, the only place with stars): sidebar with crew (score, status, alert count), views and a collapse
  toggle; compact header with crew + mission day, day navigation (buttons or the left/right arrow keys),
  last engine run and Run engine. Crew and day changes swap the page in place and keep the tab and selection.

## Tabs
- Overview: Shadow Score summary (vs the previous day, Watch/Act meter, counts), system profile radar (five
  systems on the 0-100 score, Watch < 75 and Act < 50 zones, previous day dashed), needs attention (alerts by
  tier, then the top 3 activities), five system tiles, a trend linked to the selected system (score by day, or one
  measurement against its baseline +/- MDC band), 24 h heart rate + dose rate. Selecting a system updates all of
  these; "View system details" opens a drawer with every measurement, alert and planned action.
- Systems: system list + one focused system with every check (value, baseline, change, MDC, Shadow expected,
  status, reason). All checks / Flagged filter.
- Report: in-depth health report (summary, trend chart with legend toggles + tooltips, exact-value table, alerts
  timeline, plan, radiation budget, every check, sensor doubts). Print / PDF and Earth packet (JSON) download
- Data: add a reading (checked against the metric's accepted range before sending), recent entries + undo,
  pre-mission and mission upload boxes (result shown in the box), files, Reset (generate / clear, both confirm)
    Pre-mission box -> only day 0 and earlier rows (Add = uploaded.csv, Replace = preflight.csv)
    Mission box     -> only day 1 onward rows      (Add = uploaded.csv, Replace = mission.csv)
- Engine: last run, result, counts, rejected rows, fallback errors; the log is collapsible and filterable
- How to use: six steps, what each status means, one real check worked through

## Run it (from the shadow_self folder)
    python3 UI/app.py            # opens http://localhost:8002 (landing page; dashboard at /app)  (Ctrl + C to stop)
    python3 UI/app.py --port 8100   # a different address (8002 busy -> the next free port, printed in the terminal)

One copy, always current:
- Running it again while it is already running opens the running copy instead of starting a second one
  (GET /health identifies it).
- Edit page.py, app.py or any engine module it imports -> the server restarts itself on the same address within
  a second. A file that does not compile is reported in the terminal and the last good code keeps running.
- CSS / JS links carry a version (?v=...) and every page carries a build stamp. If a day or crew switch gets a page
  from a newer build, the browser loads it normally instead of mixing old and new code. Just refresh after edits.

## How the UI talks to the engine
- Reads:   shadow_self.db (scores, alerts, plans, checks) and outputs/last_run.txt
- Writes:  data/manual.csv (typed readings), data/uploaded.csv (CSV uploads), data/mission.csv + preflight.csv (replace)
- Runs:    main.py (re-process) and generate_sample_data.py (sample data) as separate processes

| Route | Does |
|---|---|
| GET  /app | dashboard (?a=A2&day=3 picks astronaut + day) |
| GET  / | landing page (old /?a=..&day=.. links redirect to /app; /landing redirects here): WebGL radar hero, drift chart, the live dashboard as a guided read-only demo, anatomy drawing (UI/landing.py, static/landing.css, static/landing.js, static/vendor/) |
| GET  /health | identifies this server (used so a second launch reuses it) |
| GET  /template.csv | example CSV |
| GET  /report.json?a=A2&day=3 | that day's Earth packet as a download |
| GET  /static/... | CSS + JavaScript |
| POST /add | save one typed reading, re-run engine |
| POST /undo | remove last typed reading, re-run engine |
| POST /upload?mode=add or replace&section=pre or mission | CSV upload (only that phase's rows), re-run engine |
| POST /generate | fresh sample data, re-run engine |
| POST /clear | clear uploads + typed readings, re-run engine |
| POST /run | re-run engine |
