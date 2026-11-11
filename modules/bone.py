"""
BONE MODULE                                             (PSEUDOCODE.md section 9)

DAILY:    load fraction = resistance done / target (0..1)
          monthly loss rate = 2% - 1% x load fraction     (between 1% and 2%)
          bone estimate = yesterday x (1 - monthly rate / 30)   <- ESTIMATE, not measured
TEST DAY: urine calcium -> 7-step check
STONE RISK points: urine calcium up beyond MDC +1, fluids < 2 L +1, sodium > 3,500 mg +1
          0 low, 1 medium, 2-3 high
ALERTS:   fast estimated loss -> WATCH | stone risk high -> ACT
          vitamin D missed 2+ days this week -> WATCH
"""
from config.settings import BONE_FAST_LOSS, HIGH_SODIUM_MG, LOW_FLUIDS_L
from pipeline.check import check_measured, module_result


def bone_estimate(db, astronaut, day):
    """Fallback inside: a missing workload day counts as a full workout (no false alarm)."""
    est, rates = 100.0, []
    for d in range(1, day + 1):
        load = db.get_value(astronaut, "resistance_load_pct", d)
        fraction = min(max((100 if load is None else load) / 100, 0), 1)
        rate = 2.0 - 1.0 * fraction
        rates.append(rate)
        est *= 1 - rate / 100 / 30
    last7 = rates[-7:]
    return est, sum(last7) / len(last7)


def run(db, astronaut, day, ctx):
    results = check_measured(db, astronaut, day, ["urine_calcium"])
    statuses, flags, notes = [], [], []

    est, rate = bone_estimate(db, astronaut, day)
    notes.append(f"estimated bone density {est:.2f}% of pre-flight ({rate:.2f}%/month, model estimate)")
    if rate > BONE_FAST_LOSS:
        statuses.append("watch")
        flags.append("fast_bone_loss")

    latest = db.get_latest_result(astronaut, "urine_calcium", day) or {}
    urine_up = bool(latest.get("real_change") and latest.get("bad_direction"))
    if urine_up:
        flags.append("urine_up")

    fluids = db.get_value(astronaut, "fluids", day)
    sodium = db.get_value(astronaut, "sodium", day)
    low_fluids = fluids is not None and fluids < LOW_FLUIDS_L
    high_sodium = sodium is not None and sodium > HIGH_SODIUM_MG
    points = urine_up + low_fluids + high_sodium
    stone = ["low", "medium", "high", "high"][points]
    reasons = [w for w, on in [("urine Ca up", urine_up), ("low fluids", low_fluids), ("high sodium", high_sodium)] if on]
    notes.insert(0, f"kidney stone risk {stone.upper()}" + (f" ({', '.join(reasons)})" if reasons else ""))
    if stone == "high":
        statuses.append("act")
        flags.append("stone_risk_high")

    vitd = [h["value"] for h in db.get_history(astronaut, "vitamin_d", day - 6, day)]
    if sum(v < 400 for v in vitd) >= 2:
        statuses.append("watch")
        flags.append("vitd_missed")
        notes.append("vitamin D missed 2+ days this week")

    return module_result("bone", results, statuses, flags, notes,
                         bone_estimate_pct=round(est, 2), stone_risk=stone)
