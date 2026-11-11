"""
FALLBACKS — the system never stops because one part broke.   (PSEUDOCODE.md section 16)

safe(step, do_this, fallback):
    try do_this
    it breaks? -> write the error to outputs/errors.log
               -> remember it for the end-of-run summary
               -> return the fallback instead, keep going
"""
import os
import traceback
from datetime import datetime

from storage.db import ROOT

ERRORS = []
LOG_PATH = os.path.join(ROOT, "outputs", "errors.log")


def safe(step, do_this, fallback=None):
    try:
        return do_this()
    except Exception as e:                       # noqa: BLE001 — catching everything is the point
        ERRORS.append(f"{step}: {type(e).__name__}: {e}")
        try:
            os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
            with open(LOG_PATH, "a") as f:
                f.write(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {step}\n{traceback.format_exc()}\n")
        except OSError:
            pass                                 # can't even write the log -> still keep going
        return fallback


def fallback_module(domain):
    """What a module returns if it crashed: 'no data', never a fake 'healthy'."""
    return {"domain": domain, "status": "no data", "results": [], "flags": set(),
            "notes": ["module failed — fallback used (see outputs/errors.log)"], "score": None,
            "budget": {"today_msv": 0, "total_msv": 0, "used_pct": 0, "burn_msv_day": 0, "projected_msv": 0}}
