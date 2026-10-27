/main sequence code 
"""
SHADOW SELF — THE BIG LOOP                              (PSEUDOCODE.md section 0)

start system -> load settings -> open database
load pre-mission data -> build baselines -> train Shadow models
for each mission day (replaying the data files in time order):
    take in the day's readings (ingestion -> storage)
    every 5 s: heartbeat check + radiation check   (urgent -> alert NOW)
    end of day: summarize fast data -> 5 modules -> fusion -> actions -> report

Run:   python3 main.py
Data:  data/preflight.csv  +  data/mission.csv   (make sample data: python3 generate_sample_data.py)
"""
import os
import sys
from collections import defaultdict
from datetime import timedelta

from actions.act import act
from actions.report import print_report
from config.settings import ASTRONAUTS, LAUNCH_DATE, METRICS
from fast_checks.heartbeat import HeartbeatMonitor, summarize_heart_day
from fast_checks.radiation_watch import RadiationWatch, summarize_dose_day
from fusion.fuse import fuse
from ingestion.ingest import ingest, ingest_csv
from modules import bone, cardio, muscle, radiation, sans
from shadow_model.model import ShadowBank
from storage.db import DB, ROOT

DATA = os.path.join(ROOT, "data")
MODULES = {"radiation": radiation, "muscle": muscle, "bone": bone, "sans": sans, "cardio": cardio}


def save_daily(db, astronaut, day, values, source, log):
    """End-of-day numbers go through ingestion too, so they get checked like everything else."""
    stamp = (LAUNCH_DATE + timedelta(days=day - 1)).isoformat() + "T23:59:59"
    clean = [ingest({"astronaut": astronaut, "time": stamp, "metric": k, "value": v,
                     "unit": METRICS[k]["unit"], "source": source}, log)
             for k, v in values.items() if v is not None]
    db.save_readings([c for c in clean if c])


def main():
    print("=" * 70)
    print("  SHADOW SELF — astronaut health engine (no UI)")
    print("=" * 70)
    for f in ("preflight.csv", "mission.csv"):
        if not os.path.exists(os.path.join(DATA, f)):
            sys.exit(f"Missing data/{f}. Run:  python3 generate_sample_data.py")

    db = DB(fresh=True)
    log = []

    # pre-mission: baselines + Shadow models
    pre = ingest_csv(os.path.join(DATA, "preflight.csv"), log)
    db.save_readings(pre)
    n_base = db.build_baselines_from_preflight()
    shadow = ShadowBank()
    trained = shadow.train(db)
    print(f"\nPre-mission: {len(pre)} readings -> {n_base} baselines")
    for (a, t), (n, sd) in trained.items():
        print(f"  Shadow model {a} {t}: trained on {n} days, usual error ±{sd}")

    # mission data, grouped by day
    mission = ingest_csv(os.path.join(DATA, "mission.csv"), log)
    by_day = defaultdict(list)
    for r in mission:
        by_day[r["day"]].append(r)
    print(f"Mission file: {len(mission)} clean readings over days {min(by_day)}-{max(by_day)}")
    rejected = [l for l in log if l.startswith("rejected")]
    for l in log:
        if not l.startswith("rejected"):
            print(f"  ingestion: {l}")
    for l in rejected:
        print(f"  ingestion: {l[:100]}")

    ctx = {"shadow": shadow, "rad_event_days": {a: [] for a in ASTRONAUTS}}
    hearts = {a: HeartbeatMonitor(a, db.get_baseline(a, "resting_hr")) for a in ASTRONAUTS}
    rads = {a: RadiationWatch(a) for a in ASTRONAUTS}

    for day in sorted(by_day):
        db.save_readings(by_day[day])                       # take in today's readings
        print("\n" + "=" * 70 + f"\n  MISSION DAY {day}\n" + "=" * 70)
        for a in ASTRONAUTS:
            # ---- every 5 seconds (replayed) ----
            hb, rw = hearts[a], rads[a]
            hb.new_day()
            rw.new_day()
            heart_flags = set()
            for row in db.get_stream(a, "heart_rate", day):
                rr = [float(x) for x in row["detail"].split(";") if x]
                for tier, key, msg in hb.process(row["time"], row["value"], rr, row["quality"]):
                    db.save_alert(a, day, row["time"], tier, "cardio", key, msg)
                    heart_flags.add(key)
            for row in db.get_stream(a, "dose_rate", day):
                for tier, key, msg in rw.process(row["time"], row["value"], row["quality"]):
                    db.save_alert(a, day, row["time"], tier, "radiation", key, msg)
                    if key == "radiation_event":
                        ctx["rad_event_days"][a].append(day)

            # ---- end of day ----
            summary = summarize_heart_day(db, a, day, hb)
            summary.update(summarize_dose_day(rw))
            save_daily(db, a, day, summary, "end_of_day", [])
            mods = {name: mod.run(db, a, day, ctx) for name, mod in MODULES.items()}
            if "irregular_rhythm" in heart_flags:
                mods["cardio"]["flags"].add("irregular_rhythm")
            fused = fuse(db, a, day, mods, ctx, heart_flags)
            action = act(db, a, day, mods, fused)
            print_report(a, day, mods, fused, action)
            shadow.relearn(db, a, day)

    print("\nDone. Database: shadow_self.db   Earth summaries: outputs/")


if __name__ == "__main__":
    main()
