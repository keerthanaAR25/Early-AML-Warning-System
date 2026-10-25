"""Tests for the leakage-safe account-window evaluation (ADDITIVE). Run: pytest tests/test_account_window_eval.py -v"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.evaluation import account_window_eval as E  # noqa: E402


def _tx(rows):
    df = pd.DataFrame(rows, columns=["transaction_id", "sender", "receiver", "label", "day"])
    return df.sort_values("day", kind="mergesort").reset_index(drop=True)


BASE = [("t1", "A", "B", 0, 0), ("t2", "A", "C", 0, 1), ("t3", "B", "C", 1, 4), ("t4", "D", "A", 0, 6), ("t5", "C", "D", 1, 7)]


def test_label_requires_activity_today_and_an_alert_within_the_horizon():
    st = E.build_state(_tx(BASE))
    a = {x: i for i, x in enumerate(st["accts"])}
    Y2, Y3 = E.label_matrix(st, 2), E.label_matrix(st, 3)
    # B is active on day 4 (alert tx t3 itself) -> alert on day 4 is NOT in (4, 6]; C alerts on day 7
    assert not Y2[a["B"], 1]                       # B inactive on day 1 -> never positive even if an alert follows
    assert Y3[a["C"], 4]                           # C active day 4 (receives t3); alert tx t5 on day 7 is within 3 days
    assert not Y2[a["C"], 4]                       # ... but not within 2 days
    assert Y3[a["C"], 4] and not Y3[a["D"], 3]     # D inactive on day 3
    assert (Y2 <= st["active"]).all()              # positives are always active accounts


def test_features_are_causal_removing_the_future_changes_nothing_in_the_past():
    full = E.build_state(_tx(BASE))
    cut = E.build_state(_tx([r for r in BASE if r[4] <= 4]))
    a_full = {x: i for i, x in enumerate(full["accts"])}
    a_cut = {x: i for i, x in enumerate(cut["accts"])}
    for name in E.FEATURES_HISTORY:
        for acct in ("A", "B", "C"):
            for day in range(0, 5):
                assert full["feats"][name][a_full[acct], day] == pytest.approx(cut["feats"][name][a_cut[acct], day]), (name, acct, day)


def test_history_features_values():
    st = E.build_state(_tx(BASE))
    a = {x: i for i, x in enumerate(st["accts"])}
    f = st["feats"]
    assert f["first_out_today"][a["A"], 0] == 1 and f["first_out_today"][a["A"], 1] == 0      # A's first-ever outgoing tx is day 0
    assert f["age"][a["D"], 6] == 0 and f["age"][a["A"], 6] == 6
    assert f["out_to_date"][a["A"], 6] == 2 and f["cp_to_date"][a["A"], 6] == 3              # B, C, D
    assert f["idle"][a["A"], 6] == 0 and f["idle"][a["B"], 6] == 2                           # B last active day 4


def test_features_contain_no_label_information():
    assert not (set(E.FEATURES_HISTORY) & E.FORBIDDEN)


def test_split_bounds_purge_the_label_horizon_at_every_boundary():
    for H in (2, 7, 14):
        b = E.split_bounds(720, H)
        assert b["train"][1] + H < b["val"][0] and b["val"][1] + H < b["test"][0]       # labels never reach into the next period
        assert b["test"] == (576, 719) and b["train"][0] == 120
    assert E.split_bounds(720, 2)["val"] == (432, 573)


def test_threshold_uses_validation_only_and_test_labels_cannot_move_it():
    rng = np.random.default_rng(0)
    yv = np.r_[np.ones(20), np.zeros(980)].astype(int)
    sv = np.r_[rng.uniform(0.6, 1.0, 20), rng.uniform(0.0, 0.7, 980)]
    t1 = E.choose_threshold(yv, sv)
    assert 0.5 < t1 < 1.0
    assert E.choose_threshold(np.zeros(10, int), np.linspace(0, 1, 10)) == 0.5          # no validation positives -> neutral fallback


def test_weighted_ap_matches_sklearn_and_cluster_bootstrap_is_a_sensible_interval():
    from sklearn.metrics import average_precision_score
    rng = np.random.default_rng(1)
    n = 3000
    acct = rng.integers(0, 300, n)
    y = (rng.random(n) < 0.02).astype(int)
    s = rng.random(n) + 0.8 * y
    order = np.argsort(-s, kind="stable")
    assert E.fast_weighted_ap(y[order].astype(float), np.ones(n)) == pytest.approx(average_precision_score(y, s), abs=1e-3)
    lo, hi = E.cluster_bootstrap_ap(y, s, acct, n_boot=200, seed=0)
    assert lo < average_precision_score(y, s) < hi + 0.05 and 0 < lo < hi <= 1


def test_wilson_interval_is_valid_for_small_counts():
    lo, hi = E.wilson(8, 12)
    assert 0.38 < lo < 0.67 < hi < 0.88
    assert E.wilson(0, 10)[0] == 0.0 and E.wilson(10, 10)[1] == 1.0 and E.wilson(0, 0) == [None, None]


def test_weighted_ap_is_not_nan_when_the_highest_scored_rows_have_zero_weight():
    y = np.array([1, 0, 1, 0, 0, 1], float)                      # sorted by score already
    w = np.array([0, 0, 2, 1, 1, 1], float)                      # top two rows were not drawn in this resample
    v = E.fast_weighted_ap(y, w)
    assert not np.isnan(v) and 0 < v <= 1
    from sklearn.metrics import average_precision_score
    keep = np.repeat(np.arange(6), w.astype(int))                # the same resample, written out row by row
    assert v == pytest.approx(average_precision_score(y[keep], -np.arange(6)[keep]), abs=0.05)


def test_bootstrap_keeps_almost_all_resamples():
    rng = np.random.default_rng(5)
    acct = rng.integers(0, 80, 2000); y = (rng.random(2000) < 0.03).astype(int); s = rng.random(2000) + y
    order = np.argsort(-s, kind="stable"); n_acc = 80; ok = 0
    for i in range(100):
        counts = np.bincount(np.random.default_rng(i).integers(0, n_acc, n_acc), minlength=n_acc).astype(float)
        ok += not np.isnan(E.fast_weighted_ap(y[order].astype(float), counts[acct[order]]))
    assert ok >= 98


def test_end_to_end_on_a_synthetic_world_with_a_planted_signal(tmp_path):
    rng = np.random.default_rng(3)
    rows, k = [], 0
    for d in range(0, 400):
        for _ in range(6):
            rows.append((f"b{k}", f"E{rng.integers(0, 40)}", f"E{rng.integers(0, 40)}", 0, d)); k += 1
    for i, d in enumerate(range(150, 390, 8)):                    # rings: new accounts with a few alert transactions each
        for j in range(3):
            rows.append((f"r{i}_{j}", f"N{i}", f"M{i}", 1, d + j))
    tx = _tx(rows)
    csv = tmp_path / "tx.csv"
    out = tx.assign(sender=tx.sender, amount=1.0, timestamp=pd.Timestamp("2017-01-01") + pd.to_timedelta(tx.day, unit="D")).drop(columns=["day"])
    out.to_csv(csv, index=False)
    res = E.run(csv, tmp_path / "res", tmp_path / "rep", horizons=(3,), burn_in=60, n_boot=30, n_estimators=30, verbose=False)
    r = [x for x in res["results"] if x["features"] == len(E.FEATURES_HISTORY)][0]
    assert r["n_test_pos"] > 0 and r["pr_auc"] is not None and r["horizon_days"] == 3
    assert (tmp_path / "rep" / "account_window_eval_report.html").exists()
