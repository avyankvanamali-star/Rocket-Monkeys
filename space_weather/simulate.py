"""
SIMULATED SPACE WEATHER — makes data/space_weather.csv for the 30-day demo.

Looks like what NOAA / NASA dashboards show (GOES X-rays + protons, DSCOVR solar wind, Kp),
every 5 minutes (Kp every 3 hours). Same file format as the real NOAA formatter, so a real
download can replace it.

Planted solar story (matches the dosimeter spike in generate_30day_data.py):
    day 5   M6 flare 10:40 -> small proton event (S1, ~35 pfu) while A2 is on a SPACEWALK
            -> expect A1 WARNING, A2 CRITICAL (spacewalk raises the level)
    day 12  M5.5 flare 15:05, NO protons follow -> expect WATCH that clears by itself
    day 20  X2.1 flare 13:15 -> big proton event (S3, ~2,500 pfu peak 14:30)
            -> expect WATCH 13:15, WARNING before S1, CRITICAL at S3 — all BEFORE the
               crew dosimeter spike at 14:00 (that's the lead time we show)
    day 21  the CME from day 20 arrives ~15:00 -> fast wind + southward Bz -> Kp 7 (G3) evening
All numbers are made up for testing.

Run:  python3 -m space_weather.simulate          (seed 42)
"""
import csv
import math
import os
import random
import sys
from datetime import datetime, timedelta

LAUNCH = datetime(2027, 3, 1)
DAYS = 30
STEP_MIN = 5
SOURCE = "SIMULATED GOES/DSCOVR"
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "space_weather.csv")


def at(day, hhmm):
    h, m = map(int, hhmm.split(":"))
    return LAUNCH + timedelta(days=day - 1, hours=h, minutes=m)


# flares: (peak time, peak flux W/m2)
FLARES = [(at(5, "10:40"), 6.0e-5), (at(12, "15:05"), 5.5e-5), (at(20, "13:15"), 2.1e-4)]
# proton events: (start, peak time, peak pfu, minutes per 10x drop afterwards)
PROTON_EVENTS = [(at(5, "10:55"), at(5, "12:10"), 35, 60), (at(20, "13:25"), at(20, "14:30"), 2500, 100)]
# CME: (shock arrival, southward Bz start, Bz end)
CME = (at(21, "15:00"), at(21, "15:20"), at(22, "02:00"))
KP_STORM = {at(21, "18:00"): 7, at(21, "21:00"): 7, at(22, "00:00"): 6, at(22, "03:00"): 5}

BG_XRAY = -6.3        # log10 W/m2 (quiet: B/C class)
BG_PROTON = -0.5      # log10 pfu (~0.3 pfu)


def xray(t):
    flux = 10 ** (BG_XRAY + random.gauss(0, 0.08))
    for peak, top in FLARES:
        dt = (t - peak).total_seconds() / 60
        if -10 <= dt < 0:
            flux += top * (1 + dt / 10)                 # 10-min rise
        elif dt >= 0:
            flux += top * math.exp(-dt / 25)            # ~25-min decay
    return flux


def protons(t):
    logp = BG_PROTON + random.gauss(0, 0.04)
    for start, peak, top, per_decade in PROTON_EVENTS:
        if t < start:
            continue
        lpeak = math.log10(top)
        if t <= peak:
            f = (t - start).total_seconds() / (peak - start).total_seconds()
            ev = BG_PROTON + (lpeak - BG_PROTON) * f    # straight line in log = exponential growth
        else:
            ev = lpeak - (t - peak).total_seconds() / 60 / per_decade
        logp = max(logp, ev + random.gauss(0, 0.03))
    return 10 ** logp


def solar_wind(t):
    shock, bz_on, bz_off = CME
    speed = 400 + random.gauss(0, 25)
    bz = random.gauss(0, 2.5)
    if shock <= t < shock + timedelta(hours=20):
        speed = 780 - (t - shock).total_seconds() / 3600 * 12 + random.gauss(0, 20)
    if bz_on <= t < bz_off:
        bz = -18 + random.gauss(0, 2)
    return speed, bz


def kp(t):
    return KP_STORM.get(t, random.choice([1, 1, 2, 2, 2, 3]))


def rows():
    out = []
    t, end = LAUNCH, LAUNCH + timedelta(days=DAYS)
    while t < end:
        stamp = t.isoformat()
        speed, bz = solar_wind(t)
        out += [{"time": stamp, "kind": "xray_flux", "value": f"{xray(t):.3e}", "source": SOURCE},
                {"time": stamp, "kind": "proton_flux_10mev", "value": f"{protons(t):.4g}", "source": SOURCE},
                {"time": stamp, "kind": "solar_wind_speed", "value": f"{speed:.0f}", "source": SOURCE},
                {"time": stamp, "kind": "bz", "value": f"{bz:.1f}", "source": SOURCE}]
        if t.hour % 3 == 0 and t.minute == 0:
            out.append({"time": stamp, "kind": "kp", "value": f"{kp(t):g}", "source": SOURCE})
        t += timedelta(minutes=STEP_MIN)
    return out


def main(seed=42, path=OUT):
    random.seed(seed + 1000)              # own stream: doesn't change the crew data for the same seed
    data = rows()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["time", "kind", "value", "source"])
        w.writeheader()
        w.writerows(data)
    print(f"  wrote data/space_weather.csv: {len(data):,} rows ({DAYS} days, simulated)")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 42)
