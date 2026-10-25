# REBUILD V2 -- one pipeline, one set of results

## What was wrong with the old dashboard

Two pipelines were being shown at once. The v1 pipeline (pattern-trajectory candidates, in-sample risk scores, the original model table) and the
newer evaluations (ring-level lead time, leakage-safe account-window results) measured different things, so pages showed numbers that looked like
contradictions. This rebuild produces **every** result the dashboard reads from **one** configuration, so no page can disagree with another.

## What changed (and what is the same)

| Stage | v1 | v2 (this rebuild) |
|---|---|---|
| Candidates | 10-day pattern trajectories (same-day fan-in, 48 h pass-through, time-ordered cycles) | Closed cycles (circular flow), chains of transfers (layering) and accounts with several new counterparties (fan-in, fan-out), found without requiring time order, plus groups started by accounts that transact for the first time. Built from day 240 (the scored period). Overlapping duplicates are merged |
| Risk score | Scored all windows, including training windows (in-sample); network component was a density percentile among candidates | Computed **as of each day** a candidate gains evidence, by a model trained only on earlier data (one model per 120-day block); every component is size-invariant and the weights, bands and alert threshold still come from `configs/config.yaml` |
| Models | Original run, 2-day horizon | All four model families under one protocol: 14-day horizon, 120-day warm-up excluded, purge gaps, threshold chosen on validation only |
| Evaluation | Strict matching of 142 candidates, N=1 | The same 30 evaluable rings for every number |
| Database, API, risk bands, the 0-100 scale, evidence format | unchanged | unchanged (the existing `load_database.py` loads the rebuilt files) |

Ring labels are used in exactly two places: as training targets for earlier blocks (with a purge gap) and by the evaluation. Candidates, scores
and evidence never see them (a test enforces this).

## Results on your data (30 evaluable cycle rings, days 240-719)

| | Candidates | Ring-transaction share | Rings seen | Warned before completion | Median lead | False / day |
|---|---|---|---|---|---|---|
| v1 baseline (same period, same rings) | 62 | 0.4% | 0 of 30 | none | none | 0.12 |
| **Alerts: risk score >= 50** | 11 to 15 | about 66% | 9 to 11 of 30 | 5 to 6 | 0 to 1.5 days | about 0.004 |
| Whole queue (all candidates) | 171 | 29.6% | 29 of 30 | 17 | 4.0 days | 0.26 |

* About 80% to 86% of the alerts contain ring transactions. Ranked by risk, 80% of the top 10 and 85% of the top 20 candidates do (AUC 0.78 to 0.82).
* The Lead-Time page also shows the same evaluation at alert thresholds 30 to 55: a lower threshold catches more rings and warns earlier but raises
  more false alerts. 50 is the configured threshold, not a tuned choice.
* Models, 14-day horizon, 118 test positives: isolation forest PR-AUC 0.0006, logistic regression 0.0025, temporal random forest 0.139
  (precision 0.80: 20 hits, 5 false alarms), proposed gradient boosting 0.120 (precision 0.75: 15 hits, 5 false alarms).
  The proposed model does **not** beat the temporal random forest on PR-AUC or precision. Metrics are repeatable bit for bit: thresholds
  and rankings ignore floating-point noise (an earlier draft flipped this forest between "flags nothing" and "flags 25 rows" from rounding noise alone).

## Why your numbers can differ a little from this guide (and what the page shows about it)

The candidates are identical on every machine, so **queue figures never move** (171 candidates, 29.6% ring-transaction share, 29 of 30 rings seen, ranking AUC and top-10/20/50
precision). The behavioural model, however, is retrained with random seeds, and many candidates score just below the alert threshold, so **alert-level figures move by a few units**:
across nine retrainings on my machine the alerts ranged from 12 to 15, rings seen from 9 to 11, and a different environment (for example another XGBoost version) shifts them a little more.
A run with 11 alerts, 82% precision and 9 of 30 rings seen is a normal result. The rebuild therefore retrains the model 4 more times and the Lead-Time page shows
**this run, the median and the range**. Quote the ranges, not a single value.

## Commands (PowerShell, project root; stop uvicorn and `npm run dev` first)

```powershell
Expand-Archive Rebuild_V2_Final.zip -DestinationPath . -Force
python scripts/apply_dashboard_fixes.py              # dry run: read the status column
python scripts/apply_dashboard_fixes.py --apply
python -m pytest tests/test_pipeline_v2.py -q        # before the rebuild: 14 pass, 3 skip

python scripts/rebuild_v2.py all                     # about 9 minutes; backs up the v1 results to results\v1_backup
python scripts/load_database.py                      # your existing loader; rebuilds data\aml.db
python -m pytest tests/test_pipeline_v2.py -q        # after the rebuild: 17 pass

cd frontend; npm run build; cd ..
uvicorn backend.main:app --reload
# second terminal: cd frontend; npm run dev          then Ctrl+F5
```

If the dry run shows `CHANGED` for a file, that file differs from every version I know of (for example your editor re-saved it). It is skipped. Apply with
`python scripts/apply_dashboard_fixes.py --apply --force` to replace it; every replaced file is first copied to `dashboard_backup\`.
All pages must come from the same version: a sidebar entry named "Ablations & Controls" and a note under the Overview and Alert Queue headers (the production candidates) show that main.jsx, Overview and Alert Queue are the final versions.

Optional, for the Ablations page (controls and horizon sensitivity): `python scripts/run_ring_lead_time.py` and `python scripts/run_account_window_eval.py`.
`python scripts/test_pattern_combination.py` reproduces the pattern-combination test described below.

To go back: copy `results\v1_backup\*` over `results\` (the `.bak` files are in `results\v1_backup\lineage_repair_backups`), run `python scripts/load_database.py`, and restore the pages from `dashboard_backup\`.

## What happens to the old files

The rebuild overwrites `ring_candidates.json`, `risk_scores.json`, `evidence.json`, `pattern_events.json`, `trajectories.json`, `model_comparison.json`
and `lead_time_summary.json`, and regenerates their `.csv` companions. Every other file in `results/` that describes the **old** candidates, lead time
or model run (about 25 files: `lead_time_results.json`, `forensic_explanations.json`, `predictions.csv`, the SHAP and baseline files, the candidate
ground-truth diagnostics, the `.bak` files from the lineage repair, and the experiment outputs from `run_candidates_v2.py`) is **moved, not deleted**, to
`results/v1_backup/`, so nothing on disk can contradict the rebuilt results. A test checks that no file left in `results/` mentions an old candidate ID.
Nothing in your code or tests reads those files; `scripts/generate_reports.py` and `scripts/generate_explanations.py` still expect the v1 formats and are not updated.

Your existing test suite is unchanged by the rebuild: 12 tests fail before and after (9 in `test_trajectory.py`, 3 in `test_ring_candidates.py`; old-behaviour
tests against your rewritten engines), and all others pass.

## Does combining independent pattern types help? (tested, no)

The proposal expects several pattern types in one window to signal a ring. This was tested on the finished rebuild with `python scripts/test_pattern_combination.py`.
The setup was fixed before looking at results: the original (v1) detectors' events are the independent patterns (they never decide which candidates exist), the window
is 7 days (1 and 14 are sensitivity only), and they enter the score exactly like the candidate's own patterns with the project's existing weights. Nothing is re-weighted.

| Check | Result |
|---|---|
| Ring typologies in AMLSim | 40 cycle, 30 fan-in, 30 fan-out: one typology per ring; no account is in two rings |
| Sender shows an independent pattern in the last 7 days | ring transactions 43.1%, normal transactions 55.6% (0.78x: **less** often for rings) |
| Candidates containing ring transactions vs the others | 77% vs 84% show one; standalone AUC of the count 0.477 (below chance), Mann-Whitney p = 0.70 |
| Ranking AUC of the risk score | 0.778 as shipped; 0.766 with independent patterns (change -0.012, 95% CI -0.054 to +0.032, ring-clustered) |
| Alerts at threshold 50 | 14 alerts, 86% precision as shipped; 25 alerts, 72% precision with independent patterns |

Conclusion: no evidence that pattern combination helps here, so the shipped risk score does not use it. In AMLSim the original detectors fire more on normal traffic than on rings.
This is a property of this simulator, whose rings are single-typology; it does not show that combinations are useless on real data.

## What each page shows now

* **Overview, Alert Queue**: the 171 candidates, with a note giving the production numbers above. The funnel is 197,905 transactions, 720 windows, 179 pattern events, 188 raw episodes, 171 candidates.
* **Lead-Time**: the single evaluation (alerts, queue, operating points, ranking quality, definitions, caveats).
* **Model Performance**: one protocol note and one table for all four models.
* **Warning Timeline, Alert Log, Pattern Evidence** (new): the warnings given on every ring, every alert, and the pattern investigation. See NEW_PAGES.md and PATTERN_INVESTIGATION.md.
* **Ablations & Controls**: v1 as a baseline row next to the other candidate sources, the controls, and sensitivity to the horizon.
* **Pattern Analytics, Temporal Evolution, Ring Investigation, Why Flagged**: the original pattern names (fan-in, fan-out, layering, circular flow) in the original two categories (structural, temporal).

## Pattern names: back to the original ones

Every page and result file uses the project's original pattern names. Each new detector has a true old equivalent:

| Shown as | What the detector finds | Events |
|---|---|---|
| **Circular flow** | a closed loop of money | 14 |
| **Layering** | a chain of transfers through accounts (including a path that may still close into a cycle) | 21 |
| **Fan-in / Fan-out** | one account that receives from, or sends to, several new accounts | 9 / 135 |

Two honest differences from the old detectors: they allow the pattern to build up over weeks instead of requiring one day, and layering here does not require the transfers to be rapid.
A single first-time-account transfer (663 events earlier) is a **seed**, not a pattern. It has no old name, so it is not listed as one; it stays in the candidate's evidence and in the score.
Renaming changed nothing else: scores, levels, alerts and every evaluation number are identical (a test checks that no internal name reaches a result file).
Rapid pass-through, repeated intermediary, split/merge and escalating connectivity are not detected by the new pipeline.

## Honest limits

* Only cycle rings can be evaluated end to end. Fan rings take longer than the data allows to start and finish inside the scored period.
* Warnings arrive with a ring's first transactions, so lead is measured against ring completion, not against a ring's start.
* The first-time-account groups use a signal specific to AMLSim (ring members are otherwise-dormant accounts); the structure source does not.
* Parts of the risk score (network completeness, pattern weights) are documented design constants, not learned values.
* The comparison of models uses a shared account-window feature set, not your 53-feature table. They are the same task and protocol for every model, so
  the comparison is fair, but absolute numbers are not those of the earlier run.
* `results/candidate_quality_v2.json` and `results/ring_candidates_v2.json` come from earlier experiments (a different warm-up) and are no longer served by the API.
