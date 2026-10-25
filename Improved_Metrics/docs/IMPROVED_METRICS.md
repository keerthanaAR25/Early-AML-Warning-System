# IMPROVED METRICS -- account-window early warning, leakage-safe protocol

Four new files; nothing existing is modified. Needs `Additions_complete.zip` extracted first (it provides `ring_lead_time.py`).

```powershell
Expand-Archive Improved_Metrics.zip -DestinationPath . -Force
python -m pytest tests/test_account_window_eval.py -q          # expect 11 passed
python scripts/run_account_window_eval.py                       # about 2 minutes
start reports\account_window_eval_report.html
```

## What it does

It rebuilds the dashboard task (account active on day t AND in a ring transaction within the next H days; at H=2 it reproduces your test set
exactly: 653,487 rows, 32 positives) and evaluates it with a protocol that cannot leak: 120-day training burn-in, a purge gap of H days at each
split boundary, the decision threshold chosen on the **validation** period only (max F1), the test period scored once, and every horizon
(2, 7, 14 days) reported with and without account-history features.

## Results on your data (test period = days 576-719, never used for any choice)

| | Positives (accounts) | PR-AUC | Precision (Wilson 95%) | TP / FP | Positive accounts caught (Wilson 95%) | False-positive rate |
|---|---|---|---|---|---|---|
| **Dashboard as shown (H=2)** | 32 | 0.078 | 0.294 | 5 / 12 | not reported | 1.8e-5 |
| H=2, activity features, validation threshold | 32 (27) | 0.081 | 0.32 (0.17-0.52) | 8 / 17 | 8/27 (0.16-0.48) | 2.6e-5 |
| H=2, + account history | 32 (27) | 0.105 | 0.40 (0.22-0.61) | 8 / 12 | 8/27 (0.16-0.48) | 1.8e-5 |
| H=7, activity features | 81 (53) | 0.163 | 0.72 (0.52-0.86) | 18 / 7 | 18/53 (0.23-0.47) | 1.1e-5 |
| H=7, + account history | 81 (53) | 0.128 | 0.65 (0.43-0.82) | 13 / 7 | 13/53 (0.15-0.38) | 1.1e-5 |
| **H=14, activity features** | 118 (59) | 0.139 | **0.80 (0.61-0.91)** | 20 / 5 | 20/59 (0.23-0.47) | **8.0e-6** |
| H=14, + account history | 118 (59) | 0.120 | 0.75 (0.53-0.89) | 15 / 5 | 15/59 (0.16-0.38) | 8.0e-6 |

## How to read this honestly

1. **Where the gain really is.** At the same task (H=2) the improvement is small and inside the uncertainty (8 hits instead of 5, same 12
   false alarms). The clear gain is at longer horizons: precision 0.80 with a lower bound of 0.61 (well above the dashboard's 0.294) and a
   false-positive rate less than half the dashboard's, with 118 positives from 59 accounts instead of 32 from 27.
2. **It comes from a better-posed task and protocol, not a better model.** Account-history features do **not** help consistently (they score
   lower than plain activity features at H=7 and H=14). Do not present them as the source of improvement.
3. **Horizon is a choice, and it was made after seeing results.** Cycle rings in this dataset span a median of 12 days (max 19), which motivates
   H=14, but all three horizons are reported on purpose. Say so in the thesis. H=2 stays as the like-for-like comparison.
4. **Recall is still low.** Even at the best setting only about a third of the positive accounts are caught (20 of 59, Wilson 0.23-0.47).
5. **The PR-AUC "bootstrap range" in the JSON is not a confidence interval.** With few positive accounts the statistic is skewed and the range
   can sit above the estimate (e.g. H=7 with history: estimate 0.128, range 0.135-0.378). Quote the Wilson intervals for precision and recall instead.
6. **ROC-AUC is deliberately not headlined.** Because only active accounts can be positive, merely counting an account's transactions that day
   gives ROC-AUC 0.96; it says nothing about early warning.
7. The account-window task still does not measure *ring* early warning. For that, use `reports/ring_lead_time_report.html`.

Suggested wording: *"With a leakage-safe protocol (burn-in, purged splits, validation-selected threshold) and a 14-day forecast horizon matching
the typology's formation span, precision at the validation-chosen operating point was 0.80 (Wilson 95% 0.61-0.91) with 5 false alarms in
653,487 test rows, versus 0.294 for the original 2-day setup; recall remained limited (20 of 59 positive accounts)."*
