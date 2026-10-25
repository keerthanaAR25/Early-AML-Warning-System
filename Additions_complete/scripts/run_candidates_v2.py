#!/usr/bin/env python3
"""
Build second-source ring candidates and compare candidate quality + ring-level early warning against your v1 candidates.
Reads data/processed/transactions_clean.csv, data/raw/amlsim/alert_transactions.csv and (optionally) results/ring_candidates.json.
Writes NEW files only:
  results/candidate_quality_v2.json, results/candidate_quality_v2_rings.csv,
  results/ring_candidates_v2.json (+ _meta.json), reports/candidate_quality_report.html

  python scripts/run_candidates_v2.py
"""
import argparse
import json
import sys
import time
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.evaluation import candidates_v2 as C  # noqa: E402
from src.evaluation.ring_lead_time import build_features, load_alert_transactions, load_transactions, ring_table  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--clean", default=str(ROOT / "data/processed/transactions_clean.csv"))
    ap.add_argument("--alerts", default=str(ROOT / "data/raw/amlsim/alert_transactions.csv"))
    ap.add_argument("--v1", default=str(ROOT / "results/ring_candidates.json"))
    ap.add_argument("--out-dir", default=str(ROOT / "results"))
    ap.add_argument("--report-dir", default=str(ROOT / "reports"))
    ap.add_argument("--burn-in", type=int, default=120)
    ap.add_argument("--window-days", type=int, default=21)
    ap.add_argument("--seed-gap", type=int, default=30)
    ap.add_argument("--hub-gap", type=int, default=150)
    ap.add_argument("--observable-k", type=int, default=4)
    ap.add_argument("--seed", type=int, default=42)
    a = ap.parse_args()
    t0 = time.time()

    tx, day0 = load_transactions(a.clean)
    at = load_alert_transactions(a.alerts, tx)
    rings = ring_table(at, k=a.observable_k)
    tx_nl = tx.drop(columns=["label"])            # candidate builders never see labels
    feats = build_features(tx_nl)
    max_day = int(tx["day"].max())
    print(f"transactions={len(tx):,} rings={len(rings)} burn_in={a.burn_in}", flush=True)

    struct = C.detect_structures(tx_nl, window_days=a.window_days)
    print(f"structure candidates: {len(struct)} (closed cycles {sum(c['closed'] for c in struct)}) [{time.time() - t0:.0f}s]", flush=True)
    nov1 = C.detect_novelty_groups(tx_nl, feats, a.burn_in, a.seed_gap, a.hub_gap, min_seeds=1)
    nov2 = C.detect_novelty_groups(tx_nl, feats, a.burn_in, a.seed_gap, a.hub_gap, min_seeds=2)
    nov_snd = C.detect_novelty_groups(tx_nl, feats, a.burn_in, a.seed_gap, a.hub_gap, min_seeds=1, mode="sender")
    print(f"novelty candidates: {len(nov1)} (>=1 seed), {len(nov2)} (>=2 seeds) [{time.time() - t0:.0f}s]", flush=True)

    sets = {}
    if Path(a.v1).exists():
        sets["v1_pattern_trajectory"] = C.load_v1(a.v1)
    sets["v2_structure"] = struct
    sets["v2_novelty_min1_seed"] = nov1
    sets["v2_novelty_min2_seeds"] = nov2
    sets["v2_novelty_sender_only"] = nov_snd
    sets["v2_all_min1_seed"] = struct + nov1

    ring_of = dict(zip(at["transaction_id"], at["alert_id"].astype(str)))
    label_of = dict(zip(tx["transaction_id"], tx["label"]))
    day_of = dict(zip(tx["transaction_id"], tx["day"]))
    results, per_ring = [], []
    for name, cands in sets.items():
        s, pr = C.evaluate_candidate_set(name, cands, tx, rings, ring_of, label_of, day_of, a.burn_in, max_day, a.seed)
        results.append(s); per_ring.append(pr)

    out, rep = Path(a.out_dir), Path(a.report_dir)
    out.mkdir(parents=True, exist_ok=True); rep.mkdir(parents=True, exist_ok=True)
    params = dict(burn_in=a.burn_in, window_days=a.window_days, seed_gap=a.seed_gap, hub_gap=a.hub_gap,
                  observable_k=a.observable_k, seed=a.seed)
    json.dump(dict(parameters=params, results=results), open(out / "candidate_quality_v2.json", "w"), indent=2, default=str)
    pd.concat(per_ring).to_csv(out / "candidate_quality_v2_rings.csv", index=False)
    rows, meta = C.to_schema(sets["v2_all_min1_seed"], tx_nl, day0, "V2-")
    json.dump(rows, open(out / "ring_candidates_v2.json", "w"), indent=2)
    json.dump(meta, open(out / "ring_candidates_v2_meta.json", "w"), indent=2)
    C.render_quality_report(results, params, rep / "candidate_quality_report.html")

    print("\nCANDIDATE QUALITY (candidates created on/after burn-in)")
    print(f"{'set':26s} {'cands':>6s} {'ring-tx share':>14s} {'enrich':>7s} {'false/day':>10s} {'ring-tx recall':>15s}")
    for r in results:
        print(f"{r['candidate_set']:26s} {r['n_candidates']:6d} {100 * (r['ring_tx_share_of_evidence'] or 0):13.2f}% "
              f"{(r['enrichment_vs_background'] or 0):6.1f}x {r['false_candidates_per_day']:10.2f} {100 * (r['ring_tx_recall'] or 0):14.1f}%")
    print("\nRING-LEVEL EARLY WARNING (N = rings starting after burn-in and completing inside the data)")
    for r in results:
        for t, g in r["by_typology"].items():
            if g["n_evaluable_rings"]:
                print(f"{r['candidate_set']:26s} {t:8s} N={g['n_evaluable_rings']:3d} has-tx={g['n_with_any_tx_in_candidate']:3d} "
                      f"before-observable={g['n_warned_before_observable']:3d} median-lead={g['lead_days_median']} CI95={g['lead_days_median_ci95']}")
    print(f"\ndone in {time.time() - t0:.0f}s -> {out}/candidate_quality_v2.json, {rep}/candidate_quality_report.html")


if __name__ == "__main__":
    main()
