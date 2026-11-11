"""
180-DAY MISSION SIMULATOR — training data for PyTorch + a test with known answers.

Makes daily data (no 5-second streams, which would be ~25 million rows) for 4 astronauts:
    30 pre-mission days (day -29 .. 0) + 180 mission days (day 1 .. 180)

The body follows hidden "true" rules that are NOT straight lines (that's why a neural
network can beat linear regression):
    HRV depends on tonight's sleep (with diminishing returns), last night's sleep (sleep debt),
    workload, CO2 where they sleep (only above ~2,500 ppm), and a bad-sleep x high-CO2 combo.

PLANTED EVENTS (the answer key is written to data_sim/events.csv):
    A1  control. Days 150-164: short sleep + high CO2  -> HRV drops, but it's EXPLAINED (no alarm wanted)
    A2  day 60+: workouts drop to ~55%                  -> bone/muscle change; HRV dip is EXPLAINED
    A3  day 100+: hidden heart drift (HRV down, resting HR up) that sleep/workload/CO2 do NOT explain
    A4  day 130+: eye changes (vision score down, optic nerve sheath up)
    all days 90-92: solar particle event (radiation dose spike)

Output (same columns as every other Shadow Self CSV):
    data_sim/sim_daily.csv   astronaut,time,metric,value,unit,source,quality,detail
    data_sim/events.csv      the answer key

Run:  python3 simulator/run.py
All numbers are made up for testing.
"""
import csv
import math
import os
import random
from datetime import datetime, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data_sim")
LAUNCH = datetime(2027, 3, 1)
PRE_DAYS, MISSION_DAYS = 30, 180
FIELDS = ["astronaut", "time", "metric", "value", "unit", "source", "quality", "detail"]

# each astronaut's normal
CREW = {
    "A1": {"hrv": 52, "rhr": 55, "uca": 240, "vision": 94, "onsd": 5.0, "csa": 52, "torque": 110},
    "A2": {"hrv": 48, "rhr": 56, "uca": 245, "vision": 92, "onsd": 5.0, "csa": 50, "torque": 100},
    "A3": {"hrv": 45, "rhr": 58, "uca": 230, "vision": 95, "onsd": 4.9, "csa": 48, "torque": 95},
    "A4": {"hrv": 55, "rhr": 53, "uca": 250, "vision": 93, "onsd": 5.1, "csa": 54, "torque": 115},
}

EVENTS = [  # astronaut, start, end, system, what, should_alarm_heart_model
    ("A1", 150, 164, "cardio", "short sleep + high CO2 (explained HRV drop)", "no"),
    ("A2", 60, 180, "muscle/bone", "workouts drop to ~55% of target", "no"),
    ("A3", 100, 180, "cardio", "hidden heart drift: HRV down, resting HR up", "yes"),
    ("A4", 130, 180, "sans", "eye changes: vision down, optic nerve sheath up", "no"),
    ("ALL", 90, 92, "radiation", "solar particle event", "no"),
]

UNITS = {"sleep_hours": "h", "resistance_load_pct": "pct", "co2_sleep": "ppm", "sodium": "mg", "fluids": "L",
         "calories": "kcal", "protein": "g", "daily_dose": "mSv", "hrv_rmssd": "ms", "resting_hr": "bpm",
         "urine_calcium": "mg/day", "near_vision_score": "score", "onsd": "mm", "quad_csa": "cm2",
         "knee_torque": "Nm", "headache": "0-10"}


def clip(x, lo, hi):
    return max(lo, min(hi, x))


def true_heart(base_hrv, base_rhr, sleep, sleep_prev, load, co2, drift_days, rng):
    """The hidden 'true body'. The models never see this function — they must learn it from data."""
    co2_excess = max(co2 - 2500, 0) / 1000                      # only matters above 2,500 ppm
    combo = 1.0 if (sleep < 6.0 and co2 > 3200) else 0.0        # bad sleep AND stuffy air: extra hit
    hrv = (base_hrv + 7 * math.tanh(sleep - 7) + 2.5 * math.tanh(sleep_prev - 7)
           + 0.06 * (load - 100) - 4.0 * co2_excess - 3.0 * combo)
    rhr = (base_rhr - 2.5 * math.tanh(sleep - 7) - 1.0 * math.tanh(sleep_prev - 7)
           - 0.02 * (load - 100) + 1.5 * co2_excess + 1.0 * combo)
    hrv -= 0.30 * drift_days                                     # hidden drift (only A3 after day 100)
    rhr += 0.10 * drift_days
    return hrv + rng.gauss(0, 1.3), rhr + rng.gauss(0, 0.5)


def simulate(seed=42):
    rng = random.Random(seed)
    rows = []
    for a, p in CREW.items():
        sleep_prev = 7.0
        bone_frac, csa, torque = 1.0, p["csa"], p["torque"]
        for day in range(-PRE_DAYS + 1, MISSION_DAYS + 1):
            t = LAUNCH + timedelta(days=day - 1, hours=21)
            flight = day >= 1

            # ---- daily inputs (behaviour + environment) ----
            sleep = clip(rng.gauss(7.0, 0.7), 4.5, 9.0)
            load = clip(rng.gauss(95, 9), 50, 125)
            co2 = clip(rng.gauss(2600 if flight else 1800, 500), 600, 4500)
            if not flight:                                       # training camp: wider variety
                sleep, co2 = clip(rng.gauss(7.0, 0.9), 4.5, 9.0), rng.uniform(800, 4200)
            if a == "A1" and 150 <= day <= 164:                  # explained bad patch
                sleep, co2 = clip(rng.gauss(5.4, 0.3), 4.5, 6.2), clip(rng.gauss(3700, 200), 3300, 4500)
            if a == "A2" and day >= 60:                          # skipping workouts
                load = clip(rng.gauss(55, 6), 35, 75)
            sodium = clip(rng.gauss(3000, 350), 1800, 5000)
            fluids = clip(rng.gauss(2.5, 0.25), 1.4, 3.6)
            dose = (1.8 + rng.gauss(0, 0.05)) if flight else 0.01
            if flight and 90 <= day <= 92:
                dose += 25 if day == 90 else 8

            # ---- body ----
            drift = max(0, day - 100) if a == "A3" else 0
            hrv, rhr = true_heart(p["hrv"], p["rhr"], sleep, sleep_prev, load, co2, drift, rng)
            sleep_prev = sleep

            vals = {"sleep_hours": round(sleep, 2), "resistance_load_pct": round(load, 1), "co2_sleep": round(co2),
                    "sodium": round(sodium), "fluids": round(fluids, 2),
                    "calories": round(rng.gauss(2800, 70)), "protein": round(rng.gauss(118, 5)),
                    "daily_dose": round(dose, 3), "hrv_rmssd": round(hrv, 1), "resting_hr": round(rhr, 1),
                    "headache": 0}

            # bone/muscle respond slowly to workload
            if flight:
                bone_frac *= 1 - (2.0 - min(load, 100) / 100) / 100 / 30
                csa -= 0.01 + max(0, 85 - load) * 0.0025
                torque -= 0.02 + max(0, 85 - load) * 0.006
            if day % 7 == 0:
                vals["urine_calcium"] = round(p["uca"] * (1 + (1 - bone_frac) * 12) + rng.gauss(0, 8))
                vals["knee_torque"] = round(torque + rng.gauss(0, 2), 1)
            if day % 14 == 0:
                vals["quad_csa"] = round(csa + rng.gauss(0, 0.5), 1)
            # eyes
            eye = max(0, day - 130) if a == "A4" else 0
            if day % 3 == 0:
                vals["near_vision_score"] = round(p["vision"] - 0.12 * eye + rng.gauss(0, 1.0), 1)
            if day % 14 == 0:
                vals["onsd"] = round(p["onsd"] + 0.008 * eye + rng.gauss(0, 0.06), 2)
            if a == "A4" and eye > 20:
                vals["headache"] = int(clip(round(rng.gauss(3, 1)), 0, 10))

            for m, v in vals.items():
                rows.append({"astronaut": a, "time": t.isoformat(), "metric": m, "value": v, "unit": UNITS[m],
                             "source": "simulator", "quality": "good", "detail": ""})
    return rows


def main():
    os.makedirs(OUT, exist_ok=True)
    rows = simulate()
    with open(os.path.join(OUT, "sim_daily.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    with open(os.path.join(OUT, "events.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["astronaut", "start_day", "end_day", "system", "what", "heart_model_should_alarm"])
        w.writerows(EVENTS)
    print(f"wrote data_sim/sim_daily.csv: {len(rows):,} rows "
          f"({len(CREW)} astronauts x {PRE_DAYS} pre-mission + {MISSION_DAYS} mission days)")
    print("wrote data_sim/events.csv: the answer key (planted problems)")


if __name__ == "__main__":
    main()
