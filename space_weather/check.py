"""
SOLAR CHECK — connects SolarWatch to the rest of Shadow Self.   (PSEUDOCODE.md section 17)

for one astronaut, one day:
    run the day's satellite snapshots through SolarWatch
    every time the level goes UP -> alert (WATCH=watch, WARNING=act, CRITICAL=urgent), domain "radiation"
    save every level change to the space_weather table
    compare with the crew dosimeter: how many minutes earlier did the satellites warn?  (lead time)
    put the day summary in ctx["space_weather"] -> radiation module, fusion, actions, report use it
"""
from datetime import datetime

from config.settings import SW_ACTIONS, SW_LEVELS, SW_TIER
from space_weather.engine import run_day, summarize_day

COMPACT = ("max_level_name", "first_time", "peak_r", "peak_s", "peak_g", "peak_flare", "peak_proton_pfu",
           "cme", "peak_reasons", "actions", "lead_min")


def _message(st, note=""):
    todo = "; ".join(SW_ACTIONS[a] for a in st["actions"])
    return f"Space weather {st['level_name'].upper()}{note}: {'; '.join(st['reasons'][:3])} -> {todo}"


def solar_check(db, astronaut, day, watch, snaps, ctx):
    start_level = watch.level
    steps = run_day(watch, snaps)
    summary = summarize_day(steps)
    if summary is None:
        return None                                   # no satellite data today -> nothing claimed

    # alerts: each time the level rises (once per level per day — db.save_alert de-duplicates)
    level = start_level
    for i, st in enumerate(steps):
        if st["level"] > level or (i == 0 and st["level"] >= 1):
            note = " (continues from yesterday)" if i == 0 and st["level"] <= start_level else ""
            name = st["level_name"]
            db.save_alert(astronaut, day, st["time"].isoformat(timespec="seconds"), SW_TIER[name],
                          "radiation", f"solar_{name}", _message(st, note))
        level = st["level"]
    db.save_space_weather(astronaut, summary["changes"])

    # lead time: first satellite WARNING (else WATCH) vs the dosimeter's radiation_event alert
    summary["lead_min"] = None
    dos = [a for a in db.get_alerts(astronaut, day) if a["key"] == "radiation_event" and a["time"]]
    if dos:
        hit = datetime.fromisoformat(dos[0]["time"])
        for name in ("warning", "watch"):
            first = summary["first_dt"].get(name)
            if first and first <= hit:
                summary["lead_min"] = round((hit - first).total_seconds() / 60)
                summary["lead_level"] = name
                break
    ctx.setdefault("space_weather", {})[(astronaut, day)] = summary
    return summary


def compact(summary):
    """Small version for the Earth summary JSON (no datetimes, no step lists)."""
    if not summary:
        return None
    out = {k: summary.get(k) for k in COMPACT}
    out["level_index"] = SW_LEVELS.index(summary["max_level_name"])
    return out
