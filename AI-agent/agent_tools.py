
"""
AGENT TOOLS — the agent's eyes. Each tool reads shadow_self.db and returns SHORT text
(Groq's free tier allows ~8,000 tokens a minute, so every result is kept compact).
 
get_overview()                       who + which days exist + latest overall scores
get_scores(astronaut, day)           5 system scores + statuses for one day
get_alerts(astronaut, day)           alerts with reasons
get_checks(astronaut, day)           the flagged 7-step checks (value, baseline, change, expected)
get_trend(astronaut, metric)         a metric day by day vs baseline
get_plan(astronaut, day)             countermeasures already scheduled
look_up_guideline(topic)             a section of knowledge.md (the team's research)
get_model_check(astronaut, day)      PyTorch shadow model: is this day unusual for THIS astronaut (all metrics together)
 
Fallback: any error -> a short "tool error: ..." text, never a crash.
"""
import json
import os
import re
import sqlite3
import sys
 
from agent_settings import DB_PATH, KNOWLEDGE, ROOT
 
if ROOT not in sys.path:
    sys.path.append(ROOT)   # after installed packages, so our folder names never shadow them
try:
    from config.settings import METRICS
except Exception:  # noqa: BLE001
    METRICS = {}
 
TOPICS = ["radiation", "muscle", "bone", "sans", "cardio", "sleep_and_co2", "scoring"]
 
 
def _db():
    if not os.path.exists(DB_PATH):
        raise FileNotFoundError("no shadow_self.db yet — run python3 main.py first")
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con
 
 
def _rows(sql, args=()):
    con = _db()
    try:
        return [dict(r) for r in con.execute(sql, args)]
    finally:
        con.close()
 
 
def _latest_day(astronaut):
    r = _rows("SELECT MAX(day) AS d FROM daily_scores WHERE astronaut=?", (astronaut,))
    return r[0]["d"] if r and r[0]["d"] is not None else None
 
 
def _label(metric):
    return METRICS.get(metric, {}).get("label", metric)
 
 
# ---------------- tools ----------------
def get_overview():
    crew = _rows("SELECT astronaut, MIN(day) AS first, MAX(day) AS last FROM daily_scores GROUP BY astronaut")
    lines = []
    for c in crew:
        o = _rows("SELECT score, status FROM daily_scores WHERE astronaut=? AND day=? AND domain='overall'",
                  (c["astronaut"], c["last"]))
        s = o[0] if o else {}
        lines.append(f"{c['astronaut']}: days {c['first']}-{c['last']}, latest overall "
                     f"{'--' if s.get('score') is None else round(s['score'])} {str(s.get('status', '')).upper()}")
    return "\n".join(lines) or "No results in the database yet."
 
 
def get_scores(astronaut, day=None):
    day = day or _latest_day(astronaut)
    rows = _rows("SELECT domain, score, status FROM daily_scores WHERE astronaut=? AND day=?", (astronaut, day))
    if not rows:
        return f"No scores for {astronaut} on day {day}."
    out = [f"{astronaut} day {day} (0-100, 100 = like their usual self):"]
    for r in rows:
        out.append(f"- {r['domain']}: {'--' if r['score'] is None else round(r['score'])} {r['status'].upper()}")
    return "\n".join(out)
 
 
def get_alerts(astronaut, day=None):
    day = day or _latest_day(astronaut)
    rows = _rows("SELECT time, tier, domain, message FROM alerts WHERE astronaut=? AND day=? AND tier!='info' "
                 "ORDER BY CASE tier WHEN 'urgent' THEN 0 WHEN 'act' THEN 1 ELSE 2 END", (astronaut, day))
    if not rows:
        return f"No alerts for {astronaut} on day {day}."
    return "\n".join(f"- {r['tier'].upper()} {('at ' + r['time'][11:16]) if r['time'] else '(daily)'} "
                     f"[{r['domain']}] {r['message'][:220]}" for r in rows[:10])
 
 
def get_checks(astronaut, day=None):
    day = day or _latest_day(astronaut)
    rows = _rows("SELECT domain, metric, value, baseline, pct_change, predicted, status FROM results "
                 "WHERE astronaut=? AND day=? AND flagged=1 ORDER BY domain", (astronaut, day))
    if not rows:
        return f"No flagged checks for {astronaut} on day {day} (everything within normal noise)."
    out = []
    for r in rows[:14]:
        pct = "" if r["pct_change"] is None else f" ({r['pct_change']:+.1f}% vs baseline)"
        exp = ""
        if r["predicted"] is not None and r["predicted"]:
            gap = (r["value"] - r["predicted"]) / r["predicted"] * 100
            exp = f"; Shadow Self expected {r['predicted']:.1f} today ({gap:+.1f}% vs expected)"
        meaning = {"WATCH": "early change, not yet confirmed", "ACT": "confirmed, persistent"}.get(r["status"].upper(), "")
        out.append(f"- [{r['domain']}] {_label(r['metric'])}: now {r['value']:g}, baseline {round(r['baseline'], 1):g}{pct}"
                   f"{exp} -> {r['status'].upper()}" + (f" ({meaning})" if meaning else ""))
    return "\n".join(out)
 
 
def get_trend(astronaut, metric):
    metric = metric.strip().lower().replace(" ", "_")
    rows = _rows("SELECT day, value, baseline, predicted, status FROM results "
                 "WHERE astronaut=? AND metric=? ORDER BY day", (astronaut, metric))
    if not rows:
        known = ", ".join(sorted(m for m in METRICS if m not in ("heart_rate", "dose_rate")))
        return f"No checks for '{metric}'. Known metrics: {known}"
    out = [f"{_label(metric)} for {astronaut} (baseline {round(rows[0]['baseline'], 1):g}):"]
    for r in rows[-10:]:
        exp = "" if r["predicted"] is None else f", expected {r['predicted']:g}"
        out.append(f"- day {r['day']}: {r['value']:g}{exp} -> {r['status'].upper()}")
    return "\n".join(out)
 
 
def get_plan(astronaut, day=None):
    day = day or _latest_day(astronaut)
    rows = _rows("SELECT scheduled_day, action, note FROM plans WHERE astronaut=? AND made_on_day=?",
                 (astronaut, day))
    if not rows:
        return f"No countermeasures scheduled on day {day}."
    return "\n".join(f"- day {r['scheduled_day']}: {r['action']}" + (f" ({r['note']})" if r["note"] else "")
                     for r in rows)
 
 
def get_day_summary(astronaut, day=None):
    """Everything for one astronaut-day in ONE call: scores, alerts, flagged checks, plan."""
    day = day or _latest_day(astronaut)
    return "\n\n".join([get_scores(astronaut, day), "ALERTS:\n" + get_alerts(astronaut, day),
                         "CHANGED MEASUREMENTS:\n" + get_checks(astronaut, day),
                         "PLAN ALREADY SCHEDULED:\n" + get_plan(astronaut, day),
                         "AI MODEL CHECK:\n" + get_model_check(astronaut, day)])
 
 
def get_model_check(astronaut, day=None):
    """PyTorch shadow model (shadow_model.py). Never crashes the agent: problems come back as short text."""
    try:
        from shadow_model import check_day
    except ImportError:
        return "Shadow model unavailable (PyTorch not installed: pip install torch). Use the rule-based checks."
    try:
        day = day or _latest_day(astronaut)
        rows = _rows("SELECT day, metric, value, baseline, flagged FROM results WHERE astronaut=?", (astronaut,))
        return check_day(rows, astronaut, day, _label)
    except Exception as e:  # noqa: BLE001
        return f"Shadow model error: {type(e).__name__}: {e}"
 
 
def look_up_guideline(topic):
    """One topic, or several separated by commas ("bone, cardio")."""
    topics = [t for t in re.split(r"[,/ ]+(?:and\s+)?", topic) if t.strip()]
    if len(topics) > 1:
        return "\n\n".join(f"## {t.strip()}\n{_guideline(t)}" for t in topics[:5])
    return _guideline(topic)
 
 
def _guideline(topic):
    topic = topic.strip().lower()
    aliases = {"heart": "cardio", "cardiovascular": "cardio", "eyes": "sans", "eye": "sans", "brain": "sans",
               "vision": "sans", "kidney": "bone", "calcium": "bone", "strength": "muscle", "sleep": "sleep_and_co2",
               "co2": "sleep_and_co2", "score": "scoring", "scores": "scoring", "dose": "radiation"}
    topic = aliases.get(topic, topic)
    with open(KNOWLEDGE) as f:
        text = f.read()
    m = re.search(rf"^## {re.escape(topic)}\n(.*?)(?=^## |\Z)", text, re.S | re.M)
    return m.group(1).strip() if m else f"No guideline for '{topic}'. Topics: {', '.join(TOPICS)}"
 
 
# ---------------- tool registry for the model ----------------
def _spec(name, description, props=None, required=()):
    return {"type": "function", "function": {"name": name, "description": description, "parameters": {
        "type": "object", "properties": props or {}, "required": list(required)}}}
 
 
A = {"astronaut": {"type": "string", "description": "astronaut id, e.g. A2"}}
D = {"day": {"type": "integer", "description": "mission day; leave out for the latest day"}}
 
TOOL_SPECS = [
    _spec("get_day_summary", "BEST FIRST CALL: everything for one astronaut-day at once — scores, alerts, "
                             "changed measurements, scheduled plan.", {**A, **D}, ["astronaut"]),
    _spec("get_overview", "List astronauts, which mission days exist, and each one's latest overall score."),
    _spec("get_scores", "The 5 system scores (radiation, muscle, bone, sans, cardio) + overall for a day.",
          {**A, **D}, ["astronaut"]),
    _spec("get_alerts", "Alerts for a day with their reasons (urgent first).", {**A, **D}, ["astronaut"]),
    _spec("get_checks", "Measurements that changed beyond normal noise: value, baseline, % change, "
                        "what Shadow Self expected, status.", {**A, **D}, ["astronaut"]),
    _spec("get_trend", "One metric day by day vs baseline, e.g. hrv_rmssd, urine_calcium, quad_csa.",
          {**A, "metric": {"type": "string"}}, ["astronaut", "metric"]),
    _spec("get_plan", "Countermeasures the system already scheduled.", {**A, **D}, ["astronaut"]),
    _spec("get_model_check", "PyTorch shadow model: compares ALL of an astronaut's metrics together against "
                             "their own normal days. Catches several small changes adding up before rules fire. "
                             "Returns NORMAL / EDGING / UNUSUAL and the metrics driving it.", {**A, **D}, ["astronaut"]),
    _spec("look_up_guideline", "The team's research for a topic: what signals mean and what countermeasures help. "
                               "Several at once: 'bone, cardio, sans'. Topics: " + ", ".join(TOPICS), {"topic": {"type": "string"}}, ["topic"]),
]
 
FUNCTIONS = {"get_day_summary": get_day_summary, "get_overview": get_overview, "get_scores": get_scores, "get_alerts": get_alerts,
             "get_checks": get_checks, "get_trend": get_trend, "get_plan": get_plan,
             "look_up_guideline": look_up_guideline, "get_model_check": get_model_check}
 
 
def run_tool(name, arguments):
    """Run one tool call from the model. Fallback: any problem -> a short error text the model can read."""
    try:
        args = json.loads(arguments or "{}") if isinstance(arguments, str) else (arguments or {})
        if name not in FUNCTIONS:
            return f"tool error: unknown tool {name}"
        return FUNCTIONS[name](**args)[:2500]
    except Exception as e:  # noqa: BLE001
        return f"tool error: {type(e).__name__}: {e}"
