# DASHBOARD FIXES

Eleven existing files are replaced and seven are added, all through `scripts/apply_dashboard_fixes.py`, which does a dry run first,
verifies each file against the version that was reviewed, and backs up everything it replaces.

## What was wrong and what changes on screen

| Page | Problem found | What you will see after |
|---|---|---|
| Ring Investigation | Risk breakdown showed "-" (page looked for `risk_components`; the API sends `score_components`) | RING056: Behavioural 92.5, Network 97.9, Fund Flow 37.5, Persistence 28.9 |
| Ring Investigation | Evidence table "Type" repeated the account ID; "Risk" was always empty | "Role in evidence" and "Flows (out / in)", derived from the evidence edges (account 14: 1 out / 6 in) |
| Overview | "Total transactions" and "Total accounts" were **typed fallbacks, not API data** (key mismatch: API sends `total_transactions`) | Same values, now actually read from the API. "-" if missing |
| Overview | "Detection Pipeline" cards (720 / 39,869 / 3,460 / 142) were literal text | Counted from the database through `/api/pipeline-stats` |
| Model Performance | 653,487 / 32 / 0.0049% and Precision@K 40% / 25% / 14% were literal text | Read from the metrics the API returns. "-" and "Not available" if missing |
| Lead-Time | Hard-coded fallbacks (-23, 142, 89, 0.989), typed "23 windows" text, static "no early detections" claim, and a caveat that a window is not a calendar day | Follows the data. States that one window = 1 calendar day (from the database) |
| Alert Queue | "of 142" typed | Total from the API |
| Data Explorer | "671" typed twice; normal transactions called "Unlabelled" | Counted from the database; "Not in an alert" |
| Temporal Evolution | Warned that window ids are not dates | Shows the dates: `145 -> 152` becomes `2017-05-26 -> 2017-06-02` |
| Sidebar | "DEMO / REAL AMLSim data" | "REAL AMLSim data" or "DEMO / SYNTHETIC DATA" according to the database |
| Ring / Why Flagged / Temporal | Candidate list hard-limited to 142 | Limit 1000 |
| **New: Ring Early Warning** | New results were not on the dashboard | Ring-level lead time with N and CIs, controls across alert budgets, candidate quality v1 vs v2, leakage-safe account-window table |

Most typed numbers equalled the API's values, which is why nothing looked wrong. The visible change is largest on Ring Investigation and
the new page; the rest is integrity: a missing value now shows an em dash instead of a remembered number.

## Commands, one by one (PowerShell, project root, venv active)

```powershell
# 1. back up and stop the apps (Ctrl+C in the uvicorn and npm terminals)
Copy-Item -Recurse frontend\src frontend_src_backup
Copy-Item backend backend_backup -Recurse

# 2. extract (creates dashboard_fixes\ and scripts\apply_dashboard_fixes.py; overwrites nothing of yours)
Expand-Archive Dashboard_Fixes.zip -DestinationPath . -Force

# 3. dry run: nothing is written. Expect "7 NEW, 11 UPDATE"
python scripts/apply_dashboard_fixes.py

# 4. apply
python scripts/apply_dashboard_fixes.py --apply

# 5. rebuild and restart
cd frontend; npm run build; cd ..
uvicorn backend.main:app --reload
# second terminal:  cd frontend; npm run dev
```

If step 3 reports `CHANGED` for a file, you edited it after the version I reviewed. It is skipped. Send me that file, or use `--apply --force`
(it is backed up first) to replace it.

## Check each page (2 minutes)

1. Ring Investigation, RING056: four score bars show numbers; evidence table has Role and Flows columns.
2. Overview: 1,97,905 transactions, 12,043 accounts, pipeline 720 / 39,869 / 3,460 / 142.
3. Lead-Time: heading "Why the 98.9% Figure...", text "one graph window = 1 calendar day(s)".
4. Temporal Evolution, RING056: "2017-05-26 -> 2017-06-02".
5. Sidebar: "REAL AMLSim data". New entry "Ring Early Warning".
6. Ring Early Warning: needs result files. If it says none are loaded, run the three evaluation scripts:

```powershell
python scripts/run_ring_lead_time.py
python scripts/run_candidates_v2.py
python scripts/run_account_window_eval.py
```

Sections appear as each file becomes available.

## One step that needs your data: refresh the stored scores

Why Flagged still says "across 7 accounts (0.43 events/account)" for RING056. That text is stored in the risk-score table from before the
ID repair. Recompute from the repaired candidates (needs `data/processed/features.csv`):

```powershell
python scripts/compute_risk_scores.py
python scripts/build_evidence.py
python scripts/load_database.py
```

Then restart uvicorn. RING056 should read "across 6 accounts". Scores of affected candidates may move slightly.

## Optional: run the dashboard's own tests

```powershell
python -m pytest tests/test_dashboard_extras.py -q          # 5 tests; no extra installs
cd frontend
npm install -D vitest@1 jsdom@24 @testing-library/react@14  # changes package.json
npx vitest run                                              # 17 render tests on real API responses
```

## What this does not change

* The v1 pipeline results (1.0% ring detection, -23 lead, N=1) are unchanged: they are what the v1 pipeline measured.
* Model Performance still shows the account-window model's original metrics. The leakage-safe 2/7/14-day table is on Ring Early Warning.
* Risk scores are still computed in-sample (`compute_risk_scores.py`) and the network component is a density percentile.
* There is no per-account risk in the API, so the evidence table shows role and flows instead.
