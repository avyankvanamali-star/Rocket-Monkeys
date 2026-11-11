"""
TRAIN SHADOW NET (PyTorch)

1. build the table (one row per astronaut-day)
2. use HEALTHY days only: pre-mission + mission days 1-45 (learn "normal you", never "sick you")
3. fit the straight line first (least squares) — every network starts from it
4. train 5 small networks from different random starts. For each one:
       hold 15% of the days aside -> guess -> measure how wrong (loss) -> nudge weights -> repeat
       keep the version that did best on the held-aside days (stops it memorising)
5. usual error size = measured on the HELD-ASIDE days (honest: days that member never learned from)
6. save all 5 -> ml/shadow_net.pt

Run:  python3 ml/train_shadow_net.py                        (simulator data, ~30 s, no GPU needed)
      python3 ml/train_shadow_net.py --data path/to/file.csv  (any CSV in the Shadow Self format)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import torch  # noqa: E402
import torch.nn as nn  # noqa: E402

import shadow_net as sn  # noqa: E402
from build_dataset import ROOT, build, check, data_path  # noqa: E402

TRAIN_UNTIL_DAY = 45          # healthy period used for learning
MEMBERS = 5                   # networks in the ensemble
EPOCHS = 1500
LEARNING_RATE = 0.003
WEIGHT_DECAY = 0.01           # gentle pressure to keep the curves small = less memorising
HOLD_ASIDE = 0.15


def train_member(seed, Xn, yn, line_w):
    torch.manual_seed(seed)
    model = sn.HybridNet()
    model.start_from_line(line_w)
    order = torch.randperm(len(Xn), generator=torch.Generator().manual_seed(seed))
    cut = int(len(order) * (1 - HOLD_ASIDE))
    fit, hold = order[:cut], order[cut:]
    opt = torch.optim.AdamW(model.curves.parameters(), lr=LEARNING_RATE, weight_decay=WEIGHT_DECAY)
    best, best_state = float("inf"), None
    for _ in range(EPOCHS):
        model.train()
        loss = nn.functional.mse_loss(model(Xn[fit]), yn[fit])   # how wrong are the guesses?
        opt.zero_grad()
        loss.backward()                                          # which way should each weight move?
        opt.step()                                               # move them a little
        model.eval()
        with torch.no_grad():
            held = nn.functional.mse_loss(model(Xn[hold]), yn[hold]).item()
        if held < best:
            best, best_state = held, {k: v.clone() for k, v in model.state_dict().items()}
    model.load_state_dict(best_state)
    return model.eval(), hold, best


def main():
    path = data_path()
    print(f"Data: {os.path.relpath(path, ROOT)}")
    if not check(path):
        sys.exit("Can't train on this data (see above). Simulator data:  python3 simulator/run.py")
    rows, baselines = build(path)
    train_rows = [r for r in rows if r["day"] <= TRAIN_UNTIL_DAY]
    if len(train_rows) < 60:
        sys.exit(f"Only {len(train_rows)} healthy days — too few to train a network. Generate more data first.")
    print(f"Training on {len(train_rows)} healthy astronaut-days (pre-mission + mission days 1-{TRAIN_UNTIL_DAY})")

    X, y = sn.to_tensors(train_rows)
    xm, xs = sn.fit_scaler(X)
    ym, ys = sn.fit_scaler(y)
    Xn, yn = (X - xm) / xs, (y - ym) / ys
    line_w = sn.LinearModel().fit(Xn, yn).w

    members, held_errors = [], []
    for seed in range(MEMBERS):
        model, hold, best = train_member(seed, Xn, yn, line_w)
        members.append(model)
        with torch.no_grad():
            held_errors.append((model(Xn[hold]) - yn[hold]) * ys)       # errors in real units
        print(f"  network {seed + 1}/{MEMBERS} trained — held-aside error {best:.3f}")

    resid_sd = torch.cat(held_errors).std(0).tolist()
    sn.save(sn.Ensemble(members), (xm, xs, ym, ys), resid_sd, baselines,
            {"train_until_day": TRAIN_UNTIL_DAY, "rows": len(train_rows), "members": MEMBERS,
             "data": os.path.relpath(path, ROOT)})
    print(f"\nSaved ml/shadow_net.pt — usual error: HRV ±{resid_sd[0]:.2f} ms, resting HR ±{resid_sd[1]:.2f} bpm")
    extra = "" if "--data" not in sys.argv else f" --data {os.path.relpath(path, ROOT)}"
    print(f"Next:  python3 ml/evaluate.py{extra}")


if __name__ == "__main__":
    main()
