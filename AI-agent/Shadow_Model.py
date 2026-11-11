"""
SHADOW MODEL (PyTorch) — learns what each astronaut's NORMAL day looks like (their "shadow self"),
then scores how far any day drifts from it.
 
The rule checks look at one metric at a time. This model looks at ALL metrics together, so it can
catch several small changes that add up before any single one crosses its rule threshold.
 
How it works:
  1. Turn each day into a row of "% change vs baseline" for every metric (missing = 0 = at baseline).
  2. Train a small autoencoder on that astronaut's first week of the mission (their baseline),
     skipping any of those days that had a flagged check.
  3. A day the model can't rebuild well = unusual for this person. The metrics it rebuilt worst
     are reported as the "drivers".
 
Models are cached per astronaut, so it only retrains when new days are added.
"""
import torch
import torch.nn as nn
 
TRAIN_DAYS = 7      # first N mission days = what "normal" looks like for this astronaut
MIN_DAYS = 4        # need at least this many days before the model says anything
EPOCHS = 400
 
_cache = {}
 
 
class ShadowNet(nn.Module):
    def __init__(self, n):
        super().__init__()
        h, z = max(2, n // 2), max(1, n // 4)
        self.enc = nn.Sequential(nn.Linear(n, h), nn.ReLU(), nn.Linear(h, z))
        self.dec = nn.Sequential(nn.Linear(z, h), nn.ReLU(), nn.Linear(h, n))
 
    def forward(self, x):
        return self.dec(self.enc(x))
 
 
def _table(rows):
    """rows from the `results` table -> (days, metrics, matrix of % change, which days had a flagged check)."""
    days = sorted({r["day"] for r in rows})
    metrics = sorted({r["metric"] for r in rows})
    di = {d: i for i, d in enumerate(days)}
    mi = {m: i for i, m in enumerate(metrics)}
    X = torch.zeros(len(days), len(metrics))
    flagged = {d: False for d in days}
    for r in rows:
        if r["value"] is not None and r["baseline"]:
            X[di[r["day"]], mi[r["metric"]]] = (r["value"] - r["baseline"]) / abs(r["baseline"]) * 100
        if r["flagged"]:
            flagged[r["day"]] = True
    return days, metrics, X, flagged
 
 
def _train(X, normal_idx):
    torch.manual_seed(0)                                   # same data -> same answer every time
    base = X[normal_idx]
    mean = base.mean(0)
    std = base.std(0, unbiased=False) + 1.0                # +1% so very steady metrics don't blow up
    xb = (base - mean) / std
    net = ShadowNet(X.shape[1])
    opt = torch.optim.Adam(net.parameters(), lr=0.01)
    for _ in range(EPOCHS):
        loss = ((net(xb) - xb) ** 2).mean()
        opt.zero_grad()
        loss.backward()
        opt.step()
    with torch.no_grad():
        errs = ((net(xb) - xb) ** 2).mean(1)
    limit = errs.max() * 2 + 0.25      # worst normal day x2 (+ a floor) — few training days, so leave room for noise
    return net, mean, std, limit
 
 
def check_day(rows, astronaut, day, label=lambda m: m):
    """Short text verdict for one astronaut-day."""
    if not rows:
        return f"Shadow model: no measurements for {astronaut}."
    days, metrics, X, flagged = _table(rows)
    if len(days) < MIN_DAYS:
        return f"Shadow model: only {len(days)} days for {astronaut}, needs {MIN_DAYS}+ to learn their normal."
    if day not in days:
        return f"Shadow model: no data for {astronaut} on day {day}."
 
    early = list(range(min(TRAIN_DAYS, len(days) - 1)))           # the mission's first days = their baseline
    calm = [i for i in early if not flagged[days[i]]]
    normal = calm if len(calm) >= 3 else early
    key = (astronaut, days[-1], len(metrics))
    if key not in _cache:
        _cache[key] = _train(X, normal)
    net, mean, std, limit = _cache[key]
 
    i = days.index(day)
    x = (X[i] - mean) / std
    with torch.no_grad():
        err = (net(x) - x) ** 2
    ratio = err.mean().item() / limit.item()
    verdict = "UNUSUAL" if ratio > 1.5 else "EDGING" if ratio > 0.8 else "NORMAL"
    top = err.argsort(descending=True)[:3].tolist()
    drivers = ", ".join(f"{label(metrics[j])} ({X[i, j].item():+.1f}% vs baseline)" for j in top)
    return (f"Shadow model (PyTorch, learned {astronaut}'s normal from {len(normal)} days): day {day} is {verdict} "
            f"— {ratio:.1f}x the normal-day limit (1.5+ = unusual for this person). "
            f"Biggest drivers: {drivers}.")
 
