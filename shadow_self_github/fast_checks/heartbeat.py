"""
HEARTBEAT FAST CHECK — runs every 5 seconds.            (PSEUDOCODE.md section 5)

detect heartbeat -> read heart rate + beat gaps (RR intervals) from last 5 sec
is the reading possible? no -> throw out (12 bad in a row = "check ECG strap")
record irregularities  -> beat gap differs >20% from previous gap
compare with previous  -> this 5 sec vs last minute, jumped >25%?
compare with activity  -> exercising (or 10 min cool-down) = high HR fine, resting = not fine
come up with scenarios:
    A. resting + HR high for 2 min          -> WATCH
    B. >6 irregular beats in 1 minute       -> ACT
    C. resting + HR <35 or >150 for 2 min   -> URGENT
    D. HR not dropping 60 s after workout   -> note "slow recovery"
store summary -> move on

END OF DAY: resting HR, HRV, HR recovery, irregular beats -> daily metrics
"""
import math
from collections import deque
from datetime import datetime

from config.settings import (BAD_IN_A_ROW_LIMIT, DANGER_HIGH, DANGER_LOW, HR_POSSIBLE,
                             IRREGULAR_GAP_CHANGE, IRREGULAR_PER_MIN_LIMIT, RECOVERY_GRACE_MIN,
                             RECOVERY_MIN_DROP, RESTING_HIGH_ABOVE_BASELINE,
                             STANDARD_WORKOUT_END, SUDDEN_JUMP, SUSTAINED_WINDOWS,
                             activity_at, hour_of)


class HeartbeatMonitor:
    def __init__(self, astronaut, resting_baseline):
        self.astronaut = astronaut
        self.resting_baseline = resting_baseline or 60
        self.last_rr = None
        self.new_day()

    def new_day(self):
        self.bad_count = 0
        self.irr_last_min = deque(maxlen=12)     # 12 windows = 60 s
        self.hr_last_min = deque(maxlen=12)
        self.high_streak = 0
        self.danger_streak = 0
        self.prev_activity = None
        self.recovery = None                     # (start time, start HR)
        self.last_exercise = None                # time exercise last happened
        self.irregular_today = 0
        self.sudden_changes = 0

    def process(self, time_str, hr, rr, quality):
        """One 5-second window. Returns a list of events (tier, key, message)."""
        events = []
        t = datetime.fromisoformat(time_str)

        # is the reading possible?
        if quality != "good" or not (HR_POSSIBLE[0] <= hr <= HR_POSSIBLE[1]):
            self.bad_count += 1
            if self.bad_count == BAD_IN_A_ROW_LIMIT:
                events.append(("watch", "ecg_strap", "Check ECG strap: 1 minute of unusable heart data"))
            return events
        self.bad_count = 0

        # record irregularities
        irregular = 0
        prev = self.last_rr
        for gap in rr:
            if prev and abs(gap - prev) / prev > IRREGULAR_GAP_CHANGE:
                irregular += 1
            prev = gap
        self.last_rr = prev
        self.irregular_today += irregular
        self.irr_last_min.append(irregular)

        # compare with previous
        if self.hr_last_min:
            avg = sum(self.hr_last_min) / len(self.hr_last_min)
            if abs(hr - avg) / avg > SUDDEN_JUMP:
                self.sudden_changes += 1
        self.hr_last_min.append(hr)

        # compare with activity
        activity = activity_at(hour_of(t))
        exercising = activity in ("resistance", "aerobic")
        if exercising:
            self.last_exercise = t
        cooling_down = (self.last_exercise is not None and
                        (t - self.last_exercise).total_seconds() < RECOVERY_GRACE_MIN * 60)
        resting = not exercising and not cooling_down

        # scenario A: resting + high HR, sustained
        self.high_streak = self.high_streak + 1 if (
            resting and hr > self.resting_baseline + RESTING_HIGH_ABOVE_BASELINE) else 0
        if self.high_streak == SUSTAINED_WINDOWS:
            events.append(("watch", "elevated_resting_hr",
                           f"Resting HR {hr:.0f} bpm for 2+ min while not exercising (stress/fatigue?)"))

        # scenario B: irregular rhythm
        if sum(self.irr_last_min) > IRREGULAR_PER_MIN_LIMIT:
            events.append(("act", "irregular_rhythm",
                           f"{sum(self.irr_last_min)} irregular beats in the last minute"))

        # scenario C: dangerous resting HR, sustained
        self.danger_streak = self.danger_streak + 1 if (
            resting and (hr < DANGER_LOW or hr > DANGER_HIGH)) else 0
        if self.danger_streak == SUSTAINED_WINDOWS:
            events.append(("urgent", "danger_hr", f"Resting HR {hr:.0f} bpm for 2+ min"))

        # scenario D: slow recovery after workout
        if self.prev_activity in ("resistance", "aerobic") and not exercising:
            self.recovery = (t, self.hr_last_min[-2] if len(self.hr_last_min) > 1 else hr)
        if self.recovery and (t - self.recovery[0]).total_seconds() >= 60:
            drop = self.recovery[1] - hr
            if drop < RECOVERY_MIN_DROP:
                events.append(("info", f"slow_recovery_{self.recovery[0]:%H%M}",
                               f"HR only dropped {drop:.0f} bpm 60 s after workout"))
            self.recovery = None
        self.prev_activity = activity

        return events


def _rmssd(rr):
    diffs = [b - a for a, b in zip(rr, rr[1:])]
    return math.sqrt(sum(d * d for d in diffs) / len(diffs)) if diffs else None


def summarize_heart_day(db, astronaut, day, monitor):
    """END OF DAY: turn today's 5-second stream into daily cardio metrics."""
    rows = [r for r in db.get_stream(astronaut, "heart_rate", day) if r["quality"] == "good"]
    sleep_hr, sleep_rr, by_time = [], [], {}
    for r in rows:
        t = datetime.fromisoformat(r["time"])
        by_time[t.strftime("%H:%M:%S")] = r["value"]
        if activity_at(hour_of(t)) == "sleep":
            sleep_hr.append(r["value"])
            sleep_rr += [float(x) for x in r["detail"].split(";") if x]

    out = {}
    # resting HR = lowest 5-minute average during sleep (60 windows)
    if len(sleep_hr) >= 60:
        out["resting_hr"] = round(min(sum(sleep_hr[i:i + 60]) / 60 for i in range(len(sleep_hr) - 59)), 1)
    # HRV = RMSSD of beat gaps during sleep
    if sleep_rr:
        out["hrv_rmssd"] = round(_rmssd(sleep_rr), 1)
    # HR recovery = drop 60 s after the standard workout
    h = int(STANDARD_WORKOUT_END)
    m = int(round((STANDARD_WORKOUT_END - h) * 60))
    end_key, after_key = f"{h:02d}:{m:02d}:00", f"{h:02d}:{m + 1:02d}:00"
    if end_key in by_time and after_key in by_time:
        out["hr_recovery"] = round(by_time[end_key] - by_time[after_key], 1)
    if rows:                                     # no stream today -> leave it out (manual-only day)
        out["irregular_beats"] = monitor.irregular_today
    return out
