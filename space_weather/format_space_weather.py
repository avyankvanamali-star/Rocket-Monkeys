"""
FORMAT SPACE WEATHER — turns the raw NOAA downloads into clean, ready-to-use tables.

INPUT:  space_weather_raw/   (made by get_space_weather.py; every download is used, so history builds up)

OUTPUT (folder space_weather_clean/, all times UTC):
    forecast_3day.csv   one row per forecast day: chance of a solar radiation storm (S1+), of a
                        proton event, of M and X class flares, of radio blackouts. issued_utc = when
                        the newest forecast for that day was downloaded.
    observed.csv        every 5 min: GOES proton flux (>=10 and >=100 MeV, pfu), X-ray flux and
                        flare class (A/B/C/M/X). Proton flux is the radiation itself.
    alerts.csv          NOAA alerts and warnings, with a plain category (radiation storm, flare, ...)
    summary.txt         plain-language status: now, next 3 days, active radiation alerts, data age
    space_weather.csv   the Shadow Self engine format (time,kind,value,source). Also copied into
                        data/ (the engine folder; or --engine PATH), merged
                        with what is there, no duplicates.

READING THE NUMBERS
    proton flux >=10 MeV:  10 pfu = S1 minor, 100 = S2, 1,000 = S3, 10,000 = S4, 100,000 = S5
    flare class: C small, M medium, X large. X flares are the ones most often followed by proton storms.

RUN
    python3 format_space_weather.py
    python3 format_space_weather.py --raw space_weather_raw --out space_weather_clean --engine path/to/data
A bad or unexpected file is skipped and listed; it never stops the run. Built-in Python only.
"""
import argparse
import csv
import json
import os
import re
from datetime import datetime, timedelta, timezone

S_LEVELS = [(100000, 5), (10000, 4), (1000, 3), (100, 2), (10, 1)]   # >=10 MeV pfu -> S level
CATEGORIES = [("radiation storm", r"proton|radiation storm|PX"), ("solar flare", r"x-ray|radio blackout|XM|XX"),
              ("geomagnetic storm", r"geomagnetic|K-index|kp"), ("electron", r"electron"),
              ("radio burst", r"radio (emission|burst)|type ii|type iv"), ("other", r".")]
ENGINE_FIELDS = ["time", "kind", "value", "source"]
SOURCE = "NOAA SWPC"
problems = []


# ---------------- reading raw files ----------------
def snapshots(raw, feed):
    """[(fetch time, data)] oldest first; unreadable files are skipped and listed."""
    folder = os.path.join(raw, feed)
    out = []
    if not os.path.isdir(folder):
        problems.append(f"no downloads for '{feed}' yet")
        return out
    for name in sorted(os.listdir(folder)):
        if not name.endswith(".json"):
            continue
        try:
            t = datetime.strptime(name[:-5], "%Y-%m-%dT%H-%M-%SZ")
            with open(os.path.join(folder, name)) as f:
                out.append((t, json.load(f)))
        except (ValueError, OSError) as e:
            problems.append(f"skipped {feed}/{name}: {e}")
    return out


def num(x):
    try:
        v = float(x)
        return v if v == v else None
    except (TypeError, ValueError):
        return None


def utc(s):
    """NOAA time text -> 'YYYY-MM-DDTHH:MM:SS' (UTC, no zone letter, as the engine expects)."""
    s = str(s).strip().replace("Z", "").replace(" ", "T")
    return datetime.fromisoformat(s[:19]).isoformat(timespec="seconds")


def flare_class(flux):
    if flux is None or flux <= 0:
        return ""
    for letter, base in (("X", 1e-4), ("M", 1e-5), ("C", 1e-6), ("B", 1e-7)):
        if flux >= base:
            return f"{letter}{flux / base:.1f}"
    return f"A{flux / 1e-8:.1f}"


def s_level(pfu):
    return next((lvl for limit, lvl in S_LEVELS if pfu is not None and pfu >= limit), 0)


# ---------------- each feed ----------------
def read_scales(raw):
    """Storm level now + chance of S1+ storm and radio blackouts for each of the next 3 days."""
    forecast, engine = {}, []
    for fetched, data in snapshots(raw, "scales"):
        try:
            now = data.get("0", {})
            issued = fetched.isoformat(timespec="seconds")
            level = num((now.get("S") or {}).get("Scale"))
            if level is not None:
                engine.append({"time": issued, "kind": "s_scale_now", "value": f"{level:g}", "source": SOURCE})
            for k in ("1", "2", "3"):
                d = data.get(k) or {}
                day = (d.get("DateStamp") or (fetched.date() + timedelta(days=int(k))).isoformat())[:10]
                s_prob = num((d.get("S") or {}).get("Prob"))
                r = d.get("R") or {}
                forecast[(issued, day)] = {"s1_storm_pct": s_prob, "r1_r2_pct": num(r.get("MinorProb")),
                                           "r3_plus_pct": num(r.get("MajorProb"))}
                if k == "1" and s_prob is not None:
                    engine.append({"time": issued, "kind": "s1_prob_24h", "value": f"{s_prob:g}", "source": SOURCE})
        except (AttributeError, TypeError, ValueError) as e:
            problems.append(f"scales {fetched}: unexpected format ({e})")
    return forecast, engine


def read_probabilities(raw):
    """NOAA daily forecast (issued 22:00 UTC): flare and proton event chances. The record's date is the
    first forecast day, so day 1 = that date, day 2 = next day, day 3 = the day after."""
    out = {}
    for fetched, data in snapshots(raw, "probabilities"):
        for rec in data if isinstance(data, list) else []:
            try:
                issued = datetime.fromisoformat(str(rec["date"])[:19])
                for k in (1, 2, 3):
                    day = (issued.date() + timedelta(days=k - 1)).isoformat()
                    out[(fetched.isoformat(timespec="seconds"), day)] = {
                        "proton_event_pct": num(rec.get(f"10mev_protons_{k}_day")),
                        "m_flare_pct": num(rec.get(f"m_class_{k}_day")),
                        "x_flare_pct": num(rec.get(f"x_class_{k}_day"))}
            except (KeyError, TypeError, ValueError) as e:
                problems.append(f"probabilities {fetched}: unexpected record ({e})")
    return out


def read_series(raw, feed, wanted):
    """GOES 5-minute data -> {time: {column: flux}} for the energies in `wanted`."""
    out = {}
    for fetched, data in snapshots(raw, feed):
        for rec in data if isinstance(data, list) else []:
            col = wanted.get(rec.get("energy"))
            flux = num(rec.get("flux"))
            if col and flux is not None and flux >= 0:
                try:
                    out.setdefault(utc(rec["time_tag"]), {})[col] = flux
                except (KeyError, ValueError):
                    pass
    return out


def read_alerts(raw):
    out = {}
    for fetched, data in snapshots(raw, "alerts"):
        for rec in data if isinstance(data, list) else []:
            msg = str(rec.get("message", ""))
            try:
                issued = utc(rec["issue_datetime"])
            except (KeyError, ValueError):
                continue
            code = re.search(r"Message Code:\s*(\S+)", msg)
            head = re.search(r"^\s*((?:CONTINUED |EXTENDED |CANCEL )?(?:ALERT|WARNING|WATCH|SUMMARY)[^\n]*)", msg, re.M)
            code = code.group(1) if code else str(rec.get("product_id", ""))
            text = f"{code} {head.group(1) if head else msg[:200]}"
            cat = next(name for name, pat in CATEGORIES if re.search(pat, text, re.I))
            out[(issued, code)] = {"issued_utc": issued, "code": code, "category": cat,
                                   "headline": re.sub(r"\s+", " ", head.group(1) if head else msg[:160]).strip()}
    return sorted(out.values(), key=lambda r: r["issued_utc"])


# ---------------- writing ----------------
def write_csv(path, fields, rows):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path + ".tmp", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    os.replace(path + ".tmp", path)


def merge_engine(path, rows):
    old = []
    if os.path.exists(path):
        with open(path, newline="") as f:
            old = [{k: r.get(k, "") for k in ENGINE_FIELDS} for r in csv.DictReader(f)]
    seen, out = set(), []
    for r in old + rows:
        key = (r["time"], r["kind"])
        if key not in seen:
            seen.add(key)
            out.append(r)
    out.sort(key=lambda r: (r["time"], r["kind"]))
    write_csv(path, ENGINE_FIELDS, out)
    return len(out)


def blank(v, fmt="{:g}"):
    return "" if v is None else fmt.format(v)


def main():
    ap = argparse.ArgumentParser(description="Format raw NOAA space weather downloads into clean tables.")
    ap.add_argument("--raw", default="space_weather_raw")
    ap.add_argument("--out", default="space_weather_clean")
    ap.add_argument("--engine", default="data",
                    help="Shadow Self data folder (skipped if it does not exist)")
    args = ap.parse_args()

    scales, engine = read_scales(args.raw)
    probs = read_probabilities(args.raw)
    protons = read_series(args.raw, "protons", {">=10 MeV": "p10", ">=100 MeV": "p100"})
    xrays = read_series(args.raw, "xrays", {"0.1-0.8nm": "xray"})
    alerts = read_alerts(args.raw)

    # forecast: latest issue for each day from each source, combined
    by_day = {}
    for source in (probs, scales):
        for (issued, day), vals in sorted(source.items()):
            row = by_day.setdefault(day, {"for_date": day})
            row.update({k: v for k, v in vals.items() if v is not None})
            row["issued_utc"] = max(row.get("issued_utc", ""), issued)
    fcols = ["for_date", "s1_storm_pct", "proton_event_pct", "m_flare_pct", "x_flare_pct", "r1_r2_pct",
             "r3_plus_pct", "issued_utc"]
    forecast = [{c: (blank(r.get(c)) if c.endswith("pct") else r.get(c, "")) for c in fcols}
                for _, r in sorted(by_day.items())]

    # observed: protons + x-rays on one 5-minute timeline
    observed = []
    for t in sorted(set(protons) | set(xrays)):
        p, x = protons.get(t, {}), xrays.get(t, {}).get("xray")
        observed.append({"time_utc": t, "proton_10mev_pfu": blank(p.get("p10"), "{:.4g}"),
                         "proton_100mev_pfu": blank(p.get("p100"), "{:.4g}"), "s_level": s_level(p.get("p10")) if "p10" in p else "",
                         "xray_flux_wm2": blank(x, "{:.3e}"), "flare_class": flare_class(x)})
        for col, kind in (("p10", "proton_flux_10mev"), ("p100", "proton_flux_100mev")):
            if col in p:
                engine.append({"time": t, "kind": kind, "value": f"{p[col]:.4g}", "source": SOURCE})

    out = args.out
    write_csv(os.path.join(out, "forecast_3day.csv"), fcols, forecast)
    write_csv(os.path.join(out, "observed.csv"), list(observed[0].keys()) if observed else
              ["time_utc", "proton_10mev_pfu", "proton_100mev_pfu", "s_level", "xray_flux_wm2", "flare_class"], observed)
    write_csv(os.path.join(out, "alerts.csv"), ["issued_utc", "code", "category", "headline"], alerts)
    n_engine = merge_engine(os.path.join(out, "space_weather.csv"), engine)

    # plain summary
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    lines = [f"SPACE WEATHER SUMMARY  (made {now:%Y-%m-%d %H:%M} UTC, source: NOAA SWPC)", ""]
    last_p = next((r for r in reversed(observed) if r["proton_10mev_pfu"]), None)
    if last_p:
        age = now - datetime.fromisoformat(last_p["time_utc"])
        lines.append(f"Radiation now:  >=10 MeV protons {last_p['proton_10mev_pfu']} pfu -> S{last_p['s_level']}"
                     f" (at {last_p['time_utc']}, {age.total_seconds() / 3600:.1f} h ago)")
        day_ago = (datetime.fromisoformat(last_p["time_utc"]) - timedelta(hours=24)).isoformat()
        peak = max((float(r["proton_10mev_pfu"]) for r in observed if r["proton_10mev_pfu"] and r["time_utc"] >= day_ago), default=0)
        lines.append(f"                24 h peak {peak:.3g} pfu -> S{s_level(peak)}")
    else:
        lines.append("Radiation now:  no proton data")
    last_x = next((r for r in reversed(observed) if r["flare_class"]), None)
    if last_x:
        day_ago = (datetime.fromisoformat(last_x["time_utc"]) - timedelta(hours=24)).isoformat()
        peak = max((float(r["xray_flux_wm2"]) for r in observed if r["xray_flux_wm2"] and r["time_utc"] >= day_ago))
        lines.append(f"Flares:         now {last_x['flare_class']}, biggest in 24 h {flare_class(peak)}")
    lines += ["", "Next days (chance %):  date        S1+ storm  proton event  M flare  X flare"]
    for r in forecast[-4:]:
        lines.append(f"                       {r['for_date']}  {r['s1_storm_pct'] or '-':>9}  {r['proton_event_pct'] or '-':>12}"
                     f"  {r['m_flare_pct'] or '-':>7}  {r['x_flare_pct'] or '-':>7}")
    recent = [a for a in alerts if a["category"] in ("radiation storm", "solar flare")
              and a["issued_utc"] >= (now - timedelta(hours=48)).isoformat()]
    lines += ["", f"Radiation / flare alerts, last 48 h: {len(recent)}"]
    lines += [f"  {a['issued_utc']}  {a['code']:<8} {a['headline'][:90]}" for a in recent[-8:]]
    if problems:
        lines += ["", "Problems (skipped, not fatal):"] + [f"  - {p}" for p in problems[:10]]
    summary = "\n".join(lines)
    with open(os.path.join(out, "summary.txt"), "w") as f:
        f.write(summary + "\n")
    print(summary)
    print(f"\nWrote {out}/: forecast_3day.csv ({len(forecast)} days), observed.csv ({len(observed)} rows), "
          f"alerts.csv ({len(alerts)}), summary.txt, space_weather.csv ({n_engine})")
    if os.path.isdir(args.engine):
        n = merge_engine(os.path.join(args.engine, "space_weather.csv"), engine)
        print(f"Updated {args.engine}/space_weather.csv for the Shadow Self engine ({n} rows)")


if __name__ == "__main__":
    main()
