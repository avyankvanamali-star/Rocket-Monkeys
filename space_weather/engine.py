"""
SOLAR WATCH — the space-weather algorithm.              (PSEUDOCODE.md section 17)

Runs on every satellite snapshot (every 5 min), one watcher per astronaut
(the signals are the same for the whole crew; only the context differs: spacewalk or not).

1. SCORE each signal on NOAA's scales
       X-ray flux  -> R level (flare)              arrives ~8 min after the eruption
       proton flux -> S level (radiation storm)     arrives within tens of minutes  <- the real danger
       Kp index    -> G level (geomagnetic storm)   1-3 days later, after the CME
2. EARLY WARNING (catch it before it is bad)
       flare R2+ (M5 or bigger)         -> open a 60-min "protons may follow" window
       protons rising fast (slope over 15 min, flux >= 1 pfu) -> "rising" + minutes until S1
       solar wind > 600 km/s AND Bz < -10 nT for 30 min -> CME arrived, geomagnetic storm coming
3. FUSE into one alert level
       GREEN 0    all quiet
       WATCH 1    big flare window | protons rising | CME arrived | G1+
       WARNING 2  S1-S2 | protons rising INSIDE a flare window | G4+
       CRITICAL 3 S3+
       spacewalk under way -> one level higher (a spacesuit is not a shelter)
       level goes UP at once, comes DOWN only after 30 min of calmer readings
4. ACT: fixed action list per level (config SW_LEVEL_ACTIONS) — rules decide, AI only explains.

Missing / old satellite data -> that signal counts as unknown; the level is HELD, never dropped to green.
"""
import math
from collections import deque
from datetime import timedelta

from config.settings import (CME_BZ_NT, CME_SPEED_KMS, CME_SUSTAIN_MIN, EVA_HOURS, FLARE_WATCH_R,
                             FLARE_WINDOW_MIN, KP_G_LEVELS, PROTON_RISE_DECADES_H, PROTON_RISE_FLOOR,
                             PROTON_S_LEVELS, PROTON_TREND_MIN, SHIELDED_BY_EARTH, SW_ACTIONS, SW_CALM_MIN,
                             SW_LEVEL_ACTIONS, SW_LEVELS, XRAY_R_LEVELS, hour_of, mission_day)


# ---------------- 1. scales ----------------
def scale_level(value, table):
    """NOAA scale level (0-5) for one reading. Unknown reading -> None."""
    if value is None:
        return None
    for limit, level in table:
        if value >= limit:
            return level
    return 0


def flare_class(flux):
    """X-ray flux (W/m2) -> flare class text, e.g. 2.1e-4 -> 'X2.1'."""
    if not flux or flux <= 0:
        return "-"
    for letter, base in (("X", 1e-4), ("M", 1e-5), ("C", 1e-6), ("B", 1e-7)):
        if flux >= base:
            return f"{letter}{flux / base:.1f}"
    return f"A{flux / 1e-8:.1f}"


# ---------------- 2-4. the watcher ----------------
class SolarWatch:
    def __init__(self, astronaut, eva_days=()):
        self.astronaut = astronaut
        self.eva_days = set(eva_days)
        self.protons = deque()          # (time, pfu) over the last PROTON_TREND_MIN
        self.flare_until = None         # end of the "protons may follow" window
        self.flare_note = ""
        self.flare_peak = 0.0
        self.cme_since = None           # when fast wind + southward Bz started
        self.level = 0
        self.calm_since = None          # when readings first suggested a lower level

    def process(self, snap):
        """snap = {"time": datetime, "xray_flux", "proton_flux_10mev", "solar_wind_speed", "bz", "kp"}
        (any value may be None). Returns one step dict."""
        t = snap["time"]
        xray, p10 = snap.get("xray_flux"), snap.get("proton_flux_10mev")
        speed, bz, kp = snap.get("solar_wind_speed"), snap.get("bz"), snap.get("kp")
        reasons = []

        # 1. score
        r = scale_level(xray, XRAY_R_LEVELS)
        s = scale_level(p10, PROTON_S_LEVELS)
        g = scale_level(kp, KP_G_LEVELS)
        if s is not None and SHIELDED_BY_EARTH:
            s = max(0, s - 1)

        # 2a. flare precursor window
        if r is not None and r >= FLARE_WATCH_R:
            new_flare = not self.flare_until or t > self.flare_until
            if new_flare or xray > self.flare_peak:          # label with the flare's peak so far
                self.flare_peak = xray
                self.flare_note = f"{flare_class(xray)} flare (R{r}) at {t:%H:%M}"
            self.flare_until = t + timedelta(minutes=FLARE_WINDOW_MIN)
        precursor = self.flare_until is not None and t <= self.flare_until

        # 2b. proton trend (slope of log10 flux, decades per hour)
        slope, eta_s1 = self._proton_trend(t, p10)
        rising = slope is not None and slope >= PROTON_RISE_DECADES_H

        # 2c. CME arrival
        if speed is not None and bz is not None and speed >= CME_SPEED_KMS and bz <= CME_BZ_NT:
            self.cme_since = self.cme_since or t
        else:
            self.cme_since = None
        cme = self.cme_since is not None and t - self.cme_since >= timedelta(minutes=CME_SUSTAIN_MIN)

        # 3. fuse
        raw = 0
        if precursor:
            raw = 1
            reasons.append(f"{self.flare_note} — protons may follow (watch until {self.flare_until:%H:%M})")
        if rising:
            raw = max(raw, 2 if precursor else 1)
            when = f", S1 in ~{eta_s1:.0f} min" if eta_s1 is not None else ""
            reasons.append(f"protons rising x10 every {60 / slope:.0f} min (now {p10:.3g} pfu{when})")
        if cme:
            raw = max(raw, 1)
            reasons.append(f"CME arrived: solar wind {speed:.0f} km/s, Bz {bz:.0f} nT — geomagnetic storm coming")
        if g:
            raw = max(raw, 2 if g >= 4 else 1)
            reasons.append(f"geomagnetic storm G{g} (Kp {kp:g})")
        if s:
            raw = max(raw, 3 if s >= 3 else 2)
            reasons.append(f"solar radiation storm S{s} ({p10:.3g} pfu >= 10 MeV)")
        eva = self._on_eva(t)
        if eva and raw >= 1:
            raw = min(3, raw + 1)
            reasons.append("spacewalk under way — least shielding, level raised")

        # protons are the danger signal: without them the level is HELD (X-rays only add early warning)
        unknown = p10 is None
        if unknown:
            reasons.append("no fresh proton data — level held")

        # level: up at once, down only after SW_CALM_MIN of calm (and never down on missing data)
        old = self.level
        if raw >= self.level:
            self.level, self.calm_since = raw, None
        elif not unknown:
            self.calm_since = self.calm_since or t
            if t - self.calm_since >= timedelta(minutes=SW_CALM_MIN):
                self.level, self.calm_since = raw, None
            else:
                reasons.append(f"calmer, holding {SW_LEVELS[self.level].upper()} until "
                               f"{self.calm_since + timedelta(minutes=SW_CALM_MIN):%H:%M}")

        if not reasons:
            reasons.append("all quiet")

        # 4. actions
        actions = list(SW_LEVEL_ACTIONS[self.level])
        if (cme or g) and "comms_backup" not in actions:
            actions.append("comms_backup")
        return {"time": t, "day": mission_day(t), "level": self.level, "level_name": SW_LEVELS[self.level],
                "changed": self.level != old, "r": r, "s": s, "g": g, "xray_flux": xray, "proton_pfu": p10,
                "slope": slope, "eta_s1_min": eta_s1, "precursor": precursor, "cme": cme, "eva": eva,
                "reasons": reasons, "actions": actions}

    # ---------- helpers ----------
    def _proton_trend(self, t, p10):
        if p10 is None or p10 <= 0:
            return None, None
        self.protons.append((t, p10))
        while self.protons and t - self.protons[0][0] > timedelta(minutes=PROTON_TREND_MIN):
            self.protons.popleft()
        if len(self.protons) < 3 or p10 < PROTON_RISE_FLOOR:
            return None, None
        t0, p0 = self.protons[0]
        hours = (t - t0).total_seconds() / 3600
        if hours <= 0:
            return None, None
        slope = (math.log10(p10) - math.log10(p0)) / hours
        eta = None
        if slope > 0 and p10 < 10:
            eta = (1 - math.log10(p10)) / slope * 60        # minutes until 10 pfu (S1), if the climb continues
        return slope, eta

    def _on_eva(self, t):
        return mission_day(t) in self.eva_days and EVA_HOURS[0] <= hour_of(t) < EVA_HOURS[1]


def run_day(watch, snaps):
    """Feed one day of snapshots through a watcher. Returns all steps."""
    return [watch.process(s) for s in snaps]


def summarize_day(steps):
    """One day -> compact summary (for the radiation module, fusion, report, Earth packet).
    No snapshots -> None (no data, not a fake 'all clear')."""
    if not steps:
        return None
    peak = max(steps, key=lambda x: x["level"])
    first = {}
    for st in steps:
        for lv in range(1, st["level"] + 1):
            first.setdefault(SW_LEVELS[lv], st["time"])
    top = lambda k: max((st[k] for st in steps if st[k] is not None), default=None)
    return {"max_level": peak["level"], "max_level_name": peak["level_name"],
            "first_time": {k: v.strftime("%H:%M") for k, v in first.items()},
            "first_dt": first,
            "peak_r": top("r"), "peak_s": top("s"), "peak_g": top("g"),
            "peak_proton_pfu": top("proton_pfu"), "peak_flare": flare_class(top("xray_flux")),
            "cme": any(st["cme"] for st in steps),
            "peak_reasons": peak["reasons"][:3],
            "actions": [SW_ACTIONS[a] for a in peak["actions"]],
            "changes": [st for st in steps if st["changed"]]}
