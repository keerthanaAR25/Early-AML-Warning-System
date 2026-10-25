"""Tests for pipeline v2 (ADDITIVE): causal scoring, alerts, de-duplication, exports and cross-file consistency. Run: pytest tests/test_pipeline_v2.py -v"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.evaluation import account_window_eval as AW  # noqa: E402
from src.pipeline_v2 import core, evaluate, export  # noqa: E402


class StubModel:
    """Deterministic 'model': probability rises with the first feature (n_today), so tests do not depend on training."""
    def predict_proba(self, X):
        p = 1 / (1 + np.exp(-(X[:, 0] - 1.0)))
        return np.column_stack([1 - p, p])


def world():
    rng = np.random.default_rng(1)
    rows, k = [], 0
    for d in range(0, 120):
        for _ in range(6):
            rows.append((f"b{k}", f"E{rng.integers(0, 15)}", f"E{rng.integers(0, 15)}", 5.0, 0, d)); k += 1
    for i, (u, v) in enumerate([("A", "B"), ("B", "C"), ("C", "D"), ("D", "A")]):       # a 4-cycle, edges on days 60, 62, 64, 70
        rows.append((f"c{i}", u, v, 9.0, 1, [60, 62, 64, 70][i]))
    df = pd.DataFrame(rows, columns=["transaction_id", "sender", "receiver", "amount", "label", "day"]).sort_values("day", kind="mergesort").reset_index(drop=True)
    return df


def build(df):
    state = AW.build_state(df)
    ids = df["transaction_id"].values
    info = {"S": dict(zip(ids, df["sender"])), "R": dict(zip(ids, df["receiver"])), "A": dict(zip(ids, df["amount"]))}
    day_of = dict(zip(ids, df["day"]))
    flags = {"sfo": {t: 0 for t in ids}, "rfi": {t: 0 for t in ids}}
    models = {50: (StubModel(), np.linspace(0, 1, 200), 0, 0)}
    return state, info, day_of, flags, models


def cand(tx_ids, creation, closed, closure):
    return {"source": "cycle_closure" if closed else "partial_path", "tx": set(tx_ids), "nodes": set(), "creation_day": creation,
            "closed": closed, "closure_day": closure}


# ------------------------------------------------------------------ causality
def test_score_at_a_day_does_not_change_when_later_evidence_is_removed():
    df = world()
    state, info, day_of, flags, models = build(df)
    s = core.Settings(scored_from=50, horizon=5)
    full = cand(["c0", "c1", "c2", "c3"], 64, True, 70)
    # the candidate exists from day 64 (path of 4 nodes) and closes on day 70
    h_full = core.score_candidates([full], state, models, AW.FEATURES_HISTORY, info, day_of, flags, s)[0]
    cut = cand(["c0", "c1", "c2"], 64, False, None)
    h_cut = core.score_candidates([cut], state, models, AW.FEATURES_HISTORY, info, day_of, flags, s)[0]
    at64_full = [h for h in h_full if h["day"] == 64][0]
    at64_cut = [h for h in h_cut if h["day"] == 64][0]
    assert at64_full["score"] == at64_cut["score"] and at64_full["components"] == at64_cut["components"]
    assert at64_full["patterns"] == ["partial_path"]                       # closure on day 70 is invisible on day 64
    assert [h for h in h_full if h["day"] == 70][0]["patterns"] == ["cycle_closure"]


def test_closing_the_cycle_raises_the_network_and_fund_flow_components():
    df = world()
    state, info, day_of, flags, models = build(df)
    h = core.score_candidates([cand(["c0", "c1", "c2", "c3"], 64, True, 70)], state, models, AW.FEATURES_HISTORY, info, day_of, flags, core.Settings(scored_from=50))[0]
    early, late = h[0], h[-1]
    assert late["components"]["network"] > early["components"]["network"] and late["components"]["fund_flow"] > early["components"]["fund_flow"]
    assert [x["day"] for x in h] == [64, 70]                               # one entry per day the candidate gained evidence


def test_candidates_before_the_first_model_block_get_no_behavioural_score():
    df = world()
    state, info, day_of, flags, models = build(df)
    models = {100: models[50]}                                              # first block starts after the candidate
    h = core.score_candidates([cand(["c0", "c1", "c2", "c3"], 64, True, 70)], state, models, AW.FEATURES_HISTORY, info, day_of, flags, core.Settings())[0]
    assert all(x["components"]["behavioural"] == 0.0 for x in h)


# ------------------------------------------------------------------ components and alerts
def test_components_are_bounded_and_weights_must_sum_to_one(tmp_path):
    assert 0 <= core.fund_flow_component(list(core.PATTERN_WEIGHT)) <= 100 and core.fund_flow_component([]) == 0.0
    assert 0 <= core.persistence_component(10_000, 1) <= 100
    assert core.network_component({"source": "cycle_closure"}, ["cycle_closure"], 0) == 100.0
    assert core.network_component({"source": "novelty_seeded"}, ["first_time_sender"], 50) == 100.0                   # capped
    (tmp_path / "configs").mkdir()
    (tmp_path / "configs" / "config.yaml").write_text("risk_scoring:\n  component_weights: {behavioural: 0.5, network: 0.5, fund_flow: 0.5, persistence: 0.5}\n")
    with pytest.raises(ValueError):
        core.load_settings(tmp_path)


def test_alert_day_is_the_first_threshold_crossing_and_none_if_never():
    hist = [{"day": 10, "score": 40}, {"day": 12, "score": 55}, {"day": 15, "score": 30}]
    assert core.alert_day(hist, 50) == 12 and core.alert_day(hist, 60) is None


def test_risk_levels_follow_the_configured_bands():
    th = core.Settings().thresholds
    assert [core.risk_level(x, th) for x in (10, 30, 60, 80)] == ["LOW", "MODERATE", "HIGH", "CRITICAL"]


def test_novelty_patterns_need_two_distinct_counterparties_for_a_slow_drip_fan():
    S = {"t1": "N1", "t2": "N2"}; R = {"t1": "H", "t2": "H"}; sfo = {"t1": 1, "t2": 1}; rfi = {"t1": 0, "t2": 0}
    assert core.novelty_patterns(["t1"], S, R, sfo, rfi) == ["first_time_sender"]
    assert core.novelty_patterns(["t1", "t2"], S, R, sfo, rfi) == ["slow_drip_fan_in"]


def test_a_group_that_re_describes_a_structure_candidate_is_dropped():
    structs = [{"tx": {"a", "b", "c", "d"}}]
    groups = [{"tx": {"a", "b", "x"}}, {"tx": {"p", "q"}}, {"tx": {"d", "y", "z", "w"}}]
    kept = evaluate.dedupe_sources(structs, groups)
    assert {"p", "q"} in [g["tx"] for g in kept] and len(kept) == 2           # 2 of 3 overlap -> dropped; 1 of 4 overlap -> kept


# ------------------------------------------------------------------ exports
def test_artifacts_are_internally_consistent():
    df = world()
    state, info, day_of, flags, models = build(df)
    c = cand(["c0", "c1", "c2", "c3"], 64, True, 70); c["n_seeds"] = 0
    hist = core.score_candidates([c], state, models, AW.FEATURES_HISTORY, info, day_of, flags, core.Settings(scored_from=50))
    art = export.build_artifacts([c], hist, info, day_of, flags, pd.Timestamp("2017-01-01"), core.Settings(), [c])
    rc, rs, ev = art["ring_candidates"][0], art["risk_scores"][0], art["evidence"][0]
    assert rc["candidate_ring_id"] == rs["candidate_ring_id"] == ev["candidate_ring_id"] == "RING0001"
    assert rc["risk_score"] == rs["risk_score"] == ev["risk_factors"]["risk_score"] == hist[0][-1]["score"]
    assert len(ev["transactions"]) == len(ev["evidence_subgraph"]["edges"]) == len(rc["transaction_ids"]) == 4
    assert set(rc["accounts"]) == {n["id"] for n in ev["evidence_subgraph"]["nodes"]} == {"A", "B", "C", "D"}
    assert rc["formation_stage"] == "OBSERVABLE_RING" and ev["paths"][0].count("->") == 4          # the cycle path returns to its start
    assert rc["trajectory"]["pattern_sequence"] == ["partial_path", "cycle_closure"] and rc["trajectory"]["event_window_ids"] == [64, 70]
    assert ev["observable_time"] is None and ev["lead_time"] is None                                 # evidence never carries ground truth
    try:
        import dataclasses
        from src.ring.ring_candidate_engine import RingCandidate
        assert set(rc) <= {f.name for f in dataclasses.fields(RingCandidate)}
    except ImportError:
        pass


def test_no_label_enters_candidate_or_score_construction():
    import inspect
    from src.evaluation import candidates_v2 as C
    for fn in (C.detect_structures, C.detect_novelty_groups, core.score_candidates, core.novelty_patterns, export.build_artifacts):
        assert "label" not in inspect.signature(fn).parameters
    assert not (set(AW.FEATURES_HISTORY) & AW.FORBIDDEN)


# ------------------------------------------------------------------ cross-file consistency on real results (skipped when absent)
RES = ROOT / "results"
needs_results = pytest.mark.skipif(not (RES / "lead_time_summary.json").exists() or not (RES / "v1_backup").exists(), reason="rebuild not run")


@needs_results
def test_every_result_file_describes_the_same_candidates():
    rc = json.load(open(RES / "ring_candidates.json"))
    rs = {r["candidate_ring_id"]: r for r in json.load(open(RES / "risk_scores.json"))}
    ev = {e["candidate_ring_id"]: e for e in json.load(open(RES / "evidence.json"))}
    assert {c["candidate_ring_id"] for c in rc} == set(rs) == set(ev)
    assert all(c["risk_score"] == rs[c["candidate_ring_id"]]["risk_score"] for c in rc)
    assert all(isinstance(w, int) for c in rc for w in c["trajectory"]["event_window_ids"])               # window numbers are numbers, not text
    assert all(isinstance(d, int) for e in ev.values() for d, _ in e["risk_factors"]["score_history"])
    lt = json.load(open(RES / "lead_time_summary.json"))
    assert lt["all_candidates"]["n_candidates"] == len(rc)
    assert lt["alerted_candidates"]["n_alerted"] == sum(1 for c in rc if any(h[1] >= lt["protocol"]["alert_threshold"] for h in ev[c["candidate_ring_id"]]["risk_factors"]["score_history"]))
    pe = json.load(open(RES / "production_evaluation.json"))
    assert pe["ablations"]["production_alerted"]["by_typology"]["all"]["n_evaluable_rings"] == lt["rings"]["n_evaluable"]


@needs_results
def test_no_float_ids_and_full_lineage_in_the_rebuilt_files():
    from src.evaluation import lineage_tools as L
    tx = L.load_source(ROOT / "data/processed/transactions_clean.csv")
    rep = L.check_results(RES, tx)
    rebuilt = {"ring_candidates.json", "risk_scores.json", "evidence.json", "pattern_events.json", "trajectories.json"}
    assert rep["lineage"] == []
    assert all(v is None or v["count"] == 0 for k, v in rep["float_ids"].items() if k in rebuilt)


@needs_results
def test_no_file_in_results_still_describes_the_old_candidates():
    import re
    old_id = re.compile(r"\bRING\d{3}\b")                                     # v1 ids had 3 digits; v2 ids have 4
    offenders = [p.name for p in RES.iterdir() if p.is_file() and p.suffix in (".json", ".csv") and p.stat().st_size < 30_000_000
                 and old_id.search(p.read_text(errors="ignore"))]
    assert offenders == []
    assert (RES / "v1_backup" / "ring_candidates.json").exists()                  # and the old results are still recoverable


@needs_results
def test_model_performance_matches_the_horizon_sensitivity_row_it_is_part_of():
    f = RES / "account_window_eval_v2.json"
    if not f.exists():
        pytest.skip("account-window sensitivity not run")
    aw = json.load(open(f))
    mc = json.load(open(RES / "model_comparison.json"))["proposed_gradient_boosting"]["test"]
    proto = json.load(open(RES / "protocol.json"))
    row = [r for r in aw["results"] if r["horizon_days"] == proto["horizon_days"] and r["features"] == len(AW.FEATURES_HISTORY)]
    assert row and abs(row[0]["pr_auc"] - mc["pr_auc"]) < 1e-9 and row[0]["tp"] == mc["confusion_matrix"]["tp"] and row[0]["fp"] == mc["confusion_matrix"]["fp"]


# ------------------------------------------------------------------ reproducibility
def test_thresholded_metrics_are_immune_to_floating_point_noise():
    from src.pipeline_v2 import models as M
    rng = np.random.default_rng(0)
    y = (rng.random(5000) < 0.02).astype(int)
    s = np.round(rng.random(5000), 3)                       # many exact ties, like identical feature vectors
    thr = float(s[y == 1].min())                            # a threshold that sits exactly on a score value
    base = M.metrics_at(y, s, thr)
    for seed in range(5):
        noisy = s + np.random.default_rng(seed).normal(0, 3e-16, size=s.shape)
        m = M.metrics_at(y, noisy, thr)
        assert m["confusion_matrix"] == base["confusion_matrix"] and m["top_k_precision"] == base["top_k_precision"]


def test_the_random_forest_is_repeatable_bit_for_bit():
    from src.pipeline_v2 import models as M
    rng = np.random.default_rng(3)
    X = rng.random((6000, 6)).astype(np.float32); y = (X[:, 0] + 0.3 * rng.random(6000) > 1.0).astype(int)
    a = M.fit_scores("random_forest", X[:4000], y[:4000], [X[4000:]], 42, 50)[0]
    b = M.fit_scores("random_forest", X[:4000], y[:4000], [X[4000:]], 42, 50)[0]
    assert np.array_equal(a, b)
