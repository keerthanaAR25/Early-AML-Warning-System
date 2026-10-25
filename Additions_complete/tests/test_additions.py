"""Tests for the ADDITIVE modules: ring_lead_time and lineage_tools. Run: pytest tests/test_additions.py -v"""
import json
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.evaluation import ring_lead_time as R  # noqa: E402
from src.evaluation import lineage_tools as L  # noqa: E402


def _tx(rows):
    df = pd.DataFrame(rows, columns=["transaction_id", "sender", "receiver", "amount", "label", "day"])
    return df.sort_values("day", kind="mergesort").reset_index(drop=True)


# ------------------------------------------------------------------ features are causal
def test_features_use_only_strictly_prior_days():
    tx = _tx([("t1", "A", "B", 10, 0, 0), ("t2", "A", "B", 10, 0, 1), ("t3", "A", "C", 10, 0, 1),
              ("t4", "B", "A", 10, 0, 3)])
    F = R.build_features(tx).set_index("transaction_id")
    assert F.loc["t1", "s_out"] == 0 and F.loc["t1", "pair"] == 0 and F.loc["t1", "s_first_out"] == 1
    assert F.loc["t2", "s_out"] == 1 and F.loc["t2", "pair"] == 1 and F.loc["t2", "edge_is_new"] == 0
    assert F.loc["t3", "s_out"] == 1 and F.loc["t3", "pair"] == 0 and F.loc["t3", "edge_is_new"] == 1
    assert F.loc["t2", "s_out_today"] == 2                    # same-day count is allowed (end-of-day batch)
    assert F.loc["t4", "rev_pair"] == 2                       # A->B happened twice before day 3
    assert F.loc["t4", "r_in"] == 0                           # A never received before day 3
    assert F.loc["t4", "s_age"] == 3 and F.loc["t4", "s_idle"] == 2   # B first seen day0, previous active day1


def test_future_rows_do_not_change_past_features():
    base = [("t1", "A", "B", 10, 0, 0), ("t2", "A", "B", 5, 0, 1)]
    F1 = R.build_features(_tx(base)).set_index("transaction_id")
    F2 = R.build_features(_tx(base + [("t9", "A", "B", 99, 1, 50), ("t8", "Z", "A", 1, 0, 40)])).set_index("transaction_id")
    cols = [c for c in F1.columns if c != "day"]
    pd.testing.assert_frame_equal(F1.loc[["t1", "t2"], cols], F2.loc[["t1", "t2"], cols], check_dtype=False)


def test_no_label_like_columns_in_features():
    F = R.build_features(_tx([("t1", "A", "B", 10, 1, 0)]))
    assert not (set(F.columns) & R.FORBIDDEN_FEATURE_NAMES)
    for cols in R.XGB_SPECS.values():
        assert not (set(cols) & R.FORBIDDEN_FEATURE_NAMES)
    # the shortcut-free control must carry no account-history feature at all
    history = {"s_out", "r_in", "pair", "rev_pair", "edge_is_new", "s_first_out", "r_first_in", "s_age", "r_age", "s_idle", "r_idle"}
    assert not (set(R.XGB_SPECS["xgb_without_novelty"]) & history)


# ------------------------------------------------------------------ ring definitions
def _alerts(rows):
    return pd.DataFrame(rows, columns=["alert_id", "alert_type", "transaction_id", "orig_acct", "bene_acct", "day"])


def test_observable_time_cycle_is_last_edge_and_fan_is_kth_counterparty():
    at = _alerts([(1, "cycle", "c1", "A", "B", 5), (1, "cycle", "c2", "B", "C", 9), (1, "cycle", "c3", "C", "A", 7),
                  (2, "fan_in", "f1", "S1", "H", 1), (2, "fan_in", "f2", "S2", "H", 10), (2, "fan_in", "f3", "S3", "H", 20),
                  (2, "fan_in", "f4", "S4", "H", 40), (2, "fan_in", "f5", "S5", "H", 80),
                  (3, "fan_out", "o1", "H", "R1", 2), (3, "fan_out", "o2", "H", "R2", 3)])
    rt = R.ring_table(at, k=4).set_index("ring_id")
    assert rt.loc["1", "observable_day"] == 9 and rt.loc["1", "observable_tx"] == "c2"
    assert rt.loc["2", "observable_day"] == 40 and rt.loc["2", "observable_tx"] == "f4"
    assert rt.loc["3", "observable_day"] == 3            # fewer than k counterparties -> last transaction day


# ------------------------------------------------------------------ lead-time arithmetic
def test_lead_time_is_observable_minus_warning_and_missing_warning_is_not_detected():
    rings = pd.DataFrame([
        dict(ring_id="1", typology="cycle", first_day=100, last_day=112, observable_day=112, observable_tx="x3",
             n_tx=3, tx_ids=["x1", "x2", "x3"]),
        dict(ring_id="2", typology="cycle", first_day=100, last_day=110, observable_day=110, observable_tx="y2",
             n_tx=2, tx_ids=["y1", "y2"]),
        dict(ring_id="3", typology="cycle", first_day=10, last_day=20, observable_day=20, observable_tx="z2",
             n_tx=2, tx_ids=["z1", "z2"])])                       # observable before the scored period -> not evaluable
    scored = pd.DataFrame({
        "transaction_id": ["x1", "x2", "x3", "y1", "y2", "n1", "n2"],
        "day": [102, 105, 112, 100, 110, 102, 102],
        "label": [1, 1, 1, 1, 1, 0, 0],
        "score": [0.9, 0.2, 0.1, 0.0, 0.0, 0.95, 0.05],
        "s_first_out": [1, 0, 0, 0, 0, 0, 0]})
    per_ring, fs = R.evaluate_budget(scored, rings, k=1, eval_start=100, seed=0)
    r = per_ring.set_index("ring_id")
    # day 102: n1 (0.95) beats x1 (0.9) for the single daily slot -> x1 NOT flagged; day 105: x2 flagged
    assert r.loc["1", "warning_day"] == 105 and r.loc["1", "lead_days"] == 7
    assert not bool(r.loc["3", "evaluable"])
    # right-truncation guard: observable inside the scored period but ring started before it -> not (fully) evaluable
    rings2 = rings.copy(); rings2.loc[0, "first_day"] = 90
    pr2, _ = R.evaluate_budget(scored, rings2, k=1, eval_start=100, seed=0)
    assert bool(pr2.set_index("ring_id").loc["1", "observable_in_scored_period"]) and not bool(pr2.set_index("ring_id").loc["1", "evaluable"])
    s = R.summarize(per_ring)
    assert s["all"]["n_evaluable_rings"] == 2
    assert fs["alerts_per_day_budget"] == 1 and fs["false_flags"] >= 1


def test_bootstrap_ci_refuses_tiny_samples():
    assert R.bootstrap_ci([1, 2, 3]) == [None, None]
    lo, hi = R.bootstrap_ci(np.arange(20))
    assert lo < hi


def test_rolling_scores_never_use_the_scored_block_or_continuing_rings():
    rng = np.random.default_rng(0)
    rows, tid = [], 0
    for d in range(0, 400):
        for _ in range(5):
            rows.append((f"t{tid}", f"a{rng.integers(0, 50)}", f"a{rng.integers(0, 50)}", 100.0, 0, d)); tid += 1
    for i, d in enumerate(range(130, 230, 20)):                  # ring A: ends before block 1 -> usable for training
        rows.append((f"pos{i}", f"n{i}", f"m{i}", 100.0, 1, d))
    for i, d in enumerate(range(210, 390, 15)):                  # ring B: spans the block boundary -> must be excluded
        rows.append((f"posB{i}", f"q{i}", f"w{i}", 100.0, 1, d))
    tx = _tx(rows)
    at = _alerts([(1, "cycle", f"pos{i}", f"n{i}", f"m{i}", d) for i, d in enumerate(range(130, 230, 20))] +
                 [(2, "cycle", f"posB{i}", f"q{i}", f"w{i}", d) for i, d in enumerate(range(210, 390, 15))])
    rings = R.ring_table(at)
    F = R.build_features(tx)
    scored, info = R.score_rolling(tx, F, rings, "xgb_with_novelty", eval_start=240, block_len=120, burn_in=60,
                                   seed=1, n_estimators=20, min_train_pos=3)
    assert scored["day"].min() >= 240
    assert info[0]["scored"]
    n_pos_ring_a_only = sum(1 for d in range(130, 230, 20) if 60 <= d < 240)
    assert info[0]["n_train_pos"] == n_pos_ring_a_only           # ring B excluded from block-1 training


# ------------------------------------------------------------------ lineage tools
def test_normalisation_drops_float_duplicates_but_keeps_genuine_repeats():
    assert L.normalize_obj({"accounts": ["105", "14", "14.0", "174"]})["accounts"] == ["105", "14", "174"]
    assert L.normalize_obj(["A", "B", "A"]) == ["A", "B", "A"]                       # real pass-through chain: untouched
    assert L.normalize_obj(["14.0", "14.0"]) == ["14"]
    assert L.normalize_obj(["12.0", "12"]) == ["12"]                                   # float form listed first
    assert L.normalize_obj(["A", "B", "A", "7.0", "7"]) == ["A", "B", "A", "7"]
    assert L.count_float_duplicates({"x": ["14", "14.0"], "y": ["A", "B", "A"]}) == 1
    assert json.loads(L.fix_text('["14", "14.0", "9"]')) == ["14", "9"]
    assert L.fix_text("820.10") == "820.10" and L.fix_text("49066.0") == "49066"


def test_normalize_helpers():
    assert L.norm_id("49066.0") == "49066" and L.norm_id("599.15") == "599.15" and L.norm_id("820.10") == "820.10"
    assert L.normalize_obj({"a": ["1.0", "2", {"b": "3.0"}]}) == {"a": ["1", "2", {"b": "3"}]}
    assert L.normalize_json_text('["49066.0", 599.15, "820.10", "x"]') == '["49066", 599.15, "820.10", "x"]'


@pytest.fixture
def project(tmp_path):
    tx = pd.DataFrame({"transaction_id": ["1", "2", "3"], "sender": ["10", "11", "12"], "receiver": ["11", "12", "10"],
                       "amount": [5.0, 6.0, 7.0], "timestamp": ["2017-01-01"] * 3})
    clean = tmp_path / "clean.csv"; tx.to_csv(clean, index=False)
    res = tmp_path / "results"; res.mkdir()
    cand = [{"candidate_ring_id": "RING001", "accounts": ["10", "11", "12.0", "12"], "transaction_ids": ["1", "2", "3.0", "3"]}]
    ev = [{"candidate_ring_id": "RING001", "accounts": ["10", "11"], "transactions": [
        {"transaction_id": "1", "sender": "10", "receiver": "11", "amount": 5.0, "timestamp": "t"},
        {"transaction_id": "2", "sender": "11", "receiver": "12", "amount": 6.0, "timestamp": "t"}],
        "evidence_subgraph": {"nodes": [{"id": "10"}, {"id": "11"}, {"id": "12"}], "edges": [{"id": "1"}, {"id": "2"}]}}]
    (res / "ring_candidates.json").write_text(json.dumps(cand))
    (res / "evidence.json").write_text(json.dumps(ev))
    db = tmp_path / "t.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE evidence (candidate_ring_id VARCHAR, accounts_json TEXT, transactions_json TEXT, evidence_subgraph_json TEXT)")
    con.execute("INSERT INTO evidence VALUES (?,?,?,?)", ("RING001", json.dumps(["10", "11"]), json.dumps([{"transaction_id": "3.0"}]), "{}"))
    con.execute("CREATE TABLE transactions (transaction_id VARCHAR, amount FLOAT, ts DATETIME)")
    con.execute("INSERT INTO transactions VALUES ('1', 820.10, '2017-01-01 00:00:00.000000')")
    con.commit(); con.close()
    return tx, clean, res, db


def test_check_detects_float_ids_and_lineage_gap(project):
    tx, clean, res, db = project
    rep = L.check_results(res, tx)
    assert rep["float_ids"]["ring_candidates.json"]["count"] == 2
    assert rep["lineage"], "candidate lists tx 3 but evidence lacks it -> must be reported"
    assert rep["lineage"][0]["inflated_by_float_duplicates"] == 2           # '12.0' and '3.0' duplicate '12' and '3'
    assert L.check_db(db) == {"evidence.transactions_json": 1}


def test_fix_normalises_backs_up_and_rebuild_closes_the_gap(project):
    tx, clean, res, db = project
    L.fix_results(res); L.fix_db(db)
    assert (res / "ring_candidates.json.bak").exists() and Path(str(db) + ".bak").exists()
    assert L.count_float_ids(json.loads((res / "ring_candidates.json").read_text())) == 0
    fixed_c = json.loads((res / "ring_candidates.json").read_text())[0]
    assert fixed_c["accounts"] == ["10", "11", "12"] and fixed_c["transaction_ids"] == ["1", "2", "3"]
    assert L.check_db(db) == {}
    fixed = L.rebuild_evidence(res, tx, db)
    assert fixed["RING001"]["edges"] == 3
    rep = L.check_results(res, tx)
    assert rep["lineage"] == []
    con = sqlite3.connect(db)
    sub = json.loads(con.execute("SELECT evidence_subgraph_json FROM evidence").fetchone()[0])
    assert len(sub["edges"]) == 3
    # amounts and timestamps untouched
    assert con.execute("SELECT amount FROM transactions").fetchone()[0] == 820.10
