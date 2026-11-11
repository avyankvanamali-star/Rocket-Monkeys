# Shadow Self — astronaut health engine (core, no UI)

## Dashboard app (easiest)
    python3 UI/app.py                   # opens http://localhost:8002 in your browser (Ctrl + C to stop)
                                        # / = landing page with a live demo, /app = the dashboard
                                        # already running? it just opens that copy; it reloads itself on code edits
                                        # all website files are in UI/ (see UI/README.md)
- Pick an astronaut and a day, see the 5 system scores, alerts, plan, trend, and every check.
- "Add a reading": type any measurement -> it's checked like a sensor reading, saved to
  data/manual.csv, and the engine re-runs. Use the next day number to add a new day.
- "Undo last entry" removes your last typed reading.
- "Data in" panel:
    - Upload CSV -> every row is checked; bad rows are skipped and counted.
        Add     = goes into data/uploaded.csv on top of everything else (new days / readings / astronauts)
        Replace = becomes data/mission.csv (and data/preflight.csv if the file has day 0 or earlier)
    - Generate sample data -> fresh preflight.csv + mission.csv, then the engine re-runs
    - Clear uploads + typed -> empties uploaded.csv and manual.csv
    - Download template -> example CSV with the exact columns
  Duplicate readings (same astronaut + time + metric) are skipped automatically; the newest one wins.

## Run it (VS Code terminal, inside this folder)
    python3 generate_sample_data.py     # makes data/preflight.csv + data/mission.csv (3 mission days)
    python3 main.py                     # runs the whole engine, prints a daily report

Only built-in Python is used (no pip installs).

## What you get
- Terminal: a daily report per astronaut (scores, alerts, rules fired, plan)
- `shadow_self.db`: open in a SQLite app (e.g. DB Browser for SQLite)
    - measurements: every reading (5-second streams + daily logs + tests)
    - baselines:    each astronaut's pre-mission normal
    - results:      every 7-step check (value, baseline, %, MDC, Shadow prediction, status, reason)
    - alerts:       every alert, with time and tier
    - plans:        countermeasures and the day they're scheduled
- `outputs/earth_summary_<astronaut>_day<N>.json`: the daily packet sent to Earth

## How the folders connect
    data/*.csv -> ingestion/ -> storage/ (shadow_self.db)
                     -> fast_checks/ (every 5 s: heartbeat, radiation)
                     -> modules/ (radiation, muscle, bone, sans, cardio) -- use pipeline/check.py + shadow_model/
                     -> fusion/ (cross-system rules + drift scores)
                     -> actions/ (alerts, plan, Earth summary, report)
All numbers/thresholds live in config/settings.py. Logic in plain English: PSEUDOCODE.md.

## Feeding in your own data
Any CSV with columns: astronaut,time,metric,value,unit,source,quality,detail
(metric names must exist in config/settings.py METRICS). Save as data/mission.csv and run main.py.

## Fallbacks (it never crashes)
Every step is wrapped in `safe()` (pipeline/safe.py). If something breaks, the error goes to
`outputs/errors.log`, a fallback is used, and the run keeps going. A crashed system shows
"NO DATA" instead of a fake healthy score. Full list: PSEUDOCODE.md section 16.

## Planted test events in the sample data
Every test for all 5 systems runs every day in the demo so each system shows progress.
A1 = healthy control. A2 = drifting in every system (short workouts, high salt, low fluids, poor sleep, high CO2).
Change the story by editing the NORMAL / DAILY / TESTS / DRIFT tables at the top of generate_sample_data.py.
ECG strap slip (A2 day 1 06:00) · solar particle event (day 2 14:00) · stress episode (A2 day 2 20:00)
· irregular rhythm (A2 day 3 09:00) · dosimeter mismatch (A2 day 3) · 2 broken rows · 1 unit conversion.
All values are made up for testing; thresholds are demo values, not medical standards.
