"""
SHADOW NET — the PyTorch "expected you" model.

    inputs : tonight's sleep, last night's sleep, workload, CO2, sodium, fluids   (6 numbers)
    output : expected HRV and resting HR, as distance from this astronaut's baseline (2 numbers)

DESIGN (chosen by testing — see README in this folder):
    HYBRID   = straight line  +  a small neural network that learns only the CURVES the line misses
               (the network starts at zero, so the model starts exactly as good as the straight line)
    ENSEMBLE = 5 hybrids trained from different random starts, answers averaged
               (one small network on ~300 days is jumpy; the average of 5 is steady)

Also here: the plain linear model it is compared against, scaling helpers, save/load.
"""
import os

import torch
import torch.nn as nn

from build_dataset import FEATURES, TARGETS

HERE = os.path.dirname(os.path.abspath(__file__))
MODEL_PATH = os.path.join(HERE, "shadow_net.pt")
HIDDEN = 16


class HybridNet(nn.Module):
    """prediction = straight line(x) + small network(x)"""

    def __init__(self, n_in=len(FEATURES), n_out=len(TARGETS), hidden=HIDDEN):
        super().__init__()
        self.line = nn.Linear(n_in, n_out)
        self.curves = nn.Sequential(nn.Linear(n_in, hidden), nn.Tanh(), nn.Linear(hidden, n_out))

    def start_from_line(self, w):
        """Copy the least-squares straight line in; make the network's output start at exactly zero."""
        with torch.no_grad():
            self.line.bias.copy_(w[0])
            self.line.weight.copy_(w[1:].T)
            self.curves[2].weight.zero_()
            self.curves[2].bias.zero_()

    def forward(self, x):
        return self.line(x) + self.curves(x)


class Ensemble(nn.Module):
    def __init__(self, members):
        super().__init__()
        self.members = nn.ModuleList(members)

    def forward(self, x):
        return torch.stack([m(x) for m in self.members]).mean(0)


# ---------------- scaling: every input/output becomes "how many standard deviations from average" ----------------
def to_tensors(rows):
    X = torch.tensor([[r[f] for f in FEATURES] for r in rows], dtype=torch.float32)
    y = torch.tensor([[r.get(t, 0.0) for t in TARGETS] for r in rows], dtype=torch.float32)
    return X, y


def fit_scaler(t):
    mean, std = t.mean(0), t.std(0)
    return mean, torch.where(std > 0, std, torch.ones_like(std))


# ---------------- the simple model it is compared against ----------------
class LinearModel:
    """Straight-line fit (least squares) on the same inputs — what Shadow Self uses today."""

    def fit(self, Xs, ys):
        A = torch.cat([torch.ones(len(Xs), 1), Xs], 1)
        self.w = torch.linalg.lstsq(A, ys).solution
        return self

    def predict(self, Xs):
        return torch.cat([torch.ones(len(Xs), 1), Xs], 1) @ self.w


# ---------------- save / load ----------------
def save(model, scalers, resid_sd, baselines, info, path=MODEL_PATH):
    torch.save({"members": [m.state_dict() for m in model.members], "scalers": scalers, "resid_sd": resid_sd,
                "baselines": baselines, "features": FEATURES, "targets": TARGETS, "info": info}, path)


def load(path=MODEL_PATH):
    """The saved model bundle, or None if nothing is trained yet (fallback: keep the linear model)."""
    if not os.path.exists(path):
        return None
    try:
        bundle = torch.load(path, weights_only=False)
        members = []
        for state in bundle["members"]:
            m = HybridNet()
            m.load_state_dict(state)
            members.append(m)
        bundle["model"] = Ensemble(members).eval()
        return bundle
    except Exception as e:  # noqa: BLE001  broken / old file -> behave as if untrained
        print(f"  ! could not load {os.path.basename(path)} ({e}) — retrain with ml/train_shadow_net.py")
        return None


def predict(bundle, rows):
    """Expected HRV / resting HR deviation from baseline for each row, in real units (ms, bpm)."""
    X, _ = to_tensors(rows)
    xm, xs, ym, ys = bundle["scalers"]
    with torch.no_grad():
        return bundle["model"]((X - xm) / xs) * ys + ym
