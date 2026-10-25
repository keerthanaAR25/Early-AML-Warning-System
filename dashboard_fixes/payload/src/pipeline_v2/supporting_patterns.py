"""
Supporting patterns (ADDITIVE): the other patterns the ORIGINAL detectors saw on a candidate's accounts, shown for context.

They are NOT used in any candidate or score (a test checks that nothing here feeds back). Window: from 7 days before the candidate's first
evidence to its latest evidence. Because the original detectors fire far more often on normal traffic than on rings in AMLSim, this module also
measures how well they separate rings from normal accounts, so the page can say so with numbers instead of leaving the impression of strong evidence.
Ring fields are AMLSim ground truth and are used only to evaluate.
"""
from __future__ import annotations

from collections import defaultdict

import numpy as np
from scipy.stats import mannwhitneyu
from sklearn.metrics import roc_auc_score

from src.pipeline_v2.export import iso

LOOKBACK_DAYS = 7


def norm(a):
    try:
        return str(int(float(a)))
    except (TypeError, ValueError):
        return str(a)


def _index(events):
    by_acct = defaultdict(list)
    for i, e in enumerate(events):
        d = int(float(e["window_id"]))
        for a in e["accounts"]:
            by_acct[norm(a)].append((d, e["pattern_type"], i))
    return by_acct


def build(cands, index, S, R, day_of, label_of, tx, events, own_patterns, day0, s, lookback=LOOKBACK_DAYS):
    by_acct = _index(events)
    out, n_types, contains = {}, [], []
    for ci, c in enumerate(cands):
        rid = index[ci]
        nodes = {x for t in c["tx"] for x in (S[t], R[t])}
        days = [day_of[t] for t in c["tx"]]
        lo, hi = min(days) - lookback, max(days)
        hits = defaultdict(lambda: {"events": set(), "accounts": set(), "days": []})
        for a in nodes:
            for d, typ, i in by_acct.get(norm(a), ()):
                if lo <= d <= hi:
                    h = hits[typ]
                    h["events"].add(i); h["accounts"].add(a); h["days"].append(d)
        types = sorted(({"pattern": typ, "events": len(h["events"]), "accounts_involved": len(h["accounts"]), "first_date": iso(day0, min(h["days"])),
                         "last_date": iso(day0, max(h["days"])), "also_in_candidate": typ in own_patterns.get(rid, [])} for typ, h in hits.items()),
                       key=lambda x: (-x["events"], x["pattern"]))
        out[rid] = {"n_types": len(types), "types": types}
        n_types.append(len(types))
        contains.append(any(label_of.get(t, 0) == 1 for t in c["tx"]))
    n_types, contains = np.array(n_types), np.array(contains)

    # does the presence of these patterns separate rings from normal traffic? (sender level, scored period, last `lookback` days)
    scored = tx[tx["day"] >= s.scored_from]
    normal = scored[scored["label"] == 0]
    ring_tx, norm_tx = scored[scored["label"] == 1], normal.sample(min(30000, len(normal)), random_state=s.seed)
    def shows(t):
        d = day_of[t]
        return any(d - lookback < dd <= d for dd, _, _ in by_acct.get(norm(S[t]), ()))
    share = lambda ids: float(np.mean([shows(t) for t in ids])) if len(ids) else None
    pr, pn = share(ring_tx["transaction_id"]), share(norm_tx["transaction_id"])
    both = 0 < contains.sum() < len(contains)
    dist = {str(k): int((n_types == k).sum()) for k in range(0, 4)}
    dist["4+"] = int((n_types >= 4).sum())
    summary = {
        "n_candidates": len(cands), "with_any_supporting_pattern": int((n_types > 0).sum()), "distribution_of_types_per_candidate": dist,
        "candidates_with_ring_tx": int(contains.sum()),
        "share_with_supporting_pattern": {"ring_containing": float((n_types[contains] > 0).mean()) if contains.any() else None,
                                          "others": float((n_types[~contains] > 0).mean()) if (~contains).any() else None},
        "mean_types": {"ring_containing": float(n_types[contains].mean()) if contains.any() else None, "others": float(n_types[~contains].mean()) if (~contains).any() else None},
        "auc_types_vs_ring_containing": float(roc_auc_score(contains, n_types)) if both else None,
        "mannwhitney_p_more_types_in_ring_containing": float(mannwhitneyu(n_types[contains], n_types[~contains], alternative="greater").pvalue) if both else None,
        "sender_level": {"ring_transactions": int(len(ring_tx)), "normal_transactions_sampled": int(len(norm_tx)), "share_ring": pr, "share_normal": pn, "lift": pr / pn if (pr is not None and pn) else None}}
    return {"protocol": {"source": "original pattern detectors (results/v1_backup/pattern_events.json)", "events_used": len(events), "lookback_days": lookback,
                         "window": f"from {lookback} days before the candidate's first evidence to its latest evidence"},
            "summary": summary, "candidates": out,
            "caveats": ["These patterns are shown for context and are not used in any candidate or score.",
                        "Ring fields are AMLSim ground truth and are used only to evaluate."]}
