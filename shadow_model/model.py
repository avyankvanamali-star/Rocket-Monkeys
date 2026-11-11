"""
SHADOW MODEL — "what SHOULD this astronaut's body read today?"   (PSEUDOCODE.md section 12)

LEARN   : collect pre-mission days: (sleep, workload, CO2) -> (resting HR / HRV)
          fit a simple straight-line formula (linear regression)
          remember the typical residual size
PREDICT : plug today's inputs into the formula -> expected value
          not enough data -> "no prediction" (pipeline skips step 5)
RELEARN : every 14 days refit using only days that were "ok"
          (so the model never learns bad days as normal)

Note: radiation dose is not an input yet — on the ground it barely changes,
so there is nothing to learn from. Add it once in-flight "ok" days exist.
"""
import math

from config.settings import (ASTRONAUTS, MIN_TRAIN_DAYS, RELEARN_EVERY,
                             SHADOW_INPUTS, SHADOW_TARGETS)


def _solve(A, b):
    """Solve A x = b with Gaussian elimination (small systems only)."""
    n = len(A)
    M = [row[:] + [b[i]] for i, row in enumerate(A)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(M[r][col]))
        M[col], M[pivot] = M[pivot], M[col]
        for r in range(n):
            if r != col and M[col][col] != 0:
                f = M[r][col] / M[col][col]
                M[r] = [a - f * c for a, c in zip(M[r], M[col])]
    return [M[i][n] / M[i][i] for i in range(n)]


class LinearModel:
    def fit(self, X, y, ridge=0.1):
        k = len(X[0])
        self.mu = [sum(x[j] for x in X) / len(X) for j in range(k)]
        self.sd = [math.sqrt(sum((x[j] - self.mu[j]) ** 2 for x in X) / len(X)) or 1.0 for j in range(k)]
        Z = [[1.0] + self._scale(x) for x in X]
        A = [[sum(z[i] * z[j] for z in Z) + (ridge if i == j and i > 0 else 0) for j in range(k + 1)]
             for i in range(k + 1)]
        b = [sum(z[i] * yy for z, yy in zip(Z, y)) for i in range(k + 1)]
        self.w = _solve(A, b)
        resid = [yy - self.predict(x) for x, yy in zip(X, y)]
        dof = max(len(X) - k - 1, 1)
        self.resid_sd = max(math.sqrt(sum(r * r for r in resid) / dof), 0.5)
        return self

    def _scale(self, x):
        return [(x[j] - self.mu[j]) / self.sd[j] for j in range(len(x))]

    def predict(self, x):
        return sum(w * z for w, z in zip(self.w, [1.0] + self._scale(x)))


class ShadowBank:
    """One small model per astronaut per target metric."""

    def __init__(self):
        self.models = {}

    def _inputs(self, db, astronaut, day):
        vals = [db.get_value(astronaut, m, day) for m in SHADOW_INPUTS]
        return None if any(v is None for v in vals) else vals

    def _fit(self, db, astronaut, target, days):
        X, y = [], []
        for d in days:
            x, t = self._inputs(db, astronaut, d), db.get_value(astronaut, target, d)
            if x is not None and t is not None:
                X.append(x)
                y.append(t)
        if len(X) >= MIN_TRAIN_DAYS:
            self.models[(astronaut, target)] = LinearModel().fit(X, y)
        return len(X)

    def train(self, db, astronauts=ASTRONAUTS):
        """LEARN from pre-mission days (day <= 0)."""
        report = {}
        for a in astronauts:
            for t in SHADOW_TARGETS:
                n = self._fit(db, a, t, range(-60, 1))
                m = self.models.get((a, t))
                report[(a, t)] = (n, round(m.resid_sd, 2) if m else None)
        return report

    def relearn(self, db, astronaut, today):
        """RELEARN every 14 days using pre-mission + in-flight days that were 'ok'."""
        if today % RELEARN_EVERY:
            return
        for t in SHADOW_TARGETS:
            ok_days = [d for d in range(-60, today + 1)
                       if d <= 0 or (db.get_latest_result(astronaut, t, d) or {}).get("status") == "ok"]
            self._fit(db, astronaut, t, ok_days)

    def predict(self, db, astronaut, target, day):
        """Return (predicted value, typical residual size) or None."""
        model = self.models.get((astronaut, target))
        x = self._inputs(db, astronaut, day)
        if model is None or x is None:
            return None
        return model.predict(x), model.resid_sd
