# Shadow Self knowledge base
Built from the team's research notes. The agent looks sections up with look_up_guideline(topic).
Each section: what the signals mean -> what helps. Not medical advice; suggestions go to the crew medical officer.

## radiation
Signals: personal dose (mSv), percent of career limit used, burn rate, projected end-of-mission dose,
dose-rate spikes (solar particle events), active vs passive dosimeter agreement.
Meaning: a dosimeter measures EXPOSURE, not cell damage. Say "exposure", never "damage".
Helps: move to the shielded area during a solar particle event; reschedule spacewalks out of event windows;
if active and passive dosimeters disagree by more than 10%, check the sensors before trusting either.
After an event, watch the heart system more closely for 7 days.

## muscle
Signals: resistance workload (% of target), muscle cross-sectional area (ultrasound), strength (force/torque),
calories and protein.
Meaning: area AND strength both down beyond measurement error, on repeated tests, is real muscle loss.
One test alone needs a repeat. Missed workouts usually come first.
Helps: restore resistance sessions (squats, deadlifts, heel raises); increase load gradually;
check calories and protein are at target, because an energy deficit speeds up muscle loss.

## bone
Signals: resistance workload, urine calcium, sodium, fluids, vitamin D, calories. Bone density is an
ESTIMATE from a model in flight (no DXA scanner), about 1-2% per month in weight-bearing bones.
Meaning: rising urine calcium while workload falls = bone breaking down faster. Calcium leaving the bone
raises KIDNEY STONE risk, made worse by low fluids and high sodium.
Helps: resistive exercise is the main countermeasure; drink more (about 2.5 L/day keeps urine diluted);
lower sodium (high salt pushes more calcium out); vitamin D daily (about 800-1000 IU, no sunlight in space);
normal calcium intake — mega-dosing calcium does NOT stop bone loss and raises stone risk;
enough calories and protein; balance potassium-rich foods against acid-producing diets.

## sans
(Spaceflight-Associated Neuro-ocular Syndrome — eyes and brain)
Signals: near-vision self-test score, optic nerve sheath diameter (ocular ultrasound), RNFL thickness (OCT),
headache and blurred-vision logs, plus context: sodium, CO2 where the astronaut sleeps.
Meaning: fluid shifts toward the head raise pressure behind the eye -> flattened eyeball, farsighted shift,
optic disc swelling. Changes are slow; catch small drifts before permanent remodeling.
Helps: adjustable-focus or reading glasses for near-vision blur; lower-body negative pressure (LBNP) sessions;
thigh cuffs during daily tasks; lower sodium; lower CO2 in the sleep area; avoid long head-down tasks;
a falling vision score -> schedule an OCT scan.

## cardio
Signals: resting heart rate, HRV (RMSSD), heart-rate recovery 60 s after a standard workout, blood pressure,
irregular beats, stroke volume (cardiac ultrasound), plus sleep, workload, CO2, recent radiation.
Meaning: in microgravity plasma volume drops and the heart deconditions. Falling HRV, rising resting HR or
slower recovery = strain or deconditioning. Biggest risk is dizziness/fainting when returning to gravity.
Shadow Self compares readings to what the model EXPECTED given sleep, workload and CO2; a gap that persists
is the early warning.
Helps: aerobic intervals in target heart-rate zones (cycle/treadmill); heavy resistance for legs (keeps the
muscle pump that returns blood to the heart); LBNP; protect 7-8 h sleep; before landing: fluid + salt loading
and compression garments; move demanding tasks (spacewalks) when strain is high.
Irregular rhythm -> crew medical officer reviews the ECG.

## sleep_and_co2
High CO2 in the sleep area and short sleep both lower HRV and raise resting HR, and CO2 can worsen headaches
and SANS. Helps: check ventilation/airflow in the sleep pod, protect sleep schedule.

## scoring
Scores are 0-100 per system (100 = behaving like your usual self). Status: OK, WATCH (real change, not yet
persistent), ACT (real AND persistent, or a high-risk combination), URGENT (hard safety limit).
"Beyond noise" = bigger than the minimal detectable change (MDC), so not just measurement error.
Cross-system rules: Unloading Spiral (missed workouts + muscle/bone responding), Kidney Stone Watch,
Fluid Shift Cluster (eye changes + sodium/CO2/BP), Radiation Stress, Under-Fueling.
