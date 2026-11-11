"""
SPACE WEATHER DATA — read data/space_weather.csv into 5-minute snapshots.

File format (same as shadow_self_github/format_space_weather.py writes from real NOAA data):
    time,kind,value,source
    2027-03-20T13:15:00,xray_flux,2.1e-04,SIM GOES

kinds used: xray_flux (W/m2), proton_flux_10mev (pfu), solar_wind_speed (km/s), bz (nT), kp (0-9)
Other kinds (proton_flux_100mev, s_scale_now, ...) are kept out quietly.

Each snapshot carries forward the last value of every kind until it gets too old
(config SW_STALE_MIN: Kp lasts 3 h, the rest 30 min) -> then it becomes None (unknown).
Bad rows are skipped and counted, never a crash.
"""
import csv
import os
from collections import defaultdict
from datetime import datetime, timedelta

from config.settings import SW_STALE_DEFAULT_MIN, SW_STALE_MIN, mission_day

KINDS = ("xray_flux", "proton_flux_10mev", "solar_wind_speed", "bz", "kp")


def load_space_weather(path, log=None):
    """Return {mission day: [snapshot, ...]} sorted by time. Missing file -> {}."""
    log = log if log is not None else []
    if not os.path.exists(path):
        log.append(f"no space weather file ({os.path.basename(path)})")
        return {}
    by_time = defaultdict(dict)
    bad = 0
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            kind = (row.get("kind") or "").strip()
            if kind not in KINDS:
                continue
            try:
                t = datetime.fromisoformat(row["time"].strip().replace("Z", "")[:19])
                v = float(row["value"])
                if v != v:                       # NaN
                    raise ValueError
            except (KeyError, ValueError, AttributeError):
                bad += 1
                continue
            by_time[t][kind] = v
    if bad:
        log.append(f"space weather: {bad} bad row(s) skipped")

    days, last = defaultdict(list), {}
    for t in sorted(by_time):
        for kind, v in by_time[t].items():
            last[kind] = (t, v)
        snap = {"time": t}
        for kind in KINDS:
            seen = last.get(kind)
            limit = timedelta(minutes=SW_STALE_MIN.get(kind, SW_STALE_DEFAULT_MIN))
            snap[kind] = seen[1] if seen and t - seen[0] <= limit else None
        days[mission_day(t)].append(snap)
    return dict(days)
