"""
ACTIONS                                                 (PSEUDOCODE.md section 14)

ALERT TIER (zones in config/settings.py):
    URGENT = system score < 85, or a hard rule (heartbeat C, radiation event)  -> contact mission control
    ACT    = any domain "act" or score < 90                                    -> basic medical care onboard
    WATCH  = any domain "watch" or score <= 95                                 -> extra observations
    NOMINAL = above 95                                                         -> no extra observation
    don't repeat the same alert more than once a day
COUNTERMEASURES: lookup table (config) -> today's plan
SCHEDULE: heavy task on a spacewalk day? -> move it a day later
EARTH SUMMARY: once a day, scores + alerts + reasons + actions -> small JSON file
FALLBACK: can't write the file -> summary still lives in the database
"""
import json
import os

from config.settings import (COUNTERMEASURES, EVA_DAYS, LEVEL_ACTION, LEVEL_MEANING, MAX_PLAN_ACTIONS,
                             PLAN_PRIORITY, STATUS_ORDER, worst)
from space_weather.check import compact
from storage.db import ROOT

OUT_DIR = os.path.join(ROOT, "outputs")
SYSTEM_NAME = {"radiation": "radiation", "muscle": "muscle", "bone": "bone", "sans": "eyes/brain", "cardio": "heart"}


def act(db, astronaut, day, mods, fused, ctx=None):
    # 1. domain alerts (WATCH / ACT), with the module's best reason
    for d, status in fused["statuses"].items():
        if STATUS_ORDER.get(status, -1) >= 1:
            reasons = mods[d]["notes"] + [r["reason"] for r in mods[d]["results"] if r["flagged"]]
            msg = (f"{LEVEL_MEANING.get(status, status)}. {d.upper()} score {fused['scores'][d]}: "
                   + ("; ".join(reasons[:3]) or "score dropped"))
            db.save_alert(astronaut, day, None, status, d, f"domain_{d}", msg)
    for name, why in fused["rules"]:
        db.save_alert(astronaut, day, None, "watch", "fusion", f"rule_{name}", f"{name}: {why}")

    alerts = db.get_alerts(astronaut, day)
    tier = worst([a["tier"] for a in alerts] + [fused["overall_status"]])

    # 2. what each level means for the crew, then countermeasures + schedule check
    plan = []
    for level in ("urgent", "act", "watch"):                   # one plan line per level, all its systems
        systems = [d for d, st in fused["statuses"].items() if st == level]
        if systems:
            action, offset = LEVEL_ACTION[level]
            action = action.format(system=", ".join(SYSTEM_NAME.get(d, d) for d in systems))
            note = f"{level.upper()}: " + ", ".join(f"{SYSTEM_NAME.get(d, d)} {fused['scores'][d]}" for d in systems)
            db.save_plan(astronaut, day, day + offset, action, note)
            plan.append({"day": day + offset, "action": action, "note": note})
    hard = [a for a in alerts if a["tier"] == "urgent" and not a["key"].startswith("domain_")]
    if hard:                                                   # heartbeat / radiation hard rules
        action = "Contact mission control now: " + "; ".join(a["message"][:60] for a in hard[:2])
        db.save_plan(astronaut, day, day, action, "URGENT: hard rule")
        plan.append({"day": day, "action": action, "note": "URGENT: hard rule"})
    wanted = [f for f in fused["flags"] if f in COUNTERMEASURES]   # most important first, at most MAX_PLAN_ACTIONS
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
              "what_to_do": LEVEL_MEANING.get(tier, tier), "contact_mission_control": tier == "urgent",
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
