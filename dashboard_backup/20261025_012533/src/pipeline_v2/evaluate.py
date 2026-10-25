"""Production evaluation: ONE evaluation of the production candidates (ADDITIVE). Labels are read here, and only here."""
from __future__ import annotations

from pathlib import Path

import numpy as np

from src.evaluation import candidates_v2 as C
from src.pipeline_v2.core import alert_day


def dedupe_sources(structs, novelty, min_overlap=0.5):
    """A first-time-account group that mostly re-describes a structure candidate is dropped (the structure candidate has richer evidence)."""
    struct_tx = [c["tx"] for c in structs]
    kept = []
    for g in novelty:
        n = len(g["tx"])
        if any(len(g["tx"] & st) / n >= min_overlap for st in struct_tx if st & g["tx"]):
            continue
        kept.append(g)
    return kept


def _cd(c, day=None):
    return {"tx": set(c["tx"]), "nodes": set(c["nodes"]), "creation_day": c["creation_day"] if day is None else day}


def evaluate_all(cands, history, tx, rings, ring_of, label_of, day_of, s, v1_path=None):
    from sklearn.metrics import roc_auc_score
    max_day = int(tx["day"].max())
    days_scored = max_day - s.scored_from + 1
    final = [h[-1] for h in history]
    adays = [alert_day(h, s.alert_threshold) for h in history]
    sets = {
        "production_alerted": [_cd(c, a) for c, a in zip(cands, adays) if a is not None],
        "production_all": [_cd(c) for c in cands],
        "structure_only": [_cd(c) for c in cands if c["source"] != "novelty_seeded"],
        "novelty_only": [_cd(c) for c in cands if c["source"] == "novelty_seeded"],
    }
    if v1_path and Path(v1_path).exists():
        sets["v1_pattern_trajectory"] = C.load_v1(v1_path)
    summaries, per_ring = {}, {}
    for name, lst in sets.items():
        summaries[name], per_ring[name] = C.evaluate_candidate_set(name, lst, tx, rings, ring_of, label_of, day_of, s.scored_from, max_day, s.seed)
    contains = np.array([any(label_of.get(t, 0) == 1 for t in c["tx"]) for c in cands])
    scores = np.array([f["score"] for f in final])
    order = np.argsort(-scores, kind="stable")
    ranking = {"n_candidates": int(len(cands)), "n_containing_ring_tx": int(contains.sum()),
               "auc_score_vs_contains_ring_tx": float(roc_auc_score(contains, scores)) if 0 < contains.sum() < len(contains) else None,
               "precision_at_k": {str(k): float(contains[order[:k]].mean()) for k in (10, 20, 50) if len(cands) >= k}}
    alerted = [i for i, a in enumerate(adays) if a is not None]
    hit = int(contains[alerted].sum()) if alerted else 0
    alerts = {"threshold": s.alert_threshold, "n_alerted": len(alerted), "alerted_containing_ring_tx": hit,
              "alert_precision": hit / len(alerted) if alerted else None,
              "false_alerts_per_day": (len(alerted) - hit) / days_scored, "scored_days": days_scored,
              "level_counts": {lv: int(sum(1 for f in final if f["level"] == lv)) for lv in ("CRITICAL", "HIGH", "MODERATE", "LOW")}}
    frontier = []                                       # operating points of the SAME evaluation; the configured threshold is one of them, not a tuned choice
    for thr in sorted({30, 35, 40, 45, 50, 55, s.alert_threshold}):
        ad = [alert_day(h, thr) for h in history]
        lst = [_cd(c, a) for c, a in zip(cands, ad) if a is not None]
        if not lst:
            frontier.append({"threshold": thr, "n_alerted": 0})
            continue
        sm, _ = C.evaluate_candidate_set("t", lst, tx, rings, ring_of, label_of, day_of, s.scored_from, max_day, s.seed)
        g = sm["by_typology"]["all"]
        idx = [i for i, a in enumerate(ad) if a is not None]
        frontier.append({"threshold": thr, "n_alerted": len(idx), "alert_precision": float(contains[idx].mean()),
                         "false_alerts_per_day": float((len(idx) - contains[idx].sum()) / days_scored), "rings_seen": g["n_with_any_tx_in_candidate"],
                         "n_evaluable_rings": g["n_evaluable_rings"], "warned_before_completion": g["n_warned_before_observable"],
                         "lead_days_median": g["lead_days_median"], "configured": thr == s.alert_threshold})
    alerts["frontier"] = frontier
    return summaries, per_ring, ranking, alerts


def lead_time_summary(summaries, ranking, alerts, s, n_rings_total):
    head = summaries["production_alerted"]
    allc = summaries["production_all"]
    g = head["by_typology"]["all"]
    return {
        "evaluation_unit": "ring",
        "headline": "production_alerted",
        "protocol": {"burn_in_days": s.burn_in, "scored_from_day": s.scored_from, "horizon_days": s.horizon, "alert_threshold": s.alert_threshold,
                     "observable_k": s.observable_k, "model_blocks": "one model per %d-day block, trained only on earlier data" % s.block_len},
        "rings": {"n_labelled": n_rings_total, "n_evaluable": g["n_evaluable_rings"], "n_seen": g["n_with_any_tx_in_candidate"],
                  "ring_recall": g["ring_recall"], "n_warned_before_completion": g["n_warned_before_observable"],
                  "warned_before_completion_rate": g["warned_before_observable_rate"], "lead_days_median": g["lead_days_median"],
                  "lead_days_median_ci95": g["lead_days_median_ci95"], "lead_days_q25": g["lead_days_q25"], "lead_days_q75": g["lead_days_q75"],
                  "lead_vs_first_tx_median": g["lead_vs_first_tx_median"], "mean_tx_coverage_of_ring": g["mean_tx_coverage_of_ring"]},
        "alerted_candidates": {**alerts, "ring_tx_share_of_evidence": head["ring_tx_share_of_evidence"], "enrichment_vs_background": head["enrichment_vs_background"],
                               "ring_tx_recall": head["ring_tx_recall"]},
        "all_candidates": {"n_candidates": allc["n_candidates"], "ring_tx_share_of_evidence": allc["ring_tx_share_of_evidence"],
                           "enrichment_vs_background": allc["enrichment_vs_background"], "false_candidates_per_day": allc["false_candidates_per_day"],
                           "ring_tx_recall": allc["ring_tx_recall"], "rings_seen": allc["by_typology"]["all"]["n_with_any_tx_in_candidate"],
                           "warned_before_completion": allc["by_typology"]["all"]["n_warned_before_observable"],
                           "lead_days_median": allc["by_typology"]["all"]["lead_days_median"]},
        "ranking": ranking,
        "frontier": alerts.get("frontier", []),
        "by_typology": head["by_typology"],
        "definitions": {
            "observable_time": "cycle: day of the closing (last) edge; fan: day the %d-th distinct counterparty has transacted" % s.observable_k,
            "warning_time": "first day the candidate's risk score (computed only from evidence up to that day) reaches the alert threshold and the candidate contains a transaction of the ring",
            "lead_time": "observable_day - warning_day in days; positive = warned before the ring was complete",
            "evaluable_ring": "all transactions of the ring fall in the scored period (first day >= scored_from) and it completes inside the data"},
        "caveats": [
            "AMLSim-specific shortcut: ring members are drawn from otherwise-dormant accounts, so first-time accounts are unusually informative here.",
            "Only cycle rings are fully evaluable: fan rings take longer than the data allows to start and finish inside the scored period.",
            "Warnings arrive with the ring's first transactions, so lead is measured against ring completion, not against a ring's start.",
            "Labels are used only to train earlier blocks and to evaluate; never to build candidates or scores."],
    }
