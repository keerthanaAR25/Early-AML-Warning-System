# DASHBOARD FIXES 2 -- headline pages now lead with the validated results

Applies on top of `Dashboard_Fixes.zip` using the SAME apply script (it checks each file against what is on your machine and backs up
before replacing). Seven files: 1 new, 6 updated. No backend change.

## Why

After the first fixes the pages were live and truthful, but the headline pages still showed only what the v1 pipeline measured
(Lead-Time -23 / 1.0% / 98.9%, Model Performance 0.2941 / 0.0778, Overview 89 HIGH). The validated results were only on the
Ring Early Warning page. Now the pages that people open first lead with them, and the v1 numbers are labelled as v1.

## What changes on each page (all values come from the evaluation result files; nothing is typed in)

| Page | New |
|---|---|
| Overview | A note saying the candidates are v1 pattern-trajectory candidates, with their measured quality (0.3% ring transactions, 1.2x background, 0 of 39 evaluable rings present), then the ring-level headline: N=30 rings, 30 of 30 warned before observable, median lead 12.0 days (95% CI 10.0 to 13.0), 4.41 false alerts per day |
| Lead-Time | Ring-level headline first. The original strict-matching cards stay below under the heading "Pattern-trajectory candidates (v1)" with the same quality note |
| Model Performance | "Leakage-safe evaluation" table first (2, 7 and 14-day horizons, with Wilson intervals), then the original run labelled "v1 protocol". "False warning" of 1.8e-5 now shows as 1.8e-5, not 0.0000 |
| Alert Queue | The same note about what the queue's candidates are |
| Ring Early Warning | The evaluable-ring definition is printed once instead of twice |

If the result files are missing, none of the new cards appear (nothing is invented).

## Commands (PowerShell, project root; stop uvicorn and `npm run dev` first)

```powershell
Expand-Archive Dashboard_Fixes_2.zip -DestinationPath . -Force
python scripts/apply_dashboard_fixes.py            # dry run: expect "1 NEW, 6 UPDATE"
python scripts/apply_dashboard_fixes.py --apply
cd frontend; npm run build; cd ..
uvicorn backend.main:app --reload                  # from the project root
# second terminal: cd frontend; npm run dev        then Ctrl+F5 in the browser
```

If the dry run reports `CHANGED` for a file, you edited it after the last apply; it is skipped (use `--force` to replace it after a backup).

## What still shows v1 numbers, and why

These are measurements of the v1 pipeline and they do not change unless the candidates change: 142 candidates, 89 HIGH, 0 CRITICAL,
risk scores, 39,869 pattern events, the strict-matching cards (1.0%, -23, 98.9%) and the original model table. They are now labelled.

## Optional next step (not done here, unverified end to end)

To make the candidates, risk scores and alert queue themselves come from the better candidate source, back up
`results/ring_candidates.json`, copy `results/ring_candidates_v2.json` over it, then re-run `compute_risk_scores.py`,
`build_evidence.py`, `compute_lead_time.py` and `load_database.py`. I checked that the risk engine accepts those candidates without
crashing (unknown pattern names get a default weight of 0.5), but I could not run it end to end (it needs your `features.csv`), the
fund-flow component would be generic for the new pattern names, and the novelty-seeded candidates carry the AMLSim-specific caveat. Treat it as an experiment, not a fix.
