"""
30-DAY SAMPLE DATA — 2 astronauts, all 5 systems, same format as generate_sample_data.py

    data/preflight.csv   : 14 pre-mission days -> baselines + Shadow model training
    data/mission.csv     : mission days 1-30 (5-second streams + daily logs + daily tests)
    data/answer_key.json : every problem planted on purpose -> used by score_run.py
    data/space_weather.csv : simulated satellite data (flares, protons, CME) -> space_weather/simulate.py

A1 = healthy control (noise only).  A2 = slow drift that starts around day 8-15.
Planted single events:
    day 1  A2 ECG strap slips (2 min of bad readings)      -> expect "ecg_strap"
    day 10 A1 passive dose logged in uSv (unit conversion)  -> expect it converted, no alert
    day 20 BOTH solar particle event (2 h)                  -> expect "radiation_event"
    day 21 A2 stress episode (10 min high resting HR)       -> expect "elevated_resting_hr"
    day 26 A2 irregular rhythm (3 min)                      -> expect "irregular_rhythm"
    day 28 A2 passive dosimeter ~20% off                    -> expect "sensor doubt"
    2 broken rows                                           -> expect them rejected
All numbers are made up for testing — not medical reference values.

Run:  python3 generate_30day_data.py          (seed 42)
      python3 generate_30day_data.py 7        (another random seed, same story)
"""
import csv
import json
import math
import os
import random
import sys
from datetime import datetime, timedelta

LAUNCH = datetime(2027, 3, 1)
DAYS = 30
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
FIELDS = ["astronaut", "time", "metric", "value", "unit", "source", "quality", "detail"]

NORMAL = {
    "A1": {"hrv": 52, "rhr": 55, "recovery": 32, "bp": 118, "quad_csa": 52, "knee_torque": 110,
           "urine_calcium": 240, "near_vision_score": 94, "onsd": 5.0, "rnfl": 100, "stroke_volume": 75},
    "A2": {"hrv": 48, "rhr": 56, "recovery": 31, "bp": 118, "quad_csa": 50, "knee_torque": 100,
           "urine_calcium": 245, "near_vision_score": 92, "onsd": 5.0, "rnfl": 101, "stroke_volume": 72},
}
UNITS = {"sleep_hours": "h", "co2_sleep": "ppm", "resistance_load_pct": "pct", "calories": "kcal",
         "protein": "g", "sodium": "mg", "fluids": "L", "vitamin_d": "IU", "headache": "0-10",
         "vision_blur": "0-10", "systolic_bp": "mmHg", "resting_hr": "bpm", "hrv_rmssd": "ms",
         "hr_recovery": "bpm", "irregular_beats": "count", "quad_csa": "cm2", "knee_torque": "Nm",
         "urine_calcium": "mg/day", "near_vision_score": "score", "onsd": "mm", "rnfl": "um",
         "stroke_volume": "mL", "passive_dose": "mSv"}
SOURCES = {"quad_csa": "ultrasound", "knee_torque": "force_sensor", "urine_calcium": "urine_test",
           "near_vision_score": "tablet_test", "onsd": "ocular_ultrasound", "rnfl": "oct_scanner",
           "stroke_volume": "cardiac_ultrasound", "passive_dose": "passive_dosimeter"}
TEST_NOISE = {"quad_csa": 0.3, "knee_torque": 1.5, "urine_calcium": 5, "near_vision_score": 0.6,
              "onsd": 0.03, "rnfl": 0.6, "stroke_volume": 1.0}


def ramp(day, start, end, total):
    """0 before 'start', grows evenly to 'total' by 'end'."""
    return 0.0 if day < start else total * min(1.0, (day - start) / (end - start))


def row(a, t, metric, value, source, quality="good", detail="", unit=None):
    return {"astronaut": a, "time": t.isoformat(), "metric": metric, "value": value,
            "unit": unit or UNITS[metric], "source": source, "quality": quality, "detail": detail}


def body_response(n, sleep, load, co2):
    """How the body 'really' reacts to sleep, workload and CO2 — the Shadow model learns this."""
    hrv = n["hrv"] + 3 * (sleep - 7) + 0.08 * (load - 100) - 0.003 * (co2 - 2500)
    rhr = n["rhr"] - 1.2 * (sleep - 7) - 0.02 * (load - 100) + 0.0015 * (co2 - 2500)
    return hrv + random.gauss(0, 1.2), rhr + random.gauss(0, 0.6)


# ---------------- the story: daily logs (causes) ----------------
def daily_logs(a, day):
    g = random.gauss
    logs = {"sleep_hours": 7.1 + g(0, 0.25), "co2_sleep": 2700 + g(0, 80), "resistance_load_pct": 99 + g(0, 3),
            "calories": 2800 + g(0, 50), "protein": 120 + g(0, 3), "sodium": 2850 + g(0, 100),
            "fluids": 2.6 + g(0, 0.08), "vitamin_d": 800, "headache": 0, "vision_blur": 0,
            "systolic_bp": NORMAL[a]["bp"] + g(0, 1.5)}
    if a == "A2":
        logs["sleep_hours"] += ramp(day, 10, 30, -0.9) - (0.6 if 21 <= day <= 25 else 0)   # worse after storm
        logs["co2_sleep"] += ramp(day, 6, 25, 900)
        logs["resistance_load_pct"] += ramp(day, 8, 24, -40)
        logs["calories"] += ramp(day, 10, 28, -320)
        logs["protein"] += ramp(day, 10, 28, -22)
        logs["sodium"] += ramp(day, 8, 24, 1200)
        logs["fluids"] += ramp(day, 8, 24, -0.8)
        logs["vitamin_d"] = 0 if day in (14, 23, 24) else 800
        logs["headache"] = round(ramp(day, 14, 30, 3))
        logs["vision_blur"] = round(ramp(day, 16, 30, 2))
        logs["systolic_bp"] += ramp(day, 10, 30, 7)
    rounding = {"sleep_hours": 1, "fluids": 2}
    return {m: round(v, rounding.get(m, 0)) for m, v in logs.items()}


def tests(a, day, passive_total):
    n = NORMAL[a]
    drift = {}
    if a == "A2":   # tests respond a few days AFTER the causes start
        drift = {"quad_csa": ramp(day, 14, 30, -3.2), "knee_torque": ramp(day, 13, 30, -11),
                 "urine_calcium": ramp(day, 12, 26, 60), "near_vision_score": ramp(day, 12, 30, -6),
                 "onsd": ramp(day, 12, 30, 0.35), "rnfl": ramp(day, 15, 30, 4), "stroke_volume": ramp(day, 14, 30, -7)}
    out = {m: n[m] + drift.get(m, 0) + random.gauss(0, s) for m, s in TEST_NOISE.items()}
    out = {m: round(v, 2 if m == "onsd" else 1) for m, v in out.items()}
    out["passive_dose"] = round(passive_total * random.uniform(0.98, 1.02), 2)   # passive = running total
    if a == "A2" and day == 28:
        out["passive_dose"] = round(passive_total * 1.2, 2)                      # dosimeters disagree
    return out


# ---------------- 5-second streams ----------------
def heart_stream(a, day, rhr, hrv, recovery):
    rows, start = [], LAUNCH + timedelta(days=day - 1)
    awake = rhr + 12
    tau = -60 / math.log(1 - recovery / (140 - awake))           # cool-down speed after the workout
    for i in range(17280):                                         # 24 h / 5 s
        t = start + timedelta(seconds=5 * i)
        h = t.hour + t.minute / 60 + t.second / 3600
        if h >= 23 or h < 7:
            hr, spread = rhr, hrv                                  # asleep
        elif 10 <= h < 11:
            hr, spread = 115 + random.gauss(0, 2), 15              # resistance workout (matches settings.EXERCISE)
        elif 16 <= h < 16.5:
            hr, spread = 140 + random.gauss(0, 1), 12              # aerobic workout
        elif 16.5 <= h < 16.75:
            hr, spread = awake + (140 - awake) * math.exp(-(h - 16.5) * 3600 / tau), 15   # cool-down
        else:
            hr, spread = awake + random.gauss(0, 1.5), 25          # awake, resting
        quality = "good"
        if a == "A2" and day == 21 and t.hour == 20 and t.minute < 10:     # stress episode
            hr = rhr + 34 + random.gauss(0, 1)
        beats = max(1, round(5 * hr / 60))
        rr = [round(60000 / hr + random.gauss(0, spread / math.sqrt(2))) for _ in range(beats)]
        if a == "A2" and day == 26 and t.hour == 9 and t.minute < 3:       # irregular rhythm
            rr = [round(60000 / hr * (0.6 if k % 2 else 1.4)) for k in range(beats)]
        if a == "A2" and day == 1 and t.hour == 6 and t.minute < 2:       # ECG strap slipped
            hr, quality, rr = 214, "bad", []
        rows.append(row(a, t, "heart_rate", round(hr, 1), "ecg_shirt", quality, ";".join(map(str, rr)), "bpm"))
    return rows


def dose_stream(a, day):
    rows, total, start = [], 0.0, LAUNCH + timedelta(days=day - 1)
    for i in range(17280):
        t = start + timedelta(seconds=5 * i)
        rate = 75 + random.gauss(0, 3)                             # ~1.8 mSv/day background
        if day == 20 and 14 <= t.hour < 16:                        # solar particle event, both astronauts
            rate = (600 if a == "A1" else 570) + random.gauss(0, 15)
        total += rate * 5 / 3600 / 1000
        rows.append(row(a, t, "dose_rate", round(rate, 1), "active_dosimeter", unit="uSv/h"))
    return rows, total


# ---------------- pre-mission ----------------
def preflight():
    rows = []
    for a, n in NORMAL.items():
        for d in range(-13, 1):
            t = LAUNCH + timedelta(days=d - 1, hours=21)
            sleep, load, co2 = random.uniform(5.8, 8.2), random.uniform(75, 115), random.uniform(800, 4000)
            hrv, rhr = body_response(n, sleep, load, co2)
            day = {"sleep_hours": round(sleep, 1), "resistance_load_pct": round(load), "co2_sleep": round(co2),
                   "hrv_rmssd": round(hrv, 1), "resting_hr": round(rhr, 1),
                   "hr_recovery": round(n["recovery"] + random.gauss(0, 1), 1),
                   "systolic_bp": round(n["bp"] + random.gauss(0, 2)), "irregular_beats": random.randint(2, 8),
                   "calories": round(random.gauss(2800, 60)), "protein": round(random.gauss(120, 4)),
                   "sodium": round(random.gauss(2800, 120)), "fluids": round(random.gauss(2.5, 0.1), 2),
                   "vitamin_d": 800, "headache": 0, "vision_blur": 0}
            rows += [row(a, t, m, v, "preflight") for m, v in day.items()]
        for d in (-3, -2, -1):                                     # 3 pre-mission test days -> steadier baselines
            t_test = LAUNCH + timedelta(days=d - 1, hours=9)
            for m, s in TEST_NOISE.items():
                rows.append(row(a, t_test, m, round(n[m] + random.gauss(0, s), 2), "preflight_test"))
    return rows


# ---------------- mission ----------------
DRIFT = {"A1": {"hrv": 0, "rhr": 0, "recovery": 0},
         "A2": {"hrv": -0.45, "rhr": 0.18, "recovery": -0.3}}     # per day after day 12, NOT explained by sleep etc.


def mission(writer):
    count = 0
    for a, n in NORMAL.items():
        passive_total = 0.0
        for day in range(1, DAYS + 1):
            logs = daily_logs(a, day)
            hrv, rhr = body_response(n, logs["sleep_hours"], logs["resistance_load_pct"], logs["co2_sleep"])
            k = max(0, day - 12)
            hrv += DRIFT[a]["hrv"] * k
            rhr += DRIFT[a]["rhr"] * k
            recovery = n["recovery"] + DRIFT[a]["recovery"] * k + random.gauss(0, 0.5)

            rows = heart_stream(a, day, round(rhr, 1), max(hrv, 10), recovery)
            dose_rows, dose_today = dose_stream(a, day)
            rows += dose_rows
            passive_total += dose_today
            t_log = LAUNCH + timedelta(days=day - 1, hours=21)
            rows += [row(a, t_log, m, v, "bp_cuff" if m == "systolic_bp" else "daily_log") for m, v in logs.items()]
            t_test = LAUNCH + timedelta(days=day - 1, hours=9, minutes=30)
            for m, v in tests(a, day, passive_total).items():
                if a == "A1" and day == 10 and m == "passive_dose":              # unit conversion test
                    rows.append(row(a, t_test, m, round(v * 1000), SOURCES[m], unit="uSv"))
                else:
                    rows.append(row(a, t_test, m, v, SOURCES[m]))
            writer.writerows(rows)
            count += len(rows)
    # two broken rows to prove ingestion rejects junk without crashing
    writer.writerow({"astronaut": "A1", "time": (LAUNCH + timedelta(hours=12)).isoformat(), "metric": "heart_rate",
                     "value": "", "unit": "bpm", "source": "ecg_shirt", "quality": "", "detail": ""})
    writer.writerow({"astronaut": "A2", "time": "not-a-time", "metric": "blood_glow", "value": 3,
                     "unit": "lumens", "source": "mystery_sensor", "quality": "", "detail": ""})
    return count + 2


# ---------------- answer key (what the system SHOULD catch) ----------------
ANSWER_KEY = {
    "events": [   # single planted events: must be caught on exactly this day
        {"name": "ECG strap slip", "astronaut": "A2", "day": 1, "alert": "ecg_strap"},
        {"name": "Solar particle event (A1)", "astronaut": "A1", "day": 20, "alert": "radiation_event"},
        {"name": "Solar particle event (A2)", "astronaut": "A2", "day": 20, "alert": "radiation_event"},
        {"name": "Stress episode", "astronaut": "A2", "day": 21, "alert": "elevated_resting_hr"},
        {"name": "Irregular rhythm", "astronaut": "A2", "day": 26, "alert": "irregular_rhythm"},
        {"name": "Dosimeters disagree", "astronaut": "A2", "day": 28, "sensor_doubt": True},
        # space weather (data/space_weather.csv): satellites must warn on these days
        {"name": "Solar early warning, X flare (A1)", "astronaut": "A1", "day": 20, "alert": "solar_warning"},
        {"name": "Solar early warning, X flare (A2)", "astronaut": "A2", "day": 20, "alert": "solar_warning"},
        {"name": "Proton storm during spacewalk (A2)", "astronaut": "A2", "day": 5, "alert": "solar_critical"},
        {"name": "CME arrival (A1)", "astronaut": "A1", "day": 21, "alert": "solar_watch"},
    ],
    "drifts": [   # slow problems: caught if any alert of this kind fires on/after 'starts', before day 30
        {"name": "Heart drift (HRV/resting HR)", "astronaut": "A2", "starts": 12, "alerts": ["domain_cardio"]},
        {"name": "Muscle loss", "astronaut": "A2", "starts": 8, "alerts": ["domain_muscle", "rule_Unloading Spiral"]},
        {"name": "Bone loss / kidney stone risk", "astronaut": "A2", "starts": 8,
         "alerts": ["domain_bone", "rule_Kidney Stone Watch"]},
        {"name": "Eye/brain (SANS) drift", "astronaut": "A2", "starts": 12,
         "alerts": ["domain_sans", "rule_Fluid Shift Cluster"]},
        {"name": "Under-fueling", "astronaut": "A2", "starts": 10, "alerts": ["rule_Under-Fueling"]},
    ],
    # alerts that are EXPECTED on these days (not false alarms) — everything else for A1 is a false alarm
    "expected_noise": {"A1": {"5": ["solar_watch", "solar_warning", "domain_radiation"],
                              "12": ["solar_watch"],
                              "20": ["radiation_event", "domain_radiation", "rule_Radiation Stress",
                                     "solar_watch", "solar_warning", "solar_critical", "rule_Solar Storm Confirmed"],
                              "21": ["radiation_event", "domain_radiation", "rule_Radiation Stress", "solar_watch"],
                              "22": ["solar_watch"]}},
}


def main(seed=42):
    random.seed(seed)
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, "preflight.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        rows = preflight()
        w.writerows(rows)
    print(f"  wrote data/preflight.csv: {len(rows):,} rows")
    with open(os.path.join(OUT, "mission.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        n = mission(w)
    print(f"  wrote data/mission.csv: {n:,} rows ({DAYS} days)")
    with open(os.path.join(OUT, "answer_key.json"), "w") as f:
        json.dump({"seed": seed, **ANSWER_KEY}, f, indent=2)
    print("  wrote data/answer_key.json")
    from space_weather import simulate
    simulate.main(seed)


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 42)
