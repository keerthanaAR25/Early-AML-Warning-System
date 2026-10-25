#!/usr/bin/env python3
"""
Ring-level lead-time evaluation. Reads data/processed/transactions_clean.csv and the AMLSim
alert_transactions.csv only; writes NEW files (results/ring_lead_time_*.{json,csv},
reports/ring_lead_time_report.html). Does not touch the existing pipeline outputs or the database.

  python scripts/run_ring_lead_time.py
  python scripts/run_ring_lead_time.py --alerts-per-day 5 --burn-in 120 --first-scored-day 240
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.evaluation.ring_lead_time import run_evaluation, ALL_MODELS  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--clean", default=str(ROOT / "data/processed/transactions_clean.csv"))
    ap.add_argument("--alerts", default=str(ROOT / "data/raw/amlsim/alert_transactions.csv"))
    ap.add_argument("--out-dir", default=str(ROOT / "results"))
    ap.add_argument("--report-dir", default=str(ROOT / "reports"))
    ap.add_argument("--burn-in", type=int, default=120)
    ap.add_argument("--first-scored-day", type=int, default=240)
    ap.add_argument("--block-len", type=int, default=120)
    ap.add_argument("--alerts-per-day", type=int, default=5, help="headline daily alert budget")
    ap.add_argument("--observable-k", type=int, default=4)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--n-estimators", type=int, default=200)
    a = ap.parse_args()

    summary, _ = run_evaluation(
        a.clean, a.alerts, a.out_dir, a.report_dir, burn_in=a.burn_in, eval_start=a.first_scored_day,
        block_len=a.block_len, ks=tuple(sorted({1, 3, 5, 10, a.alerts_per_day})), headline_k=a.alerts_per_day,
        observable_k=a.observable_k, seed=a.seed, n_estimators=a.n_estimators, models=ALL_MODELS)

    hm, hk = summary["parameters"]["headline_model"], str(a.alerts_per_day)
    print(f"\nHEADLINE {hm} @ {hk} alerts/day (N = evaluable rings)")
    for name, g in summary["results"][hm][hk]["summary"].items():
        print(f"  {name:8s} N={g['n_evaluable_rings']:3d} detected={g['n_detected']:3d} "
              f"before-observable={g['n_warned_before_observable']:3d} median lead={g['lead_days_median']} "
              f"CI95={g['lead_days_median_ci95']}")
    print("  flags:", summary["results"][hm][hk]["flag_stats"])
    print(f"\nWrote {a.out_dir}/ring_lead_time_summary.json, ring_lead_time_rings.csv, "
          f"ring_lead_time_rings_all_configs.csv and {a.report_dir}/ring_lead_time_report.html")


if __name__ == "__main__":
    main()
