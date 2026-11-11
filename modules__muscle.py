"""
MUSCLE MODULE                                           (PSEUDOCODE.md section 8)

DAILY:    workload % of target -> 7-step check
          workload under 70% for 3 days in a row -> WATCH "missed workouts"
TEST DAY: muscle area (ultrasound), strength (force sensor) -> 7-step check
COMBINE:  area AND strength both "act" -> ACT "muscle loss"
          only one changed               -> WATCH
"""
from config.settings import LOW_WORKLOAD_DAYS, LOW_WORKLOAD_PCT
from pipeline.check import check_measured, module_result


def run(db, astronaut, day, ctx):
    results = check_measured(db, astronaut, day, ["resistance_load_pct", "quad_csa", "knee_torque"])
    statuses, flags, notes = [], [], []

    # missed workouts
    recent = [h["value"] for h in db.get_history(astronaut, "resistance_load_pct", day - LOW_WORKLOAD_DAYS + 1, day)]
    if len(recent) == LOW_WORKLOAD_DAYS and all(v < LOW_WORKLOAD_PCT for v in recent):
        statuses.append("watch")
        flags.append("missed_workouts")
        notes.append(f"workload under {LOW_WORKLOAD_PCT}% for {LOW_WORKLOAD_DAYS} days")

    # combine area + strength (latest test of each)
    area = (db.get_latest_result(astronaut, "quad_csa", day) or {}).get("status", "ok")
    strength = (db.get_latest_result(astronaut, "knee_torque", day) or {}).get("status", "ok")
    if area == "act" and strength == "act":
        statuses.append("act")
        flags.append("muscle_loss")
        notes.append("muscle area AND strength both down, persistent")
    elif {area, strength} & {"watch", "act"}:
        flags.append("muscle_change")
        notes.append("muscle area or strength changed")
        # one test alone can't be "act": cap those results at watch
        for r in results:
            if r["metric"] in ("quad_csa", "knee_torque") and r["status"] == "act":
                r["status"] = "watch"

    return module_result("muscle", results, statuses, flags, notes)
