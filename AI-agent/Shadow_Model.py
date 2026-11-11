import torch
import torch.nn as nn

FEATURES = ["heart_rate", "hrv", "bp_sys", "bone_density", "muscle_mass", "radiation_dose"]

class ShadowSelf(nn.Module):
    def __init__(self, n=len(FEATURES)):
        super().__init__()
        self.encoder = nn.Sequential(nn.Linear(n, 8), nn.ReLU(), nn.Linear(8, 3))
        self.decoder = nn.Sequential(nn.Linear(3, 8), nn.ReLU(), nn.Linear(8, n))
    def forward(self, x):
        return self.decoder(self.encoder(x))

def train(baseline):                        # baseline: tensor [days, features] of normal data
    mean, std = baseline.mean(0), baseline.std(0) + 1e-6
    x = (baseline - mean) / std
    model = ShadowSelf()
    opt = torch.optim.Adam(model.parameters(), lr=1e-2)
    for _ in range(500):
        loss = ((model(x) - x) ** 2).mean()
        opt.zero_grad(); loss.backward(); opt.step()
    with torch.no_grad():
        threshold = ((model(x) - x) ** 2).mean(1).max() * 1.5
    return model, mean, std, threshold

def check(model, mean, std, threshold, reading):   # reading: tensor [features]
    x = (reading - mean) / std
    with torch.no_grad():
        err = (model(x) - x) ** 2
    score = err.mean().item()
    worst = FEATURES[err.argmax().item()]
    return {"anomaly": score > threshold.item(), "score": round(score, 3), "most_off": worst}
