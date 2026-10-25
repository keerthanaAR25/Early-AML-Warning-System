# ADDITIONS -- ring-level lead-time evaluation + ID/lineage repair

These are **new files only**. Nothing in your project is replaced, and nothing is re-run from scratch.
They read two files you already have and write to **new** output paths.

| New file | Purpose |
|---|---|
| `src/evaluation/ring_lead_time.py` | Causal features, rolling-origin ring-grouped scoring, daily-budget warnings, ring-level lead time |
| `src/evaluation/lineage_tools.py` | Detect and (opt-in) repair float IDs such as `49066.0`, check evidence lineage |
| `scripts/run_ring_lead_time.py` | Runs the evaluation (about 20 seconds) |
| `scripts/check_lineage.py` | Lineage report; `--fix` repairs with `.bak` backups |
| `tests/test_additions.py` | 11 tests (causality, no label leakage, ring grouping, lead-time arithmetic, lineage repair) |
| `docs/ADDITIONS.md` | This file |

Inputs used: `data/processed/transactions_clean.csv` and `data/raw/amlsim/alert_transactions.csv`.
Outputs written: `results/ring_lead_time_summary.json`, `results/ring_lead_time_rings.csv`,
`results/ring_lead_time_rings_all_configs.csv`, `reports/ring_lead_time_report.html`.
The database, dashboard, feature table, models and all existing results are not touched.

## Install (PowerShell, from the project root)

```powershell
Expand-Archive Additions.zip -DestinationPath . -Force   # adds 6 files; none of them exist yet
python -m pytest tests/test_additions.py -q               # expect: 11 passed
python scripts/check_lineage.py                           # report only
python scripts/run_ring_lead_time.py
start reports\ring_lead_time_report.html
```

To repair the `49066.0` problem (makes `.bak` copies first; restart the API afterwards):

```powershell
python scripts/check_lineage.py --fix --rebuild-evidence
```

## Definitions (fixed before looking at results)

* **observable_time** -- cycle: day of the last (closing) edge. fan_in / fan_out: day the 4th distinct counterparty has
  transacted (`--observable-k`); if a ring has fewer, its last transaction day.
* **warning_time** -- earliest day any transaction of the ring is flagged by the daily budget.
* **lead_time** -- `observable_day - warning_day` in days (one window = one day here). `> 0` means warned before the ring was observable.
* **Daily budget** -- the top `--alerts-per-day` (default 5) scored transactions per day are flagged. No threshold is tuned on the scored period.
* **Rolling origin, ring-grouped** -- days 240-719 are scored in 120-day blocks; each block's model is trained only on days
  120 (burn-in) up to the block start, excluding every ring that has any transaction in the block.
* **Evaluable ring** -- *all* its transactions fall in the scored period, so a warning cannot be cut off by the start of scoring.
  The JSON also keeps `summary_observable_in_period`, which includes right-truncated slow rings.

Labels are used only as training targets for earlier rows and for evaluation. They never enter the feature set (a test enforces this).

## What the run on your AMLSim data shows (alerts/day = 5; seed 42)

Evaluable rings under the strict rule: **N = 30, all cycles** (fan rings need more than the 720 days available to start *and*
finish inside the scored period, so they cannot be fully evaluated here).

| Model | Cycle rings warned before observable | Median lead (days) | Transaction-level PR-AUC | False alerts/day (5/day budget) |
|---|---|---|---|---|
| xgb_with_novelty | 30 / 30 | 12 (95% CI 10-13) | 0.70 | 4.4 |
| xgb_without_novelty (same-day info only) | 11 / 30 | 5 | 0.006 | 5.0 |
| newness_rule (first-ever sender/receiver) | 30 / 30 | 12 | 0.70 | 4.4 |
| random | 5 / 30 | 12 | 0.003 | 5.0 |

At 1 alert/day: 29 of 30 cycles warned early, median lead 11 days, 0.66 false alerts/day (precision of flags 34%).

### How to read this (important)

1. **The positive lead time is real arithmetic but it comes from a simulator artifact.** AMLSim draws ring members from
   otherwise-dormant accounts, so a first-ever sender after warm-up is almost always a ring transaction.
2. **The ML model adds nothing beyond that shortcut**: `xgb_with_novelty` and the two-bit `newness_rule` are indistinguishable.
   Do not present the XGBoost as the source of the early warning.
3. **Without account history there is no signal** (`xgb_without_novelty` is close to random), consistent with amounts and
   same-day structure being identical for normal and ring transactions in this dataset.
4. A real bank onboards new accounts continuously, so this rule would produce far more false alerts there. Treat the result as
   simulator-specific and validate on another AMLSim run (different seed/config) or another dataset before generalising.
5. Fan-in / fan-out lead times are not evaluable without truncation here. Their truncated lead is about 0 days.

Suggested wording for the thesis: *"On AMLSim, cycle rings can be warned a median of 12 days before closure using
account-history novelty, but the same result is obtained by a two-feature newness rule, and it reflects the simulator's
dormant-account construction; it is not evidence of general early-warning capability."*

## Notes

* `check_lineage.py` expects the SQLite database at `data/aml.db` (or `DATABASE_URL=sqlite:///...`).
  It only touches text columns that contain float-formatted IDs; amounts and timestamps are left alone.
* `--rebuild-evidence` re-derives an evidence record's transactions and subgraph from `transactions_clean.csv` only where the
  candidate lists transactions the evidence lacks (the symptom of the float-ID join failure).
* The "6 accounts" in a candidate's behavioural-score text is stored text from an earlier run; it is not recomputed.
* Numbers are deterministic for a fixed seed; small differences across XGBoost versions are possible.
