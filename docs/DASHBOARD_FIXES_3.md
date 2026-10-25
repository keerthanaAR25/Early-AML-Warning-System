# DASHBOARD FIXES 3 -- one consistent result per page

Applies on top of Fixes 1 and 2 with the same apply script. Five files, all updates, no backend change.

## Why you saw two different results

They answered different questions, and the pages put them side by side without saying so.

| Page | The two numbers | The real difference |
|---|---|---|
| Lead-Time | "-23 / 0.0% early / 1.0% detected" and "30 of 30 warned, median 12 days" | Different candidate sources (v1 pattern-trajectory candidates vs flagged transactions), different "observable" events (the ring's first transaction vs the ring's completion), different samples (1 matched candidate vs 30 rings) |
| Model Performance | Precision 0.2941 and 0.80 | Different tasks: the original is a 2-day forecast; 0.80 was a 14-day forecast with far more positives. Comparing them was misleading, and the previous batch did exactly that |

## What the pages show now

**Lead-Time**: one table, "Candidate sources compared on the same rings". Every source (v1, v2 structure, v2 novelty) is evaluated
identically on the same rings, with lead measured both against ring **completion** and against the ring's **first transaction** (the original
v1 definition). A data-driven sentence states whether any source warns before a ring's first transaction. The original strict-matching cards
(1.0%, -23, 98.9%) are collapsed under "Original v1 strict-matching evaluation (superseded; kept for reproducibility)". The disclaimer stays visible.

**Model Performance**: one table, "Account-window evaluation: one protocol, every horizon". The original run is a row in it. Only like-for-like
claims are made: on the original 2-day task the validated precision is compared with 0.294, and the text says whether the original value lies inside the
validated Wilson interval. The 7 and 14-day rows are described as different, easier tasks and are explicitly not compared with the 2-day figure.

**Overview**: no second headline. It explains what the queue's candidates are and links to the comparison.

## Commands (PowerShell, project root; stop uvicorn and `npm run dev` first)

```powershell
Expand-Archive Dashboard_Fixes_3.zip -DestinationPath . -Force
python scripts/apply_dashboard_fixes.py            # dry run: expect "5 UPDATE"
python scripts/apply_dashboard_fixes.py --apply
cd frontend; npm run build; cd ..
uvicorn backend.main:app --reload                  # project root
# second terminal: cd frontend; npm run dev        then Ctrl+F5
```

## Honest limits

* No candidate source warns before a ring's first transaction; the novelty sources warn with it. The positive leads are measured against ring completion.
* The static, behavioural and temporal baseline models were evaluated only in the original run (the table lower on the Model Performance page). Evaluating
  them under the validated protocol on your 53-feature table is the remaining step for a fully like-for-like model comparison; it needs `features.csv`.
* The novelty sources rely on a signal specific to AMLSim.
