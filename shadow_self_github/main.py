"""
SHADOW SELF — THE BIG LOOP                              (PSEUDOCODE.md section 0)

1. load data          (no data files? -> make sample data first)
                      + data/uploaded.csv + data/manual.csv from the dashboard, duplicates skipped
2. pre-mission        baselines + train Shadow models
3. for each mission day:
       take in the day's readings
       every 5 s  : heartbeat check + radiation check   (urgent -> alert NOW)
       end of day : summarize -> 5 modules -> fusion -> actions -> report
4. print any errors that happened (the run never stops because of them)

Every step runs inside safe(): if it breaks, the error goes to outputs/errors.log,
a fallback is used, and the system keeps going.

Run:  python3 main.py      (from inside the shadow_self folder)
"""
import os
from collections import defaultdict
from datetime import timedelta

from actions.act import act, fallback_action
from actions.report import print_report
from config.settings import ASTRONAUTS, LAUNCH_DATE, METRICS
from fast_checks.heartbeat import HeartbeatMonitor, summarize_heart_day
from fast_checks.radiation_watch import RadiationWatch, summarize_dose_day
from fusion.fuse import fallback_fusion, fuse
from ingestion.ingest import ingest, ingest_csv
from modules import bone, cardio, muscle, radiation, sans
from pipeline.safe import ERRORS, LOG_PATH, fallback_module, safe
from shadow_model.model import ShadowBank
from storage.db import ROOT, open_db

DATA = os.path.join(ROOT, "data")
FILES = {"preflight": os.path.join(DATA, "preflight.csv"), "mission": os.path.join(DATA, "mission.csv")}
UPLOADED = os.path.join(DATA, "uploaded.csv")  # CSV files uploaded in the dashboard ("add" mode)
MANUAL = os.path.join(DATA, "manual.csv")      # readings typed into the dashboard
MODULES = {"radiation": radiation, "muscle": muscle, "bone": bone, "sans": sans, "cardio": cardio}


# ---------------- 1. load data ----------------
def load_data(log):
    if not all(os.path.exists(f) for f in FILES.values()):
        print("  No data files found -> making sample data first")
        import generate_sample_data
        safe("generate sample data", generate_sample_data.main)
    preflight, mission = ingest_csv(FILES["preflight"], log), ingest_csv(FILES["mission"], log)
    for path, name in ((UPLOADED, "uploaded"), (MANUAL, "typed-in")):   # dashboard data: day <= 0 = pre-mission
        if os.path.exists(path):
            extra = ingest_csv(path, log)
            preflight += [r for r in extra if r["day"] <= 0]
            mission += [r for r in extra if r["day"] > 0]
            if extra:
                log.append(f"loaded {len(extra):,} {name} dashboard readings")
    return dedupe(preflight, log), dedupe(mission, log)


def dedupe(readings, log):
    """Same astronaut + time + metric twice? keep the LAST one (uploads/typed entries win)."""
    unique = {(r["astronaut"], r["time"], r["metric"]): r for r in readings}
    if len(unique) < len(readings):
        log.append(f"skipped {len(readings) - len(unique):,} duplicate readings")
    return list(unique.values())


# ---------------- 2. pre-mission ----------------
def pre_mission(db, readings, astronauts):
    db.save_readings(readings)
    n = db.build_baselines_from_preflight()
    shadow = ShadowBank()
    trained = safe("train Shadow models", lambda: shadow.train(db, astronauts), fallback={})
    print(f"\nPre-mission: {len(readings)} readings -> {n} baselines")
    for (a, t), (days, err) in trained.items():
        print(f"  Shadow model {a} {t}: " + (f"trained on {days} days, usual error ±{err}" if err else
                                             f"not enough data ({days} days) — checks run without it"))
    return shadow


# ---------------- 3a. every 5 seconds ----------------
def fast_checks(db, a, day, heart, rad, ctx):
    heart.new_day()
    rad.new_day()
    fired = set()
    for row in db.get_stream(a, "heart_rate", day):
        rr = [float(x) for x in (row["detail"] or "").split(";") if x.strip()]
        for tier, key, msg in safe(f"heartbeat {a} {row['time']}",
                                   lambda: heart.process(row["time"], row["value"], rr, row["quality"]), []):
            db.save_alert(a, day, row["time"], tier, "cardio", key, msg)
            fired.add(key)
    for row in db.get_stream(a, "dose_rate", day):
        for tier, key, msg in safe(f"radiation {a} {row['time']}",
                                   lambda: rad.process(row["time"], row["value"], row["quality"]), []):
            db.save_alert(a, day, row["time"], tier, "radiation", key, msg)
            if key == "radiation_event":
                ctx["rad_event_days"][a].append(day)
    return fired


# ---------------- 3b. end of day ----------------
def save_daily(db, a, day, values):
    """End-of-day numbers go through ingestion too, so they get checked like everything else."""
    stamp = (LAUNCH_DATE + timedelta(days=day - 1)).isoformat() + "T23:59:59"
    clean = [ingest({"astronaut": a, "time": stamp, "metric": k, "value": v,
                     "unit": METRICS[k]["unit"], "source": "end_of_day"}, [])
             for k, v in values.items() if v is not None]
    db.save_readings([c for c in clean if c])


def end_of_day(db, a, day, heart, rad, fired, ctx):
    summary = safe(f"heart summary {a} day {day}", lambda: summarize_heart_day(db, a, day, heart), {})
    summary.update(safe(f"dose summary {a} day {day}", lambda: summarize_dose_day(rad), {}))
    save_daily(db, a, day, summary)

    mods = {name: safe(f"{name} module {a} day {day}", lambda m=mod: m.run(db, a, day, ctx),
                       fallback_module(name)) for name, mod in MODULES.items()}
    if "irregular_rhythm" in fired:
        mods["cardio"]["flags"].add("irregular_rhythm")

    fused = safe(f"fusion {a} day {day}", lambda: fuse(db, a, day, mods, ctx, fired), None) or fallback_fusion(mods)
    action = safe(f"actions {a} day {day}", lambda: act(db, a, day, mods, fused), None) \
        or fallback_action(db, a, day, fused)
    safe(f"save scores {a} day {day}", lambda: db.save_scores(a, day, fused, action["tier"]))
    safe(f"report {a} day {day}", lambda: print_report(a, day, mods, fused, action))
    safe(f"relearn {a} day {day}", lambda: ctx["shadow"].relearn(db, a, day))


# ---------------- main ----------------
def main():
    print("=" * 72 + "\n  SHADOW SELF — astronaut health engine (no UI)\n" + "=" * 72)
    log = []
    preflight, mission = load_data(log)
    if not mission:
        print("  No usable mission data — nothing to process. Check the data folder.")
        return

    db = open_db()
    astronauts = sorted({r["astronaut"] for r in preflight + mission}) or ASTRONAUTS   # whoever is in the data
    shadow = pre_mission(db, preflight, astronauts)

    by_day = defaultdict(list)
    for r in mission:
        by_day[r["day"]].append(r)
    print(f"Mission data: {len(mission):,} clean readings, days {min(by_day)}-{max(by_day)}")
    for note in log:
        print(f"  ingestion: {note[:100]}")

    print(f"Astronauts: {', '.join(astronauts)}")
    ctx = {"shadow": shadow, "rad_event_days": {a: [] for a in astronauts}}
    hearts = {a: HeartbeatMonitor(a, db.get_baseline(a, "resting_hr")) for a in astronauts}
    rads = {a: RadiationWatch(a) for a in astronauts}

    for day in sorted(by_day):
        db.save_readings(by_day[day])
        print("\n" + "=" * 72 + f"\n  MISSION DAY {day}\n" + "=" * 72)
        for a in astronauts:
            if not any(r["astronaut"] == a for r in by_day[day]):
                continue                                   # no data for this astronaut today
            fired = fast_checks(db, a, day, hearts[a], rads[a], ctx)
            end_of_day(db, a, day, hearts[a], rads[a], fired, ctx)

    print("\n" + "=" * 72)
    if ERRORS:
        print(f"  {len(ERRORS)} problem(s) handled with fallbacks — details in outputs/errors.log:")
        for e in ERRORS[:10]:
            print(f"   - {e[:100]}")
    else:
        print("  No errors.")
    print("  Database: shadow_self.db   Earth summaries: outputs/")


if __name__ == "__main__":
    main()
