"""
The warning log (ADDITIVE): every alert that was given, and where it falls on each ground-truth ring.

Built by the export stage from the same scored histories as everything else, so it cannot disagree with the Lead-Time page.
An ALERT is the first day a candidate's risk score (computed only from evidence up to that day) reaches the alert threshold.
Ring fields (ring id, type, first transaction, completion, lead, coverage) come from AMLSim ground truth and are EVALUATION ONLY:
they are never used to build a candidate or a score.
"""
from __future__ import annotations

from collections import Counter, defaultdict

import numpy as np
import pandas as pd

from src.pipeline_v2.core import alert_day, old_names
from src.pipeline_v2.export import iso


def _status(detected, lead):
    if not detected or lead is None:
        return "not_seen"
    return "before" if lead > 0 else ("at" if lead == 0 else "after")


def _py(v):
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return None
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating,)):
        return float(v)
    if isinstance(v, (np.bool_,)):
        return bool(v)
    return v


def build_warnings(cands, history, index, per_ring, rings, ring_of, label_of, day_of, tx, day0, s):
    thr, max_day = s.alert_threshold, int(tx["day"].max())
    ring_info = {str(r.ring_id): r for r in rings.itertuples()}
    # ring ids are text in memory and numbers once read back from CSV; every lookup below uses text so the two cannot disagree
    pq = per_ring["production_all"].astype({"ring_id": str}).set_index("ring_id")
    pa = per_ring["production_alerted"].astype({"ring_id": str}).set_index("ring_id")

    ring_cands = defaultdict(dict)                                   # ring -> candidate index -> earliest day of one of the ring's transactions in it
    ring_tx_count = []
    for ci, c in enumerate(cands):
        rr = Counter()
        for t in c["tx"]:
            if label_of.get(t, 0) == 1 and t in ring_of:
                rr[ring_of[t]] += 1
                d = day_of[t]
                if ci not in ring_cands[ring_of[t]] or d < ring_cands[ring_of[t]][ci]:
                    ring_cands[ring_of[t]][ci] = d
        ring_tx_count.append(rr)

    alerts, adays = [], {}
    for ci, c in enumerate(cands):
        a = alert_day(history[ci], thr)
        adays[ci] = a
        if a is None:
            continue
        h = next(x for x in history[ci] if x["day"] == a)
        rr = ring_tx_count[ci]
        rid = rr.most_common(1)[0][0] if rr else None
        info = ring_info.get(str(rid)) if rid is not None else None
        evaluable = bool(pq.loc[str(rid), "evaluable"]) if rid is not None and str(rid) in pq.index else False
        alerts.append({
            "candidate_ring_id": index[ci], "alert_day": int(a), "alert_date": iso(day0, a), "score_at_alert": float(h["score"]), "level_at_alert": h["level"],
            "final_score": float(history[ci][-1]["score"]), "created_day": int(c["creation_day"]), "created_date": iso(day0, c["creation_day"]),
            "days_creation_to_alert": int(a - c["creation_day"]), "patterns": old_names(h["patterns"]), "n_accounts": int(h["n_nodes"]), "n_transactions": int(h["n_tx"]),
            "contains_ring_tx": rid is not None, "ring_id": None if rid is None else int(rid), "ring_type": None if info is None else info.typology,
            "ring_tx_in_candidate": None if rid is None else int(rr[rid]), "ring_evaluable": evaluable,
            "ring_completion_day": None if info is None else int(info.observable_day),
            "lead_days": (int(info.observable_day) - int(a)) if (info is not None and evaluable) else None})
    alerts.sort(key=lambda x: (x["alert_day"], x["candidate_ring_id"]))

    rows = []
    for r in rings.itertuples():
        rid = int(r.ring_id)
        q = pq.loc[str(rid)] if str(rid) in pq.index else None
        a = pa.loc[str(rid)] if str(rid) in pa.index else None
        evaluable = bool(q["evaluable"]) if q is not None else False
        reason = None
        if not evaluable:
            reason = f"starts before the scored period (day {s.scored_from})" if r.first_day < s.scored_from else "completes after the data ends"
        qd = bool(q["detected"]) if q is not None else False
        ad = bool(a["detected"]) if a is not None else False
        ql, al = (_py(q["lead_days"]) if q is not None else None), (_py(a["lead_days"]) if a is not None else None)
        best_q = min(((max(cands[ci]["creation_day"], d), ci) for ci, d in ring_cands.get(str(rid), {}).items()), default=None)
        best_a = min(((max(adays[ci], d), ci) for ci, d in ring_cands.get(str(rid), {}).items() if adays[ci] is not None), default=None)
        rows.append({
            "ring_id": rid, "type": r.typology, "n_tx": int(r.n_tx), "first_day": int(r.first_day), "first_date": iso(day0, r.first_day),
            "completion_day": int(r.observable_day), "completion_date": iso(day0, r.observable_day), "last_day": int(r.last_day),
            "evaluable": evaluable, "not_evaluable_reason": reason,
            "queue": {"seen": qd, "warning_day": _py(q["warning_day"]) if q is not None else None, "lead_days": ql, "tx_coverage": _py(q["tx_coverage"]) if q is not None else None,
                      "status": _status(qd, ql) if evaluable else None, "candidate": None if best_q is None else index[best_q[1]]},
            "alert": {"seen": ad, "warning_day": _py(a["warning_day"]) if a is not None else None, "lead_days": al, "tx_coverage": _py(a["tx_coverage"]) if a is not None else None,
                      "status": _status(ad, al) if evaluable else None, "candidate": None if best_a is None else index[best_a[1]]}})
        for k in ("queue", "alert"):
            w = rows[-1][k]["warning_day"]
            rows[-1][k]["warning_date"] = None if w is None else iso(day0, w)

    ev = [r for r in rows if r["evaluable"]]
    count = lambda lvl, st: sum(1 for r in ev if r[lvl]["status"] == st)
    by_type = {}
    for r in rows:
        b = by_type.setdefault(r["type"], {"rings": 0, "evaluable": 0, "queue_seen": 0, "alert_seen": 0})
        b["rings"] += 1; b["evaluable"] += r["evaluable"]
        b["queue_seen"] += int(r["evaluable"] and r["queue"]["seen"]); b["alert_seen"] += int(r["evaluable"] and r["alert"]["seen"])
    reasons = Counter(r["not_evaluable_reason"] for r in rows if not r["evaluable"])
    days = np.arange(s.scored_from, max_day + 1)
    ac, nc, rc = Counter(x["alert_day"] for x in alerts), Counter(int(c["creation_day"]) for c in cands), Counter(r["completion_day"] for r in ev)
    daily = [{"day": int(d), "date": iso(day0, d), "alerts": ac.get(int(d), 0), "new_candidates": nc.get(int(d), 0), "ring_completions": rc.get(int(d), 0)} for d in days]
    true = [x for x in alerts if x["contains_ring_tx"]]
    gaps = [x["days_creation_to_alert"] for x in alerts]
    return {
        "protocol": {"scored_from_day": s.scored_from, "last_day": max_day, "first_date": iso(day0, 0), "alert_threshold": thr, "observable_k": s.observable_k},
        "summary": {"n_alerts": len(alerts), "alerts_with_ring_tx": len(true), "false_alerts": len(alerts) - len(true),
                    "first_alert_date": alerts[0]["alert_date"] if alerts else None, "last_alert_date": alerts[-1]["alert_date"] if alerts else None,
                    "median_days_creation_to_alert": float(np.median(gaps)) if gaps else None, "n_rings": len(rows), "n_evaluable": len(ev),
                    "queue": {st: count("queue", st) for st in ("before", "at", "after", "not_seen")},
                    "alert": {st: count("alert", st) for st in ("before", "at", "after", "not_seen")},
                    "by_type": by_type, "not_evaluable_reasons": dict(reasons),
                    "mean_tx_coverage": {"queue": float(np.mean([r["queue"]["tx_coverage"] or 0 for r in ev])) if ev else None,
                                         "alert": float(np.mean([r["alert"]["tx_coverage"] or 0 for r in ev])) if ev else None}},
        "alerts": alerts, "rings": rows, "daily": daily,
        "caveats": ["Ring fields (id, type, first transaction, completion, lead, coverage) are AMLSim ground truth and are used only to evaluate.",
                    "Lead is the ring's completion day minus the day the alert was given. A positive lead means the alert came before the ring was complete.",
                    "Only rings that start in the scored period and complete inside the data are evaluable; the others are listed with the reason."]}
