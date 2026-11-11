"""
BUILD DATASET — CSV (one reading per row) -> table (one row per astronaut per day).

    CSV (long)                          TABLE (wide)
    A3, day 101, sleep_hours, 6.4  ->   astronaut day | sleep sleep_prev load co2 sodium fluids | hrv_dev rhr_dev
    A3, day 101, hrv_rmssd, 41.2        A3        101 |  6.4    7.1      93   2900  3100  2.4   |  -3.8    +1.2
    ...

INPUTS (what the model is allowed to look at) = things that EXPLAIN heart changes:
    tonight's sleep, last night's sleep, workload, CO2 while sleeping, sodium, fluids
TARGETS (what it predicts) = how far HRV and resting HR are from that astronaut's own baseline
    (deviation from baseline lets ONE model work for the whole crew)

Not used on purpose:
    - yesterday's HRV: a slow hidden drift would leak in through it and the model would "explain" it away
    - mission day: same reason — the model must not learn "it's normal to get worse over time"
    - radiation dose: storm doses are far outside anything in training (the radiation module handles it)

Run:  python3 ml/build_dataset.py                       -> data_sim/train_table.csv (simulator data)
      python3 ml/build_dataset.py --data path/to/file.csv  -> check + build from any CSV (e.g. a friend's)
"""
import csv
import os
import sys
from collections import defaultdict
from datetime import date, datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SIM_CSV = os.path.join(ROOT, "data_sim", "sim_daily.csv")
TABLE_CSV = os.path.join(ROOT, "data_sim", "train_table.csv")
LAUNCH = date(2027, 3, 1)

FEATURES = ["sleep_hours", "sleep_prev", "resistance_load_pct", "co2_sleep", "sodium", "fluids"]
TARGETS = ["hrv_dev", "rhr_dev"]
NEEDED = ["sleep_hours", "resistance_load_pct", "co2_sleep", "sodium", "fluids", "hrv_rmssd", "resting_hr"]


def data_path():
    """--data <file.csv> on the command line, otherwise the simulator's data."""
    args = sys.argv[1:]
    if "--data" in args:
        i = args.index("--data")
        if i + 1 < len(args):
            return os.path.abspath(args[i + 1])
        sys.exit("--data needs a file path, e.g.  --data data_friend/mission.csv")
    return SIM_CSV


def mission_day(time_str):
    return (datetime.fromisoformat(time_str).date() - LAUNCH).days + 1


def read_long(path=SIM_CSV):
    """{(astronaut, day): {metric: value}} — bad or unreadable rows are skipped, never crash."""
    days = defaultdict(dict)
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            try:
                if (r.get("quality") or "good") != "good":
                    continue
                days[(r["astronaut"], mission_day(r["time"]))][r["metric"]] = float(r["value"])
            except (KeyError, ValueError):
                continue
    return days


def build(path=SIM_CSV):
    """Return (rows, baselines). Each row = one astronaut-day with all FEATURES and TARGETS."""
    days = read_long(path)
    # baseline = average of pre-mission days (day <= 0)
    sums = defaultdict(lambda: [0.0, 0.0, 0])
    for (a, d), m in days.items():
        if d <= 0 and "hrv_rmssd" in m and "resting_hr" in m:
            s = sums[a]
            s[0] += m["hrv_rmssd"]; s[1] += m["resting_hr"]; s[2] += 1
    baselines = {a: {"hrv": s[0] / s[2], "rhr": s[1] / s[2]} for a, s in sums.items() if s[2]}

    rows = []
    for (a, d), m in sorted(days.items()):
        prev = days.get((a, d - 1), {})
        if a not in baselines or any(k not in m for k in NEEDED) or "sleep_hours" not in prev:
            continue                                    # incomplete day -> skip it (fallback, no crash)
        rows.append({"astronaut": a, "day": d,
                     "sleep_hours": m["sleep_hours"], "sleep_prev": prev["sleep_hours"],
                     "resistance_load_pct": m["resistance_load_pct"], "co2_sleep": m["co2_sleep"],
                     "sodium": m["sodium"], "fluids": m["fluids"],
                     "hrv": m["hrv_rmssd"], "rhr": m["resting_hr"],
                     "hrv_dev": m["hrv_rmssd"] - baselines[a]["hrv"],
                     "rhr_dev": m["resting_hr"] - baselines[a]["rhr"]})
    return rows, baselines


def check(path):
    """Print what's in a CSV and what's missing. Returns True if it can be used for training."""
    if not os.path.exists(path):
        print(f"  ! file not found: {path}")
        return False
    days = read_long(path)
    if not days:
        print("  ! no readable rows (needs columns: astronaut,time,metric,value,unit)")
        return False
    crew = sorted({a for a, _ in days})
    all_days = [d for _, d in days]
    print(f"  {len(crew)} astronauts ({', '.join(crew)}), days {min(all_days)} to {max(all_days)}")
    pre = sum(1 for _, d in days if d <= 0)
    ok = True
    for metric in NEEDED:
        have = sum(1 for m in days.values() if metric in m)
        mark = "ok" if have else "MISSING"
        ok &= bool(have)
        print(f"    {metric:22} {have:5} days  {mark}")
    if pre == 0:
        print("  ! no pre-mission days (day 0 or earlier) -> no baselines. Mission day 1 = 2027-03-01.")
        ok = False
    return ok


def main():
    path = data_path()
    print(f"Data: {os.path.relpath(path, ROOT)}")
    if not check(path):
        sys.exit("Fix the data above, then run again.")
    rows, baselines = build(path)
    cols = ["astronaut", "day"] + FEATURES + ["hrv", "rhr"] + TARGETS
    with open(TABLE_CSV, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: (round(v, 3) if isinstance(v, float) else v) for k, v in r.items()})
    print(f"{len(rows)} astronaut-days -> data_sim/train_table.csv")
    for a, b in baselines.items():
        print(f"  {a} baseline: HRV {b['hrv']:.1f} ms, resting HR {b['rhr']:.1f} bpm")


if __name__ == "__main__":
    main()
