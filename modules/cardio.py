"""
CARDIO MODULE — daily                                   (PSEUDOCODE.md section 11)

uses the heartbeat end-of-day summary
resting HR, HRV       -> 7-step check WITH Shadow model
HR recovery, BP, irregular beats, stroke volume -> 7-step check
CUSUM: running total of 'worse than Shadow Self expected' gaps passes CUSUM_H -> ACT "cardio drift"
radiation event in last 7 days -> stricter checks
"""
from config.settings import CUSUM_H, CUSUM_K, METRICS, STRICT_DAYS
from pipeline.check import check_measured, module_result

METRICS_TODAY = ["resting_hr", "hrv_rmssd", "hr_recovery", "systolic_bp", "irregular_beats", "stroke_volume"]


def cusum(db, astronaut, metric, day):
    """CUSUM drift score for one metric, mission day 1..today.
    Each day: gap = how much worse than expected (in noise units).  total = max(0, total + gap - K).
    Returns the total — above CUSUM_H means a slow, steady drift (not just one bad day)."""
    rows = db.get_recent_results(astronaut, metric, 1000, before_day=day + 1)
    up_is_bad = METRICS[metric]["bad"] == "up"
    total = 0.0
    for r in sorted(rows, key=lambda r: r["day"]):
        if r["day"] < 1 or r["residual"] is None or not r["resid_sd"]:
            continue
        gap = (r["residual"] if up_is_bad else -r["residual"]) / r["resid_sd"]
        total = max(0.0, total + gap - CUSUM_K)
    return total


def run(db, astronaut, day, ctx):
    strict = any(0 <= day - d < STRICT_DAYS for d in ctx["rad_event_days"].get(astronaut, []))
    results = check_measured(db, astronaut, day, METRICS_TODAY, shadow=ctx.get("shadow"), strict=strict)
    statuses, flags, notes = [], [], []

    for metric in ("hrv_rmssd", "resting_hr"):
        drift = cusum(db, astronaut, metric, day)
        if drift > CUSUM_H:
            statuses.append("act")
            if "cardio_drift" not in flags:
                flags.append("cardio_drift")
            notes.append(f"{METRICS[metric]['label']} drifting: steadily worse than Shadow Self expected "
                         f"(drift score {drift:.1f} > {CUSUM_H:g})")

    if any(r["metric"] == "irregular_beats" and r["flagged"] for r in results):
        flags.append("irregular_rhythm")
    if strict:
        notes.append("stricter limits (radiation event in last 7 days)")

    return module_result("cardio", results, statuses, flags, notes)
