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
    assert rc["trajectory"]["pattern_sequence"] == ["layering", "circular_flow"] and rc["trajectory"]["event_window_ids"] == [64, 70]
    assert all("cycle_closure" not in f for f in rs["top_factors"]) and "circular_flow" in " ".join(rs["top_factors"])   # explanations use the original names
    assert set(rc["patterns"]) <= core.OLD_VOCABULARY and set(ev["patterns"]) <= core.OLD_VOCABULARY
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


# ------------------------------------------------------------------ stability across retrainings
def test_stability_summary_reports_this_run_median_and_range():
    rows = {"42": {"alerts": 14, "precision": 0.857, "lead": 1.0, "p10": None},
            "43": {"alerts": 12, "precision": 0.833, "lead": None, "p10": 0.7},
            "44": {"alerts": 13, "precision": 0.846, "lead": 0.5, "p10": 0.8}}
    st = evaluate.summarize_stability(rows, "42")
    a = st["metrics"]["alerts"]
    assert (a["production"], a["min"], a["median"], a["max"], a["n"]) == (14, 12, 13.0, 14, 3)
    assert st["metrics"]["lead"]["n"] == 2 and st["metrics"]["lead"]["min"] == 0.5              # a missing value is skipped, not counted as zero
    assert st["metrics"]["p10"]["production"] is None and st["n_retrainings"] == 3 and st["production_seed"] == "42"


def test_the_apply_script_accepts_several_known_previous_versions(tmp_path):
    import hashlib, importlib.util
    spec = importlib.util.spec_from_file_location("ap", ROOT / "scripts" / "apply_dashboard_fixes.py")
    ap = importlib.util.module_from_spec(spec); spec.loader.exec_module(ap)
    h = lambda b: hashlib.sha256(b).hexdigest()
    ap.ROOT = tmp_path
    (tmp_path / "f.txt").write_bytes(b"version two\n")
    meta = {"original_sha256": [h(b"version one\n"), h(b"version two\n")], "new_sha256": h(b"version three\n")}
    assert ap.classify("f.txt", meta) == "UPDATE"
    (tmp_path / "f.txt").write_bytes(b"my own edit\n")
    assert ap.classify("f.txt", meta) == "CHANGED"
    (tmp_path / "f.txt").write_bytes(b"version three\n")
    assert ap.classify("f.txt", meta) == "ALREADY APPLIED"


# ------------------------------------------------------------------ original pattern names
def test_old_names_map_each_detector_to_its_true_equivalent_and_drop_seed_signals():
    assert core.old_names(["cycle_closure"]) == ["circular_flow"]
    assert core.old_names(["partial_path"]) == core.old_names(["new_account_chain"]) == ["layering"]
    assert core.old_names(["slow_drip_fan_in", "slow_drip_fan_out"]) == ["fan_in", "fan_out"]
    assert core.old_names(["partial_path", "new_account_chain"]) == ["layering"]                      # no duplicates
    assert core.old_names(["first_time_sender", "first_time_receiver"]) == []                         # a seed transfer is not a pattern
    assert set(core.OLD_NAME.values()) <= core.OLD_VOCABULARY


def test_scoring_does_not_depend_on_the_names_shown():
    """Renaming is a display change: the weights still use the detectors' internal labels."""
    assert core.fund_flow_component(["cycle_closure"]) == 30.0 and core.fund_flow_component(["slow_drip_fan_out"]) == 10.0


@needs_results
def test_result_files_use_only_the_original_pattern_names():
    text = " ".join((RES / f"{n}.json").read_text() for n in ("ring_candidates", "pattern_events", "evidence", "risk_scores", "trajectories"))
    for internal in ("slow_drip", "cycle_closure", "partial_path", "new_account_chain", "first_time_"):
        assert internal not in text
    assert {e["pattern_type"] for e in json.load(open(RES / "pattern_events.json"))} <= core.OLD_VOCABULARY
    assert all(c["patterns"] and set(c["patterns"]) <= core.OLD_VOCABULARY for c in json.load(open(RES / "ring_candidates.json")))


# ------------------------------------------------------------------ warning log and pattern evidence
def _warning_world():
    from src.pipeline_v2 import warning_log
    s = core.Settings(scored_from=10, alert_threshold=50.0)
    cands = [{"tx": {"a1", "a2"}, "nodes": {"A", "B"}, "creation_day": 20},         # contains ring 7's transactions
             {"tx": {"b1"}, "nodes": {"C", "D"}, "creation_day": 30},               # never alerts
             {"tx": {"c1", "c2"}, "nodes": {"E", "F"}, "creation_day": 40}]         # alerts, but holds no ring transaction
    mk = lambda d, sc, pats: {"day": d, "score": sc, "level": core.risk_level(sc, s.thresholds), "components": {}, "patterns": pats, "n_nodes": 2, "n_tx": 2}
    hist = [[mk(20, 40.0, ["cycle_closure"]), mk(22, 55.0, ["cycle_closure"]), mk(25, 45.0, ["cycle_closure"])],       # alert on day 22, fell back to 45
            [mk(30, 30.0, ["slow_drip_fan_out"])],
            [mk(40, 60.0, ["partial_path"])]]
    index = {0: "RING0001", 1: "RING0002", 2: "RING0003"}
    day_of = {"a1": 20, "a2": 21, "b1": 30, "c1": 40, "c2": 41}
    label_of = {"a1": 1, "a2": 1, "b1": 0, "c1": 0, "c2": 0}
    ring_of = {"a1": "7", "a2": "7"}
    tx = pd.DataFrame({"day": [20, 21, 30, 40, 41, 60]})
    # ring ids are TEXT in memory (they only become numbers once read back from a CSV) -- the first version of this module missed that
    rings = pd.DataFrame({"ring_id": ["7", "8"], "typology": ["cycle", "fan_in"], "first_day": [20, 2], "last_day": [21, 50], "observable_day": [30, 100], "n_tx": [2, 5]})
    base = {"ring_id": ["7", "8"], "typology": ["cycle", "fan_in"], "evaluable": [True, False]}
    per_ring = {"production_all": pd.DataFrame({**base, "detected": [True, False], "warning_day": [20.0, None], "lead_days": [10.0, None], "tx_coverage": [1.0, 0.0]}),
                "production_alerted": pd.DataFrame({**base, "detected": [True, False], "warning_day": [22.0, None], "lead_days": [8.0, None], "tx_coverage": [1.0, 0.0]})}
    return warning_log.build_warnings(cands, hist, index, per_ring, rings, ring_of, label_of, day_of, tx, pd.Timestamp("2017-01-01"), s)


def test_the_warning_log_records_each_alert_and_where_it_falls_on_its_ring():
    w = _warning_world()
    assert [a["candidate_ring_id"] for a in w["alerts"]] == ["RING0001", "RING0003"]          # RING0002 never reached the threshold
    a, b = w["alerts"]
    assert (a["alert_day"], a["score_at_alert"], a["final_score"], a["days_creation_to_alert"]) == (22, 55.0, 45.0, 2)
    assert a["patterns"] == ["circular_flow"] and a["contains_ring_tx"] and a["ring_id"] == 7 and a["ring_evaluable"] and a["lead_days"] == 8   # 30 - 22
    assert b["contains_ring_tx"] is False and b["ring_id"] is None and b["lead_days"] is None and b["patterns"] == ["layering"]


def test_text_ring_ids_are_matched_so_evaluable_rings_are_not_lost():
    w = _warning_world()
    r7, r8 = w["rings"]
    assert r7["evaluable"] is True and r8["evaluable"] is False                                # the bug made every ring "not evaluable"
    assert r7["alert"]["status"] == "before" and r7["queue"]["status"] == "before" and r7["alert"]["candidate"] == "RING0001"
    assert r8["not_evaluable_reason"].startswith("starts before the scored period") and r8["queue"]["status"] is None
    S = w["summary"]
    assert (S["n_alerts"], S["alerts_with_ring_tx"], S["false_alerts"], S["n_evaluable"]) == (2, 1, 1, 1)
    assert S["alert"] == {"before": 1, "at": 0, "after": 0, "not_seen": 0}
    assert sum(d["alerts"] for d in w["daily"]) == S["n_alerts"] and w["daily"][0]["day"] == 10


def test_ring_status_classification():
    from src.pipeline_v2.warning_log import _status
    assert [_status(True, 3), _status(True, 0), _status(True, -2), _status(False, None), _status(True, None)] == ["before", "at", "after", "not_seen", "not_seen"]


def test_pattern_evidence_groups_every_candidate_once_and_explains_the_contributions():
    from src.pipeline_v2 import pattern_evidence
    s = core.Settings()
    art = {"ring_candidates": [{"candidate_ring_id": f"R{i}", "patterns": p} for i, p in enumerate([["circular_flow"], ["fan_out"], ["fan_out"], ["fan_in", "fan_out"]])],
           "risk_scores": [{"candidate_ring_id": f"R{i}", "risk_score": sc, "risk_level": core.risk_level(sc, s.thresholds), "score_components": dict.fromkeys(s.weights, 10.0)}
                           for i, sc in enumerate([60.0, 40.0, 42.0, 38.0])]}
    cands = [{"tx": {f"t{i}", f"u{i}"}} for i in range(4)]
    label_of = {"t0": 1, "t3": 1}
    wl = {"alerts": [{"candidate_ring_id": "R0", "alert_date": "d", "score_at_alert": 60.0}]}
    p = pattern_evidence.build_pattern_evidence(art, cands, {i: f"R{i}" for i in range(4)}, label_of, wl, s)
    assert sum(r["candidates"] for r in p["by_count"]) == p["n_candidates"] == 4 and (p["single_pattern_candidates"], p["multi_pattern_candidates"]) == (3, 1)
    assert (p["alerts_on_single_pattern"], p["alerts_on_multi_pattern"]) == (1, 0) and p["multi_pattern"][0]["contains_ring_tx"] is True
    pts = {c["pattern"]: c["score_points"] for c in p["pattern_contributions"]}
    assert pts["circular_flow"] == 3.0 / core.MAX_PATTERN_WEIGHT * 100 * s.weights["fund_flow"] and pts["circular_flow"] > pts["layering"] > pts["fan_in"] == pts["fan_out"]


@needs_results
def test_warning_log_agrees_with_the_lead_time_results_and_the_candidates():
    w = json.load(open(RES / "warnings.json")); lt = json.load(open(RES / "lead_time_summary.json"))
    S = w["summary"]
    assert S["n_alerts"] == lt["alerted_candidates"]["n_alerted"] and S["alerts_with_ring_tx"] == lt["alerted_candidates"]["alerted_containing_ring_tx"]
    assert S["n_evaluable"] == lt["rings"]["n_evaluable"] and S["n_evaluable"] - S["alert"]["not_seen"] == lt["rings"]["n_seen"]
    assert S["alert"]["before"] == lt["rings"]["n_warned_before_completion"] and S["queue"]["before"] == lt["all_candidates"]["warned_before_completion"]
    assert S["n_evaluable"] - S["queue"]["not_seen"] == lt["all_candidates"]["rings_seen"]
    ids = {c["candidate_ring_id"] for c in json.load(open(RES / "ring_candidates.json"))}
    assert all(a["candidate_ring_id"] in ids for a in w["alerts"]) and sum(d["alerts"] for d in w["daily"]) == S["n_alerts"]
    import pandas as pd
    csv = pd.read_csv(RES / "production_evaluation_rings.csv"); csv = csv[csv.candidate_set == "production_alerted"].set_index("ring_id")
    for r in w["rings"]:
        if r["evaluable"] and r["alert"]["seen"]:
            assert r["alert"]["lead_days"] == csv.loc[r["ring_id"], "lead_days"]                  # the log and the evaluation file say the same thing
    assert all(r["alert"]["status"] is None for r in w["rings"] if not r["evaluable"])


@needs_results
def test_pattern_evidence_agrees_with_the_candidates_and_the_alerts():
    p = json.load(open(RES / "pattern_evidence.json")); rc = json.load(open(RES / "ring_candidates.json")); w = json.load(open(RES / "warnings.json"))
    assert p["n_candidates"] == len(rc) == sum(r["candidates"] for r in p["by_count"]) == sum(r["candidates"] for r in p["by_set"])
    assert p["multi_pattern_candidates"] == sum(1 for c in rc if len(c["patterns"]) >= 2) == len(p["multi_pattern"])
    assert p["alerts_on_single_pattern"] + p["alerts_on_multi_pattern"] == w["summary"]["n_alerts"]
    assert all(set(r["patterns"]) <= core.OLD_VOCABULARY for r in p["by_set"])


# ------------------------------------------------------------------ score calculation card
def _entry(kind="closed_cycle", pats=("cycle_closure",), n_tx=7, n_nodes=6, seeds=0):
    s = core.Settings()
    comp = {"behavioural": 72.14, "network": core.network_component({"source": "cycle_closure"} if kind != "first_time_group" else {"source": "novelty_seeded"}, list(pats), seeds),
            "fund_flow": core.fund_flow_component(list(pats)), "persistence": core.persistence_component(n_tx, n_nodes)}
    score = core.combine(comp, s.weights)
    return s, {"day": 5, "score": score, "level": core.risk_level(score, s.thresholds), "components": comp, "patterns": list(pats), "n_tx": n_tx, "n_nodes": n_nodes,
               "inputs": {"kind": kind, "n_first_time_transfers": seeds, "n_accounts_scored": n_nodes, "top_account": "A7", "top_percentile": 98.4}}


def test_the_calculation_is_the_score_and_quotes_the_scorers_own_numbers():
    from src.pipeline_v2 import score_calculation
    s, e = _entry()
    c = score_calculation.explain(e, s)
    assert c["total_points"] == c["score"] == e["score"]                                     # the total is exactly the score
    assert [x["component"] for x in c["steps"]] == list(s.weights)
    for x in c["steps"]:
        assert abs(x["points"] - x["value"] * x["weight"]) < 1e-3
    how = {x["component"]: x["how"] for x in c["steps"]}
    assert "closed cycle of money scores 100" in how["network"] and "circular flow (weight 3)" in how["fund_flow"] and "3 / 10 x 100" in how["fund_flow"]
    assert "35 x ln(1 + 3 x 7 evidence transactions / 6 accounts)" in how["persistence"] and "account A7 at the 98th percentile" in how["behavioural"]
    assert c["formula"] == "score = 0.35 x behavioural + 0.20 x network + 0.25 x fund flow + 0.20 x persistence"
    assert c["alert"] is (e["score"] >= s.alert_threshold)


def test_a_first_time_group_explains_its_network_value_from_its_transfers():
    from src.pipeline_v2 import score_calculation
    s, e = _entry(kind="first_time_group", pats=("slow_drip_fan_out",), n_tx=3, n_nodes=4, seeds=3)
    net = [x for x in score_calculation.explain(e, s)["steps"] if x["component"] == "network"][0]
    assert net["value"] == 80.0 and "20 for each of the 3 first-time transfers" in net["how"] and "+20 for a fan that builds over time" in net["how"] and "capped at 100" in net["how"]


@needs_results
def test_every_candidates_calculation_is_the_score_and_recomputes_from_its_inputs():
    import math
    calc = json.load(open(RES / "score_calculation.json")); rs = {r["candidate_ring_id"]: r for r in json.load(open(RES / "risk_scores.json"))}
    rc = {c["candidate_ring_id"]: c for c in json.load(open(RES / "ring_candidates.json"))}; w = json.load(open(RES / "warnings.json"))
    weights = json.load(open(RES / "pattern_evidence.json"))["component_weights"]
    pw = {"circular_flow": 3.0, "layering": 2.0, "fan_in": 1.0, "fan_out": 1.0}
    assert set(calc) == set(rs)
    alerted = {a["candidate_ring_id"]: a for a in w["alerts"]}
    for rid, e in calc.items():
        c, steps = e["calculation"], e["steps"]
        assert c["total_points"] == c["score"] == rs[rid]["risk_score"] and steps[-1]["score"] == c["score"]
        assert abs(sum(x["value"] * x["weight"] for x in c["steps"]) - c["score"]) < 0.011
        assert {x["component"]: x["weight"] for x in c["steps"]} == weights
        last = steps[-1]
        ff = sum(pw[p] for p in set(last["patterns"])) / 10.0 * 100
        pers = min(100.0, 35 * math.log(1 + 3 * last["n_tx"] / max(last["n_nodes"], 1)))
        got = {x["component"]: x["value"] for x in c["steps"]}
        assert abs(got["persistence"] - pers) < 0.011                                        # recomputed independently from the evidence counts
        if set(rc[rid]["patterns"]) <= set(pw) and not any(p in last["patterns"] for p in ()):
            assert abs(got["fund_flow"] - ff) < 0.011
        if rc[rid]["patterns"] == ["circular_flow"]:
            assert got["network"] == 100.0
        assert (e["alert_day"] is not None) == (rid in alerted)                              # the card and the warning log agree on who raised an alert
        if rid in alerted:
            assert e["alert_day"] == alerted[rid]["alert_day"] and next(s for s in steps if s["day"] == e["alert_day"])["score"] >= c["alert_threshold"]


def test_export_asks_for_the_scoring_stage_when_the_saved_scores_predate_the_inputs():
    import pytest
    from src.pipeline_v2 import score_calculation
    s, e = _entry()
    old = {k: v for k, v in e.items() if k != "inputs"}
    with pytest.raises(SystemExit, match="rebuild_v2.py scoring"):
        score_calculation.build_all([{}], [[old]], {0: "RING0001"}, pd.Timestamp("2017-01-01"), s)
    ok = score_calculation.build_all([{}], [[e]], {0: "RING0001"}, pd.Timestamp("2017-01-01"), s)
    assert ok["RING0001"]["calculation"]["score"] == e["score"] and e["score"] >= core.Settings().alert_threshold and ok["RING0001"]["alert_day"] == 5     # a score above the threshold is an alert on that day
