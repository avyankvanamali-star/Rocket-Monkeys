"""
SAMPLE DATA — 3 mission days for 2 astronauts (NOT the full simulator).

    data/preflight.csv : 14 pre-mission days (habitat training) -> baselines + Shadow model training
    data/mission.csv   : mission days 1-3
        - heart rate + beat gaps every 5 s (17,280 windows/day)
        - dose rate every 5 s
        - daily logs (sleep, CO2, workload, nutrition, symptoms, BP)
        - test days (vision, strength, ultrasound, urine, passive dosimeter)

A1 = healthy control.  A2 = slowly drifting (short workouts, high salt, low fluids,
poor sleep in a high-CO2 pod) — the system should catch it.
Planted events: ECG strap slip (A2 day 1), solar particle event (day 2, both),
stress episode (A2 day 2), irregular rhythm (A2 day 3), 2 broken rows, 1 unit conversion.
All numbers are made up for testing.
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

PEOPLE = {
    "A1": {"hrv": 52, "rhr": 55, "rec": 32, "bp": 118, "csa": 52, "torque": 110, "uca": 240,
           "vision": 94, "onsd": 5.0, "rnfl": 100, "sv": 75},
    "A2": {"hrv": 48, "rhr": 56, "rec": 31, "bp": 118, "csa": 50, "torque": 100, "uca": 245,
           "vision": 92, "onsd": 5.0, "rnfl": 101, "sv": 72},
}
# A2's daily logs in flight (day 1, 2, 3)
A2_LOGS = {"sleep_hours": [6.4, 6.1, 6.3], "co2_sleep": [3500, 3600, 3550],
           "resistance_load_pct": [63, 60, 58], "calories": [2650, 2500, 2550],
           "protein": [105, 98, 100], "sodium": [3900, 4100, 3800], "fluids": [2.0, 1.8, 1.9],
           "vitamin_d": [800, 0, 800], "headache": [1, 2, 2], "vision_blur": [0, 1, 1]}
A1_LOGS = {"sleep_hours": [7.1, 7.3, 7.0], "co2_sleep": [2700, 2650, 2750],
           "resistance_load_pct": [98, 101, 97], "calories": [2800, 2850, 2780],
           "protein": [121, 118, 122], "sodium": [2900, 2800, 3000], "fluids": [2.6, 2.7, 2.5],
           "vitamin_d": [800, 800, 800], "headache": [0, 0, 0], "vision_blur": [0, 0, 0]}
UNITS = {"sleep_hours": "h", "co2_sleep": "ppm", "resistance_load_pct": "pct", "calories": "kcal",
         "protein": "g", "sodium": "mg", "fluids": "L", "vitamin_d": "IU", "headache": "0-10",
         "vision_blur": "0-10", "systolic_bp": "mmHg", "resting_hr": "bpm", "hrv_rmssd": "ms",
         "hr_recovery": "bpm", "irregular_beats": "count"}


def truth(p, sleep, load, co2, drift_hrv=0.0, drift_rhr=0.0):
    """How the body 'really' responds — the Shadow model has to learn this."""
    hrv = p["hrv"] + 3 * (sleep - 7) + 0.08 * (load - 100) - 0.003 * (co2 - 2500) + drift_hrv
    rhr = p["rhr"] - 1.2 * (sleep - 7) - 0.02 * (load - 100) + 0.0015 * (co2 - 2500) + drift_rhr
    return hrv + random.gauss(0, 1.2), rhr + random.gauss(0, 0.6)


def row(a, t, metric, value, unit, source, quality="good", detail=""):
    return {"astronaut": a, "time": t.isoformat(), "metric": metric, "value": value, "unit": unit,
            "source": source, "quality": quality, "detail": detail}


def preflight():
    rows = []
    for a, p in PEOPLE.items():
        for d in range(-13, 1):                       # days -13 .. 0
            t = LAUNCH + timedelta(days=d - 1, hours=21)
            sleep, load, co2 = random.uniform(5.8, 8.2), random.uniform(75, 115), random.uniform(800, 4000)
            hrv, rhr = truth(p, sleep, load, co2)
            vals = {"sleep_hours": round(sleep, 1), "resistance_load_pct": round(load), "co2_sleep": round(co2),
                    "hrv_rmssd": round(hrv, 1), "resting_hr": round(rhr, 1),
                    "hr_recovery": round(p["rec"] + random.gauss(0, 1), 1),
                    "systolic_bp": round(p["bp"] + random.gauss(0, 2)), "irregular_beats": random.randint(2, 8),
                    "calories": round(random.gauss(2800, 60)), "protein": round(random.gauss(120, 4)),
                    "sodium": round(random.gauss(2800, 120)), "fluids": round(random.gauss(2.5, 0.1), 2),
                    "vitamin_d": 800, "headache": 0, "vision_blur": 0}
            rows += [row(a, t, m, v, UNITS[m], "preflight") for m, v in vals.items()]
        t0 = LAUNCH + timedelta(days=-1, hours=9)      # pre-flight test day
        for m, u, k in [("quad_csa", "cm2", "csa"), ("knee_torque", "Nm", "torque"),
                        ("urine_calcium", "mg/day", "uca"), ("near_vision_score", "score", "vision"),
                        ("onsd", "mm", "onsd"), ("rnfl", "um", "rnfl"), ("stroke_volume", "mL", "sv")]:
            rows.append(row(a, t0, m, p[k], u, "preflight_test"))
    return rows


def rr_list(hr, rmssd, n):
    base = 60000 / hr
    s = rmssd / math.sqrt(2)
    return [round(base + random.gauss(0, s)) for _ in range(n)]


def heart_day(a, day, rhr, hrv, recovery):
    rows, start = [], LAUNCH + timedelta(days=day - 1)
    a_rest = rhr + 12
    tau = -60 / math.log(1 - recovery / (140 - a_rest))
    for i in range(17280):
        t = start + timedelta(seconds=5 * i)
        h = t.hour + t.minute / 60 + t.second / 3600
        if h >= 23 or h < 7:
            hr, rm = rhr, hrv
        elif 10 <= h < 11:
            hr, rm = 115 + random.gauss(0, 2), 15
        elif 16 <= h < 16.5:
            hr, rm = 140 + random.gauss(0, 1), 12
        elif 16.5 <= h < 16.75:                      # recovery after the standard workout
            sec = (h - 16.5) * 3600
            hr, rm = a_rest + (140 - a_rest) * math.exp(-sec / tau), 15
        else:
            hr, rm = a_rest + random.gauss(0, 1.5), 25
        quality, rr = "good", None

        # planted events
        if a == "A2" and day == 1 and t.hour == 6 and t.minute < 2:        # strap slipped
            hr, quality, rr = 214, "bad", []
        if a == "A2" and day == 2 and t.hour == 20 and t.minute < 10:      # stress episode
            hr = rhr + 34 + random.gauss(0, 1)
        n = max(1, round(5 * hr / 60))
        if rr is None:
            rr = rr_list(hr, rm, n)
        if a == "A2" and day == 3 and t.hour == 9 and t.minute < 3:        # irregular rhythm
            rr = [round(60000 / hr * (0.6 if k % 2 else 1.4)) for k in range(n)]
        rows.append(row(a, t, "heart_rate", round(hr, 1), "bpm", "ecg_shirt", quality, ";".join(map(str, rr))))
    return rows


def dose_day(a, day):
    rows, start = [], LAUNCH + timedelta(days=day - 1)
    for i in range(17280):
        t = start + timedelta(seconds=5 * i)
        rate = 75 + random.gauss(0, 3)
        if day == 2 and t.hour == 14 and t.minute < 40:                   # solar particle event
            rate = (400 if a == "A1" else 380) + random.gauss(0, 10)
        rows.append(row(a, t, "dose_rate", round(rate, 1), "uSv/h", "active_dosimeter"))
    return rows


def mission():
    rows = []
    for a, p in PEOPLE.items():
        logs = A2_LOGS if a == "A2" else A1_LOGS
        for day in (1, 2, 3):
            i = day - 1
            sleep, load, co2 = logs["sleep_hours"][i], logs["resistance_load_pct"][i], logs["co2_sleep"][i]
            drift = (-3.0 * day, 1.0 * day) if a == "A2" else (0.0, 0.0)
            hrv, rhr = truth(p, sleep, load, co2, *drift)
            rec = p["rec"] - (2 * day if a == "A2" else 0) + random.gauss(0, 0.5)
            rows += heart_day(a, day, round(rhr, 1), max(hrv, 10), rec)
            rows += dose_day(a, day)
            t = LAUNCH + timedelta(days=day - 1, hours=21)
            for m, vals in logs.items():
                rows.append(row(a, t, m, vals[i], UNITS[m], "daily_log"))
            bp = p["bp"] + (2 + day if a == "A2" else 0) + random.gauss(0, 1)
            rows.append(row(a, t, "systolic_bp", round(bp), "mmHg", "bp_cuff"))

            tt = LAUNCH + timedelta(days=day - 1, hours=9, minutes=30)
            if day == 1:
                rows.append(row(a, tt, "near_vision_score", 94 if a == "A1" else 87, "score", "tablet_test"))
            if day == 2:
                rows.append(row(a, tt, "knee_torque", 109 if a == "A1" else 91, "Nm", "force_sensor"))
            if day == 3:
                rows.append(row(a, tt, "quad_csa", 51.8 if a == "A1" else 47.8, "cm2", "ultrasound"))
                rows.append(row(a, tt, "urine_calcium", 250 if a == "A1" else 290, "mg/day", "urine_test"))
                rows.append(row(a, tt, "onsd", 5.0 if a == "A1" else 5.3, "mm", "ocular_ultrasound"))
                # passive dosimeter: A1 reported in uSv (tests unit conversion), A2 is off by ~15%
                if a == "A1":
                    rows.append(row(a, tt, "passive_dose", 5550, "uSv", "passive_dosimeter"))
                else:
                    rows.append(row(a, tt, "passive_dose", 6.4, "mSv", "passive_dosimeter"))
    # two broken rows to show ingestion rejecting junk
    rows.append({"astronaut": "A1", "time": (LAUNCH + timedelta(hours=12)).isoformat(), "metric": "heart_rate",
                 "value": "", "unit": "bpm", "source": "ecg_shirt", "quality": "", "detail": ""})
    rows.append(row("A2", LAUNCH + timedelta(hours=12), "blood_glow", 3, "lumens", "mystery_sensor"))
    return rows


def write(name, rows):
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, name), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    print(f"wrote data/{name}: {len(rows):,} rows")


if __name__ == "__main__":
    write("preflight.csv", preflight())
    write("mission.csv", mission())
