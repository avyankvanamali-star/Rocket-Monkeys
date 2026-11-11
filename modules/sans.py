"""
SANS MODULE — eyes / brain                              (PSEUDOCODE.md section 10)

TESTS:    vision self-test score, optic nerve sheath diameter, RNFL thickness -> 7-step check
          vision score dropping -> also "schedule OCT scan"
DAILY:    headache or blur >= 3 for 3 days -> WATCH
CONTEXT:  high sodium, high CO2 where they sleep -> added to the notes
"""
from config.settings import HIGH_CO2_PPM, HIGH_SODIUM_MG, SYMPTOM_DAYS, SYMPTOM_LEVEL
from pipeline.check import check_measured, module_result


def run(db, astronaut, day, ctx):
    results = check_measured(db, astronaut, day, ["near_vision_score", "onsd", "rnfl", "headache", "vision_blur"])
    statuses, flags, notes = [], [], []

    if any(r["metric"] == "near_vision_score" and r["flagged"] for r in results):
        flags.append("schedule_oct")

    for metric in ("headache", "vision_blur"):
        recent = [h["value"] for h in db.get_history(astronaut, metric, day - SYMPTOM_DAYS + 1, day)]
        if len(recent) == SYMPTOM_DAYS and all(v >= SYMPTOM_LEVEL for v in recent):
            statuses.append("watch")
            notes.append(f"{metric.replace('_', ' ')} >= {SYMPTOM_LEVEL} for {SYMPTOM_DAYS} days")

    sodium = db.get_value(astronaut, "sodium", day) or 0
    co2 = db.get_value(astronaut, "co2_sleep", day) or 0
    if sodium > HIGH_SODIUM_MG:
        notes.append(f"context: high sodium ({sodium:.0f} mg)")
    if co2 > HIGH_CO2_PPM:
        notes.append(f"context: high CO2 in sleep area ({co2:.0f} ppm)")

    out = module_result("sans", results, statuses, flags, notes)
    if out["status"] in ("watch", "act"):
        out["flags"].add("sans_watch")
    return out
