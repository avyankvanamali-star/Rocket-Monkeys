"""
RADIATION MODULE — daily                                (PSEUDOCODE.md section 7)

total so far    = sum of daily doses
percent used    = total / career limit x 100
burn rate       = MEDIAN daily dose over last 7 days (one storm day doesn't inflate it)
projected total = total + burn rate x days left
projected > limit -> ACT | percent used > 80% -> WATCH
passive dosimeter differs from active by >10% -> "sensor doubt"
event today -> note it (cardio gets stricter for 7 days)
"""
from config.settings import CAREER_LIMIT_MSV, MISSION_DAYS, PASSIVE_MISMATCH
from pipeline.check import module_result


def run(db, astronaut, day, ctx):
    doses = [h["value"] for h in db.get_history(astronaut, "daily_dose", 1, day)]
    total = sum(doses)
    last7 = doses[-7:]
    burn = sorted(last7)[len(last7) // 2] if last7 else 0.0     # median: a one-off storm is already in 'total'
    projected = total + burn * (MISSION_DAYS - day)
    used_pct = total / CAREER_LIMIT_MSV * 100
    fraction = projected / CAREER_LIMIT_MSV
    statuses, flags, notes = [], [], []

    if fraction > 1:
        statuses.append("act")
        notes.append(f"on track to exceed career limit ({projected:.0f} mSv projected)")
    elif used_pct > 80:
        statuses.append("watch")
        notes.append(f"{used_pct:.0f}% of career limit used")

    passive = db.get_value(astronaut, "passive_dose", day)
    if passive is not None and total > 0:
        gap = abs(passive - total) / total
        if gap > PASSIVE_MISMATCH:
            flags.append("sensor_doubt")
            notes.append(f"passive {passive:.2f} vs active {total:.2f} mSv ({gap:.0%} apart) — check dosimeters")

    if day in ctx["rad_event_days"].get(astronaut, []):
        flags.append("radiation_event")
        notes.append("radiation event today")

    # score: 100 while projected < 80% of limit, falling to 0 at 120%
    score = 100.0 if fraction <= 0.8 else max(0.0, 100 * (1.2 - fraction) / 0.4)
    if "radiation_event" in flags:
        score -= 10

    return module_result("radiation", [], statuses, flags, notes, score=score,
                         budget={"today_msv": round(doses[-1], 3) if doses else 0, "total_msv": round(total, 2),
                                 "used_pct": round(used_pct, 2), "burn_msv_day": round(burn, 3),
                                 "projected_msv": round(projected, 1)})
