"""
INGESTION — turn one raw reading into one clean reading.   (PSEUDOCODE.md section 2)

take one raw reading
check it has: astronaut, time, metric, value, unit      → missing? reject
is the metric known in config?                          → no? reject
convert unit if needed                                  → can't? reject
look up its domain, work out the mission day
value inside possible range?                            → no? quality = "bad"
hand the clean reading to storage
"""
import csv
from datetime import datetime

from config.settings import METRICS, UNIT_CONVERSIONS, mission_day

REQUIRED = ("astronaut", "time", "metric", "value", "unit")


def ingest(raw, log):
    """Return a clean reading dict, or None (and a note in `log`) if rejected.
    Fallback: anything unexpected about a row -> reject that row, keep going."""
    try:
        return _ingest(raw, log)
    except Exception as e:  # noqa: BLE001
        log.append(f"rejected (unreadable row: {type(e).__name__}): {str(dict(raw))[:80]}")
        return None


def _ingest(raw, log):
    missing = [k for k in REQUIRED if raw.get(k) in (None, "")]
    if missing:
        log.append(f"rejected (missing {', '.join(missing)}): {dict(raw)}")
        return None

    metric = raw["metric"]
    if metric not in METRICS:
        log.append(f"rejected (unknown metric '{metric}')")
        return None
    cfg = METRICS[metric]

    try:
        value = float(raw["value"])
        dt = datetime.fromisoformat(raw["time"])
    except ValueError:
        log.append(f"rejected (bad value/time): {dict(raw)}")
        return None

    unit = raw["unit"]
    if unit != cfg["unit"]:
        factor = UNIT_CONVERSIONS.get((unit, cfg["unit"]))
        if factor is None:
            log.append(f"rejected (can't convert {unit} -> {cfg['unit']} for {metric})")
            return None
        log.append(f"converted {metric}: {value} {unit} -> {value * factor} {cfg['unit']}")
        value, unit = value * factor, cfg["unit"]

    lo, hi = cfg["range"]
    sensor_says_bad = (raw.get("quality") or "good") == "bad"
    quality = "bad" if sensor_says_bad or not (lo <= value <= hi) else "good"

    return {"astronaut": raw["astronaut"], "time": dt.isoformat(), "day": mission_day(dt),
            "domain": cfg["domain"], "metric": metric, "value": value, "unit": unit,
            "source": raw.get("source") or "", "quality": quality, "detail": raw.get("detail") or ""}


def ingest_csv(path, log):
    """Read a whole CSV file and return the clean readings."""
    clean = []
    try:
        with open(path, newline="") as f:
            for raw in csv.DictReader(f):
                reading = ingest(raw, log)
                if reading:
                    clean.append(reading)
    except OSError as e:
        log.append(f"rejected (could not read file {path}: {e})")
    return clean
