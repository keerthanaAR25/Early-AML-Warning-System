"""
Pipeline v2 core (ADDITIVE): candidate source, out-of-sample risk scoring, evidence/pattern/trajectory export.

Everything the dashboard reads is produced from ONE configuration (Settings), so no page can disagree with another.
Ring labels are used in exactly two places: as training targets for rows strictly before a scored block (with a purge gap),
and by evaluation code. They never enter candidate construction or any score.

Risk score (investigative priority 0-100, NOT a probability of guilt), computed AS OF each day the candidate gains evidence:
  behavioural  mean over the candidate's accounts of the percentile of the account's model score within a fixed reference
               population (active accounts in the H days before the block). The model was trained only on earlier data.
  network      structural completeness: closed cycle 100, path-like partial cycle 60; first-time-account groups
               20 per seed (+20 slow-drip fan, +10 new-account chain), capped at 100. Size-invariant by construction.
  fund_flow    distinct pattern weights / sum of all weights (same form as the original engine)
  persistence  35 * log1p(3 * evidence transactions / accounts), capped at 100 (same form as the original engine)
Weights, band thresholds and the alert threshold come from configs/config.yaml (risk_scoring).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

PATTERN_WEIGHT = {
    "cycle_closure": 3.0, "partial_path": 2.0, "new_account_chain": 2.0,
    "slow_drip_fan_in": 1.0, "slow_drip_fan_out": 1.0, "first_time_sender": 0.5, "first_time_receiver": 0.5,
}
MAX_PATTERN_WEIGHT = sum(PATTERN_WEIGHT.values())
STRUCTURAL = {"cycle_closure", "partial_path", "new_account_chain", "slow_drip_fan_in", "slow_drip_fan_out"}
PATTERN_STRENGTH = {"cycle_closure": 1.0, "partial_path": 0.6, "new_account_chain": 0.6, "slow_drip_fan_in": 0.7,
                    "slow_drip_fan_out": 0.7, "first_time_sender": 0.4, "first_time_receiver": 0.4}


@dataclass
class Settings:
    burn_in: int = 120
    scored_from: int = 240
    block_len: int = 120
    horizon: int = 14
    window_days: int = 21
    seed: int = 42
    min_seeds: int = 2
    novelty_mode: str = "either"
    seed_gap: int = 30
    hub_gap: int = 150
    observable_k: int = 4
    n_estimators: int = 200
    alert_threshold: float = 50.0
    thresholds: dict = field(default_factory=lambda: {"low": [0, 24], "moderate": [25, 49], "high": [50, 74], "critical": [75, 100]})
    weights: dict = field(default_factory=lambda: {"behavioural": 0.35, "network": 0.20, "fund_flow": 0.25, "persistence": 0.20})


def load_settings(root: Path, **overrides) -> Settings:
    s = Settings()
    cfg = root / "configs" / "config.yaml"
    if cfg.exists():
        import yaml
        rs = (yaml.safe_load(open(cfg)) or {}).get("risk_scoring", {})
        s.thresholds = rs.get("thresholds", s.thresholds)
        s.weights = rs.get("component_weights", s.weights)
        s.alert_threshold = float(rs.get("alert_threshold", s.alert_threshold))
    for k, v in overrides.items():
        if v is not None:
            setattr(s, k, v)
    if abs(sum(s.weights.values()) - 1.0) > 1e-6:
        raise ValueError("risk_scoring.component_weights must sum to 1.0")
    return s


def risk_level(score: float, thresholds: dict) -> str:
    for name in ("critical", "high", "moderate", "low"):
        lo, hi = thresholds[name]
        if lo <= score <= hi:
            return name.upper()
    return "CRITICAL" if score > 75 else "LOW"


# ----------------------------------------------------------------------------------------------- as-of components
def novelty_patterns(txs, S, R, sfo, rfi) -> list:
    """Pattern names of a first-time-account group from the seed transactions known so far."""
    hubs_in = {R[t] for t in txs if sfo[t] and not rfi[t]}
    hubs_out = {S[t] for t in txs if rfi[t] and not sfo[t]}
    pats = set()
    if any(len({S[t] for t in txs if R[t] == h}) >= 2 for h in hubs_in):
        pats.add("slow_drip_fan_in")
    if any(len({R[t] for t in txs if S[t] == h}) >= 2 for h in hubs_out):
        pats.add("slow_drip_fan_out")
    if any(sfo[t] and rfi[t] for t in txs):
        pats.add("new_account_chain")
    if not pats:
        pats.add("first_time_sender" if any(sfo[t] for t in txs) else "first_time_receiver")
    return sorted(pats)


def asof_patterns(c: dict, d: int, S, R, sfo, rfi, day_of) -> list:
    if c["source"] in ("cycle_closure", "partial_path"):
        closed = c["closed"] and c["closure_day"] is not None and c["closure_day"] <= d
        return ["cycle_closure"] if closed else ["partial_path"]
    return novelty_patterns([t for t in c["tx"] if day_of[t] <= d], S, R, sfo, rfi)


def network_component(c: dict, pats: list, n_seeds: int) -> float:
    if c["source"] in ("cycle_closure", "partial_path"):
        return 100.0 if "cycle_closure" in pats else 60.0
    score = 20 * n_seeds + (20 if any(p.startswith("slow_drip") for p in pats) else 0) + (10 if "new_account_chain" in pats else 0)
    return float(min(100, score))


def fund_flow_component(pats: list) -> float:
    return float(min(100.0, sum(PATTERN_WEIGHT.get(p, 0.5) for p in set(pats)) / MAX_PATTERN_WEIGHT * 100))


def persistence_component(n_tx: int, n_nodes: int) -> float:
    return float(min(100.0, 35 * math.log1p(3 * n_tx / max(n_nodes, 1))))


def combine(components: dict, weights: dict) -> float:
    return round(float(sum(components[k] * weights[k] for k in weights)), 2)


# ----------------------------------------------------------------------------------------------- block models (out of sample)
def fit_block_models(state, Y, cols, s: Settings):
    """One XGBoost per scored block, trained only on rows up to (block start - 1 - horizon). Returns {start: (model, sorted reference scores)}."""
    import xgboost as xgb
    from src.evaluation import account_window_eval as AW
    models = {}
    for start in range(s.scored_from, state["W"], s.block_len):
        X, y, _, _ = AW.make_rows(state, Y, cols, s.burn_in, start - 1 - s.horizon)
        pos = max(int(y.sum()), 1)
        m = xgb.XGBClassifier(n_estimators=s.n_estimators, max_depth=4, learning_rate=0.05, subsample=0.8, colsample_bytree=0.8,
                              scale_pos_weight=(len(y) - pos) / pos / 2.0, random_state=s.seed, tree_method="hist", n_jobs=2,
                              eval_metric="aucpr", verbosity=0)
        m.fit(X, y)
        Xr, _, ar, dr = AW.make_rows(state, Y, cols, start - s.horizon, start - 1)      # reference: the purged window, never trained on
        act = state["active"][ar, dr]
        ref = np.sort(m.predict_proba(Xr[act])[:, 1])
        models[start] = (m, ref, int(len(y)), pos)
    return models


def block_of(models: dict, day: int):
    starts = [b for b in models if b <= day]
    return max(starts) if starts else None


def account_percentiles(pairs, state, models, cols):
    """pairs: iterable of (account_index, day). Returns {(a, d): percentile 0-100} using the block model valid for that day."""
    by_block = {}
    for a, d in pairs:
        b = block_of(models, d)
        if b is not None and state["seen"][a, d]:
            by_block.setdefault(b, []).append((a, d))
    out = {}
    for b, lst in by_block.items():
        m, ref = models[b][0], models[b][1]
        X = np.column_stack([state["feats"][c][[a for a, _ in lst], [d for _, d in lst]] for c in cols]).astype(np.float32)
        p = m.predict_proba(X)[:, 1]
        pct = np.searchsorted(ref, p, side="right") / max(len(ref), 1) * 100.0
        for (a, d), v in zip(lst, pct):
            out[(a, d)] = float(v)
    return out


def score_candidates(cands, state, models, cols, tx_info, day_of, flags, s: Settings):
    """Risk score for every (candidate, day it gained evidence), using only information up to that day. Returns per-candidate history."""
    S, R = tx_info["S"], tx_info["R"]
    sfo, rfi = flags["sfo"], flags["rfi"]
    acct_idx = {a: i for i, a in enumerate(state["accts"])}
    plan, asof = [], {}
    for ci, c in enumerate(cands):
        days = sorted({day_of[t] for t in c["tx"] if day_of[t] >= c["creation_day"]} | {c["creation_day"]})
        for d in days:
            txs = [t for t in c["tx"] if day_of[t] <= d]
            nodes = {x for t in txs for x in (S[t], R[t])}
            asof[(ci, d)] = (txs, nodes)
            plan.append((ci, d))
    pairs = {(acct_idx[a], d) for (ci, d), (_, nodes) in asof.items() for a in nodes if a in acct_idx}
    pct = account_percentiles(pairs, state, models, cols)
    history = [[] for _ in cands]
    for ci, d in plan:
        c = cands[ci]
        txs, nodes = asof[(ci, d)]
        pats = asof_patterns(c, d, S, R, sfo, rfi, day_of)
        accs = [(a, pct[(acct_idx[a], d)]) for a in sorted(nodes) if a in acct_idx and (acct_idx[a], d) in pct]
        beh = float(np.mean([p for _, p in accs])) if accs else 0.0
        top = max(accs, key=lambda x: x[1]) if accs else (None, 0.0)
        comp = {"behavioural": round(beh, 2), "network": round(network_component(c, pats, len(txs) if c["source"] == "novelty_seeded" else 0), 2),
                "fund_flow": round(fund_flow_component(pats), 2), "persistence": round(persistence_component(len(txs), len(nodes)), 2)}
        score = combine(comp, s.weights)
        factors = [
            f"Mean account score percentile {comp['behavioural']:.0f} across {len(accs)} accounts (highest: {top[0]} at the {top[1]:.0f}th percentile)",
            f"Structure: {', '.join(pats)} (network completeness {comp['network']:.0f}/100)",
            f"Combines {len(set(pats))} pattern type(s); strongest: {max(pats, key=lambda p: PATTERN_WEIGHT.get(p, 0.5))}",
            f"{len(txs)} evidence transactions across {len(nodes)} accounts ({len(txs) / max(len(nodes), 1):.2f} per account)",
        ]
        history[ci].append(dict(day=d, score=score, level=risk_level(score, s.thresholds), components=comp, patterns=pats,
                                n_tx=len(txs), n_nodes=len(nodes), factors=factors))
    return history


def alert_day(hist: list, threshold: float):
    for h in hist:
        if h["score"] >= threshold:
            return h["day"]
    return None
