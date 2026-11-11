"""
RADIATION FAST CHECK — runs every 5 seconds.            (PSEUDOCODE.md section 6)

read dose rate (uSv/h)
bad reading? -> skip
add to running total: total += dose_rate x (5 sec in hours)
dose rate > 3 x background for 1 minute? -> EVENT MODE -> URGENT "go to shielded area"
back to normal for 30 min                 -> end event mode
"""
from config.settings import (BACKGROUND_DOSE_RATE, EVENT_END_WINDOWS, EVENT_FACTOR,
                             EVENT_START_WINDOWS, FAST_CHECK_SECONDS)


class RadiationWatch:
    def __init__(self, astronaut):
        self.astronaut = astronaut
        self.event_mode = False
        self.high = 0
        self.normal = 0
        self.today_usv = 0.0
        self.peak = 0.0
        self.windows = 0

    def new_day(self):
        self.windows = 0
        self.today_usv = 0.0
        self.peak = 0.0

    def process(self, time_str, rate, quality):
        events = []
        if quality != "good":
            return events
        self.windows += 1
        self.today_usv += rate * FAST_CHECK_SECONDS / 3600
        self.peak = max(self.peak, rate)

        if rate > BACKGROUND_DOSE_RATE * EVENT_FACTOR:
            self.high, self.normal = self.high + 1, 0
        else:
            self.normal, self.high = self.normal + 1, 0

        if not self.event_mode and self.high >= EVENT_START_WINDOWS:
            self.event_mode = True
            events.append(("urgent", "radiation_event",
                           f"Dose rate {rate:.0f} uSv/h (>{EVENT_FACTOR:g}x background) — "
                           "possible solar particle event: GO TO SHIELDED AREA"))
        if self.event_mode and self.normal >= EVENT_END_WINDOWS:
            self.event_mode = False
            events.append(("info", "radiation_event_end", "Dose rate back to normal for 30 min — event over"))
        return events


def summarize_dose_day(watch):
    """END OF DAY: daily dose in mSv. Fallback: no stream today -> no number (not a fake 0)."""
    if watch.windows == 0:
        return {}
    return {"daily_dose": round(watch.today_usv / 1000, 4)}
