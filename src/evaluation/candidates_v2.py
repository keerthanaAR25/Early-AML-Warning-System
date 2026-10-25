"""
Second ring-candidate source + candidate-quality evaluation (ADDITIVE -- no existing file is modified).

WHY: measured on the delivered build, the 142 pattern-trajectory candidates hold 2,374 evidence transactions of which
17 (0.72%) are ring transactions (2.1x the 0.34% background rate); 0 of 40 cycle rings appear in any candidate.
The detectors behind them (same-day fan-in, 48 h pass-through, repeated intermediary, TIME-ORDERED cycles) find motifs that
normal AMLSim traffic also produces, and AMLSim cycle edges arrive in arbitrary order (0 of 35 reconstructable cycles are
time-ordered along the path).

WHAT THIS ADDS (all label-free; labels are read only by the evaluation functions):
  1. structure candidates  -- UNORDERED cycle closure in a sliding window (default 21 d) and path-like partial cycles.
  2. novelty-seeded candidates -- transactions whose sender (or receiver) has never been active before (after a warm-up),
     grouped by shared account within a short gap, and by shared hub across a long gap (slow-drip fans).
     SIMULATOR-SPECIFIC: AMLSim draws ring members from otherwise-dormant accounts, so this signal is unusually strong here.
  3. candidate_quality / evaluate_candidate_set -- the SAME metrics for any candidate set (including your v1 candidates):
     ring-transaction precision, enrichment, ring coverage, false candidates per day, and ring-level lead time.

Operational definitions are identical to src/evaluation/ring_lead_time.py:
  observable_time: cycle -> closing (last) edge; fan -> day the k-th (k=4) distinct counterparty has transacted.
  warning_time   : day a candidate that contains a transaction of the ring exists (>= the day that transaction occurred).
  lead_time      : observable_day - warning_day. A secondary view uses the ring's FIRST transaction as the observable event.
"""
from __future__ import annotations

import html
import json
from collections import defaultdict, deque
from pathlib import Path

import numpy as np
import pandas as pd

STRUCTURAL_V1 = {"fan_in", "fan_out", "layering", "repeated_intermediary"}
SCHEMA_FIELDS = ["candidate_ring_id", "accounts", "transaction_ids", "time_span", "patterns", "trajectory",
                 "network_statistics", "formation_stage", "formation_stage_is_provisional", "risk_score",
                 "evidence_event_count", "source_trajectory_id"]


# =============================================================================================
# 1. structure candidates: unordered cycle closure + path-like partial cycles
# =============================================================================================
def _shortest_path(out_nb, src, dst, max_nodes, visit_cap=3000):
    """Shortest directed path src -> dst with at most max_nodes nodes (inclusive); None if absent."""
    if src == dst:
        return [src]
    parent, q, seen = {src: None}, deque([(src, 1)]), 1
    while q:
        x, depth = q.popleft()
        if depth >= max_nodes:
            continue
        for y in out_nb.get(x, ()):
            if y in parent:
                continue
            parent[y] = x
            if y == dst:
                path = [y]
                while parent[path[-1]] is not None:
                    path.append(parent[path[-1]])
                return path[::-1]
            seen += 1
            if seen > visit_cap:
                return None
            q.append((y, depth + 1))
    return None


def _reach(nb, start, cap):
    seen, q = {start}, deque([start])
    while q:
        x = q.popleft()
        for y in nb.get(x, ()):
            if y not in seen:
                seen.add(y)
                if len(seen) > cap:
                    return None
                q.append(y)
    return seen


def _scc_containing(out_nb, in_nb, node, cap=20000):
    """Strongly connected component of `node` in the window graph (forward-reach AND backward-reach); None if it is huge."""
    fwd, bwd = _reach(out_nb, node, cap), _reach(in_nb, node, cap)
    return None if fwd is None or bwd is None else fwd & bwd


def _bounded_component(out_nb, in_nb, start, cap):
    """Weakly connected component containing `start`; None if it exceeds `cap` nodes."""
    comp, q = {start}, deque([start])
    while q:
        x = q.popleft()
        for y in list(out_nb.get(x, ())) + list(in_nb.get(x, ())):
            if y not in comp:
                comp.add(y)
                if len(comp) > cap:
                    return None
                q.append(y)
    return comp


def detect_structures(tx: pd.DataFrame, window_days=21, min_cycle_nodes=4, max_cycle_nodes=12,
                      min_path_nodes=4, max_path_nodes=10, max_chords=2, max_candidate_span_days=None,
                      max_candidate_nodes=40) -> list:
    """tx needs columns transaction_id, sender, receiver, day (sorted by day). NO label column is used.

    A new structure is merged into an earlier candidate ONLY if that candidate is still active (touched within the last
    `window_days`), is younger than `max_candidate_span_days` (default 2 x window) and would stay under `max_candidate_nodes`
    accounts. Without these limits a single early candidate keeps absorbing everything that touches one of its accounts and
    becomes a giant blob (observed: one candidate with 40,999 transactions over 720 days)."""
    max_span = max_candidate_span_days if max_candidate_span_days is not None else 2 * window_days
    S, R, T = tx["sender"].values, tx["receiver"].values, tx["transaction_id"].values
    idx_by_day = tx.groupby("day").indices
    out_nb, in_nb = defaultdict(set), defaultdict(set)
    etx = defaultdict(list)                  # (u, v) -> [(day, tid)] currently in the window
    added = defaultdict(list)                # day -> [(u, v, tid)]
    cands, cand_of = [], {}
    seen_cycle = set()

    def edges_among(nodes):
        tids = set()
        for a in nodes:
            for b in out_nb.get(a, ()):
                if b in nodes:
                    tids.update(t for _, t in etx[(a, b)])
        return tids

    def register(nodes, tids, day, closed):
        owners = {cand_of[n] for n in nodes if n in cand_of
                  and cands[cand_of[n]]["last_day"] >= day - window_days
                  and day - cands[cand_of[n]]["creation_day"] <= max_span
                  and len(cands[cand_of[n]]["nodes"] | nodes) <= max_candidate_nodes}
        if owners:
            k = min(owners)
            c = cands[k]
            c["nodes"] |= nodes
            c["tx"] |= tids
            c["last_day"] = day
            if closed and not c["closed"]:
                c["closed"], c["closure_day"] = True, day
        else:
            k = len(cands)
            cands.append(dict(nodes=set(nodes), tx=set(tids), creation_day=day, closed=closed,
                              closure_day=day if closed else None, last_day=day))
        for n in nodes:
            cand_of[n] = k

    for d in range(int(tx["day"].min()), int(tx["day"].max()) + 1):
        for (u, v, tid) in added.pop(d - window_days, []):          # expire the day leaving the window
            lst = etx[(u, v)]
            lst.remove((d - window_days, tid))
            if not lst:
                del etx[(u, v)]
                out_nb[u].discard(v)
                in_nb[v].discard(u)
        new_edges = []
        for pos in idx_by_day.get(d, ()):
            u, v, tid = S[pos], R[pos], T[pos]
            if u == v:
                continue
            etx[(u, v)].append((d, tid))
            out_nb[u].add(v)
            in_nb[v].add(u)
            added[d].append((u, v, tid))
            new_edges.append((u, v))
        for (u, v) in dict.fromkeys(new_edges):
            if _shortest_path(out_nb, v, u, max_cycle_nodes) is not None:        # u->v closes a cycle
                # accept it only if the WHOLE strongly connected component is small and nearly a simple cycle;
                # small cycles buried inside the big tangled core are background (thousands per window otherwise)
                scc = _scc_containing(out_nb, in_nb, u)
                if scc is not None and min_cycle_nodes <= len(scc) <= max_cycle_nodes:
                    nodes = frozenset(scc)
                    chords = sum(1 for a in nodes for b in out_nb.get(a, ()) if b in nodes)
                    if chords <= len(nodes) + max_chords and nodes not in seen_cycle:
                        seen_cycle.add(nodes)
                        register(set(nodes), edges_among(nodes), d, True)
                        continue
            comp = _bounded_component(out_nb, in_nb, u, max_path_nodes)
            if comp and min_path_nodes <= len(comp) <= max_path_nodes:
                n_edges = sum(1 for a in comp for b in out_nb.get(a, ()) if b in comp)
                pure = n_edges == len(comp) - 1 and all(
                    len(out_nb.get(a, set()) & comp) <= 1 and len(in_nb.get(a, set()) & comp) <= 1 for a in comp)
                if pure:
                    register(comp, edges_among(comp), d, False)
    for c in cands:
        c["source"] = "cycle_closure" if c["closed"] else "partial_path"
    return cands


# =============================================================================================
# 2. novelty-seeded candidates (simulator-specific signal -- always label as such)
# =============================================================================================
class _UF:
    def __init__(self, n):
        self.p = list(range(n))

    def find(self, x):
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[max(ra, rb)] = min(ra, rb)


def detect_novelty_groups(tx: pd.DataFrame, feats: pd.DataFrame, burn_in=120, seed_gap=30, hub_gap=150, min_seeds=1,
                          mode="either") -> list:
    """Seeds = transactions on/after `burn_in` whose sender has never sent, or whose receiver has never received, before.
    Seeds sharing an account within `seed_gap` days are linked; seeds sharing a HUB (the established side of a seed) are
    linked across up to `hub_gap` days (slow-drip fans). A group becomes a candidate on the day its min_seeds-th seed occurs.
    mode="either": first-ever sender OR first-ever receiver (higher recall, lower precision);
    mode="sender": first-ever sender only (higher precision; cannot see fan-out counterparties)."""
    assert "label" not in feats.columns
    if mode not in ("either", "sender"):
        raise ValueError("mode must be 'either' or 'sender'")
    new_side = (feats["s_first_out"].values == 1) if mode == "sender" else \
               ((feats["s_first_out"].values == 1) | (feats["r_first_in"].values == 1))
    m = (feats["day"].values >= burn_in) & new_side
    pos = np.flatnonzero(m)
    if len(pos) == 0:
        return []
    S, R, T, D = tx["sender"].values[pos], tx["receiver"].values[pos], tx["transaction_id"].values[pos], tx["day"].values[pos]
    sfo, rfi = feats["s_first_out"].values[pos], feats["r_first_in"].values[pos]
    uf = _UF(len(pos))
    by_acct, by_hub = defaultdict(list), defaultdict(list)
    for i in range(len(pos)):
        by_acct[S[i]].append((D[i], i)); by_acct[R[i]].append((D[i], i))
        if sfo[i] and not rfi[i]:
            by_hub[("in", R[i])].append((D[i], i))
        elif rfi[i] and not sfo[i]:
            by_hub[("out", S[i])].append((D[i], i))
    for groups, gap in ((by_acct, seed_gap), (by_hub, hub_gap)):
        for lst in groups.values():
            lst.sort()
            for (d1, i1), (d2, i2) in zip(lst, lst[1:]):
                if d2 - d1 <= gap:
                    uf.union(i1, i2)
    comps = defaultdict(list)
    for i in range(len(pos)):
        comps[uf.find(i)].append(i)
    out = []
    for members in comps.values():
        if len(members) < min_seeds:
            continue
        members.sort(key=lambda i: D[i])
        hubs_in = {R[i] for i in members if sfo[i] and not rfi[i]}
        hubs_out = {S[i] for i in members if rfi[i] and not sfo[i]}
        pats = set()
        if any(len({S[i] for i in members if R[i] == h}) >= 2 for h in hubs_in): pats.add("slow_drip_fan_in")
        if any(len({R[i] for i in members if S[i] == h}) >= 2 for h in hubs_out): pats.add("slow_drip_fan_out")
        if any(sfo[i] and rfi[i] for i in members): pats.add("new_account_chain")
        if not pats: pats.add("novelty_first_sender" if any(sfo[i] for i in members) else "novelty_first_receiver")
        out.append(dict(nodes={x for i in members for x in (S[i], R[i])}, tx={T[i] for i in members},
                        creation_day=int(D[members[min_seeds - 1]]), closed=False, closure_day=None,
                        source="novelty_seeded", patterns=sorted(pats), n_seeds=len(members)))
    return out


# =============================================================================================
# 3. schema export (same fields as your RingCandidate, extras go to a sidecar)
# =============================================================================================
def to_schema(cands: list, tx: pd.DataFrame, day0, prefix: str):
    info = {t: (d, s, r, a) for t, d, s, r, a in zip(tx["transaction_id"], tx["day"], tx["sender"], tx["receiver"], tx["amount"])}
    rows, meta = [], []
    for i, c in enumerate(sorted(cands, key=lambda c: (c["creation_day"], sorted(c["tx"])[0])), start=1):
        days = sorted(info[t][0] for t in c["tx"])
        pairs = {(info[t][1], info[t][2]) for t in c["tx"]}
        n = len(c["nodes"])
        pats = c.get("patterns") or [c["source"]]
        stage = ("OBSERVABLE_RING" if c["closed"] else
                 "EMERGING" if c.get("n_seeds", 0) >= 3 else
                 "FORMING" if (c["source"] == "partial_path" or c.get("n_seeds", 0) == 2) else "WATCH")
        iso = lambda d: (day0 + pd.Timedelta(days=int(d))).isoformat()
        rows.append(dict(
            candidate_ring_id=f"{prefix}{i:04d}", accounts=sorted(c["nodes"]), transaction_ids=sorted(c["tx"]),
            time_span=[iso(days[0]), iso(days[-1])], patterns=pats,
            trajectory=dict(pattern_count=len(days), pattern_diversity=len(pats),
                            pattern_sequence=[pats[0]] * len(days), event_window_ids=days),
            network_statistics=dict(n_nodes=n, n_edges=len(c["tx"]), density=round(len(pairs) / max(n * (n - 1), 1), 4),
                                    weakly_connected_components=1, strongly_connected_components=1 if c["closed"] else n,
                                    largest_scc_size=n if c["closed"] else 1),
            formation_stage=stage, formation_stage_is_provisional=True, risk_score=None,
            evidence_event_count=len(c["tx"]), source_trajectory_id=""))
        meta.append(dict(candidate_ring_id=rows[-1]["candidate_ring_id"], source=c["source"], creation_day=c["creation_day"],
                         closure_day=c["closure_day"], n_seeds=c.get("n_seeds"), signal=("simulator-specific novelty" if c["source"] == "novelty_seeded" else "structure")))
    return rows, meta


# =============================================================================================
# 4. evaluation (labels used ONLY here)
# =============================================================================================
def v1_creation_day(c: dict) -> int:
    """Day a v1 trajectory candidate exists: window of its 2nd structural event (the engine's MIN_STRUCTURAL_EVENTS=2)."""
    seq, wins = c["trajectory"].get("pattern_sequence", []), c["trajectory"].get("event_window_ids", [])
    sw = sorted(w for p, w in zip(seq, wins) if p in STRUCTURAL_V1)
    return int(sw[1] if len(sw) >= 2 else (sw[0] if sw else (max(wins) if wins else 0)))


def load_v1(path, tx_ids_set=None):
    norm = lambda v: v[:-2] if isinstance(v, str) and v.endswith(".0") and v[:-2].isdigit() else v
    out = []
    for c in json.load(open(path)):
        out.append(dict(tx={norm(t) for t in c["transaction_ids"]}, nodes={norm(a) for a in c["accounts"]},
                        creation_day=v1_creation_day(c), source="v1_pattern_trajectory"))
    return out


def _boot(vals, seed=0):
    from src.evaluation.ring_lead_time import bootstrap_ci
    return bootstrap_ci(vals, seed=seed)


def evaluate_candidate_set(name, cands, tx, rings, ring_of, label_of, day_of, burn_in, max_day, seed=0):
    """cands: dicts with tx (set of ids) and creation_day. Returns (summary, per_ring DataFrame)."""
    cs = [c for c in cands if c["creation_day"] >= burn_in]
    ring_tx_total = sum(1 for t in ring_of if day_of[t] >= burn_in)
    n_ev_tx = sum(len(c["tx"]) for c in cs)
    n_ring_ev = sum(1 for c in cs for t in c["tx"] if label_of.get(t, 0) == 1)
    with_ring = [c for c in cs if any(label_of.get(t, 0) == 1 for t in c["tx"])]
    half = [c for c in cs if len(c["tx"]) and sum(label_of.get(t, 0) == 1 for t in c["tx"]) / len(c["tx"]) >= 0.5]
    days_scored = max(max_day - burn_in + 1, 1)
    base = float(np.mean([label_of[t] for t in tx["transaction_id"][tx["day"] >= burn_in]])) if len(tx) else None
    covered = {t for c in cs for t in c["tx"] if label_of.get(t, 0) == 1}

    best = {}                                  # ring -> earliest effective warning day over candidates containing its tx
    for c in cs:
        per_ring = defaultdict(list)
        for t in c["tx"]:
            r = ring_of.get(t)
            if r is not None:
                per_ring[r].append(day_of[t])
        for r, ds in per_ring.items():
            w = max(c["creation_day"], min(ds))
            if r not in best or w < best[r]:
                best[r] = w
    rows = []
    for _, r in rings.iterrows():
        w = best.get(r["ring_id"])
        n_cov = len(covered & set(r["tx_ids"]))
        rows.append(dict(candidate_set=name, ring_id=r["ring_id"], typology=r["typology"], first_day=r["first_day"],
                         observable_day=r["observable_day"], n_tx=r["n_tx"], n_tx_in_candidates=n_cov,
                         tx_coverage=n_cov / r["n_tx"], detected=w is not None, warning_day=w,
                         lead_days=(r["observable_day"] - w) if w is not None else None,
                         lead_vs_first_tx_days=(r["first_day"] - w) if w is not None else None,
                         evaluable=bool(r["first_day"] >= burn_in and r["observable_day"] <= max_day)))
    pr = pd.DataFrame(rows)
    ev = pr[pr["evaluable"]]

    def grp(g):
        det = g[g["detected"]]
        L, L1 = det["lead_days"].astype(float), det["lead_vs_first_tx_days"].astype(float)
        f = lambda x: None if x is None or (isinstance(x, float) and np.isnan(x)) else float(x)
        return dict(n_evaluable_rings=len(g), n_with_any_tx_in_candidate=int(len(det)),
                    ring_recall=len(det) / len(g) if len(g) else None,
                    n_warned_before_observable=int((L > 0).sum()),
                    warned_before_observable_rate=float((L > 0).sum() / len(g)) if len(g) else None,
                    lead_days_median=f(L.median()) if len(L) else None, lead_days_median_ci95=_boot(L, seed),
                    lead_days_q25=f(L.quantile(.25)) if len(L) else None, lead_days_q75=f(L.quantile(.75)) if len(L) else None,
                    lead_vs_first_tx_median=f(L1.median()) if len(L1) else None,
                    mean_tx_coverage_of_ring=f(g["tx_coverage"].mean()) if len(g) else None)
    summary = dict(
        candidate_set=name, n_candidates=len(cs), evidence_transactions=n_ev_tx, ring_transactions_in_candidates=n_ring_ev,
        ring_tx_share_of_evidence=n_ring_ev / n_ev_tx if n_ev_tx else None,
        background_ring_tx_rate=base, enrichment_vs_background=(n_ring_ev / n_ev_tx) / base if n_ev_tx and base else None,
        candidates_with_any_ring_tx=len(with_ring), candidates_majority_ring=len(half),
        false_candidates_per_day=(len(cs) - len(with_ring)) / days_scored,
        distinct_ring_tx_covered=len(covered), ring_tx_recall=len(covered) / ring_tx_total if ring_tx_total else None,
        median_accounts_per_candidate=float(np.median([len(c["nodes"]) for c in cs])) if cs else None,
        by_typology={"all": grp(ev), **{t: grp(g) for t, g in ev.groupby("typology")}})
    return summary, pr


# =============================================================================================
# 5. report
# =============================================================================================
def _p(x, nd=1, pct=False):
    return "&mdash;" if x is None else (f"{100 * x:.1f}%" if pct else f"{x:.{nd}f}")


def render_quality_report(results: list, params: dict, path):
    css = ("body{font-family:Segoe UI,Arial,sans-serif;margin:24px;color:#1a1a2e;background:#f7f8fb}table{border-collapse:collapse;background:#fff;margin:8px 0 22px}"
           "th,td{border:1px solid #e3e6ef;padding:6px 10px;font-size:13px;text-align:left}th{background:#eef1fa}"
           ".warn{background:#fff4e5;border:1px solid #f5c26b;padding:10px 14px;margin:12px 0;border-radius:6px}.note{color:#667;font-size:12px}")
    a = "".join(
        f"<tr><td>{html.escape(r['candidate_set'])}</td><td>{r['n_candidates']}</td><td>{r['evidence_transactions']}</td>"
        f"<td>{_p(r['ring_tx_share_of_evidence'], 2, True)}</td><td>{_p(r['enrichment_vs_background'], 1)}x</td>"
        f"<td>{r['candidates_with_any_ring_tx']} / {r['candidates_majority_ring']}</td><td>{_p(r['false_candidates_per_day'], 2)}</td>"
        f"<td>{_p(r['ring_tx_recall'], 1, True)}</td></tr>" for r in results)
    b = ""
    for r in results:
        for t, g in r["by_typology"].items():
            lo, hi = g["lead_days_median_ci95"]
            ci = "n too small" if lo is None else f"[{lo:.1f}, {hi:.1f}]"
            b += (f"<tr><td>{html.escape(r['candidate_set'])}</td><td>{t}</td><td>{g['n_evaluable_rings']}</td>"
                  f"<td>{g['n_with_any_tx_in_candidate']} ({_p(g['ring_recall'], 0, True)})</td>"
                  f"<td>{g['n_warned_before_observable']} ({_p(g['warned_before_observable_rate'], 0, True)})</td>"
                  f"<td>{_p(g['lead_days_median'])}</td><td>{ci}</td><td>{_p(g['lead_vs_first_tx_median'])}</td>"
                  f"<td>{_p(g['mean_tx_coverage_of_ring'], 0, True)}</td></tr>")
    doc = f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>Candidate quality</title><style>{css}</style></head><body>
<h1>Candidate quality and ring-level early warning</h1>
<div class="warn"><b>Read before citing.</b> <i>v2_novelty</i> uses a signal specific to AMLSim (ring members are otherwise-dormant accounts). <i>v2_structure</i> uses only
graph structure and is the more defensible comparison with v1. Ring labels are used only to evaluate, never to build candidates.</div>
<h2>Candidate quality (candidates created on/after day {params['burn_in']})</h2>
<table><tr><th>Candidate set</th><th>Candidates</th><th>Evidence tx</th><th>Ring-tx share</th><th>Enrichment vs background</th><th>With any ring tx / majority ring</th><th>False candidates/day</th><th>Ring-tx recall</th></tr>{a}</table>
<h2>Ring-level early warning (N = rings that start after the burn-in and complete inside the data)</h2>
<table><tr><th>Candidate set</th><th>Typology</th><th>N rings</th><th>Ring has a tx in a candidate</th><th>Warned before observable</th><th>Median lead (days)</th><th>Median 95% CI</th><th>Median lead vs ring's first tx</th><th>Mean tx coverage</th></tr>{b}</table>
<p class="note">observable_time: cycle = closing (last) edge; fan = day the {params['observable_k']}th distinct counterparty has transacted. Warning = day a candidate containing a ring transaction exists.
Positive lead = warned before the ring was observable. Parameters: {html.escape(json.dumps(params))}</p></body></html>"""
    Path(path).write_text(doc, encoding="utf-8")
