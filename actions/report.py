"""
DAILY REPORT — printed in the terminal.                 (PSEUDOCODE.md section 15)
FALLBACK: a domain with no score shows "--" and "NO DATA" instead of crashing.
"""
LABEL = {"ok": "OK", "info": "info", "watch": "WATCH", "act": "ACT", "urgent": "URGENT", "no data": "NO DATA"}
DOMAINS = ("radiation", "muscle", "bone", "sans", "cardio")


def _line(domain, mod, status):
    if status == "ok":
        return "normal"
    if status == "no data" and not mod["results"]:
        return "nothing measured today" if not mod["notes"] or "failed" not in mod["notes"][0] else mod["notes"][0]
    if domain == "radiation":
        b = mod.get("budget", {})
        main = f"{b.get('career_msv', b.get('total_msv', 0))} mSv career dose ({b.get('used_pct', 0)}%), projected {b.get('projected_msv', 0)} mSv"
        return (mod["notes"] or [main])[0] if status != "ok" else main
    flagged = [r["reason"] for r in mod["results"] if r["flagged"]]
    notes = [n for n in mod["notes"] if not n.startswith(("estimated", "context", "stricter"))
             and "risk LOW" not in n]
    return (notes + flagged + ["score lowered by cross-system rules"])[0]


def budget_line(b):
    """One line: how much more radiation this astronaut can safely take."""
    spare = b["spare_msv"]
    extra = (f"SPARE {spare:.0f} mSv (~{b['spare_days']:.0f} extra mission days)" if spare > 0 else
             f"NO SPARE ({spare:.0f} mSv)")
    chance = "" if b.get("storm_chance_24h") is None else f", storm chance 24 h {b['storm_chance_24h']:.0f}%"
    return (f"  Radiation budget: {b['career_msv']:.1f} of {b['limit_msv']:.0f} mSv used (earlier flights "
            f"{b['prior_msv']:.0f}) | {b['left_msv']:.0f} left | {b['reserved_msv']:.0f} reserved for "
            f"{b['days_left']} days left | {b['margin_msv']:.0f} safety margin | {extra}\n"
            f"                    [{b['feed']}{chance}]")


def print_report(astronaut, day, mods, fused, action, sw=None):
    score = lambda s: "--" if s is None else f"{s:.0f}"
    print(f"\n  Astronaut {astronaut} — Day {day}   [{LABEL.get(action['tier'], action['tier'])}]")
    print("  " + "-" * 68)
    for d in DOMAINS:
        st = fused["statuses"][d]
        print(f"  {d.capitalize():<10}{score(fused['scores'][d]):>4}  {LABEL[st]:<7} {_line(d, mods[d], st)[:72]}")
    b = mods["radiation"].get("budget", {})
    print(f"  {'OVERALL':<10}{score(fused['overall']):>4}  {LABEL[fused['overall_status']]:<7} "
          f"(radiation used: {b.get('career_msv', b.get('total_msv', 0))} mSv = {b.get('used_pct', 0)}% of career limit)")
    if "spare_msv" in b:
        print(budget_line(b))

    if sw and sw["max_level_name"] != "green":
        times = " ".join(f"{k.upper()} {v}" for k, v in sw["first_time"].items())
        peak = " ".join(f"{k}{sw['peak_' + k.lower()]}" for k in ("S", "R", "G") if sw["peak_" + k.lower()])
        print(f"  Space wx  {sw['max_level_name'].upper():<8} {times}  | peak {peak} flare {sw['peak_flare']}")
        if sw.get("lead_min") is not None:
            print(f"            satellites warned {sw['lead_min']} min before the crew dosimeter "
                  f"({sw['lead_level'].upper()} level)")
    if fused["rules"]:
        print("  Rules fired: " + ", ".join(r[0] for r in fused["rules"]))
    for a in action["alerts"]:
        if a["time"]:
            print(f"  ! {a['time'][11:16]} {LABEL.get(a['tier'], a['tier']):<6} {a['message']}")
    if fused["sensor_doubt"]:
        print("  Low confidence: " + "; ".join(fused["sensor_doubt"]))
    for p in action["plan"]:
        print(f"  Plan day {p['day']}: {p['action']}" + (f"  ({p['note']})" if p["note"] else ""))
