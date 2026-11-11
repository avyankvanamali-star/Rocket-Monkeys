"""
THE SHARED 7-STEP CHECK — every module uses this.      (PSEUDOCODE.md section 4)

check_metric(astronaut, metric, new_value):
1. VALIDATE     quality bad?                     -> "ignored"
2. BASELINE     no baseline yet?                 -> "no baseline"
3. CHANGE       pct_change = (new - baseline) / baseline x 100
4. NOISE CHECK  |new - baseline| > MDC ?  moving in the BAD direction?
5. EXPECTED     (if a Shadow model exists) residual = new - predicted, too big?
6. PERSISTENCE  last 3 results all flagged?      -> persistent
7. STATUS       not flagged -> ok | flagged -> watch | flagged + persistent -> act
"""
from config.settings import METRICS, PERSIST_COUNT, RESIDUAL_LIMIT, STRICT_FACTOR


def check_metric(db, astronaut, metric, value, day, quality="good", prediction=None, strict=False):
    cfg = METRICS[metric]
    r = {"astronaut": astronaut, "day": day, "domain": cfg["domain"], "metric": metric,
         "value": value, "baseline": None, "pct_change": None, "mdc": None,
         "real_change": 0, "bad_direction": 0, "predicted": None, "residual": None,
         "resid_sd": None, "unexpected": 0, "flagged": 0, "persistent": 0,
         "status": "ok", "reason": ""}
    label = cfg["label"]

    # 1. VALIDATE
    if value is None or quality != "good":
        r["status"], r["reason"] = "ignored", f"{label}: bad or missing reading"
        db.save_result(r)
        return r

    # 2. BASELINE
    base = db.get_baseline(astronaut, metric)
    if base is None:
        r["status"], r["reason"] = "no baseline", f"{label}: no baseline yet"
        db.save_result(r)
        return r
    r["baseline"] = base

    # 3. CHANGE
    diff = value - base
    r["pct_change"] = round(diff / base * 100, 1) if base else None

    # 4. NOISE CHECK (stricter after a radiation event)
    mdc = cfg["mdc"] * (STRICT_FACTOR if strict else 1.0)
    r["mdc"] = round(mdc, 3)
    r["real_change"] = int(abs(diff) > mdc)
    r["bad_direction"] = int(diff > 0 if cfg["bad"] == "up" else diff < 0)

    # 5. EXPECTED (Shadow Self)
    if prediction:
        predicted, resid_sd = prediction
        residual = value - predicted
        bad_resid = residual > 0 if cfg["bad"] == "up" else residual < 0
        r.update(predicted=round(predicted, 2), residual=round(residual, 2), resid_sd=round(resid_sd, 2),
                 unexpected=int(abs(residual) > RESIDUAL_LIMIT * resid_sd and bad_resid))

    # 6. PERSISTENCE
    r["flagged"] = int((r["real_change"] and r["bad_direction"]) or r["unexpected"])
    previous = db.get_recent_results(astronaut, metric, PERSIST_COUNT - 1, before_day=day)
    r["persistent"] = int(bool(r["flagged"]) and len(previous) == PERSIST_COUNT - 1
                          and all(p["flagged"] for p in previous))

    # 7. STATUS + reason
    if not r["flagged"]:
        r["status"] = "ok"
    elif r["persistent"]:
        r["status"] = "act"
    else:
        r["status"] = "watch"

    pct = f" ({r['pct_change']:+.1f}%)" if r["pct_change"] is not None else ""
    parts = [f"{label} {value:g} vs baseline {base:g}{pct}",
             "beyond noise" if r["real_change"] else "within noise"]
    if r["predicted"] is not None:
        parts.append(f"expected {r['predicted']:g}" + (" -> UNEXPECTED" if r["unexpected"] else ""))
    if r["persistent"]:
        parts.append(f"{PERSIST_COUNT} checks in a row")
    if strict:
        parts.append("strict mode (recent radiation event)")
    r["reason"] = ", ".join(parts)

    db.save_result(r)
    return r


def check_measured(db, astronaut, day, metrics, shadow=None, strict=False):
    """Run the 7-step check on every metric in `metrics` that was measured today.
    Metrics in SHADOW_TARGETS also get a Shadow Self prediction (if one exists)."""
    from config.settings import SHADOW_TARGETS
    results = []
    for metric in metrics:
        value = db.get_value(astronaut, metric, day)
        if value is None:
            continue                                   # not measured today -> nothing to check
        prediction = None
        if shadow and metric in SHADOW_TARGETS:
            try:
                prediction = shadow.predict(db, astronaut, metric, day)
            except Exception:                          # noqa: BLE001  fallback: skip step 5
                prediction = None
        results.append(check_metric(db, astronaut, metric, value, day, prediction=prediction, strict=strict))
    return results


def module_result(domain, results, statuses=(), flags=(), notes=(), **extra):
    """Every module returns the same shape (Contract B)."""
    from config.settings import worst
    out = {"domain": domain, "status": worst([r["status"] for r in results] + list(statuses)),
           "results": results, "flags": set(flags), "notes": list(notes)}
    out.update(extra)
    return out
