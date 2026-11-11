"""
FUSION — where the 5 systems mesh together.             (PSEUDOCODE.md section 13)

gather today's results from all 5 modules for one astronaut
CROSS-SYSTEM RULES:
    Unloading Spiral   : workload low AND (muscle down OR urine calcium up) -> raise muscle, bone, cardio
    Kidney Stone Watch : stone risk high                                   -> raise bone
    Fluid Shift Cluster: SANS watch AND (BP up OR sodium high OR CO2 high)  -> raise SANS + cardio
    Radiation Stress   : radiation event in last 7 days AND cardio watch    -> raise cardio
    Under-Fueling      : calories/protein low AND (muscle OR bone watch)    -> raise muscle + bone
    Solar Storm Confirmed: satellites say WARNING+ AND crew dosimeter saw the event -> raise radiation
    Sensor Doubt       : conflicting or bad data -> low confidence, no alert
                         (also: satellites show S3+ storm but the dosimeter stayed flat)
DRIFT SCORE (each domain):
    severity = |change| / MDC   (or |residual| / usual residual)   — only bad-direction changes count
    score = 100 - 25 x average severity, each rule that fired -> -10, never below 0
OVERALL = lowest domain score
ZONES (config/settings.py): score <=95 WATCH, <90 ACT, <85 URGENT
FALLBACK: fusion breaks -> keep module statuses, simple scores, no rules
"""
from config.settings import (HIGH_CO2_PPM, HIGH_SODIUM_MG, LOW_FUEL_FRACTION, SCORE_ACT, SCORE_URGENT,
                             SCORE_WATCH, STATUS_ORDER, STRICT_DAYS, worst)

DOMAINS = ["radiation", "muscle", "bone", "sans", "cardio"]
# score shown when a module gives only a status (no measurements); each sits inside its own zone
SIMPLE_SCORE = {"ok": 100, "watch": (SCORE_WATCH + SCORE_ACT) / 2 + 0.5, "act": (SCORE_ACT + SCORE_URGENT) / 2,
                "urgent": SCORE_URGENT - 5}


def _severity(r):
    if r["status"] in ("ignored", "no baseline") or r["baseline"] is None:
        return None
    if r["residual"] is not None and r["resid_sd"]:
        bad = r["residual"] < 0 if r["metric"] == "hrv_rmssd" else r["residual"] > 0
        return abs(r["residual"]) / r["resid_sd"] if bad else 0.0
    if not r["bad_direction"]:
        return 0.0
    return abs(r["value"] - r["baseline"]) / r["mdc"]


MAX_SEVERITY = 4.0


def _score(results):
    sev = [min(s, MAX_SEVERITY) for s in (_severity(r) for r in results) if s is not None]
    return 100.0 if not sev else max(0.0, 100 - 25 * sum(sev) / len(sev))


def _score_status(score):
    """Score zones (config/settings.py): <85 urgent, <90 act, <=95 watch, else ok."""
    if score < SCORE_URGENT:
        return "urgent"
    if score < SCORE_ACT:
        return "act"
    return "watch" if score <= SCORE_WATCH else "ok"


def fuse(db, astronaut, day, mods, ctx, heart_flags=()):
    m, flags = mods, set().union(*(mod["flags"] for mod in mods.values()))
    at_least_watch = lambda d: STATUS_ORDER.get(m[d]["status"], -1) >= 1
    rules, penalties = [], {d: 0 for d in DOMAINS}

    def fire(name, domains, why):
        rules.append((name, why))
        for d in domains:
            penalties[d] += 10

    # Unloading Spiral
    if "missed_workouts" in flags and ({"muscle_change", "muscle_loss"} & flags or "urine_up" in flags):
        fire("Unloading Spiral", ["muscle", "bone", "cardio"],
             "missed workouts + muscle/bone already responding")
    # Kidney Stone Watch
    if "stone_risk_high" in flags:
        fire("Kidney Stone Watch", ["bone"], "urine calcium / fluids / sodium")
    # Fluid Shift Cluster
    sodium = db.get_value(astronaut, "sodium", day)
    co2 = db.get_value(astronaut, "co2_sleep", day)
    bp = db.get_latest_result(astronaut, "systolic_bp", day)
    if at_least_watch("sans") and ((bp and bp["flagged"]) or (sodium or 0) > HIGH_SODIUM_MG
                                   or (co2 or 0) > HIGH_CO2_PPM):
        fire("Fluid Shift Cluster", ["sans", "cardio"], "eye changes + sodium/CO2/BP")
    # Radiation Stress
    if any(0 <= day - d < STRICT_DAYS for d in ctx["rad_event_days"].get(astronaut, [])) and at_least_watch("cardio"):
        fire("Radiation Stress", ["cardio"], "radiation event in last 7 days + cardio changes")
    # Under-Fueling
    cal, cal_b = db.get_value(astronaut, "calories", day), db.get_baseline(astronaut, "calories")
    pro, pro_b = db.get_value(astronaut, "protein", day), db.get_baseline(astronaut, "protein")
    low_fuel = (cal and cal_b and cal < LOW_FUEL_FRACTION * cal_b) or (pro and pro_b and pro < LOW_FUEL_FRACTION * pro_b)
    if low_fuel and (at_least_watch("muscle") or at_least_watch("bone")):
        fire("Under-Fueling", ["muscle", "bone"], "calories/protein below target")
        flags.add("under_fueling")
    # Solar Storm Confirmed (two independent sources agree)
    sw = ctx.get("space_weather", {}).get((astronaut, day))
    dosimeter_event = day in ctx["rad_event_days"].get(astronaut, [])
    if sw and "solar_storm" in flags and dosimeter_event:
        fire("Solar Storm Confirmed", ["radiation"], "satellite proton storm + crew dosimeter spike")
    # Sensor Doubt (no alert, lower confidence)
    doubts = []
    if sw and (sw["peak_s"] or 0) >= 3 and not dosimeter_event:
        doubts.append(f"satellites show S{sw['peak_s']} storm but crew dosimeter stayed flat — check dosimeter")
    if "sensor_doubt" in flags:
        doubts.append("radiation dosimeters disagree")
    if "ecg_strap" in heart_flags:
        doubts.append("ECG strap gave bad data today")

    scores, statuses = {}, {}
    for d in DOMAINS:
        if m[d]["status"] == "no data" and not m[d]["results"]:
            scores[d], statuses[d] = None, "no data"        # module failed: show "--", not a fake score
            continue
        base = m[d].get("score")
        if base is None and not m[d]["results"]:
            # nothing measured today: no score unless the module still raised something
            simple = SIMPLE_SCORE.get(m[d]["status"]) if m[d]["status"] != "ok" else None
            if simple is None:
                scores[d], statuses[d] = None, "no data"
                continue
            base = simple
        base = _score(m[d]["results"]) if base is None else base
        scores[d] = round(max(0.0, base - penalties[d]))
        statuses[d] = worst([m[d]["status"], _score_status(scores[d])])

    known = [s for s in scores.values() if s is not None]
    return {"scores": scores, "statuses": statuses, "rules": rules, "flags": flags,
            "sensor_doubt": doubts, "overall": min(known) if known else None,
            "overall_status": worst(statuses.values())}


def fallback_fusion(mods):
    """If fusion itself breaks: keep each module's own status, simple scores, no rules."""
    simple = SIMPLE_SCORE
    statuses = {d: mods[d]["status"] for d in DOMAINS}
    scores = {d: simple.get(s) for d, s in statuses.items()}
    known = [s for s in scores.values() if s is not None]
    return {"scores": scores, "statuses": statuses, "rules": [], "flags": set().union(*(m["flags"] for m in mods.values())),
            "sensor_doubt": ["fusion failed — simple scores used"], "overall": min(known) if known else None,
            "overall_status": worst(statuses.values())}
