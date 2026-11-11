"""
ACTIONS                                                 (PSEUDOCODE.md section 14)

ALERT TIER:
    URGENT only from hard rules (heartbeat C, radiation event)
    ACT    = any domain "act" or score < 50
    WATCH  = any domain "watch" or score < 75
    don't repeat the same alert more than once a day
COUNTERMEASURES: lookup table (config) -> today's plan
SCHEDULE: heavy task on a spacewalk day? -> move it a day later
EARTH SUMMARY: once a day, scores + alerts + reasons + actions -> small JSON file
FALLBACK: can't write the file -> summary still lives in the database
"""
import json
import os

from config.settings import COUNTERMEASURES, EVA_DAYS, MAX_PLAN_ACTIONS, PLAN_PRIORITY, STATUS_ORDER, worst
from space_weather.check import compact
from storage.db import ROOT

OUT_DIR = os.path.join(ROOT, "outputs")


def act(db, astronaut, day, mods, fused, ctx=None):
    # 1. domain alerts (WATCH / ACT), with the module's best reason
    for d, status in fused["statuses"].items():
        if STATUS_ORDER.get(status, -1) >= 1:
            reasons = mods[d]["notes"] + [r["reason"] for r in mods[d]["results"] if r["flagged"]]
            msg = f"{d.upper()} score {fused['scores'][d]}: " + ("; ".join(reasons[:3]) or "score dropped")
            db.save_alert(astronaut, day, None, status, d, f"domain_{d}", msg)
    for name, why in fused["rules"]:
        db.save_alert(astronaut, day, None, "watch", "fusion", f"rule_{name}", f"{name}: {why}")

    alerts = db.get_alerts(astronaut, day)
    tier = worst([a["tier"] for a in alerts] + [fused["overall_status"]])

    # 2. countermeasures + schedule check — most important first, at most MAX_PLAN_ACTIONS
    plan = []
    wanted = [f for f in fused["flags"] if f in COUNTERMEASURES]
    wanted.sort(key=lambda f: PLAN_PRIORITY.index(f) if f in PLAN_PRIORITY else len(PLAN_PRIORITY))
    for flag in wanted[:MAX_PLAN_ACTIONS]:
        if flag in COUNTERMEASURES:
            action, heavy = COUNTERMEASURES[flag]
            when, note = day + 1, ""
            if heavy and when in EVA_DAYS.get(astronaut, []):
                when, note = when + 1, f"moved: spacewalk on day {day + 1}"
            db.save_plan(astronaut, day, when, action, note)
            plan.append({"day": when, "action": action, "note": note})

    # 3. Earth summary packet
    packet = {"astronaut": astronaut, "mission_day": day, "tier": tier, "overall_score": fused["overall"],
              "scores": fused["scores"], "rules_fired": [r[0] for r in fused["rules"]],
              "alerts": [{k: a[k] for k in ("tier", "domain", "message")} for a in alerts
                         if STATUS_ORDER.get(a["tier"], 0) >= 1],
              "plan": plan, "sensor_doubt": fused["sensor_doubt"],
              "radiation_budget": mods["radiation"]["budget"],
              "space_weather": compact((ctx or {}).get("space_weather", {}).get((astronaut, day)))}
    path = os.path.join(OUT_DIR, f"earth_summary_{astronaut}_day{day}.json")
    try:
        os.makedirs(OUT_DIR, exist_ok=True)
        with open(path, "w") as f:
            json.dump(packet, f, indent=2, default=str)
    except OSError:
        path = None                      # fallback: summary stays in the database alerts/plans
    return {"tier": tier, "plan": plan, "alerts": alerts, "summary_file": path}


def fallback_action(db, astronaut, day, fused):
    """If actions break: still return today's alerts and the worst status, no plan."""
    try:
        alerts = db.get_alerts(astronaut, day)
    except Exception:  # noqa: BLE001
        alerts = []
    return {"tier": worst([a["tier"] for a in alerts] + [fused["overall_status"]]),
            "plan": [], "alerts": alerts, "summary_file": None}
