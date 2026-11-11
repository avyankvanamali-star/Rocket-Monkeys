"""
GET SPACE WEATHER — downloads radiation and solar storm forecast data from NOAA.

SOURCE: NOAA Space Weather Prediction Center (SWPC), the official US space weather service.
        Free, no account or key needed. https://www.swpc.noaa.gov

WHAT IT DOWNLOADS (5 feeds)
    scales        noaa-scales.json            radiation storm level now (S0-S5) + chance of a storm
                                              in each of the next 3 days, plus solar flare (radio
                                              blackout) chances
    protons       integral-protons-1-day.json GOES satellite proton flux, last 24 h, every 5 min.
                                              This is the radiation itself: >=10 MeV flux >= 10 pfu
                                              means an S1 solar radiation storm is under way
    xrays         xrays-1-day.json            GOES satellite X-ray flux, last 24 h: solar flares as
                                              they happen (big flares often come before proton storms)
    probabilities solar_probabilities.json    NOAA forecast: chance of C/M/X flares and of a proton
                                              event in each of the next 3 days
    alerts        alerts.json                 NOAA's official alerts and warnings (last few days)

WHERE IT SAVES (raw, unchanged, so nothing is lost)
    space_weather_raw/<feed>/<UTC time>.json   one file per download, history builds up
    space_weather_raw/fetch_log.csv            when each feed was tried, ok or what went wrong
Then run format_space_weather.py to turn these into clean tables.

RUN
    python3 get_space_weather.py                 # download once
    python3 get_space_weather.py --every 30      # keep downloading every 30 minutes (Ctrl+C to stop)
    python3 get_space_weather.py --out somewhere # save somewhere else
NOAA updates most feeds every 5 minutes and forecasts daily; every 15-30 minutes is plenty.

If a feed is down or the internet is off, that feed is skipped and logged; the others still download.
Built-in Python only.
"""
import argparse
import csv
import json
import os
import time
import urllib.request
from datetime import datetime, timezone

BASE = "https://services.swpc.noaa.gov"
FEEDS = {
    "scales": f"{BASE}/products/noaa-scales.json",
    "protons": f"{BASE}/json/goes/primary/integral-protons-1-day.json",
    "xrays": f"{BASE}/json/goes/primary/xrays-1-day.json",
    "probabilities": f"{BASE}/json/solar_probabilities.json",
    "alerts": f"{BASE}/products/alerts.json",
}
KEEP_FILES = 2000          # per feed; oldest raw files are deleted past this (about 6 weeks at every 30 min)


def download(url):
    req = urllib.request.Request(url, headers={"User-Agent": "shadow-self-space-weather/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode("utf-8"))   # must be valid JSON, or it counts as a failure
    if not data:
        raise ValueError("empty response")
    return data


def fetch_all(out):
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
    os.makedirs(out, exist_ok=True)
    log_path = os.path.join(out, "fetch_log.csv")
    new_log = not os.path.exists(log_path)
    ok = 0
    with open(log_path, "a", newline="") as log:
        w = csv.writer(log)
        if new_log:
            w.writerow(["fetched_utc", "feed", "status", "detail"])
        for name, url in FEEDS.items():
            try:
                data = download(url)
                folder = os.path.join(out, name)
                os.makedirs(folder, exist_ok=True)
                path = os.path.join(folder, f"{stamp}.json")
                with open(path + ".tmp", "w") as f:
                    json.dump(data, f)
                os.replace(path + ".tmp", path)               # never leaves a half-written file
                old = sorted(os.listdir(folder))[:-KEEP_FILES]
                for o in old:
                    os.remove(os.path.join(folder, o))
                ok += 1
                n = len(data) if isinstance(data, list) else len(data.keys())
                w.writerow([stamp, name, "ok", f"{n} records"])
                print(f"  ok    {name:<14} {n} records")
            except Exception as e:  # noqa: BLE001  network down, site changed, bad JSON -> keep going
                w.writerow([stamp, name, "failed", f"{type(e).__name__}: {e}"])
                print(f"  FAIL  {name:<14} {type(e).__name__}: {e}")
    print(f"{stamp}: {ok} of {len(FEEDS)} feeds saved in {out}/")
    return ok


def main():
    ap = argparse.ArgumentParser(description="Download radiation + solar storm forecast data from NOAA SWPC.")
    ap.add_argument("--out", default="space_weather_raw", help="folder for the raw downloads")
    ap.add_argument("--every", type=float, default=0, help="repeat every N minutes (0 = once)")
    args = ap.parse_args()
    while True:
        fetch_all(args.out)
        if args.every <= 0:
            break
        try:
            time.sleep(args.every * 60)
        except KeyboardInterrupt:
            print("Stopped.")
            break


if __name__ == "__main__":
    main()
