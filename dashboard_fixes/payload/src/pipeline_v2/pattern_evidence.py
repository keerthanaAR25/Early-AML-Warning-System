"""
Pattern evidence (ADDITIVE): how the number and kind of patterns relate to the risk score and to the alerts, computed from the same
candidates and scores as everything else. Ring labels are used only to say whether a candidate contains ring transactions (evaluation only).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.stats import fisher_exact, spearmanr

from src.pipeline_v2 import core

SIZE_BINS = [(0, 3, "2-3 transactions"), (3, 6, "4-6 transactions"), (6, 10, "7-10 transactions"), (10, 10 ** 6, "11 or more")]


def _f(x):
    return None if x is None or (isinstance(x, float) and np.isnan(x)) else float(x)


def build_pattern_evidence(art, cands, index, label_of, warnings, s):
    rc = {c["candidate_ring_id"]: c for c in art["ring_candidates"]}
    rs = {r["candidate_ring_id"]: r for r in art["risk_scores"]}
    alerted = {a["candidate_ring_id"]: a for a in warnings["alerts"]}
    rows = []
    for ci, c in enumerate(cands):
        rid = index[ci]
        pats = rc[rid]["patterns"]
        comp = rs[rid]["score_components"]
        rows.append({"id": rid, "n": len(pats), "patterns": sorted(pats), "key": "+".join(sorted(pats)), "score": float(rs[rid]["risk_score"]), "level": rs[rid]["risk_level"],
                     "alerted": rid in alerted, "contains": any(label_of.get(t, 0) == 1 for t in c["tx"]), "n_tx": len(c["tx"]), **comp})
    d = pd.DataFrame(rows)
    comps = list(s.weights)

    def agg(g):
        o = {"candidates": int(len(g)), "mean_score": float(g.score.mean()), "min_score": float(g.score.min()), "max_score": float(g.score.max()),
             "alerts_given": int(g.alerted.sum()), "high": int((g.level == "HIGH").sum()), "critical": int((g.level == "CRITICAL").sum()),
             "moderate": int((g.level == "MODERATE").sum()), "low": int((g.level == "LOW").sum()),
             "contain_ring_tx": int(g.contains.sum()), "share_containing_ring_tx": float(g.contains.mean()), "mean_evidence_tx": float(g.n_tx.mean())}
        o.update({f"mean_{k}": float(g[k].mean()) for k in comps})
        return o

    by_count = [{"n_patterns": int(n), **agg(g)} for n, g in d.groupby("n")]
    by_set = sorted(({"patterns": k.split("+"), **agg(g)} for k, g in d.groupby("key")), key=lambda x: -x["mean_score"])
    one, multi = d[d.n == 1], d[d.n >= 2]
    sp = spearmanr(d.n, d.score) if d.n.nunique() > 1 else None
    tab = [[int(multi.contains.sum()), int((~multi.contains).sum())], [int(one.contains.sum()), int((~one.contains).sum())]]
    by_size = []
    for lo, hi, label in SIZE_BINS:
        g = d[(d.n_tx > lo) & (d.n_tx <= hi)]
        by_size.append({"size": label, "single_pattern": int((g.n == 1).sum()), "single_contain": int(g[g.n == 1].contains.sum()),
                        "multi_pattern": int((g.n >= 2).sum()), "multi_contain": int(g[g.n >= 2].contains.sum())})
    internal_of = {}
    for internal, old in core.OLD_NAME.items():
        internal_of.setdefault(old, []).append(internal)
    contributions = []
    for old, internals in internal_of.items():
        w = max(core.PATTERN_WEIGHT[i] for i in internals)
        ff = w / core.MAX_PATTERN_WEIGHT * 100
        contributions.append({"pattern": old, "weight": w, "fund_flow_points": ff, "score_points": ff * s.weights["fund_flow"]})
    contributions.sort(key=lambda x: -x["weight"])
    mult = []
    for r in multi.sort_values("score", ascending=False).itertuples():
        a = alerted.get(r.id)
        mult.append({"candidate_ring_id": r.id, "patterns": r.patterns, "current_score": r.score, "current_level": r.level, "alert_date": a["alert_date"] if a else None,
                     "score_at_alert": a["score_at_alert"] if a else None, "contains_ring_tx": bool(r.contains), "n_tx": int(r.n_tx),
                     "components": {k: float(getattr(r, k)) for k in comps}})
    return {
        "n_candidates": int(len(d)), "component_weights": dict(s.weights), "alert_threshold": s.alert_threshold,
        "single_pattern_candidates": int(len(one)), "multi_pattern_candidates": int(len(multi)),
        "alerts_on_single_pattern": int(one.alerted.sum()), "alerts_on_multi_pattern": int(multi.alerted.sum()),
        "spearman_count_vs_score": None if sp is None else {"rho": _f(sp[0]), "p": _f(sp[1])},
        "multi_vs_single_contain_ring_tx": {"table": tab, "fisher_p": float(fisher_exact(tab)[1]) if multi.shape[0] and one.shape[0] else None},
        "by_count": by_count, "by_set": by_set, "by_size": by_size, "pattern_contributions": contributions, "multi_pattern": mult,
        "notes": ["Ring-transaction fields are AMLSim ground truth and are used only to evaluate.",
                  "Every AMLSim ring has a single type (cycle, fan-in or fan-out), so one pattern is the expected shape of a ring.",
                  "Candidates with several patterns are also the largest ones, so pattern count and size cannot be separated with this few cases."]}
