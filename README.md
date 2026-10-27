# Rocket Monkeys
# Shadow Self — astronaut health engine (core, no UI)

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

## Planted test events in the sample data
A1 = healthy control. A2 = drifting (short workouts, high salt, low fluids, poor sleep, high CO2).
ECG strap slip (A2 day 1 06:00) · solar particle event (day 2 14:00) · stress episode (A2 day 2 20:00)
· irregular rhythm (A2 day 3 09:00) · dosimeter mismatch (A2 day 3) · 2 broken rows · 1 unit conversion.
All values are made up for testing; thresholds are demo values, not medical standards.
