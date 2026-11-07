"""
SAMPLE DATA — 3 mission days, 2 astronauts, ALL 5 systems.   (not the full simulator)

    data/preflight.csv : 14 pre-mission days -> baselines + Shadow model training
    data/mission.csv   : mission days 1-3

What's in it (edit the tables below to change the story):
    STREAMS (every 5 s)  heart rate + beat gaps, radiation dose rate
    DAILY LOGS           sleep, CO2, workload, nutrition, symptoms, blood pressure
    TESTS                muscle area, strength, urine calcium, vision test, optic nerve sheath,
                         OCT (RNFL), cardiac ultrasound (stroke volume), passive dosimeter
                         -> every test runs EVERY day in this demo so each system shows progress
                            (on a real mission most are weekly or monthly)

A1 = healthy control.  A2 = slowly drifting in every system.
Planted events: ECG strap slip (A2 d1 06:00) · solar particle event (d2 14:00, both)
· stress episode (A2 d2 20:00) · irregular rhythm (A2 d3 09:00) · dosimeter mismatch (A2 d3)
· 2 broken rows · 1 unit conversion (A1 passive dose in uSv).   All numbers are made up.
"""
import csv
import math
import os
import random
from datetime import datetime, timedelta

random.seed(7)
LAUNCH = datetime(2027, 3, 1)
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
FIELDS = ["astronaut", "time", "metric", "value", "unit", "source", "quality", "detail"]

# ---------------- each astronaut's normal (pre-mission) ----------------
NORMAL = {
    "A1": {"hrv": 52, "rhr": 55, "recovery": 32, "bp": 118, "quad_csa": 52, "knee_torque": 110,
           "urine_calcium": 240, "near_vision_score": 94, "onsd": 5.0, "rnfl": 100, "stroke_volume": 75},
    "A2": {"hrv": 48, "rhr": 56, "recovery": 31, "bp": 118, "quad_csa": 50, "knee_torque": 100,
           "urine_calcium": 245, "near_vision_score": 92, "onsd": 5.0, "rnfl": 101, "stroke_volume": 72},
}

# ---------------- in-flight daily logs: [day 1, day 2, day 3] ----------------
DAILY = {
    "A1": {"sleep_hours": [7.1, 7.3, 7.0], "co2_sleep": [2700, 2650, 2750], "resistance_load_pct": [98, 101, 97],
           "calories": [2800, 2850, 2780], "protein": [121, 118, 122], "sodium": [2900, 2800, 3000],
           "fluids": [2.6, 2.7, 2.5], "vitamin_d": [800, 800, 800], "headache": [0, 0, 0],
           "vision_blur": [0, 0, 0], "systolic_bp": [119, 118, 120]},
    "A2": {"sleep_hours": [6.4, 6.1, 6.3], "co2_sleep": [3500, 3600, 3550], "resistance_load_pct": [63, 60, 58],
           "calories": [2650, 2500, 2550], "protein": [105, 98, 100], "sodium": [3900, 4100, 3800],
           "fluids": [2.0, 1.8, 1.9], "vitamin_d": [800, 0, 0], "headache": [1, 2, 3],
           "vision_blur": [0, 1, 2], "systolic_bp": [121, 123, 125]},
}

# ---------------- in-flight tests: [day 1, day 2, day 3] ----------------
TESTS = {
    "A1": {"quad_csa": [51.9, 52.1, 51.8], "knee_torque": [110, 109, 111], "urine_calcium": [242, 238, 246],
           "near_vision_score": [94, 93, 94], "onsd": [5.0, 5.02, 4.98], "rnfl": [100, 101, 100],
           "stroke_volume": [75, 74, 76], "passive_dose": [1.78, 3.85, 5550]},      # day 3 in uSv on purpose
    "A2": {"quad_csa": [48.6, 47.6, 46.5], "knee_torque": [95, 91, 87], "urine_calcium": [262, 280, 295],
           "near_vision_score": [89, 87, 85], "onsd": [5.15, 5.25, 5.35], "rnfl": [102, 104, 106],
           "stroke_volume": [66, 62, 58], "passive_dose": [1.82, 3.79, 6.4]},       # day 3 ~15% off on purpose
}

# ---------------- hidden drift the Shadow model should NOT be able to explain ----------------
DRIFT = {"A1": {"hrv": 0, "rhr": 0, "recovery": 0}, "A2": {"hrv": -3.0, "rhr": 1.0, "recovery": -2.0}}  # per day

UNITS = {"sleep_hours": "h", "co2_sleep": "ppm", "resistance_load_pct": "pct", "calories": "kcal",
         "protein": "g", "sodium": "mg", "fluids": "L", "vitamin_d": "IU", "headache": "0-10",
         "vision_blur": "0-10", "systolic_bp": "mmHg", "resting_hr": "bpm", "hrv_rmssd": "ms",
         "hr_recovery": "bpm", "irregular_beats": "count", "quad_csa": "cm2", "knee_torque": "Nm",
         "urine_calcium": "mg/day", "near_vision_score": "score", "onsd": "mm", "rnfl": "um",
         "stroke_volume": "mL", "passive_dose": "mSv"}
SOURCES = {"quad_csa": "ultrasound", "knee_torque": "force_sensor", "urine_calcium": "urine_test",
           "near_vision_score": "tablet_test", "onsd": "ocular_ultrasound", "rnfl": "oct_scanner",
           "stroke_volume": "cardiac_ultrasound", "passive_dose": "passive_dosimeter"}


def row(a, t, metric, value, source, quality="good", detail="", unit=None):
    return {"astronaut": a, "time": t.isoformat(), "metric": metric, "value": value,
            "unit": unit or UNITS[metric], "source": source, "quality": quality, "detail": detail}


def body_response(n, sleep, load, co2):
    """How the body 'really' reacts to sleep, workload and CO2 — the Shadow model learns this."""
    hrv = n["hrv"] + 3 * (sleep - 7) + 0.08 * (load - 100) - 0.003 * (co2 - 2500)
    rhr = n["rhr"] - 1.2 * (sleep - 7) - 0.02 * (load - 100) + 0.0015 * (co2 - 2500)
    return hrv + random.gauss(0, 1.2), rhr + random.gauss(0, 0.6)


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
        t_test = LAUNCH + timedelta(days=-1, hours=9)
        for m in ("quad_csa", "knee_torque", "urine_calcium", "near_vision_score", "onsd", "rnfl", "stroke_volume"):
            rows.append(row(a, t_test, m, n[m], "preflight_test"))
    return rows


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
            hr, spread = 115 + random.gauss(0, 2), 15              # resistance workout
        elif 16 <= h < 16.5:
            hr, spread = 140 + random.gauss(0, 1), 12              # aerobic workout
        elif 16.5 <= h < 16.75:
            hr, spread = awake + (140 - awake) * math.exp(-(h - 16.5) * 3600 / tau), 15   # cool-down
        else:
            hr, spread = awake + random.gauss(0, 1.5), 25          # awake, resting
        quality = "good"

        if a == "A2" and day == 2 and t.hour == 20 and t.minute < 10:     # stress episode
            hr = rhr + 34 + random.gauss(0, 1)
        beats = max(1, round(5 * hr / 60))
        rr = [round(60000 / hr + random.gauss(0, spread / math.sqrt(2))) for _ in range(beats)]
        if a == "A2" and day == 3 and t.hour == 9 and t.minute < 3:       # irregular rhythm
            rr = [round(60000 / hr * (0.6 if k % 2 else 1.4)) for k in range(beats)]
        if a == "A2" and day == 1 and t.hour == 6 and t.minute < 2:       # ECG strap slipped
            hr, quality, rr = 214, "bad", []
        rows.append(row(a, t, "heart_rate", round(hr, 1), "ecg_shirt", quality, ";".join(map(str, rr)), "bpm"))
    return rows


def dose_stream(a, day):
    rows, start = [], LAUNCH + timedelta(days=day - 1)
    for i in range(17280):
        t = start + timedelta(seconds=5 * i)
        rate = 75 + random.gauss(0, 3)
        if day == 2 and t.hour == 14 and t.minute < 40:                    # solar particle event
            rate = (400 if a == "A1" else 380) + random.gauss(0, 10)
        rows.append(row(a, t, "dose_rate", round(rate, 1), "active_dosimeter", unit="uSv/h"))
    return rows


# ---------------- mission days ----------------
def mission():
    rows = []
    for a, n in NORMAL.items():
        for day in (1, 2, 3):
            i = day - 1
            logs = {m: v[i] for m, v in DAILY[a].items()}
            hrv, rhr = body_response(n, logs["sleep_hours"], logs["resistance_load_pct"], logs["co2_sleep"])
            hrv += DRIFT[a]["hrv"] * day
            rhr += DRIFT[a]["rhr"] * day
            recovery = n["recovery"] + DRIFT[a]["recovery"] * day + random.gauss(0, 0.5)

            rows += heart_stream(a, day, round(rhr, 1), max(hrv, 10), recovery)
            rows += dose_stream(a, day)
            t_log = LAUNCH + timedelta(days=i, hours=21)
            rows += [row(a, t_log, m, v, "bp_cuff" if m == "systolic_bp" else "daily_log") for m, v in logs.items()]
            t_test = LAUNCH + timedelta(days=i, hours=9, minutes=30)
            for m, values in TESTS[a].items():
                unit = "uSv" if m == "passive_dose" and values[i] > 1000 else None
                rows.append(row(a, t_test, m, values[i], SOURCES[m], unit=unit))

    # two broken rows to prove ingestion rejects junk without crashing
    rows.append({"astronaut": "A1", "time": (LAUNCH + timedelta(hours=12)).isoformat(), "metric": "heart_rate",
                 "value": "", "unit": "bpm", "source": "ecg_shirt", "quality": "", "detail": ""})
    rows.append({"astronaut": "A2", "time": "not-a-time", "metric": "blood_glow", "value": 3,
                 "unit": "lumens", "source": "mystery_sensor", "quality": "", "detail": ""})
    return rows


def write(name, rows):
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, name), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    print(f"  wrote data/{name}: {len(rows):,} rows")


def main():
    write("preflight.csv", preflight())
    write("mission.csv", mission())


if __name__ == "__main__":
    main()
