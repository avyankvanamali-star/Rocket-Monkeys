"""
CONFIG — every number the system uses lives here.      (PSEUDOCODE.md section 1)

For every metric we write down:
    domain, unit, possible range, SEM (measurement error), bad direction
    MDC = 1.96 x sqrt(2) x SEM   (computed automatically)

NOTE: SEM values and thresholds are illustrative demo values for the
hackathon, NOT medical standards.
"""
import math
from datetime import date, datetime

# ---------------- mission ----------------
LAUNCH_DATE = date(2027, 3, 1)       # mission day 1
MISSION_DAYS = 180
CAREER_LIMIT_MSV = 600.0             # double-check the current NASA limit before presenting
ASTRONAUTS = ["A1", "A2"]

# ---------------- shared 7-step check ----------------
PERSIST_COUNT = 3                    # this many flagged results in a row = "persistent"
RESIDUAL_LIMIT = 2.0                 # residual bigger than 2 x usual size = unexpected
STRICT_FACTOR = 0.75                 # after a radiation event, cardio uses MDC x 0.75
STRICT_DAYS = 7

# ---------------- heartbeat fast check ----------------
FAST_CHECK_SECONDS = 5
HR_POSSIBLE = (30, 220)
BAD_IN_A_ROW_LIMIT = 12              # 12 x 5 s = 1 minute
IRREGULAR_GAP_CHANGE = 0.20          # beat gap differs >20% from previous gap
IRREGULAR_PER_MIN_LIMIT = 6
SUDDEN_JUMP = 0.25
RESTING_HIGH_ABOVE_BASELINE = 25     # bpm above resting baseline
SUSTAINED_WINDOWS = 24               # 24 x 5 s = 2 minutes
DANGER_LOW, DANGER_HIGH = 35, 150
RECOVERY_MIN_DROP = 12               # bpm drop expected 60 s after workout
RECOVERY_GRACE_MIN = 10              # HR may stay high this long after a workout

# ---------------- radiation ----------------
BACKGROUND_DOSE_RATE = 75.0          # uSv/h, rough deep-space background
EVENT_FACTOR = 3.0
EVENT_START_WINDOWS = 12             # 1 minute above 3x background
EVENT_END_WINDOWS = 360              # 30 minutes back to normal
PASSIVE_MISMATCH = 0.10

# ---------------- crew schedule (hours of the day) ----------------
SLEEP = (23.0, 7.0)
EXERCISE = [(10.0, 11.0, "resistance"), (16.0, 16.5, "aerobic")]
STANDARD_WORKOUT_END = 16.5
EVA_DAYS = {"A1": [], "A2": [5]}     # spacewalk days (planner avoids clashes)

# ---------------- module thresholds ----------------
LOW_WORKLOAD_PCT = 70
LOW_WORKLOAD_DAYS = 3
BONE_FAST_LOSS = 1.5                 # % per month
LOW_FLUIDS_L = 2.0
HIGH_SODIUM_MG = 3500
HIGH_CO2_PPM = 3000
SYMPTOM_LEVEL = 3
SYMPTOM_DAYS = 3
LOW_FUEL_FRACTION = 0.90
# CUSUM drift detector (heart): adds up each day's 'worse than expected' gap (in noise units).
# Small random gaps cancel out; a slow steady drift builds up -> alarm when the total passes CUSUM_H.
# Tuned on seeds 1-6, checked on unseen seeds (see score_run.py).
CUSUM_K = 0.25                       # ignore gaps smaller than this (noise allowance per day)
CUSUM_H = 2.5                        # alarm when the running total passes this
CARDIO_DRIFT_DAYS = 3                # 7 on a real mission; 3 so the 3-day demo can show it

# ---------------- Shadow model ----------------
SHADOW_INPUTS = ["sleep_hours", "resistance_load_pct", "co2_sleep"]
SHADOW_TARGETS = ["resting_hr", "hrv_rmssd"]
MIN_TRAIN_DAYS = 10
RELEARN_EVERY = 14


def _m(domain, unit, lo, hi, sem, bad, label):
    return {"domain": domain, "unit": unit, "range": (lo, hi), "sem": sem,
            "mdc": 1.96 * math.sqrt(2) * sem, "bad": bad, "label": label}


METRICS = {
    # fast streams (every 5 s)
    "heart_rate":          _m("cardio", "bpm", 25, 230, 2, "up", "Heart rate"),
    "dose_rate":           _m("radiation", "uSv/h", 0, 100000, 2, "up", "Dose rate"),
    # cardio daily (made by end-of-day summary)
    "resting_hr":          _m("cardio", "bpm", 30, 120, 1.5, "up", "Resting HR"),
    "hrv_rmssd":           _m("cardio", "ms", 5, 200, 3, "down", "HRV"),
    "hr_recovery":         _m("cardio", "bpm", 0, 80, 2, "down", "HR recovery"),
    "irregular_beats":     _m("cardio", "count", 0, 100000, 15, "up", "Irregular beats"),
    "systolic_bp":         _m("cardio", "mmHg", 70, 220, 3, "up", "Systolic BP"),
    "stroke_volume":       _m("cardio", "mL", 20, 200, 4, "down", "Stroke volume"),
    # radiation
    "daily_dose":          _m("radiation", "mSv", 0, 1000, 0.05, "up", "Daily dose"),
    "passive_dose":        _m("radiation", "mSv", 0, 5000, 0.1, "up", "Passive dose"),
    # muscle
    "resistance_load_pct": _m("muscle", "pct", 0, 200, 5, "down", "Workload"),
    "quad_csa":            _m("muscle", "cm2", 10, 150, 0.8, "down", "Muscle area"),
    "knee_torque":         _m("muscle", "Nm", 20, 400, 3, "down", "Strength"),
    # bone
    "urine_calcium":       _m("bone", "mg/day", 20, 800, 12, "up", "Urine calcium"),
    # sans (eyes / brain)
    "near_vision_score":   _m("sans", "score", 0, 100, 1.5, "down", "Vision score"),
    "onsd":                _m("sans", "mm", 3, 9, 0.1, "up", "Optic nerve sheath"),
    "rnfl":                _m("sans", "um", 50, 200, 2, "up", "RNFL thickness"),
    "headache":            _m("sans", "0-10", 0, 10, 1, "up", "Headache"),
    "vision_blur":         _m("sans", "0-10", 0, 10, 1, "up", "Vision blur"),
    # context + nutrition (used by rules, not scored on their own)
    "sleep_hours":         _m("context", "h", 0, 16, 0.3, "down", "Sleep"),
    "co2_sleep":           _m("context", "ppm", 300, 10000, 100, "up", "CO2 while sleeping"),
    "calories":            _m("nutrition", "kcal", 0, 6000, 100, "down", "Calories"),
    "protein":             _m("nutrition", "g", 0, 400, 5, "down", "Protein"),
    "sodium":              _m("nutrition", "mg", 0, 15000, 150, "up", "Sodium"),
    "fluids":              _m("nutrition", "L", 0, 8, 0.1, "down", "Fluids"),
    "vitamin_d":           _m("nutrition", "IU", 0, 10000, 50, "down", "Vitamin D"),
}

UNIT_CONVERSIONS = {
    ("uSv", "mSv"): 0.001, ("Sv", "mSv"): 1000.0, ("mSv/h", "uSv/h"): 1000.0,
    ("ml", "L"): 0.001, ("mL", "L"): 0.001, ("lb", "kg"): 0.4536,
}

# plan: at most this many actions per astronaut per day, most important first
MAX_PLAN_ACTIONS = 3
PLAN_PRIORITY = ["irregular_rhythm", "radiation_event", "cardio_drift", "missed_workouts", "muscle_loss",
                 "stone_risk_high", "sans_watch", "under_fueling", "schedule_oct", "vitd_missed"]

# countermeasure lookup table  (PSEUDOCODE section 14)
COUNTERMEASURES = {
    "missed_workouts": ("Add 2 resistance sessions", True),
    "muscle_loss":     ("Increase resistance load, check protein intake", True),
    "stone_risk_high": ("Fluid goal 2.5 L/day + low-sodium meals", False),
    "vitd_missed":     ("Take vitamin D with breakfast (missed this week)", False),
    "sans_watch":      ("Lower-body negative pressure session + check CO2 in sleep area", False),
    "schedule_oct":    ("Schedule OCT eye scan", False),
    "cardio_drift":    ("Adjust aerobic intervals + protect 7.5 h sleep", True),
    "radiation_event": ("Use shielded area; move spacewalks out of event window", False),
    "under_fueling":   ("Raise calories/protein back to target", False),
    "irregular_rhythm":("Crew medical officer: review ECG rhythm strip", False),
}
# the bool = heavy physical task (planner keeps it off spacewalk days)

STATUS_ORDER = {"no data": -1, "no baseline": -1, "ignored": -1,
                "ok": 0, "info": 0, "watch": 1, "act": 2, "urgent": 3}


def worst(statuses):
    """Return the most serious status in a list."""
    best = "ok"
    for s in statuses:
        if STATUS_ORDER.get(s, -1) > STATUS_ORDER[best]:
            best = s
    return best


def mission_day(dt):
    return (dt.date() - LAUNCH_DATE).days + 1


def hour_of(dt):
    return dt.hour + dt.minute / 60 + dt.second / 3600


def activity_at(hour):
    """Crew schedule: sleep / resistance / aerobic / rest."""
    start, end = SLEEP
    if hour >= start or hour < end:
        return "sleep"
    for a, b, kind in EXERCISE:
        if a <= hour < b:
            return kind
    return "rest"
