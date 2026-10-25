#!/usr/bin/env python3
"""
Rebuild every result the dashboard reads from ONE configuration (pipeline v2). Reads data/processed/transactions_clean.csv,
data/raw/amlsim/alert_transactions.csv and configs/config.yaml (risk_scoring). Backs up the v1 results to results/v1_backup first.

Stages (run `all`, or one at a time -- each is resumable and writes to results/v2_work/):
  candidates   build candidates (structure + first-time-account groups), scored period only
  scoring      out-of-sample, as-of-day risk scores for every candidate
  models       the four model families under one protocol
  export       evaluate, write ring_candidates / risk_scores / evidence / pattern_events / trajectories / model_comparison / lead_time_summary
then:  python scripts/load_database.py   and restart the API.

  python scripts/rebuild_v2.py all
"""
import argparse
import json
import pickle
import shutil
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.evaluation import account_window_eval as AW  # noqa: E402
from src.evaluation import candidates_v2 as C  # noqa: E402
from src.evaluation.ring_lead_time import build_features, load_alert_transactions, load_transactions, ring_table  # noqa: E402
from src.pipeline_v2 import core, evaluate, export, models  # noqa: E402

WORK = ROOT / "results" / "v2_work"
# v1 artifacts that describe the OLD candidates, lead time or model run. They are moved to results/v1_backup (never deleted) so
# nothing on disk can contradict the rebuilt results. Revert: copy results/v1_backup/* back over results/.
STALE_V1 = ["forensic_explanations.json", "lead_time_results.json", "lead_time.csv", "candidate_ground_truth_diagnostic.csv",
            "candidate_temporal_ground_truth.csv", "candidate_temporal_ground_truth_summary.json", "amlsim_alert_candidate_diagnostic.csv",
            "early_warning_ground_truth.csv", "trajectory_features.csv", "shap_global_importance.json", "proposed_model_feature_importances.json",
            "ablation_results.csv", "baseline_metrics.json", "class_weight_experiment.csv", "class_weight_experiment.json",
            "selected_proposed_model_config.json", "metrics.json", "predictions.csv",
            "alert_transaction_ground_truth.csv", "alert_transaction_ground_truth_summary.json",
            "candidate_quality_v2.json", "candidate_quality_v2_rings.csv", "ring_candidates_v2.json", "ring_candidates_v2_meta.json"]
V1_FILES = ["ring_candidates.json", "ring_candidates.csv", "risk_scores.json", "risk_scores.csv", "evidence.json", "pattern_events.json",
            "pattern_events.csv", "trajectories.json", "model_comparison.json", "model_comparison.csv", "lead_time_summary.json",
            "lead_time_results.json", "lead_time.csv", "metrics.json"]


def prepare(a, s):
    tx, day0 = load_transactions(a.clean)
    at = load_alert_transactions(a.alerts, tx)
    tx_nl = tx.drop(columns=["label"])
    F = build_features(tx_nl)
    ids = tx["transaction_id"].values
    info = {"S": dict(zip(ids, tx["sender"].values)), "R": dict(zip(ids, tx["receiver"].values)), "A": dict(zip(ids, tx["amount"].values))}
    flags = {"sfo": dict(zip(F["transaction_id"].values, F["s_first_out"].values)), "rfi": dict(zip(F["transaction_id"].values, F["r_first_in"].values))}
    return tx, day0, at, tx_nl, F, info, flags, dict(zip(ids, tx["day"].values))


def stage_candidates(a, s):
    t0 = time.time()
    tx, day0, at, tx_nl, F, info, flags, day_of = prepare(a, s)
    structs = C.detect_structures(tx_nl, window_days=s.window_days)
    raw_nov = C.detect_novelty_groups(tx_nl, F, s.burn_in, s.seed_gap, s.hub_gap, min_seeds=1, mode=s.novelty_mode)
    prod_nov = C.detect_novelty_groups(tx_nl, F, s.burn_in, s.seed_gap, s.hub_gap, min_seeds=s.min_seeds, mode=s.novelty_mode)
    structs = [c for c in structs if c["creation_day"] >= s.scored_from]
    prod_nov = evaluate.dedupe_sources(structs, [c for c in prod_nov if c["creation_day"] >= s.scored_from])
    raw = structs + evaluate.dedupe_sources(structs, [c for c in raw_nov if c["creation_day"] >= s.scored_from])
    cands = structs + prod_nov
    WORK.mkdir(parents=True, exist_ok=True)
    pickle.dump({"cands": cands, "raw": raw}, open(WORK / "candidates.pkl", "wb"))
    print(f"candidates: {len(cands)} production ({len(structs)} structure + {len(prod_nov)} first-time-account groups), {len(raw)} raw episodes [{time.time() - t0:.0f}s]")


def stage_scoring(a, s):
    t0 = time.time()
    tx, day0, at, tx_nl, F, info, flags, day_of = prepare(a, s)
    cands = pickle.load(open(WORK / "candidates.pkl", "rb"))["cands"]
    state = AW.build_state(tx)
    Y = AW.label_matrix(state, s.horizon)
    cols = AW.FEATURES_HISTORY
    mods = core.fit_block_models(state, Y, cols, s)
    print("block models:", {b: {"n_train": v[2], "n_train_pos": v[3]} for b, v in mods.items()}, f"[{time.time() - t0:.0f}s]")
    hist = core.score_candidates(cands, state, mods, cols, info, day_of, flags, s)
    pickle.dump({"history": hist, "blocks": {b: {"n_train": v[2], "n_train_pos": v[3]} for b, v in mods.items()}}, open(WORK / "scoring.pkl", "wb"))
    top = sorted((h[-1]["score"] for h in hist), reverse=True)[:5]
    print(f"scored {len(hist)} candidates, top scores {top} [{time.time() - t0:.0f}s]")


def stage_models(a, s, only=None):
    t0 = time.time()
    tx, *_ = prepare(a, s)
    state = AW.build_state(tx)
    Y = AW.label_matrix(state, s.horizon)
    WORK.mkdir(parents=True, exist_ok=True)
    out_path = WORK / "models.json"
    out = json.load(open(out_path)) if out_path.exists() else {}
    for name in models.FAMILIES:
        if only and name != only:
            continue
        out[name] = models.evaluate_family(state, Y, name, s)
        t = out[name]["test"]
        print(f"  {name:40s} PR-AUC={t['pr_auc']:.4f} precision={t['precision']:.3f} recall={t['recall']:.3f} FP={t['confusion_matrix']['fp']} [{time.time() - t0:.0f}s]", flush=True)
        json.dump(out, open(out_path, "w"))


def stage_export(a, s):
    t0 = time.time()
    tx, day0, at, tx_nl, F, info, flags, day_of = prepare(a, s)
    pk = pickle.load(open(WORK / "candidates.pkl", "rb"))
    cands, raw = pk["cands"], pk["raw"]
    hist = pickle.load(open(WORK / "scoring.pkl", "rb"))["history"]
    mdl = json.load(open(WORK / "models.json"))
    res = ROOT / "results"
    bak = res / "v1_backup"
    bak.mkdir(exist_ok=True)
    for f in V1_FILES:                                   # keep the v1 results, once
        if (res / f).exists() and not (bak / f).exists():
            shutil.copy2(res / f, bak / f)
    archived = []
    for f in STALE_V1:                                   # move (not delete) what would contradict the rebuilt results
        if (res / f).exists():
            if not (bak / f).exists():
                shutil.move(str(res / f), str(bak / f))
            else:
                (res / f).unlink()
            archived.append(f)
    (bak / "lineage_repair_backups").mkdir(exist_ok=True)
    for b in res.glob("*.bak"):                          # backups made by check_lineage --fix hold v1 ids
        shutil.move(str(b), str(bak / "lineage_repair_backups" / b.name))
        archived.append(b.name)
    rings = ring_table(at, k=s.observable_k)
    ring_of = dict(zip(at["transaction_id"], at["alert_id"].astype(str)))
    label_of = dict(zip(tx["transaction_id"], tx["label"]))
    summaries, per_ring, ranking, alerts = evaluate.evaluate_all(cands, hist, tx, rings, ring_of, label_of, day_of, s, bak / "ring_candidates.json")
    art = export.build_artifacts(cands, hist, info, day_of, flags, day0, s, raw)
    dump = lambda name, obj: json.dump(obj, open(res / name, "w"), indent=1, default=str)
    dump("ring_candidates.json", art["ring_candidates"])
    dump("risk_scores.json", art["risk_scores"])
    dump("evidence.json", art["evidence"])
    dump("pattern_events.json", art["pattern_events"])
    dump("trajectories.json", art["trajectories"])
    dump("model_comparison.json", {k: {"val": v["val"], "test": v["test"], "threshold_selection": v["threshold_selection"]} for k, v in mdl.items()})
    dump("lead_time_summary.json", evaluate.lead_time_summary(summaries, ranking, alerts, s, len(rings)))
    dump("production_evaluation.json", {"parameters": vars(s), "ablations": summaries, "ranking": ranking, "alerts": alerts})
    dump("protocol.json", {"horizon_days": s.horizon, "burn_in_days": s.burn_in, "scored_from_day": s.scored_from, "block_len_days": s.block_len,
                           "purge": "H days at every boundary", "threshold_rule": "max F1 on validation",
                           "model_protocols": {k: v["protocol"] for k, v in mdl.items()}})
    import pandas as pd
    pd.concat(per_ring.values()).to_csv(res / "production_evaluation_rings.csv", index=False)
    # CSV companions regenerated from the same data, so no CSV still describes the old run
    pd.DataFrame([{"candidate_ring_id": c["candidate_ring_id"], "n_accounts": len(c["accounts"]), "n_transactions": len(c["transaction_ids"]),
                   "formation_stage": c["formation_stage"], "risk_score": c["risk_score"], "patterns": ";".join(c["patterns"]),
                   "start": c["time_span"][0], "end": c["time_span"][1]} for c in art["ring_candidates"]]).to_csv(res / "ring_candidates.csv", index=False)
    pd.DataFrame([{"candidate_ring_id": r["candidate_ring_id"], "risk_score": r["risk_score"], "risk_level": r["risk_level"], **r["score_components"]}
                  for r in art["risk_scores"]]).to_csv(res / "risk_scores.csv", index=False)
    pd.DataFrame([{**{k: v for k, v in e.items() if k not in ("accounts", "transaction_ids", "evidence")}, "n_accounts": len(e["accounts"]),
                   "n_transactions": len(e["transaction_ids"]), "candidate_ring_id": e["evidence"]["candidate_ring_id"]} for e in art["pattern_events"]]).to_csv(res / "pattern_events.csv", index=False)
    pd.DataFrame([{"method": k, "split": sp, **{m: v for m, v in mdl[k][sp].items() if m not in ("confusion_matrix", "top_k_precision")},
                   **{f"cm_{a}": b for a, b in mdl[k][sp]["confusion_matrix"].items()}} for k in mdl for sp in ("val", "test")]).to_csv(res / "model_comparison.csv", index=False)
    g = summaries["production_alerted"]["by_typology"]["all"]
    print(f"exported {len(cands)} candidates; alerted {alerts['n_alerted']}; rings seen {g['n_with_any_tx_in_candidate']} of {g['n_evaluable_rings']}; "
          f"median lead {g['lead_days_median']}; false alerts/day {alerts['false_alerts_per_day']:.2f}; v1 backed up in {bak}; {len(archived)} stale v1 files archived [{time.time() - t0:.0f}s]")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=["candidates", "scoring", "models", "export", "all"])
    ap.add_argument("--clean", default=str(ROOT / "data/processed/transactions_clean.csv"))
    ap.add_argument("--alerts", default=str(ROOT / "data/raw/amlsim/alert_transactions.csv"))
    ap.add_argument("--family", default=None, help="models stage: evaluate one family only")
    ap.add_argument("--horizon", type=int, default=None)
    a = ap.parse_args()
    s = core.load_settings(ROOT, horizon=a.horizon)
    stages = ["candidates", "scoring", "models", "export"] if a.stage == "all" else [a.stage]
    for st in stages:
        print(f"== {st}", flush=True)
        {"candidates": stage_candidates, "scoring": stage_scoring, "models": lambda x, y: stage_models(x, y, a.family), "export": stage_export}[st](a, s)


if __name__ == "__main__":
    main()
