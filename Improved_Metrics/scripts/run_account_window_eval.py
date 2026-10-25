#!/usr/bin/env python3
"""
Re-evaluate the account-window early-warning task with a leakage-safe protocol, at horizons 2/7/14 days, with and without account-history
features, with account-cluster bootstrap intervals. Reads data/processed/transactions_clean.csv (and results/model_comparison.json for the
dashboard baseline column). Writes NEW files only: results/account_window_eval_v2.json, reports/account_window_eval_report.html.

  python scripts/run_account_window_eval.py
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.evaluation import account_window_eval as E  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--clean", default=str(ROOT / "data/processed/transactions_clean.csv"))
    ap.add_argument("--out-dir", default=str(ROOT / "results"))
    ap.add_argument("--report-dir", default=str(ROOT / "reports"))
    ap.add_argument("--horizons", type=int, nargs="+", default=[2, 7, 14])
    ap.add_argument("--burn-in", type=int, default=120)
    ap.add_argument("--n-boot", type=int, default=300)
    ap.add_argument("--seed", type=int, default=42)
    a = ap.parse_args()
    E.run(a.clean, a.out_dir, a.report_dir, tuple(a.horizons), a.burn_in, a.seed, a.n_boot,
          model_comparison_path=ROOT / "results" / "model_comparison.json")
    print(f"\nWrote {a.out_dir}/account_window_eval_v2.json and {a.report_dir}/account_window_eval_report.html")


if __name__ == "__main__":
    main()
