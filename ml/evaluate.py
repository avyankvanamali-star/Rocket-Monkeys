"""
EVALUATE — is the PyTorch model actually better? Two tests, both on data it never trained on.

TEST 1  ACCURACY: every healthy mission day after training (unseen), plus the "hard days" (A1: bad sleep +
        high CO2). Average error, PyTorch vs the straight-line model.

TEST 2  EARLY WARNING: every mission day, 3 methods try to catch the planted problems:
    Threshold  : HRV below baseline by more than the noise limit (MDC), or resting HR above it,
                 3 days in a row — what most health apps do
    Linear     : Shadow Self with the straight-line model
    PyTorch    : Shadow Self with the neural network
    Shadow rule: gap = actual - expected, in "usual error" units, for HRV (down = bad) and resting HR
                 (up = bad); alarm when the 7-day average gap >= 1.0 for 3 days in a row
    Scored against the answer key: events.csv in the SAME folder as the data
        caught early = alarm after a planted heart drift starts (heart_model_should_alarm = yes)
        false alarm  = alarm anywhere the heart model should stay quiet
    No events.csv (real or friend's data without an answer key)? TEST 2 is skipped.

Writes: outputs/ml_scorecard.txt  +  residuals.csv next to the data (day by day, for charts)
Run:    python3 ml/evaluate.py                        (simulator data)
        python3 ml/evaluate.py --data path/to/file.csv
"""
import csv
import math
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import torch  # noqa: E402

import shadow_net as sn  # noqa: E402
from build_dataset import ROOT, build, data_path  # noqa: E402

WINDOW, LEVEL, IN_A_ROW = 7, 1.0, 3
OUT_TXT = os.path.join(ROOT, "outputs", "ml_scorecard.txt")


def read_answer_key(data_file):
    """events.csv next to the data -> (drift astronaut, drift start, list of 'hard' heart periods).
    Fallback: no file or unreadable -> (None, None, [])."""
    path = os.path.join(os.path.dirname(data_file), "events.csv")
    drift, hard = (None, None), []
    try:
        with open(path, newline="") as f:
            for e in csv.DictReader(f):
                start, end = int(e["start_day"]), int(e["end_day"])
                if e.get("heart_model_should_alarm", "").strip().lower() == "yes" and drift[0] is None:
                    drift = (e["astronaut"], start)
                elif "cardio" in e.get("system", "") and e["astronaut"] != "ALL":
                    hard.append((e["astronaut"], start, end, e.get("what", "")))
    except (OSError, KeyError, ValueError):
        pass
    return drift[0], drift[1], hard


def mae(pred, y):
    return (pred - y).abs().mean(0).tolist()


def alarm_days(series):
    """series: list of (day, badness). Returns the days an alarm is active."""
    out, streak, window = [], 0, []
    for day, bad in series:
        window = (window + [bad])[-WINDOW:]
        avg = sum(window) / len(window)
        streak = streak + 1 if (len(window) == WINDOW and avg >= LEVEL) else 0
        if streak >= IN_A_ROW:
            out.append(day)
    return out


def threshold_alarm_days(rows, mdc_hrv, mdc_rhr):
    out, streak = [], 0
    for r in rows:
        bad = r["hrv_dev"] < -mdc_hrv or r["rhr_dev"] > mdc_rhr
        streak = streak + 1 if bad else 0
        if streak >= IN_A_ROW:
            out.append(r["day"])
    return out


def main():
    bundle = sn.load()
    if bundle is None:
        sys.exit("No trained model yet. Run:  python3 ml/train_shadow_net.py")
    data_file = data_path()
    rows, baselines = build(data_file)
    if not rows:
        sys.exit("No usable astronaut-days in this data. Check it with:  python3 ml/build_dataset.py --data <file>")
    DRIFT_ASTRONAUT, DRIFT_START, hard_periods = read_answer_key(data_file)
    out_csv = os.path.join(os.path.dirname(data_file), "residuals.csv")
    xm, xs, ym, ys = bundle["scalers"]
    sd_net = torch.tensor(bundle["resid_sd"])

    # the straight-line model, trained on exactly the same healthy days
    train_rows = [r for r in rows if r["day"] <= bundle["info"]["train_until_day"]]
    Xt, yt = sn.to_tensors(train_rows)
    lin = sn.LinearModel().fit((Xt - xm) / xs, (yt - ym) / ys)
    lin_pred_train = lin.predict((Xt - xm) / xs) * ys + ym
    sd_lin = (yt - lin_pred_train).std(0)

    def preds(subset):
        X, y = sn.to_tensors(subset)
        return y, sn.predict(bundle, subset), lin.predict((X - xm) / xs) * ys + ym

    lines = []
    say = lambda s="": (print(s), lines.append(s))

    # ---------------- TEST 1: accuracy ----------------
    # every mission day after training where the heart was healthy (A3's drift days left out)
    test = [r for r in rows if r["day"] > bundle["info"]["train_until_day"]
            and not (r["astronaut"] == DRIFT_ASTRONAUT and r["day"] >= DRIFT_START)]
    hard = [r for r in rows if any(r["astronaut"] == a and s <= r["day"] <= e for a, s, e, _ in hard_periods)]
    hard_name = f"{len(hard)} hard days ({hard_periods[0][3][:22]})," if hard_periods else ""
    say("=" * 66)
    say("TEST 1 — ACCURACY: average error on days the models never trained on")
    say("=" * 66)
    say(f"{'':58}{'Linear':>9}{'PyTorch':>9}{'better':>9}")
    wins = []
    for label, subset in ((f"All {len(test)} healthy days,", test), (hard_name, hard)):
        if not subset:
            continue                                   # nothing to test here -> skip, don't crash
        y, p_net, p_lin = preds(subset)
        e_net, e_lin = mae(p_net, y), mae(p_lin, y)
        for i, unit in enumerate(["HRV (ms)", "resting HR (bpm)"]):
            say(f"{label + ' ' + unit:58}{e_lin[i]:9.2f}{e_net[i]:9.2f}{(1 - e_net[i] / e_lin[i]) * 100:8.0f}%")
        wins.append(e_net[0] <= e_lin[0] and e_net[1] <= e_lin[1])
    if not wins:
        sys.exit(f"No days after training day {bundle['info']['train_until_day']} to test on. Need more mission days.")
    net_wins = wins[0]                               # the big test decides

    # ---------------- TEST 2: early warning ----------------
    mission = [r for r in rows if r["day"] >= 1]
    y, p_net, p_lin = preds(mission)
    pre = [r for r in rows if r["day"] <= 0]
    def sd(key):                                   # day-to-day spread before the mission
        vals = [r[key] for r in pre]
        mean = sum(vals) / len(vals)
        return math.sqrt(sum((v - mean) ** 2 for v in vals) / (len(vals) - 1))
    mdc_hrv, mdc_rhr = 2.77 * sd("hrv_dev"), 2.77 * sd("rhr_dev")   # MDC = 1.96 x sqrt(2) x spread

    per_a = defaultdict(lambda: {"rows": [], "net": [], "lin": []})
    residual_rows = []
    for i, r in enumerate(mission):
        bad_net = (-(y[i, 0] - p_net[i, 0]) / sd_net[0] + (y[i, 1] - p_net[i, 1]) / sd_net[1]).item() / 2
        bad_lin = (-(y[i, 0] - p_lin[i, 0]) / sd_lin[0] + (y[i, 1] - p_lin[i, 1]) / sd_lin[1]).item() / 2
        d = per_a[r["astronaut"]]
        d["rows"].append(r)
        d["net"].append((r["day"], bad_net))
        d["lin"].append((r["day"], bad_lin))
        b = baselines[r["astronaut"]]
        residual_rows.append({"astronaut": r["astronaut"], "day": r["day"], "hrv": r["hrv"],
                              "hrv_expected_pytorch": round(b["hrv"] + p_net[i, 0].item(), 2),
                              "hrv_expected_linear": round(b["hrv"] + p_lin[i, 0].item(), 2),
                              "hrv_baseline": round(b["hrv"], 2), "rhr": r["rhr"],
                              "rhr_expected_pytorch": round(b["rhr"] + p_net[i, 1].item(), 2),
                              "badness_pytorch": round(bad_net, 3), "badness_linear": round(bad_lin, 3)})

    results = {}
    for a, d in sorted(per_a.items()):
        results[a] = {"Threshold": threshold_alarm_days(d["rows"], mdc_hrv, mdc_rhr),
                      "Linear": alarm_days(d["lin"]), "PyTorch": alarm_days(d["net"])}

    say()
    if DRIFT_ASTRONAUT is None or DRIFT_ASTRONAUT not in results:
        say("TEST 2 skipped — no answer key (events.csv with a planted heart drift) next to this data.")
        return finish(lines, residual_rows, out_csv, say, net_wins)
    last_day = max(r["day"] for r in mission)
    say("=" * 66)
    say(f"TEST 2 — EARLY WARNING over mission days 1-{last_day} (planted heart drift: {DRIFT_ASTRONAUT} from day {DRIFT_START})")
    say("=" * 66)
    say(f"{'Method':12}{'Caught ' + DRIFT_ASTRONAUT + ' drift':>20}{'False-alarm days':>20}")
    summary = {}
    for method in ("Threshold", "Linear", "PyTorch"):
        hits = [d for d in results[DRIFT_ASTRONAUT][method] if d >= DRIFT_START]
        caught = f"day {hits[0]} (+{hits[0] - DRIFT_START} days)" if hits else "missed"
        false = sum(len([d for d in days if not (a == DRIFT_ASTRONAUT and d >= DRIFT_START)])
                    for a, r in results.items() for m, days in r.items() if m == method)
        summary[method] = (hits[0] - DRIFT_START if hits else None, false)
        say(f"{method:12}{caught:>20}{false:>20}")

    say()
    say("Where the false alarms happened (astronaut: first day, number of days):")
    for method in ("Threshold", "Linear", "PyTorch"):
        parts = []
        for a, r in sorted(results.items()):
            days = [d for d in r[method] if not (a == DRIFT_ASTRONAUT and d >= DRIFT_START)]
            if days:
                parts.append(f"{a}: from day {days[0]}, {len(days)} days")
        say(f"  {method:10} " + ("; ".join(parts) if parts else "none"))

    t_lead, net_lead = summary["Threshold"][0], summary["PyTorch"][0]
    if net_lead is not None and t_lead is not None:
        lead = f"  PyTorch Shadow Self caught the hidden drift {t_lead - net_lead} days before the threshold alarm."
    elif net_lead is not None:
        lead = "  PyTorch Shadow Self caught the hidden drift; the threshold method never did."
    else:
        lead = "  PyTorch Shadow Self did not catch the hidden drift."
    finish(lines, residual_rows, out_csv, say, net_wins, lead)


def finish(lines, residual_rows, out_csv, say, net_wins, lead=None):
    say()
    say("VERDICT")
    say(f"  More accurate than the straight-line model: {'YES' if net_wins else 'NO'}")
    if lead:
        say(lead)
    say("  Keep PyTorch as the Shadow Self model." if net_wins else
        "  Keep the straight-line model for now (PyTorch was not more accurate).")
    os.makedirs(os.path.dirname(OUT_TXT), exist_ok=True)
    with open(OUT_TXT, "w") as f:
        f.write("\n".join(lines) + "\n")
    if residual_rows:
        with open(out_csv, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(residual_rows[0]))
            w.writeheader()
            w.writerows(residual_rows)
    print(f"\nSaved outputs/ml_scorecard.txt and {os.path.relpath(out_csv, ROOT)}")


if __name__ == "__main__":
    main()
