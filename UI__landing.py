"""
SHADOW SELF — landing page (served at / by app.py; the dashboard lives at /app)
The front door (/). Persuade surface: explains the idea, then hands the visitor the real dashboard (/app?a=..) as a live demo in the middle.
Every number on it comes from shadow_self.db through page.load(); nothing is typed in by hand.
Styles in UI/static/landing.css; the WebGL hero, scroll choreography and the demo tour in UI/static/landing.js.
Fallbacks: no JS / no WebGL / reduced motion -> the server-drawn radar and every section shown in its final state.
"""
import html
import json
import math

from config.settings import METRICS
from UI.page import BUILD, asset_v, client_data, load

e = lambda s: html.escape(str(s), quote=True)
LABEL = {"ok": "Nominal", "watch": "Watch", "act": "Act", "urgent": "Urgent", None: "No data"}
ORDER = ["radiation", "muscle", "bone", "sans", "cardio"]


def crew_data():
    """{astronaut: {"days": [...], "by_day": {day: {"overall": .., "status": .., "sys": {dom: [score, status]}}}}}"""
    out, names, d0 = {}, {}, load("", None)
    if d0 is None:
        return None
    for a in d0["crew"]:
        first = load(a, None)
        days, by_day = first["days"], {}
        for day in days:
            c = client_data(load(a, day))
            names.update({k: v["name"] for k, v in c["sys"].items()})
            ov = c["sys"].get("overall", {})
            by_day[day] = {"overall": ov.get("score"), "status": ov.get("status"),
                           "alerts": len(c["alerts"]),
                           "sys": {k: [c["sys"][k]["score"], c["sys"][k]["status"]] for k in ORDER if k in c["sys"]}}
        out[a] = {"days": days, "by_day": by_day}
    return {"crew": out, "names": {k: names.get(k, k) for k in ORDER}}


def featured(data):
    """The crew member whose score moved the most: the clearest story."""
    def spread(a):
        v = [x["overall"] for x in data["crew"][a]["by_day"].values() if x["overall"] is not None]
        return max(v) - min(v) if v else 0
    return max(data["crew"], key=spread)


def series(a, metric_label):
    """Day-by-day history of one check: [[day, value, baseline, mdc, status], ...] and its unit."""
    d = load(a, None)
    c = client_data(d)
    for checks in c["checks"].values():
        for x in checks:
            if x["label"] == metric_label:
                return x.get("hist", []), x["unit"]
    return [], ""


def pt(cx, cy, r, i, n=5):
    ang = -math.pi / 2 + i * 2 * math.pi / n
    return cx + r * math.cos(ang), cy + r * math.sin(ang)


def poly(cx, cy, scale, values):
    return " ".join(f"{x:.1f},{y:.1f}" for x, y in (pt(cx, cy, scale * v, i) for i, v in enumerate(values)))


def hero_fallback(data, a):
    """Static radar of the featured astronaut's latest day (shown without JS / WebGL / under reduced motion)."""
    day = data["crew"][a]["days"][-1]
    sys = data["crew"][a]["by_day"][day]["sys"]
    vals = [(sys.get(k, [None])[0] or 0) / 100 for k in ORDER]
    cx, cy, R = 300, 300, 230
    rings = "".join(f'<polygon class="ring" points="{poly(cx, cy, R * f, [1] * 5)}"/>' for f in (.5, .75))
    spokes = "".join(f'<line class="spoke" x1="{cx}" y1="{cy}" x2="{x:.1f}" y2="{y:.1f}"/>'
                     for x, y in (pt(cx, cy, R, i) for i in range(5)))
    return f"""<svg class="hero-still" viewBox="0 0 600 600" role="img" aria-label="{e(a)}, mission day {day}: system scores
 {', '.join(f'{data["names"][k]} {sys[k][0]:.0f}' for k in ORDER if k in sys)} out of 100">
  <polygon class="shadow" points="{poly(cx, cy, R, [1] * 5)}"/>{rings}{spokes}
  <polygon class="self" points="{poly(cx, cy, R, vals)}"/></svg>"""


def drift_chart(hist, unit, w=720, h=300):
    """One measurement against its owner's baseline ± MDC band (real values)."""
    if not hist:
        return ""
    base, mdc = hist[-1][2], hist[-1][3]
    vals = [x[1] for x in hist] + [base - mdc, base + mdc]
    lo, hi = min(vals), max(vals)
    pad = (hi - lo) * .25 or 1
    lo, hi = lo - pad, hi + pad
    pl, pr, pt_, pb = 64, 120, 24, 44
    X = lambda i: pl + (w - pl - pr) * (i / max(1, len(hist) - 1))
    Y = lambda v: pt_ + (h - pt_ - pb) * (1 - (v - lo) / (hi - lo))
    path = " ".join(f'{"M" if i == 0 else "L"}{X(i):.1f},{Y(x[1]):.1f}' for i, x in enumerate(hist))
    ticks = "".join(f'<text class="ax" x="{X(i):.1f}" y="{h - 14}" text-anchor="middle">Day {x[0]}</text>'
                    for i, x in enumerate(hist))
    pts = "".join(
        f'<g class="pt {"out" if abs(x[1] - x[2]) > x[3] else "in"}" style="--i:{i}">'
        f'<circle cx="{X(i):.1f}" cy="{Y(x[1]):.1f}" r="6"/>'
        f'<text x="{X(i):.1f}" y="{Y(x[1]) - 14:.1f}" text-anchor="middle">{x[1]:g}</text></g>' for i, x in enumerate(hist))
    return f"""<svg class="drift-chart" viewBox="0 0 {w} {h}" role="img"
 aria-label="Readings {', '.join(f'day {x[0]} {x[1]:g}' for x in hist)} {e(unit)}; own baseline {base:g} plus or minus {mdc:.1f}">
  <rect class="band" x="{pl}" y="{Y(base + mdc):.1f}" width="{w - pl - pr}" height="{Y(base - mdc) - Y(base + mdc):.1f}"/>
  <line class="base" x1="{pl}" x2="{w - pr}" y1="{Y(base):.1f}" y2="{Y(base):.1f}"/>
  <text class="lab" x="{w - pr + 10}" y="{Y(base) + 4:.1f}">Baseline {base:g}</text>
  <text class="lab dim" x="{w - pr + 10}" y="{Y(base + mdc) + 4:.1f}">+{mdc:.1f} noise</text>
  <text class="lab dim" x="{w - pr + 10}" y="{Y(base - mdc) + 4:.1f}">−{mdc:.1f} noise</text>
  <path class="line" d="{path}" pathLength="1"/>{pts}{ticks}
  <text class="ax" x="{pl - 12}" y="{Y(hi) + 10:.1f}" text-anchor="end">{e(unit)}</text></svg>"""


def anatomy():
    """Monochrome dimensional drawing of the score radar: codes on the drawing, values in the tables."""
    cx, cy, R = 430, 320, 190
    L = []
    add = L.append
    for f, cls in ((1, "obj"), (.75, "zone"), (.5, "zone"), (.25, "grid")):
        add(f'<polygon class="d {cls}" pathLength="1" points="{poly(cx, cy, R * f, [1] * 5)}"/>')
    for i in range(5):
        x, y = pt(cx, cy, R, i)
        add(f'<line class="d cl" pathLength="1" x1="{cx}" y1="{cy}" x2="{x:.1f}" y2="{y:.1f}"/>')
    slots = ["SYSTEM SLOT S1", "SYSTEM SLOT S2", "SYSTEM SLOT S3", "SYSTEM SLOT S4", "SYSTEM SLOT S5"]
    for i, s in enumerate(slots):
        x, y = pt(cx, cy, R + 34, i)
        anchor = "middle" if i == 0 else ("start" if i in (1, 2) else "end")
        add(f'<text class="slot" x="{x:.1f}" y="{y + 4:.1f}" text-anchor="{anchor}">{s}</text>')
    # a sample shape (schematic, not data) to anchor the centre callout
    add(f'<polygon class="d sample" pathLength="1" points="{poly(cx, cy, R, [.82, .58, .66, .9, .44])}"/>')
    # radius chain outside the plan, on the left: centre line up to the S1 vertex at 50 / 75 / 100
    for k, (f, code) in enumerate(((.5, "Z2"), (.75, "Z1"), (1, "R0"))):
        y2, x = cy - R * f, cx - R - 124 - k * 30
        add(f'<line class="d ext" pathLength="1" x1="{cx - 8}" y1="{y2:.1f}" x2="{x - 6}" y2="{y2:.1f}"/>')
        add(f'<line class="d dim" pathLength="1" marker-start="url(#arr)" marker-end="url(#arr)" x1="{x}" y1="{cy}" x2="{x}" y2="{y2:.1f}"/>')
        add(f'<text class="code" x="{x}" y="{(cy + y2) / 2:.1f}" text-anchor="middle" transform="rotate(-90 {x} {(cy + y2) / 2:.1f})">{code}</text>')
    add(f'<line class="d ext" pathLength="1" x1="{cx - 8}" y1="{cy}" x2="{cx - R - 190}" y2="{cy}"/>')
    # centre callout, down and right, clear of the shape
    add(f'<circle class="dot" cx="{cx}" cy="{cy}" r="3.5"/>')
    add(f'<polyline class="d ext" pathLength="1" points="{cx},{cy} {cx + 130},{cy + 236} {cx + 160},{cy + 236}"/>')
    add(f'<text class="code" x="{cx + 166}" y="{cy + 240}">C = MIN(S1…S5)</text>')
    # detail A: one check against its band, circled on the S5 spoke, leader down and left
    vx, vy = pt(cx, cy, R * .44, 4)
    add(f'<circle class="d det" pathLength="1" cx="{vx:.1f}" cy="{vy:.1f}" r="24"/>')
    add(f'<polyline class="d ext" pathLength="1" points="{vx - 14:.1f},{vy + 20:.1f} {vx - 70:.1f},{cy + 236} {vx - 100:.1f},{cy + 236}"/>')
    add(f'<text class="code" x="{vx - 106:.1f}" y="{cy + 240}" text-anchor="end">DETAIL A</text>')
    plan = "".join(L)

    # detail A view: baseline ± MDC band, readings in and out
    dx, dy, dw, dh = 770, 80, 370, 220
    band_t, band_b, base_y = dy + 70, dy + 160, dy + 115
    detail = f"""<g class="detail">
  <rect class="d obj" pathLength="1" x="{dx}" y="{dy}" width="{dw}" height="{dh}" rx="2"/>
  <rect class="hatch" x="{dx + 30}" y="{band_t}" width="{dw - 60}" height="{band_b - band_t}"/>
  <line class="d base" pathLength="1" x1="{dx + 30}" x2="{dx + dw - 30}" y1="{base_y}" y2="{base_y}"/>
  <line class="d dim" pathLength="1" marker-start="url(#arr)" marker-end="url(#arr)" x1="{dx + dw - 14}" y1="{band_t}" x2="{dx + dw - 14}" y2="{base_y}"/>
  <text class="code" x="{dx + dw - 20}" y="{(band_t + base_y) / 2 + 4}" text-anchor="end">MDC</text>
  <text class="code" x="{dx + 36}" y="{base_y - 8}">B</text>
  <circle class="pin in" cx="{dx + 110}" cy="{base_y + 20}" r="6"/><circle class="pin in" cx="{dx + 200}" cy="{base_y - 30}" r="6"/>
  <circle class="pin out" cx="{dx + 250}" cy="{dy + 40}" r="6"/>
  <line class="d ext" pathLength="1" x1="{dx + 256}" y1="{dy + 36}" x2="{dx + 290}" y2="{dy + 26}"/>
  <text class="code" x="{dx + 296}" y="{dy + 30}">FLAG</text>
  <text class="title" x="{dx}" y="{dy + dh + 28}">DETAIL A · ONE CHECK</text>
  <text class="sub" x="{dx}" y="{dy + dh + 46}">SCALE 2:1 · READING VS OWN BASELINE B ± MDC</text></g>"""

    rows = [("R0", "usual self", "100"), ("Z1", "watch edge", "75"), ("Z2", "act edge", "50"),
            ("S#", "system score", "100 − 25·σ̄ − 10·F"), ("C", "shadow score", "min(S1…S5)"),
            ("B", "baseline", "pre-flight mean"), ("MDC", "noise", "1.96·√2·SEM")]
    ty, tx = 390, 770
    table = [f'<text class="title" x="{tx}" y="{ty - 14}">VARIABLES</text>']
    for i, (c, n, v) in enumerate(rows):
        y = ty + i * 30
        table.append(f'<line class="d rule" pathLength="1" x1="{tx}" x2="1140" y1="{y}" y2="{y}"/>'
                     f'<text class="code" x="{tx + 8}" y="{y + 20}">{c}</text><text class="cell" x="{tx + 70}" y="{y + 20}">{e(n)}</text>'
                     f'<text class="cell v" x="1132" y="{y + 20}" text-anchor="end">{e(v)}</text>')
    table.append(f'<line class="d rule" pathLength="1" x1="{tx}" x2="1140" y1="{ty + len(rows) * 30}" y2="{ty + len(rows) * 30}"/>')
    return f"""<svg class="sheet" viewBox="0 0 1180 640" role="img" aria-labelledby="anat-h anat-p">
  <defs><marker id="arr" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
    <path d="M0 0 8 4 0 8z" fill="currentColor"/></marker>
    <pattern id="hatch" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
    <line x1="0" y1="0" x2="0" y2="6" stroke="currentColor" stroke-width=".7"/></pattern></defs>
  {plan}
  <text class="title" x="40" y="604">PLAN · SCORE RADAR</text><text class="sub" x="40" y="622">SCALE 1:1 · FIVE SYSTEMS ON ONE 0–100 SCALE · SHAPE SCHEMATIC</text>
  {detail}{"".join(table)}</svg>"""


def landing():
    data = crew_data()
    if data is None:
        return ("<!doctype html><meta charset=utf-8><title>Shadow Self</title>"
                "<p style='font:16px system-ui;padding:40px'>No engine results yet. <a href='/app'>Open the dashboard</a> and run the engine first.</p>")
    a = featured(data)
    days = data["crew"][a]["days"]
    first, last = data["crew"][a]["by_day"][days[0]], data["crew"][a]["by_day"][days[-1]]
    calc, calc_unit = series(a, "Urine calcium")
    calc_range = METRICS.get("urine_calcium", {}).get("range", ("", ""))
    worst_last = min(last["sys"], key=lambda k: last["sys"][k][0] if last["sys"][k][0] is not None else 999)
    others = [x for x in data["crew"] if x != a]
    payload = json.dumps({"featured": a, **data}, separators=(",", ":")).replace("</", "<\\/")
    v = asset_v()

    crew_rows = ""
    for x in data["crew"]:
        cells = "".join(
            f'<td class="n"><b>{r["overall"]:.0f}</b><span class="st {r["status"] or "none"}">{LABEL.get(r["status"], "")}</span></td>'
            for r in (data["crew"][x]["by_day"][dd] for dd in data["crew"][x]["days"]))
        crew_rows += f'<tr><th scope="row">{e(x)}</th>{cells}</tr>'
    day_heads = "".join(f'<th scope="col" class="n">Day {dd}</th>' for dd in days)

    calc_txt = ""
    if len(calc) >= 2:
        out_day = next((h[0] for h in calc if abs(h[1] - h[2]) > h[3]), None)
        calc_txt = (f"{e(a)}'s urine calcium read {', '.join(f'{h[1]:g}' for h in calc[:-1])} and {calc[-1][1]:g} {e(calc_unit)}. "
                    f"Every one of those sits inside the sensor's accepted range of {calc_range[0]} to {calc_range[1]}. "
                    f"Against {e(a)}'s own pre-flight baseline of {calc[-1][2]:g} ± {calc[-1][3]:.1f}, "
                    + (f"day {out_day} has already left the noise band, and the Bone score falls with it." if out_day
                       else "all of them stay within the noise band."))

    return f"""<!doctype html><html lang="en" data-build="{BUILD}-{v}" class="no-js"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Shadow Self · each astronaut against their own shadow</title>
<meta name="description" content="Shadow Self learns each crew member's pre-flight normal and scores five body systems every mission day by how far they drift from it.">
<meta name="theme-color" content="#070B14"><meta name="color-scheme" content="dark light">
<script>document.documentElement.classList.replace("no-js","js")</script>
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 40 40'%3E%3Ccircle cx='23' cy='21' r='11' fill='%235C6B76'/%3E%3Ccircle cx='17' cy='19' r='11' fill='%233459E6'/%3E%3C/svg%3E">
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Geist:wght@300;400;500;600&family=Geist+Mono:wght@400;500&display=swap">
<link rel="stylesheet" href="/static/landing.css?v={v}">
</head><body>
<a class="skip" href="#main">Skip to content</a>
<header class="nav" data-nav>
  <a class="brand" href="#top" aria-label="Shadow Self, back to top"><svg viewBox="0 0 40 40" aria-hidden="true"><circle cx="23" cy="21" r="11" class="m-sh"/><circle cx="17" cy="19" r="11" class="m-me"/></svg><span>Shadow Self</span></a>
  <nav aria-label="Sections"><a href="#drift">Idea</a><a href="#demo">Live demo</a><a href="#anatomy">Anatomy</a><a href="#how">How a day runs</a></nav>
  <a class="btn light sm" href="/app">Open dashboard</a>
</header>

<main id="main">
<section class="hero" id="top" aria-labelledby="hero-h">
  <div class="hero-stage" data-hero>
    <div class="gl" data-gl aria-hidden="true">{hero_fallback(data, a)}</div>
    <div class="ax-labels" data-axlabels aria-hidden="true"></div>
    <div class="hero-copy">
      <h1 id="hero-h" data-split>Every astronaut, measured against their own shadow</h1>
      <p class="lede">Shadow Self learns each crew member's pre-flight normal, then scores five body systems every mission day by how far they have drifted from it.</p>
      <div class="ctas"><a class="btn light" href="#demo">Watch the live demo</a><a class="link" href="/app">Open the dashboard</a></div>
    </div>
    <aside class="readout" data-readout aria-live="polite">
      <p class="who">{e(a)} · Mission day <b data-r-day>{days[-1]}</b></p>
      <p class="score"><b data-r-score>{last["overall"]:.0f}</b><span>/100</span></p>
      <p class="st-line"><span class="st {last["status"]}" data-r-status>{LABEL.get(last["status"])}</span>
        <span data-r-low>Lowest: {e(data["names"][worst_last])}</span></p>
      <ol class="daymarks" data-daymarks>{"".join(f'<li data-day="{dd}"{" class=on" if dd == days[-1] else ""}><span>Day {dd}</span></li>' for dd in days)}</ol>
    </aside>
    <p class="hero-key" aria-hidden="true"><span class="k-self"></span>{e(a)} today<span class="k-shadow"></span>Usual self, 100 on every system</p>
    <p class="scroll-cue" aria-hidden="true">Scroll to play {len(days)} mission days</p>
  </div>
</section>

<section class="drift" id="drift" aria-labelledby="drift-h">
  <div class="wrap split">
    <div class="copy">
      <h2 id="drift-h" data-split>A reading only means something next to its owner's normal</h2>
      <p>{calc_txt}</p>
      <p class="muted">The band is the measurement's own noise, its minimum detectable change. Inside it, a change could be the sensor. Outside it, the body moved.</p>
    </div>
    <figure class="chart-fig" data-draw>{drift_chart(calc, calc_unit)}
      <figcaption>{e(a)} · urine calcium by mission day, with the baseline ± noise band from the pre-flight days</figcaption></figure>
  </div>
</section>

<section class="demo" id="demo" aria-labelledby="demo-h">
  <div class="wrap">
    <div class="demo-head">
      <h2 id="demo-h" data-split>The real dashboard, running on this machine</h2>
      <p>Not a recording. This is the dashboard, reading the same database. Watch one pass through {e(a)}'s mission, then take the controls.</p>
    </div>
    <div class="demo-bar" data-tourbar>
      <ol class="beats" data-beats>
        <li data-beat="0">Day {days[0]}</li><li data-beat="1">Day {days[-1]}</li><li data-beat="2">Pick a system</li><li data-beat="3">Its evidence</li><li data-beat="4">Your turn</li>
      </ol>
      <div class="tour-ctl"><button class="btn ghost sm" type="button" data-tour-replay>Replay tour</button>
        <button class="btn ghost sm" type="button" data-tour-skip>Skip to controls</button></div>
    </div>
    <div class="window" data-window>
      <div class="chrome"><span class="lights" aria-hidden="true"><i></i><i></i><i></i></span>
        <span class="addr">localhost · Shadow Self dashboard</span><a class="pop" href="/app?a={e(a)}&amp;day={days[0]}" target="_blank" rel="noopener">Open full screen</a></div>
      <div class="viewport" data-viewport>
        <iframe title="Shadow Self dashboard, live and read-only" data-src="/app?a={e(a)}&amp;day={days[0]}" loading="lazy" tabindex="0"></iframe>
        <div class="shield" data-shield hidden></div>
        <div class="cursor" data-cursor hidden aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M5 3l14 8-6.2 1.6L9.6 19z"/></svg></div>
        <p class="caption" data-caption aria-live="polite"></p>
      </div>
    </div>
    <p class="note">Read-only here: adding readings, uploads and engine runs are switched off inside the demo. They work in the <a href="/app">full dashboard</a>.</p>
  </div>
</section>

<section class="anatomy" id="anatomy" aria-labelledby="anat-h">
  <div class="wrap">
    <div class="tblock">
      <h2 id="anat-h" data-split>Anatomy of a Shadow Score</h2>
      <p id="anat-p">Five systems share one scale. 100 is the crew member's usual self. Each system loses points as its checks leave their noise bands and when cross-system rules fire. The centre number is the lowest system, because a crew member is only as well as their weakest system today.</p>
      <dl class="tcells"><div><dt>Units</dt><dd>Score 0–100</dd></div><div><dt>Systems</dt><dd>5</dd></div>
        <div><dt>Checks</dt><dd>{len(METRICS)} metrics</dd></div><div><dt>Thresholds</dt><dd>Demo, not medical</dd></div></dl>
    </div>
    <div class="sheet-wrap" data-sheet>{anatomy()}</div>
  </div>
</section>

<section class="how" id="how" aria-labelledby="how-h">
  <div class="wrap">
    <h2 id="how-h" data-split>One mission day, end to end</h2>
    <ol class="steps">
      <li><h3>Every reading is checked</h3><p>Sensor streams, daily logs and lab tests arrive. Readings outside a metric's possible range are rejected as broken sensors; doubtful ones are marked, not dropped.</p></li>
      <li><h3>Compared with its owner</h3><p>Each check is measured against the crew member's pre-flight baseline and its noise band, and against the shadow: where the model expected that reading to be today.</p></li>
      <li><h3>Five systems are scored</h3><p>Radiation, muscle, bone, eyes and brain, and heart each get a 0 to 100 score. Cross-system rules catch patterns no single check shows.</p></li>
      <li><h3>A plan comes back</h3><p>Alerts by urgency, the top countermeasures for tomorrow, and a summary packet for the flight surgeons on Earth.</p></li>
    </ol>
  </div>
</section>

<section class="crew" id="crew" aria-labelledby="crew-h">
  <div class="wrap split">
    <div class="copy"><h2 id="crew-h" data-split>Same mission, different shadows</h2>
      <p>The same days, the same thresholds. {e(", ".join(others))} {"stays" if len(others) == 1 else "stay"} near their usual self while {e(a)} drifts. That difference is the whole point: nobody is compared with an average astronaut.</p></div>
    <div class="scroll"><table class="crew-t"><caption class="sr">Shadow Score by crew member and mission day</caption>
      <thead><tr><th scope="col">Crew</th>{day_heads}</tr></thead><tbody>{crew_rows}</tbody></table></div>
  </div>
</section>

<section class="end" aria-labelledby="end-h">
  <div class="wrap">
    <h2 id="end-h" data-split>Open the dashboard and inspect any day</h2>
    <div class="ctas"><a class="btn light" href="/app">Open the dashboard</a><code class="cmd">python3 UI/app.py</code></div>
  </div>
</section>
</main>
<footer class="foot"><div class="wrap"><span>Shadow Self · astronaut health engine</span>
  <span>Sample mission data from generate_sample_data.py. Demo thresholds, not medical standards.</span></div></footer>
<script type="application/json" id="ld-data">{payload}</script>
<script src="/static/vendor/gsap.min.js" defer></script>
<script src="/static/vendor/ScrollTrigger.min.js" defer></script>
<script src="/static/vendor/lenis.min.js" defer></script>
<script src="/static/landing.js?v={v}" defer></script>
</body></html>"""
