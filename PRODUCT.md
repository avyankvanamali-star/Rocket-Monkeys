# Shadow Self: product context

Inferred from the brief and the codebase (no interview); assumptions are marked.

- **What it is:** an astronaut health engine. It learns each crew member's pre-flight baseline, checks every reading
  against that baseline ± its measurement noise (MDC), predicts where the reading should be today (the "shadow"),
  and scores five body systems (radiation, muscle, bone, eyes/brain, heart) from 0 to 100 every mission day.
  The lowest system is the day's Shadow Score. Alerts, a countermeasure plan and an Earth summary follow.
- **Who uses it:** a crew medical officer and flight surgeons on the ground (assumption, from the dashboard's design).
- **Surfaces:**
  - `/` landing page, the front door (Persuade mode): explains the idea and hands the visitor the live dashboard as a demo.
  - `/app` dashboard (Operate mode): see UI/DESIGN.md. Old `/?a=..&day=..` links redirect here.
- **Honesty rules:** all numbers on any surface come from the engine's database. Thresholds are demo thresholds, not
  medical standards. No invented customers, missions, partners or claims.
- **Tone:** exact, nocturnal, quietly human. Plain words, no hype.
