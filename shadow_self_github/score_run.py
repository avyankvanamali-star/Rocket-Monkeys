"""
SCORECARD — did Shadow Self catch the problems we planted on purpose?

    python3 score_run.py              score the LAST run (reads shadow_self.db + data/answer_key.json)
    python3 score_run.py --seeds 10   make data + run the engine + score, for seeds 1..10,
                                      then average (takes the "luck" out of one random run)

What it counts
    events   : single planted problems (strap slip, solar storm, ...) caught on the right day?
    drifts   : slow problems caught at all? on which day? (earlier = better)
    false    : WATCH/ACT/URGENT alerts for healthy A1 that the story doesn't explain
    vs plain : first day a plain fixed limit (HRV 20% below baseline — a demo rule, not a medical one)
               would have fired, compared with Shadow Self's first heart alert
"""
import json
import os
import sqlite3
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(ROOT, "shadow_self.db")
KEY = os.path.join(ROOT, "data", "answer_key.json")
OUT = os.path.join(ROOT, "outputs")
REAL = ("watch", "act", "urgent")


def score_last_run(quiet=False):
    key = json.load(open(KEY))
    con = sqlite3.connect(DB)
    alerts = con.execute("SELECT astronaut, day, tier, key FROM alerts").fetchall()
    fired = {}                                     # (astronaut, key) -> sorted days
    for a, d, tier, k in alerts:
        fired.setdefault((a, k), []).append(d)

    def sensor_doubt(a, d):
        path = os.path.join(OUT, f"earth_summary_{a}_day{d}.json")
        return os.path.exists(path) and bool(json.load(open(path)).get("sensor_doubt"))

    # 1. single events
    events = []
    for e in key["events"]:
        ok = sensor_doubt(e["astronaut"], e["day"]) if e.get("sensor_doubt") \
            else e["day"] in fired.get((e["astronaut"], e["alert"]), [])
        events.append((e["name"], ok))

    # 2. slow drifts
    drifts = []
    for d in key["drifts"]:
        days = sorted(x for k in d["alerts"] for x in fired.get((d["astronaut"], k), []) if x >= d["starts"])
        drifts.append((d["name"], days[0] if days else None, d["starts"]))

    # 3. false alarms for healthy A1
    expected = key.get("expected_noise", {}).get("A1", {})
    false = [(d, k, t) for a, d, t, k in alerts
             if a == "A1" and t in REAL and k not in expected.get(str(d), [])]

    # 4. Shadow Self vs a plain fixed limit (A2 heart)
    base = con.execute("SELECT value FROM baselines WHERE astronaut='A2' AND metric='hrv_rmssd'").fetchone()
    plain = None
    if base:
        for d, v in con.execute("SELECT day, value FROM measurements WHERE astronaut='A2' AND metric='hrv_rmssd'"
                                " AND day > 0 AND quality='good' ORDER BY day"):
            if v < 0.8 * base[0]:
                plain = d
                break
    shadow = next((day for name, day, _ in drifts if name.startswith("Heart")), None)

    result = {"events_caught": sum(ok for _, ok in events), "events_total": len(events),
              "drifts_caught": sum(day is not None for _, day, _ in drifts), "drifts_total": len(drifts),
              "drift_days": {n: day for n, day, _ in drifts}, "false_alarms": len(false),
              "shadow_heart_day": shadow, "plain_limit_day": plain}
    if not quiet:
        print("\nSHADOW SELF SCORECARD (seed %s)\n" % key.get("seed") + "-" * 60)
        for n, ok in events:
            print(f"  {'CAUGHT' if ok else 'MISSED':7} {n}")
        for n, day, start in drifts:
            print(f"  {'CAUGHT' if day else 'MISSED':7} {n}" +
                  (f" — first alert day {day} (problem starts ~day {start})" if day else ""))
        print(f"\n  False alarms for healthy A1: {len(false)}")
        for d, k, t in false[:8]:
            print(f"     day {d}: {t} {k}")
        print(f"  Heart drift: Shadow Self alerted day {shadow}; plain 20% HRV limit would fire day "
              f"{plain if plain else 'never (within 30 days)'}")
        print(f"\n  TOTAL: events {result['events_caught']}/{result['events_total']}, "
              f"drifts {result['drifts_caught']}/{result['drifts_total']}, false alarms {len(false)}")
    return result


def many_seeds(n):
    rows = []
    for seed in range(1, n + 1):
        print(f"seed {seed}/{n}: making data + running engine ...", flush=True)
        subprocess.run([sys.executable, "generate_30day_data.py", str(seed)], cwd=ROOT, check=True,
                       capture_output=True)
        subprocess.run([sys.executable, "main.py"], cwd=ROOT, check=True, capture_output=True)
        r = score_last_run(quiet=True)
        rows.append(r)
        print(f"   events {r['events_caught']}/{r['events_total']}  drifts {r['drifts_caught']}/{r['drifts_total']}"
              f"  false alarms {r['false_alarms']}  heart: shadow day {r['shadow_heart_day']}"
              f" vs plain day {r['plain_limit_day']}", flush=True)
    ev = sum(r["events_caught"] for r in rows) / sum(r["events_total"] for r in rows)
    dr = sum(r["drifts_caught"] for r in rows) / sum(r["drifts_total"] for r in rows)
    fa = sum(r["false_alarms"] for r in rows) / len(rows)
    leads = [r["plain_limit_day"] - r["shadow_heart_day"] for r in rows
             if r["plain_limit_day"] and r["shadow_heart_day"]]
    print("\n" + "=" * 60 + f"\n  {n}-SEED SCORECARD\n" + "=" * 60)
    print(f"  Planted events caught : {ev:.0%}")
    print(f"  Slow drifts caught    : {dr:.0%}")
    print(f"  False alarms (A1)     : {fa:.1f} per 30-day run")
    if leads:
        print(f"  Heart drift warning   : {sum(leads) / len(leads):.1f} days earlier than a plain 20% limit "
              f"(on average, {len(leads)}/{n} runs where both fired)")
    never = sum(1 for r in rows if r["shadow_heart_day"] and not r["plain_limit_day"])
    if never:
        print(f"  In {never}/{n} runs the plain limit never fired at all — Shadow Self still caught it")


if __name__ == "__main__":
    if "--seeds" in sys.argv:
        many_seeds(int(sys.argv[sys.argv.index("--seeds") + 1]))
    else:
        score_last_run()
