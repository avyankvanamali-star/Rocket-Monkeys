# generate_30day_data.py
# Makes 14 pre-mission days + 30 mission days of fake data for A1 (healthy) and A2 (drifting).

# ---------- SECTION 1: setup ----------
import csv
import os
import random
from datetime import datetime, timedelta

os.chdir(os.path.dirname(os.path.abspath(__file__)))   # work from this file's folder (helps in IDLE)
random.seed(42)                      # same data every run
LAUNCH = datetime(2027, 3, 1)        # mission day 1
PRE_DAYS = 14                        # pre-mission days: -13 .. 0
MISSION_DAYS = 30                    # mission days: 1 .. 30
ASTRONAUTS = ["A1", "A2"]
STEP = 5                             # seconds between stream readings

def day_start(day):
    return LAUNCH + timedelta(days=day - 1)

def ramp(day, start, end, total):
    """0 before 'start', then grows evenly to 'total' by 'end'."""
    if day < start:
        return 0
    return total * min(1, (day - start) / (end - start))

def row(astro, time, metric, value, unit, source, quality="good", detail=""):
    return [astro, time.isoformat(timespec="seconds"), metric,
            round(value, 2), unit, source, quality, detail]

# ---------- SECTION 2: daily logs (the causes) ----------
def daily_inputs(astro, day):
    d = {
        "sleep_hours": 7.2 + random.gauss(0, 0.5),
        "co2_sleep":   2800 + random.gauss(0, 100),
        "workload":    100 + random.gauss(0, 4),
        "sodium":      2800 + random.gauss(0, 150),
        "fluids":      2.5 + random.gauss(0, 0.15),
        "calories":    2800 + random.gauss(0, 80),
        "protein":     120 + random.gauss(0, 5),
        "vitamin_d":   800,
        "mood":        4,
    }
    if astro == "A2":
        d["sleep_hours"] += ramp(day, 10, 30, -1.0)
        if 21 <= day <= 25:              # bad sleep after the day-20 storm
            d["sleep_hours"] -= 0.6
        d["co2_sleep"] += ramp(day, 8, 30, 800)
        d["workload"]  += ramp(day, 8, 30, -40)
        d["sodium"]    += ramp(day, 8, 30, 1100)
        d["fluids"]    += ramp(day, 8, 30, -0.7)
        d["calories"]  += ramp(day, 10, 30, -300)
        d["protein"]   += ramp(day, 10, 30, -20)
        if day in (14, 23):
            d["vitamin_d"] = 0           # missed doses
        if day >= 15:
            d["mood"] = 3
    return d

# ---------- SECTION 3: body readings (the effects) ----------
def body_readings(astro, day, inp):
    sleep_debt = 7.2 - inp["sleep_hours"]
    extra_co2 = inp["co2_sleep"] - 2800
    b = {
        "resting_hr": 56 + 1.5 * sleep_debt + 0.002 * extra_co2 + random.gauss(0, 0.8),
        "hrv":        48 - 3.0 * sleep_debt - 0.002 * extra_co2 + random.gauss(0, 1.2),
        "hr_recovery": 32 + random.gauss(0, 1),
        "bp_sys":     118 + 0.004 * (inp["sodium"] - 2800) + random.gauss(0, 2),
        "bp_dia":     76 + 0.003 * (inp["sodium"] - 2800) + random.gauss(0, 1.5),
        "headache":   0,
        "blur":       0,
    }
    if astro == "A2":
        b["hrv"] += ramp(day, 12, 30, -7)        # the drop sleep does NOT explain
        b["hr_recovery"] += ramp(day, 12, 30, -6)
        b["headache"] = round(ramp(day, 14, 30, 2))
        b["blur"] = round(ramp(day, 18, 30, 1))
    return b

# ---------- SECTION 4: streams (every 5 seconds) ----------
def heart_stream(astro, day, b):
    rows = []
    t0 = day_start(day)
    for s in range(0, 86400, STEP):
        hour = s // 3600
        hr = b["resting_hr"]
        if hour < 7:
            hr -= 4                      # asleep
        elif hour == 17:
            hr += 60                     # workout hour
        else:
            hr += 10                     # awake, working
        gap = 60000 / hr + random.gauss(0, b["hrv"] / 1.4)
        quality = "good"
        # day 1: A2 strap slips for 3 readings
        if astro == "A2" and day == 1 and 21600 <= s < 21615:
            hr, gap, quality = 214, 280, "bad"
        # day 26: A2 irregular rhythm for 5 minutes
        if astro == "A2" and day == 26 and 36000 <= s < 36300:
            gap = random.uniform(600, 1400)
        hr_shown = 60000 / gap if quality == "good" else hr
        rows.append(row(astro, t0 + timedelta(seconds=s), "heart_rate",
                        hr_shown, "bpm", "ecg_shirt", quality, round(gap)))
    return rows

def dose_stream(astro, day):
    rows = []
    total_mSv = 0
    t0 = day_start(day)
    for s in range(0, 86400, STEP):
        rate = 75 + random.gauss(0, 2)   # uSv/h background
        if day == 20 and 6 <= s // 3600 < 24:
            rate *= 20                   # solar storm (demo number)
        total_mSv += rate * STEP / 3600 / 1000
        rows.append(row(astro, t0 + timedelta(seconds=s), "dose_rate",
                        rate, "uSv/h", "active_dosimeter"))
    return rows, total_mSv

# ---------- SECTION 5: daily logs + periodic tests as rows ----------
def daily_rows(astro, day, inp, b, dose_today):
    t = day_start(day)
    r = [
        row(astro, t + timedelta(hours=7),  "sleep_hours", inp["sleep_hours"], "h", "wearable"),
        row(astro, t + timedelta(hours=7),  "co2_sleep", inp["co2_sleep"], "ppm", "cabin_sensor"),
        row(astro, t + timedelta(hours=18), "resistance_load_pct", inp["workload"], "pct", "ared"),
        row(astro, t + timedelta(hours=21), "sodium", inp["sodium"], "mg", "daily_log"),
        row(astro, t + timedelta(hours=21), "fluids", inp["fluids"], "L", "daily_log"),
        row(astro, t + timedelta(hours=21), "calories", inp["calories"], "kcal", "daily_log"),
        row(astro, t + timedelta(hours=21), "protein", inp["protein"], "g", "daily_log"),
        row(astro, t + timedelta(hours=21), "vitamin_d", inp["vitamin_d"], "IU", "daily_log"),
        row(astro, t + timedelta(hours=21), "mood", inp["mood"], "score", "daily_log"),
        row(astro, t + timedelta(hours=21), "headache", b["headache"], "score", "daily_log"),
        row(astro, t + timedelta(hours=21), "blurred_vision", b["blur"], "score", "daily_log"),
        row(astro, t + timedelta(hours=8),  "bp_systolic", b["bp_sys"], "mmHg", "cuff"),
        row(astro, t + timedelta(hours=8),  "bp_diastolic", b["bp_dia"], "mmHg", "cuff"),
        row(astro, t + timedelta(hours=18), "hr_recovery", b["hr_recovery"], "bpm", "ergometer"),
    ]
    # Pre-mission days have no stream, so give the baseline HR/HRV directly
    if day <= 0:
        r.append(row(astro, t + timedelta(hours=7), "resting_hr", b["resting_hr"], "bpm", "ecg_summary"))
        r.append(row(astro, t + timedelta(hours=7), "hrv_rmssd", b["hrv"], "ms", "ecg_summary"))

    # Periodic tests (daily in the demo). Lagged effects use later ramp starts.
    a2 = astro == "A2"
    r += [
        row(astro, t + timedelta(hours=9), "urine_calcium",
            245 + (ramp(day, 13, 30, 55) if a2 else 0) + random.gauss(0, 6), "mg/day", "urine_test"),
        row(astro, t + timedelta(hours=10), "quad_csa",
            50 + (ramp(day, 15, 30, -3) if a2 else 0) + random.gauss(0, 0.3), "cm2", "ultrasound"),
        row(astro, t + timedelta(hours=10), "knee_torque",
            100 + (ramp(day, 15, 30, -10) if a2 else 0) + random.gauss(0, 1.5), "N*m", "force_sensor"),
        row(astro, t + timedelta(hours=11), "near_vision_score",
            92 + (ramp(day, 12, 30, -5) if a2 else 0) + random.gauss(0, 0.8), "score", "tablet_test"),
        row(astro, t + timedelta(hours=11), "onsd",
            5.0 + (ramp(day, 12, 30, 0.3) if a2 else 0) + random.gauss(0, 0.03), "mm", "ocular_ultrasound"),
        row(astro, t + timedelta(hours=11), "rnfl_thickness",
            100 + (ramp(day, 15, 30, 3) if a2 else 0) + random.gauss(0, 0.5), "um", "oct"),
        row(astro, t + timedelta(hours=12), "stroke_volume",
            70 + (ramp(day, 15, 30, -3) if a2 else 0) + random.gauss(0, 1), "mL", "cardiac_ultrasound"),
    ]
    if day >= 1:
        passive = dose_today * random.uniform(0.98, 1.02)
        if a2 and day == 28:
            passive *= 1.3               # dosimeters disagree
        r.append(row(astro, t + timedelta(hours=23, minutes=59), "passive_dose",
                     passive, "mSv", "passive_dosimeter"))
    return r

# ---------- SECTION 6: run everything and write the files ----------
HEADER = ["astronaut", "time", "metric", "value", "unit", "source", "quality", "detail"]
os.makedirs("data", exist_ok=True)

with open("data/preflight.csv", "w", newline="") as pre, \
     open("data/mission.csv", "w", newline="") as mis:
    pre_w, mis_w = csv.writer(pre), csv.writer(mis)
    pre_w.writerow(HEADER)
    mis_w.writerow(HEADER)
    for day in range(-PRE_DAYS + 1, MISSION_DAYS + 1):
        for astro in ASTRONAUTS:
            inp = daily_inputs(astro, day)
            b = body_readings(astro, day, inp)
            if day <= 0:
                pre_w.writerows(daily_rows(astro, day, inp, b, 0))
            else:
                mis_w.writerows(heart_stream(astro, day, b))
                dose_rows, dose_today = dose_stream(astro, day)
                mis_w.writerows(dose_rows)
                mis_w.writerows(daily_rows(astro, day, inp, b, dose_today))
        print("done day", day)

    # planted bad rows: 2 broken + 1 unit conversion
    t = day_start(5)
    mis_w.writerow(["A2", t.isoformat(), "fluids", "", "L", "daily_log", "good", ""])
    mis_w.writerow(["A1", "not-a-time", "sodium", 2900, "mg", "daily_log", "good", ""])
    mis_w.writerow(["A2", (t + timedelta(hours=21)).isoformat(), "fluids", 1900, "mL", "daily_log", "good", ""])

print("Finished! Files are in the data folder.")
