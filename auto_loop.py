"""
AUTO LOOP — the continuous training flow, hands-free.

Each round, by itself:
    1. make a NEW simulated 180-day mission (new random seed -> different data every round)
    2. train the PyTorch Shadow Self model on it            (ml/train_shadow_net.py)
    3. test it against the answer key                        (ml/evaluate.py)
    4. keep the results + the best model so far
    5. delete the raw data (data_sim/) — results and models are kept

Run (from the Rocket Monkeys folder, with PyTorch installed — see setup_env.sh):
    .venv/bin/python auto_loop.py                 5 rounds, then stop
    .venv/bin/python auto_loop.py --rounds 20     20 rounds
    .venv/bin/python auto_loop.py --rounds 0      forever
    .venv/bin/python auto_loop.py --every 30      wait 30 minutes between rounds
Stop any time: press Ctrl + C, or create a file named STOP in this folder (it stops after the current round).

Kept in ml/loop/:
    history.csv                 one line per round: seed, caught on day, false alarms, beat the straight line?
    round_<n>_seed_<s>.txt      the full scorecard of that round
    best_shadow_net.pt          the best model so far (earliest catch, then fewest false alarms)
"""
import csv
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
from simulator import run as sim  # noqa: E402  (Timothy's simulator — used as-is, just with a new seed)

LOOP = os.path.join(ROOT, "ml", "loop")
HISTORY = os.path.join(LOOP, "history.csv")
DATA_SIM = os.path.join(ROOT, "data_sim")
MODEL = os.path.join(ROOT, "ml", "shadow_net.pt")
SCORECARD = os.path.join(ROOT, "outputs", "ml_scorecard.txt")
STOP = os.path.join(ROOT, "STOP")
COLUMNS = ["round", "time", "seed", "pytorch_caught_day", "pytorch_days_late", "pytorch_false_alarms",
           "linear_caught_day", "linear_false_alarms", "threshold_caught_day", "threshold_false_alarms",
           "more_accurate_than_line", "best_so_far"]


def option(name, default):
    args = sys.argv[1:]
    return int(args[args.index(name) + 1]) if name in args else default


def make_data(seed):
    """Timothy's simulator with a NEW seed (his main() always uses seed 42)."""
    os.makedirs(DATA_SIM, exist_ok=True)
    rows = sim.simulate(seed)
    with open(os.path.join(DATA_SIM, "sim_daily.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=sim.FIELDS)
        w.writeheader()
        w.writerows(rows)
    with open(os.path.join(DATA_SIM, "events.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["astronaut", "start_day", "end_day", "system", "what", "heart_model_should_alarm"])
        w.writerows(sim.EVENTS)


def run_step(script):
    p = subprocess.run([sys.executable, script], cwd=ROOT, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"{script} failed:\n{(p.stdout + p.stderr)[-800:]}")


def read_scorecard(text):
    """Pull the TEST 2 table + verdict out of ml_scorecard.txt."""
    out = {}
    for method in ("Threshold", "Linear", "PyTorch"):
        m = re.search(rf"^{method}\s+(?:day (\d+) \(\+(\d+) days\)|missed)\s+(\d+)\s*$", text, re.M)
        if m:
            out[method] = (int(m.group(1)) if m.group(1) else None,
                           int(m.group(2)) if m.group(2) else None, int(m.group(3)))
    out["better"] = "YES" in (re.search(r"More accurate than the straight-line model: (\w+)", text) or [""])[0]
    return out


def is_better(new, best):
    """Earliest catch wins; tie -> fewer false alarms. A miss never beats a catch."""
    if best is None:
        return True
    (n_late, n_false), (b_late, b_false) = new, best
    if n_late is None:
        return False
    if b_late is None or n_late < b_late:
        return True
    return n_late == b_late and n_false < b_false


def load_history():
    if not os.path.exists(HISTORY):
        return [], None
    with open(HISTORY, newline="") as f:
        rows = list(csv.DictReader(f))
    best = None
    for r in rows:
        if r["best_so_far"] == "yes":
            late = int(r["pytorch_days_late"]) if r["pytorch_days_late"] else None
            best = (late, int(r["pytorch_false_alarms"]))
    return rows, best


def main():
    rounds, every = option("--rounds", 5), option("--every", 0)
    os.makedirs(LOOP, exist_ok=True)
    history, best = load_history()
    n = len(history)
    print(f"AUTO LOOP — {'forever' if rounds == 0 else rounds} round(s). Stop: Ctrl+C or create a file named STOP.")
    done = 0
    while rounds == 0 or done < rounds:
        if os.path.exists(STOP):
            os.remove(STOP)
            print("STOP file found — stopping.")
            break
        n, done = n + 1, done + 1
        seed = 1000 + n                                  # a new, repeatable seed every round
        print(f"\nround {n}  (seed {seed})")
        try:
            print("  1/4 making a new 180-day mission ...", flush=True)
            make_data(seed)
            print("  2/4 training PyTorch model ...", flush=True)
            run_step(os.path.join("ml", "train_shadow_net.py"))
            print("  3/4 testing against the answer key ...", flush=True)
            run_step(os.path.join("ml", "evaluate.py"))
            text = open(SCORECARD).read()
            s = read_scorecard(text)
            shutil.copy(SCORECARD, os.path.join(LOOP, f"round_{n}_seed_{seed}.txt"))
            pt = s.get("PyTorch", (None, None, 0))
            new_best = is_better((pt[1], pt[2]), best)
            if new_best:
                best = (pt[1], pt[2])
                shutil.copy(MODEL, os.path.join(LOOP, "best_shadow_net.pt"))
            row = {"round": n, "time": f"{datetime.now():%Y-%m-%d %H:%M}", "seed": seed,
                   "pytorch_caught_day": pt[0] or "missed", "pytorch_days_late": "" if pt[1] is None else pt[1],
                   "pytorch_false_alarms": pt[2],
                   "linear_caught_day": (s.get("Linear") or (None,))[0] or "missed",
                   "linear_false_alarms": (s.get("Linear") or (0, 0, ""))[2],
                   "threshold_caught_day": (s.get("Threshold") or (None,))[0] or "missed",
                   "threshold_false_alarms": (s.get("Threshold") or (0, 0, ""))[2],
                   "more_accurate_than_line": "yes" if s["better"] else "no",
                   "best_so_far": "yes" if new_best else ""}
            new_file = not os.path.exists(HISTORY)
            with open(HISTORY, "a", newline="") as f:
                w = csv.DictWriter(f, fieldnames=COLUMNS)
                if new_file:
                    w.writeheader()
                w.writerow(row)
            print(f"  4/4 PyTorch caught the drift on day {row['pytorch_caught_day']}, "
                  f"{row['pytorch_false_alarms']} false alarms" + ("  <- best so far, model kept" if new_best else ""))
        except Exception as e:                           # one bad round never stops the loop
            print(f"  round {n} failed, skipping it: {e}")
        finally:
            shutil.rmtree(DATA_SIM, ignore_errors=True)  # raw data deleted; results + models kept
        if every and (rounds == 0 or done < rounds):
            print(f"  waiting {every} min ...", flush=True)
            time.sleep(every * 60)
    print(f"\nDone. Results: ml/loop/history.csv   Best model: ml/loop/best_shadow_net.pt")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        shutil.rmtree(DATA_SIM, ignore_errors=True)
        print("\nStopped (Ctrl+C). Results so far are in ml/loop/history.csv")
