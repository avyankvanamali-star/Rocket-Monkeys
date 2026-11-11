# SHADOW SELF — CORE PSEUDOCODE
Plain-English logic for every core part. Read top to bottom.
Each section = one folder/file. Arrows (→) mean "then".

---------------------------------------------------------------
## 0. THE BIG LOOP  (main.py)
---------------------------------------------------------------
start system
load settings (config)
open database

LOOP forever:
    get any new readings that arrived
    for each reading:
        clean it (ingestion) → save it (storage)

    EVERY 5 SECONDS:
        run heartbeat check      (fast_checks/heartbeat.py)
        run radiation check      (fast_checks/radiation_watch.py)
        if anything urgent → send alert NOW

    AT END OF EACH DAY:
        summarize the day's fast data (resting HR, HRV, daily dose)
        run all 5 modules        (radiation, muscle, bone, sans, cardio)
        run fusion               (cross-system rules + drift scores)
        run actions              (alerts, plan, Earth summary)
        print daily report
    move on

---------------------------------------------------------------
## 1. CONFIG  (config/settings.py)
---------------------------------------------------------------
For EVERY metric, write down:
    name             e.g. "hrv_rmssd"
    domain           e.g. "cardio"
    unit             e.g. "ms"
    possible range   e.g. 5 to 200   (anything outside = broken sensor)
    SEM              measurement error, e.g. 3 ms
    MDC              = 1.96 × √2 × SEM   (computed automatically)
    bad direction    "down" (HRV dropping is bad) or "up" (urine calcium rising is bad)

Also store:
    radiation career limit
    mission length in days
    alert thresholds (how many repeats = "persistent", etc.)

---------------------------------------------------------------
## 2. INGESTION  (ingestion/ingest.py)
---------------------------------------------------------------
take one raw reading
check it has: astronaut, time, metric, value, unit
    if anything missing → reject, log "incomplete reading", move on
is the metric known in config?
    no → reject, log "unknown metric", move on
convert unit if needed (e.g. Gy-based → stay separate, mSv vs µSv → convert)
look up its domain from config
check value is inside possible range
    no → quality = "bad"
    yes → quality = "good"
hand the clean reading to storage
move on

---------------------------------------------------------------
## 3. STORAGE  (storage/db.py)   — SQLite file: shadow_self.db
---------------------------------------------------------------
Tables:
    measurements  (every reading)
    baselines     (pre-mission normal for each astronaut + metric)
    results       (what each module concluded, every day)
    alerts        (every alert raised)
    plans         (countermeasures scheduled)

Functions:
    save_reading(reading)
    get_history(astronaut, metric, last N days)
    get_latest(astronaut, metric)
    get_baseline(astronaut, metric)
    set_baseline(astronaut, metric, value)
    save_result(result)
    save_alert(alert)

---------------------------------------------------------------
## 4. THE SHARED 7-STEP CHECK  (pipeline/check.py)
---------------------------------------------------------------
Every module calls this for each metric:  check_metric(astronaut, metric, new_value)

1. VALIDATE
       is quality "bad"? → stop, status = "ignored"
2. BASELINE
       get baseline
       none yet? → stop, status = "no baseline"
3. CHANGE
       pct_change = (new − baseline) / baseline × 100
4. NOISE CHECK
       real_change = |new − baseline| > MDC
       is it moving in the BAD direction?
5. EXPECTED (only if a Shadow model exists for this metric)
       predicted = shadow model guess for today
       residual  = new − predicted
       residual too big? (bigger than 2 × usual residual size)
6. PERSISTENCE
       look at the last 3 results for this metric
       all 3 real_change AND bad direction? → persistent = yes
7. STATUS
       not real change            → "ok"
       real change, not persistent → "watch"
       real change AND persistent  → "act"
       write a reason, e.g. "HRV down 19%, beyond MDC, 3 checks in a row"
save result → return it

---------------------------------------------------------------
## 5. HEARTBEAT FAST CHECK  (fast_checks/heartbeat.py)
---------------------------------------------------------------
EVERY 5 SECONDS:
    detect heartbeat → read heart rate + beat-to-beat gaps (RR intervals) from last 5 sec
    is the reading possible? (HR between 30 and 220, sensor quality good)
        no → throw it out, add 1 to "bad count"
             bad count reaches 12 in a row (1 minute) → message "check ECG strap"
             move on
        yes → reset bad count
    record irregularities:
        for each beat: gap differs from the previous gap by more than 20%?
            → mark as irregular beat, add to irregular count (last 60 sec)
    compare with previous:
        this 5-sec average vs. last 1-minute average
        jumped more than 25%? → note "sudden change"
    compare with activity:
        is astronaut exercising right now? (exercise log or motion sensor)
        exercising → high HR is expected → fine
        resting    → high HR is NOT expected
    come up with scenarios:
        A. resting + HR high + steady for 2 min     → WATCH "elevated resting HR (stress/fatigue?)"
        B. more than 6 irregular beats in 1 min     → ACT   "irregular rhythm"
        C. resting + HR < 35 or > 150 for 2 min     → URGENT
        D. exercise ended 1 min ago + HR not dropping by 12+ bpm → note "slow recovery"
        none of these → ok
    store the 5-sec summary
    move on

END OF DAY (summarize for the cardio module):
    resting HR      = lowest 5-minute average during sleep
    HRV (RMSSD)     = from RR gaps during sleep
    HR recovery     = drop in bpm 60 sec after the standard workout
    irregular beats = total count today
    → save as daily metrics

---------------------------------------------------------------
## 6. RADIATION FAST CHECK  (fast_checks/radiation_watch.py)
---------------------------------------------------------------
EVERY 5 SECONDS:
    read dose rate (µSv/h)
    bad reading? → skip, move on
    add to running total:  total += dose_rate × (5 sec in hours)
    compare with normal:
        dose rate > 3 × normal background for 1 minute straight?
            → EVENT MODE "possible solar particle event" → URGENT "go to shielded area"
        back to normal for 30 min → end event mode
    move on

---------------------------------------------------------------
## 7. RADIATION MODULE  (modules/radiation.py)  — daily
---------------------------------------------------------------
daily dose      = sum of today's readings
total so far    = all-mission sum
percent used    = total / career limit × 100
burn rate       = average daily dose over last 7 days
projected total = total + burn rate × days left in mission
compare:
    projected > limit         → ACT "on track to exceed limit"
    percent used > 80%        → WATCH
    passive dosimeter arrived? compare with active total
        differ by more than 10% → "sensor doubt", ask for check
was there an event today? → note it so cardio watches closely for 7 days
return radiation budget + status

---------------------------------------------------------------
## 8. MUSCLE MODULE  (modules/muscle.py)
---------------------------------------------------------------
DAILY:
    workload % of target → 7-step check
    workload under 70% for 3 days in a row → WATCH "missed workouts"
ON TEST DAYS:
    muscle area (ultrasound)  → 7-step check
    strength (force sensor)   → 7-step check
combine:
    area AND strength both "act"    → ACT  "real muscle loss"
    only one of them changed         → WATCH
    nothing changed                  → OK
return muscle status

---------------------------------------------------------------
## 9. BONE MODULE  (modules/bone.py)
---------------------------------------------------------------
DAILY:
    load fraction = resistance done / target (0 to 1)
    monthly loss rate = 2% − (1% × load fraction)      → between 1% and 2%
    bone estimate = yesterday's estimate × (1 − monthly rate / 30)
    (label this as an ESTIMATE, not a measurement)
ON TEST DAYS:
    urine calcium → 7-step check
KIDNEY STONE RISK:
    points = 0
    urine calcium up beyond MDC → +1
    fluids under 2.0 L today     → +1
    sodium over 3,500 mg today   → +1
    0 = low, 1 = medium, 2–3 = high
compare:
    estimate dropping faster than 1.5%/month for 7 days → WATCH
    urine calcium "act"                               → ACT
    stone risk high                                   → ACT "drink more, less salt"
    vitamin D missed 2+ days this week                → WATCH
return bone status + estimate + stone risk

---------------------------------------------------------------
## 10. SANS MODULE  (modules/sans.py)  — eyes/brain
---------------------------------------------------------------
EVERY 3 DAYS (vision self-test):
    vision score → 7-step check
    dropping? → WATCH + "schedule OCT scan"
ON TEST DAYS:
    optic nerve sheath diameter (ultrasound) → 7-step check
    RNFL thickness (OCT)                     → 7-step check
    either "act" → ACT
DAILY:
    headache or blur score ≥ 3 for 3 days → WATCH
context (not alerts on their own):
    high sodium, high CO₂ where they sleep → add to reason
return SANS status

---------------------------------------------------------------
## 11. CARDIO MODULE  (modules/cardio.py)
---------------------------------------------------------------
DAILY (uses heartbeat end-of-day summary):
    resting HR  → 7-step check (with Shadow model)
    HRV         → 7-step check (with Shadow model)
    HR recovery → 7-step check
    blood pressure → 7-step check
Shadow model:
    predict today's resting HR + HRV from: sleep, workload, CO₂, dose
    residual same bad direction for 7 days → ACT "cardio drift"
radiation event in last 7 days? → be stricter (watch at smaller changes)
irregular beats today > usual → WATCH
MONTHLY:
    stroke volume, LV mass → 7-step check
return cardio status

---------------------------------------------------------------
## 12. SHADOW MODEL  (shadow_model/model.py)
---------------------------------------------------------------
LEARN (first 14 days, or pre-mission data):
    collect pairs: (sleep, workload, CO₂, dose) → (resting HR / HRV)
    fit a simple straight-line formula (linear regression)
    remember typical residual size
PREDICT:
    plug today's inputs into the formula → expected value
    not enough data yet? → say "no prediction", pipeline skips step 5
RELEARN:
    every 14 days, refit using only "ok" days (so it never learns bad days as normal)

---------------------------------------------------------------
## 13. FUSION  (fusion/fuse.py)
---------------------------------------------------------------
gather today's results from all 5 modules for one astronaut
CROSS-SYSTEM RULES:
    Unloading Spiral   : workload low AND (muscle down OR urine calcium up) → raise muscle, bone, cardio
    Kidney Stone Watch : stone risk high                                   → raise bone
    Fluid Shift Cluster: SANS watch AND (BP up OR sodium high OR CO₂ high)  → raise SANS + cardio
    Radiation Stress   : radiation event in last 7 days AND cardio watch    → raise cardio
    Under-Fueling      : calories/protein low AND (muscle OR bone watch)    → raise muscle + bone
    Sensor Doubt       : conflicting or bad data                            → mark low confidence, no alert
DRIFT SCORE (each domain):
    for each metric: severity = |change| / MDC   (or |residual| / usual residual)
    score = 100 − 25 × average severity   (never below 0)
    each fusion rule that fired → subtract 10
OVERALL = lowest domain score
return scores + rules fired

---------------------------------------------------------------
## 14. ACTIONS  (actions/act.py)
---------------------------------------------------------------
ALERT TIER:
    URGENT comes ONLY from hard rules (heartbeat C, radiation event)
    ACT    = any domain "act" or score < 50
    WATCH  = any domain "watch" or score < 75
    OK     = everything else
    don't repeat the same alert more than once a day (no alarm fatigue)
COUNTERMEASURES (lookup table):
    missed workouts      → add 2 resistance sessions
    stone risk high      → fluid goal 2.5 L, low-sodium meals
    SANS watch           → lower-body negative pressure session, check CO₂
    cardio drift         → adjust aerobic intervals, protect sleep
    radiation event      → shielded area, move spacewalks
    muscle loss          → increase load, check protein
check schedule: does it clash with spacewalks or sleep? → move it
EARTH SUMMARY:
    once a day: scores + all WATCH/ACT/URGENT alerts + reasons + actions taken
    save as a small file to send when link is up

---------------------------------------------------------------
## 15. DAILY REPORT (printed in the terminal)
---------------------------------------------------------------
Astronaut A2 — Day 74
    Radiation  92   OK      133.2 mSv used (22%), projected 330 mSv
    Muscle     61   WATCH   workload 58% of target, 3 days
    Bone       48   ACT     urine calcium +18%, stone risk HIGH
    SANS       80   WATCH   vision score 88 (baseline 92)
    Cardio     70   WATCH   HRV −19%, 4 days trending down
    OVERALL    48   ACT
    Rules fired: Unloading Spiral, Kidney Stone Watch
    Plan: +2 resistance sessions, 2.5 L fluids, low-sodium meals

---------------------------------------------------------------
## 16. FALLBACKS — the system never stops  (pipeline/safe.py)
---------------------------------------------------------------
every step runs inside safe(step, do_this, fallback):
    try do_this
    breaks? → write error to outputs/errors.log → use the fallback → keep going
at the end of the run → list every problem that was handled

WHAT BREAKS              → FALLBACK
no data files            → make sample data automatically
can't read a file        → skip it, note it, keep going
one bad row              → reject that row only
database locked/broken   → run in memory (warn: nothing saved)
Shadow model can't train → checks run without step 5
one 5-sec reading breaks → skip that reading
a module crashes         → that system shows "NO DATA" (never a fake "healthy")
fusion crashes           → keep module statuses, simple scores, no rules
actions crash            → still show today's alerts, no plan
Earth file can't save    → summary stays in the database
report crashes           → error logged, next astronaut still runs

---------------------------------------------------------------
## 17. SPACE WEATHER — SOLAR EVENTS  (space_weather/)
---------------------------------------------------------------
SIGNAL TREE
    solar cycle (sets how often) → solar eruption →
        solar flare          → X-ray flux (GOES)          arrives ~8 min      → R level
        solar particle event → proton flux ≥10 MeV (GOES) arrives tens of min → S level  ← the real danger
        CME                  → solar wind + Bz (DSCOVR)   arrives 1–3 days    → geomagnetic storm → Kp → G level
    crew dosimeter = ground truth on board (fast_checks/radiation_watch.py)

DATA  (space_weather/data.py)
    data/space_weather.csv: time,kind,value,source   (simulated by space_weather/simulate.py,
    or real NOAA data — same format as format_space_weather.py)
    group into 5-min snapshots, carry each value forward until it is too old (Kp 3 h, rest 30 min)

EVERY 5 MIN, PER ASTRONAUT  (space_weather/engine.py — SolarWatch)
    1. SCORE (NOAA scales)
        X-ray:   M1=R1  M5=R2  X1=R3  X10=R4  X20=R5
        protons: 10 pfu=S1  100=S2  1,000=S3  10,000=S4  100,000=S5
        Kp:      5=G1  6=G2  7=G3  8=G4  9=G5
    2. EARLY WARNING
        flare R2 or bigger            → 60-min "protons may follow" window
        proton slope over 15 min ≥ 10x per 2 h (flux ≥ 1 pfu) → "rising" + minutes until S1
        wind > 600 km/s AND Bz < −10 nT for 30 min → CME arrived
    3. FUSE → ONE LEVEL
        GREEN    all quiet
        WATCH    flare window | protons rising | CME arrived | G1+
        WARNING  S1–S2 | protons rising INSIDE a flare window | G4+
        CRITICAL S3+
        on a spacewalk (EVA day, EVA_HOURS) → one level higher
        goes UP at once; DOWN only after 30 min calmer; no proton data → level HELD
    4. ACT  (fixed list, config SW_LEVEL_ACTIONS — the AI may explain these, never invent new ones)
        WATCH    tell crew, review shelter route, plan to end spacewalk within 60 min
        WARNING  end spacewalk now, move toward storm shelter
        CRITICAL shelter now, electronics safe mode, log dose every 5 min
        CME/G    + expect comms dropouts, back up data

CONNECTIONS  (space_weather/check.py)
    level goes up → alert (WATCH=watch, WARNING=act, CRITICAL=urgent), domain radiation, key solar_<level>
    every level change → space_weather table
    lead time = dosimeter event time − first satellite WARNING (or WATCH) time
    radiation module: WARNING+ → flag solar_storm + WATCH; CME/G → flag geomagnetic_storm
    fusion: "Solar Storm Confirmed" = satellites WARNING+ AND dosimeter event
            sensor doubt = satellites S3+ but dosimeter flat
    Earth summary JSON: "space_weather" block;  report: "Space wx" line + lead time

FALLBACKS
    no space weather file → simulate one;  can't load → run without space weather
    bad row → skipped and counted;  a crash in one day → safe() logs it, run continues
