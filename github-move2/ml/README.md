# Shadow Self — PyTorch model (`ml/`)

Trains the "expected you" model: given sleep, last night's sleep, workload, CO2, sodium and fluids,
what should this astronaut's HRV and resting heart rate be today? A growing gap between expected and
actual is the early warning.

## Set up the environment (once, no admin needed)
    bash setup_env.sh                  # makes .venv/ and installs PyTorch + the AI agent package
    source .venv/bin/activate          # every new terminal (your prompt starts with "(.venv)")
In VS Code: Cmd+Shift+P -> "Python: Select Interpreter" -> pick the one in .venv

## Run it (from the shadow_self folder, with .venv active)
    python3 simulator/run.py           # 4 astronauts x 210 days of data + answer key  (data_sim/)
    python3 ml/build_dataset.py        # optional: see the training table (data_sim/train_table.csv)
    python3 ml/train_shadow_net.py     # trains 5 networks, ~10-30 s, saves ml/shadow_net.pt
    python3 ml/evaluate.py             # scorecard -> outputs/ml_scorecard.txt

## Files
| File | What it does |
|---|---|
| simulator/run.py | 180-day mission + 30 pre-mission days, with planted problems (answer key: data_sim/events.csv) |
| ml/build_dataset.py | CSV (one reading per row) -> one row per astronaut-day |
| ml/shadow_net.py | The model: straight line + small network for the curves, 5 averaged (ensemble) |
| ml/train_shadow_net.py | Trains on healthy days only, saves ml/shadow_net.pt |
| ml/evaluate.py | Accuracy vs the straight line + early-warning test vs a threshold alarm |

## Why this design (what testing showed)
- A plain neural network memorised the ~300 training days and was LESS accurate than a straight line.
- Hybrid (straight line + network for the curves) can't start worse than the line.
- One small network was jumpy between runs; the average of 5 was steady.
- Result on 459 unseen healthy days: ~10% lower HRV error, ~7% lower resting HR error than the line.
  Caught the hidden heart drift ~28 days before a normal threshold alarm, with 1 false-alarm day.
- Honest limits: on the 15 "hard days" it's roughly a tie; all data is simulated.

## Train on your own / a friend's CSV
    python3 ml/build_dataset.py    --data data_friend/mission.csv    # checks the file, lists anything missing
    python3 ml/train_shadow_net.py --data data_friend/mission.csv
    python3 ml/evaluate.py         --data data_friend/mission.csv

The CSV uses the usual columns: astronaut,time,metric,value,unit (+ optional source,quality,detail).
- Needs one value per astronaut per day of: sleep_hours, resistance_load_pct, co2_sleep, sodium,
  fluids, hrv_rmssd, resting_hr
- Needs pre-mission days (day 0 or earlier) for each astronaut's baseline. Mission day 1 = 2027-03-01.
- Training uses days up to 45 (TRAIN_UNTIL_DAY in ml/train_shadow_net.py); testing uses the days after.
- Optional answer key: put an events.csv (same columns as data_sim/events.csv) in the same folder,
  and evaluate.py also runs the early-warning test. Without it, only the accuracy test runs.
- Training on new data overwrites ml/shadow_net.pt. evaluate.py tells you whether to keep it.
