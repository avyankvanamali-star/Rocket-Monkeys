"""
CARDIO MODULE — daily                                   (PSEUDOCODE.md section 11)

uses the heartbeat end-of-day summary
resting HR, HRV       -> 7-step check WITH Shadow model
HR recovery, BP, irregular beats, stroke volume -> 7-step check
Shadow residual in the bad direction N days in a row -> ACT "cardio drift"
radiation event in last 7 days -> stricter checks
"""
from config.settings import CARDIO_DRIFT_DAYS, METRICS, STRICT_DAYS
from pipeline.check import check_measured, module_result

METRICS_TODAY = ["resting_hr", "hrv_rmssd", "hr_recovery", "systolic_bp", "irregular_beats", "stroke_volume"]


def _drifting(db, astronaut, metric, day):
    """True if the Shadow residual was in the bad direction for N days in a row."""
    today = db.get_latest_result(astronaut, metric, day)
    if not today or today["day"] != day:
        return False
    past = [today] + db.get_recent_results(astronaut, metric, CARDIO_DRIFT_DAYS - 1, before_day=day)
    up_is_bad = METRICS[metric]["bad"] == "up"
    return len(past) == CARDIO_DRIFT_DAYS and all(
        p["residual"] is not None and p["resid_sd"]
        and (p["residual"] > 0 if up_is_bad else p["residual"] < 0)
        and abs(p["residual"]) > p["resid_sd"] for p in past)


def run(db, astronaut, day, ctx):
    strict = any(0 <= day - d < STRICT_DAYS for d in ctx["rad_event_days"].get(astronaut, []))
    results = check_measured(db, astronaut, day, METRICS_TODAY, shadow=ctx.get("shadow"), strict=strict)
    statuses, flags, notes = [], [], []

    for metric in ("hrv_rmssd", "resting_hr"):
        if _drifting(db, astronaut, metric, day):
            statuses.append("act")
            flags.append("cardio_drift")
            notes.append(f"{METRICS[metric]['label']} worse than Shadow Self expected {CARDIO_DRIFT_DAYS} days in a row")

    if any(r["metric"] == "irregular_beats" and r["flagged"] for r in results):
        flags.append("irregular_rhythm")
    if strict:
        notes.append("stricter limits (radiation event in last 7 days)")

    return module_result("cardio", results, statuses, flags, notes)
