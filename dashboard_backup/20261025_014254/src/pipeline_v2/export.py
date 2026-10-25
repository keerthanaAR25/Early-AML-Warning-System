"""Build the JSON artifacts the existing database loader and API read, from the scored production candidates (ADDITIVE)."""
from __future__ import annotations

import networkx as nx
import pandas as pd

from src.pipeline_v2.core import PATTERN_STRENGTH, STRUCTURAL, novelty_patterns


def iso(day0, d) -> str:
    return (day0 + pd.Timedelta(days=int(d))).isoformat() + "+00:00"


def ordered_path(edges):
    """Node order along a path or cycle given directed edges; falls back to sorted nodes when the structure is not a simple chain."""
    nxt, indeg = {}, {}
    for u, v in edges:
        nxt.setdefault(u, v)
        indeg[v] = indeg.get(v, 0) + 1
    nodes = {x for e in edges for x in e}
    starts = [n for n in nodes if indeg.get(n, 0) == 0] or [min(nodes)]
    path, cur, seen = [], starts[0], set()
    while cur is not None and cur not in seen:
        path.append(cur); seen.add(cur); cur = nxt.get(cur)
    return path if len(path) >= len(nodes) - 0 else sorted(nodes)


def candidate_events(c, S, R, sfo, rfi, day_of):
    """Chronological detector events of one candidate: (day, pattern, central_account, accounts, transaction_ids)."""
    ev = []
    if c["source"] in ("cycle_closure", "partial_path"):
        def at(d):
            txs = [t for t in c["tx"] if day_of[t] <= d]
            return sorted({x for t in txs for x in (S[t], R[t])}), sorted(txs)
        if c["closed"] and c["closure_day"] is not None and c["closure_day"] != c["creation_day"]:
            a, t = at(c["creation_day"]); ev.append((c["creation_day"], "partial_path", a[0], a, t))
            a, t = at(c["closure_day"]); ev.append((c["closure_day"], "cycle_closure", a[0], a, t))
        else:
            a, t = at(c["creation_day"]); ev.append((c["creation_day"], "cycle_closure" if c["closed"] else "partial_path", a[0], a, t))
        return ev
    seeds = sorted(c["tx"], key=lambda t: (day_of[t], t))
    announced = set()
    for i, t in enumerate(seeds):
        d = day_of[t]
        kind = "first_time_sender" if sfo[t] else "first_time_receiver"
        ev.append((d, kind, S[t] if sfo[t] else R[t], sorted({S[t], R[t]}), [t]))
        known = [u for u in seeds if day_of[u] <= d]
        for p in novelty_patterns(known, S, R, sfo, rfi):
            if p not in announced and p not in ("first_time_sender", "first_time_receiver"):
                announced.add(p)
                hub = (R[t] if p == "slow_drip_fan_in" else S[t]) if p.startswith("slow_drip") else S[t]
                ev.append((d, p, hub, sorted({x for u in known for x in (S[u], R[u])}), sorted(known)))
    return ev


def network_stats(txs, S, R):
    g = nx.DiGraph()
    g.add_edges_from((S[t], R[t]) for t in txs)
    n = g.number_of_nodes()
    sccs = list(nx.strongly_connected_components(g))
    return {"n_nodes": n, "n_edges": len(txs), "density": round(nx.density(g), 4) if n > 1 else 0.0,
            "weakly_connected_components": nx.number_weakly_connected_components(g), "strongly_connected_components": len(sccs),
            "largest_scc_size": max((len(x) for x in sccs), default=0)}


def stage_of(c, n_seeds):
    if c["closed"]:
        return "OBSERVABLE_RING"
    if c["source"] == "partial_path" or n_seeds == 2:
        return "FORMING"
    return "EMERGING" if n_seeds >= 3 else "WATCH"


def build_artifacts(cands, history, tx_info, day_of, flags, day0, s, raw_episodes):
    S, R, A = tx_info["S"], tx_info["R"], tx_info["A"]
    sfo, rfi = flags["sfo"], flags["rfi"]
    order = sorted(range(len(cands)), key=lambda i: (cands[i]["creation_day"], min(cands[i]["tx"])))
    out = dict(ring_candidates=[], risk_scores=[], evidence=[], pattern_events=[], trajectories=[], index={})
    for rank, ci in enumerate(order, start=1):
        c, hist = cands[ci], history[ci]
        rid = f"RING{rank:04d}"
        out["index"][ci] = rid
        final = hist[-1]
        txs = sorted(c["tx"], key=lambda t: (day_of[t], t))
        nodes = sorted({x for t in txs for x in (S[t], R[t])})
        ev = candidate_events(c, S, R, sfo, rfi, day_of)
        seq = [e[1] for e in ev]
        traj = {"pattern_count": len(ev), "pattern_diversity": len(set(seq)), "pattern_sequence": seq,
                "event_window_ids": [e[0] for e in ev], "structural_pattern_types": sorted(set(seq) & STRUCTURAL),
                "supporting_pattern_types": sorted(set(seq) - STRUCTURAL)}
        n_seeds = len(txs) if c["source"] == "novelty_seeded" else 0
        pats = final["patterns"]
        d0, d1 = day_of[txs[0]], day_of[txs[-1]]
        out["ring_candidates"].append({
            "candidate_ring_id": rid, "accounts": nodes, "transaction_ids": txs, "time_span": [iso(day0, d0), iso(day0, d1)],
            "patterns": pats, "trajectory": traj, "network_statistics": network_stats(txs, S, R),
            "formation_stage": stage_of(c, n_seeds), "formation_stage_is_provisional": True, "risk_score": final["score"],
            "evidence_event_count": len(txs), "source_trajectory_id": ""})
        out["risk_scores"].append({"candidate_ring_id": rid, "risk_score": final["score"], "risk_level": final["level"],
                                   "score_components": final["components"], "top_factors": final["factors"]})
        edges = [(S[t], R[t]) for t in txs]
        if c["source"] in ("cycle_closure", "partial_path"):
            path = ordered_path(list(dict.fromkeys(edges)))
            paths = [" -> ".join(path + ([path[0]] if "cycle_closure" in pats and len(path) > 1 else []))]
        else:
            paths = [f"{p}: " + ", ".join(sorted({x for t in txs for x in (S[t], R[t])})[:8]) for p in pats]
        sub_nodes = [{"id": n, "label": n} for n in nodes]
        sub_edges = [{"id": t, "source": S[t], "target": R[t], "amount": float(A[t]), "timestamp": iso(day0, day_of[t])} for t in txs]
        out["evidence"].append({
            "candidate_ring_id": rid, "accounts": nodes,
            "transactions": [{"transaction_id": t, "sender": S[t], "receiver": R[t], "amount": float(A[t]), "timestamp": iso(day0, day_of[t])} for t in txs],
            "paths": paths, "patterns": pats, "time_range": [iso(day0, d0), iso(day0, d1)],
            "risk_factors": {"candidate_ring_id": rid, "risk_score": final["score"], "risk_level": final["level"], "score_components": final["components"],
                             "top_factors": final["factors"], "score_history": [[h["day"], h["score"]] for h in hist]},
            "trajectory": traj, "warning_time": iso(day0, c["creation_day"]), "observable_time": None, "lead_time": None,
            "evidence_subgraph": {"nodes": sub_nodes, "edges": sub_edges}})
        for (d, p, central, accs, tids) in ev:
            out["pattern_events"].append({
                "pattern_type": p, "window_id": int(d), "timestamp": iso(day0, d), "central_account": central, "accounts": accs,
                "transaction_ids": tids, "pattern_strength": PATTERN_STRENGTH.get(p, 0.5),
                "evidence": {"candidate_ring_id": rid, "n_transactions": len(tids), "total_amount": round(sum(float(A[t]) for t in tids), 2)}})
    for i, c in enumerate(raw_episodes, start=1):
        ev = candidate_events(c, S, R, sfo, rfi, day_of)
        accs = sorted({x for t in c["tx"] for x in (S[t], R[t])})
        out["trajectories"].append({"candidate_id": f"EP{i:04d}", "accounts": accs, "n_accounts": len(accs), "n_events": len(ev),
                                    "pattern_sequence": [e[1] for e in ev], "events": [{"day": e[0], "pattern": e[1]} for e in ev]})
    return out
