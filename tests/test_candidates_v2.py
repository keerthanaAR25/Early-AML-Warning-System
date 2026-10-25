"""Tests for candidates_v2 and patch_id_dtypes (ADDITIVE). Run: pytest tests/test_candidates_v2.py -v"""
import dataclasses
import importlib.util
import inspect
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.evaluation import candidates_v2 as C  # noqa: E402
from src.evaluation import ring_lead_time as R  # noqa: E402


def _tx(rows):
    df = pd.DataFrame(rows, columns=["transaction_id", "sender", "receiver", "amount", "day"])
    return df.sort_values("day", kind="mergesort").reset_index(drop=True)


def _cycle(prefix, nodes, days, start_tid=0):
    return [(f"{prefix}{i}", nodes[i], nodes[(i + 1) % len(nodes)], 100.0, d) for i, d in enumerate(days)]


# ------------------------------------------------------------------ cycles / paths
def test_unordered_cycle_is_detected_when_it_closes_even_if_edge_times_are_not_path_ordered():
    # AMLSim-style: edge times are NOT increasing along the cycle
    tx = _tx(_cycle("c", list("ABCDE"), [5, 12, 3, 9, 7]))
    cands = C.detect_structures(tx, window_days=21)
    closed = [c for c in cands if c["closed"]]
    assert len(closed) == 1 and closed[0]["nodes"] == set("ABCDE")
    assert closed[0]["closure_day"] == 12 and len(closed[0]["tx"]) == 5


def test_cycle_spanning_more_than_the_window_is_not_detected():
    tx = _tx(_cycle("c", list("ABCDE"), [0, 6, 12, 18, 30]))
    assert not [c for c in C.detect_structures(tx, window_days=21) if c["closed"]]


def test_partial_path_becomes_a_closed_cycle_and_keeps_its_earlier_creation_day():
    tx = _tx(_cycle("c", list("ABCDE"), [1, 2, 3, 4, 10]))      # 4-node path A-B-C-D exists from day 3, closes day 10
    c = C.detect_structures(tx, window_days=21)
    assert len(c) == 1 and c[0]["closed"] and c[0]["creation_day"] == 3 and c[0]["closure_day"] == 10


def test_old_candidates_do_not_absorb_later_structures_that_share_an_account():
    # two cycles share account A but are 200 days apart: they must stay two separate candidates
    tx = _tx(_cycle("c", list("ABCDE"), [1, 2, 3, 4, 5]) + _cycle("d", ["A", "F", "G", "H", "I"], [201, 202, 203, 204, 205]))
    cands = C.detect_structures(tx, window_days=21)
    closed = sorted((c for c in cands if c["closed"]), key=lambda c: c["creation_day"])
    assert len(closed) == 2 and closed[0]["creation_day"] < 20 and closed[1]["creation_day"] > 190
    assert not (closed[0]["tx"] & closed[1]["tx"]) and "F" not in closed[0]["nodes"]


def test_small_cycle_buried_in_a_large_strongly_connected_core_is_not_reported():
    # two 8-cycles joined by two cross edges form ONE 16-node SCC: no closure may be reported for the 5-cycle inside it
    a, b = [f"a{i}" for i in range(8)], [f"b{i}" for i in range(8)]
    rows = _cycle("x", a, [1] * 8) + _cycle("y", b, [1] * 8) + [("j1", "a0", "b0", 1.0, 1), ("j2", "b3", "a3", 1.0, 1)]
    assert not [c for c in C.detect_structures(_tx(rows), window_days=21) if c["closed"]]
    # the same 8-cycle alone IS reported
    assert [c for c in C.detect_structures(_tx(_cycle("x", a, [1, 2, 3, 4, 5, 6, 7, 8])), window_days=21) if c["closed"]]


def test_candidate_growth_is_bounded_in_size():
    # a long chain of overlapping 5-node cycles must not grow into one unbounded candidate
    rows = []
    for k in range(30):
        nodes = [f"n{k * 4 + j}" for j in range(5)]
        rows += _cycle(f"c{k}_", nodes, [k + 1] * 5)
    cands = C.detect_structures(_tx(rows), window_days=21, max_candidate_nodes=12)
    assert max(len(c["nodes"]) for c in cands) <= 12


def test_branching_structures_are_not_partial_paths():
    star = [("s%d" % i, "H", f"X{i}", 1.0, 1) for i in range(6)]
    assert C.detect_structures(_tx(star), window_days=21) == []


def test_structure_detection_uses_no_label_column():
    assert "label" not in inspect.signature(C.detect_structures).parameters
    C.detect_structures(_tx(_cycle("c", list("ABCDE"), [1, 2, 3, 4, 5])).assign(label=1).drop(columns=["label"]))


# ------------------------------------------------------------------ novelty seeds
def _novelty_inputs():
    rows = []
    for d in range(0, 40):                                     # established population: 10 accounts trade daily
        for i in range(10):
            rows.append((f"b{d}_{i}", f"E{i}", f"E{(i + 1) % 10}", 50.0, d))
    rows += [("n1", "NEW1", "E3", 99.0, 20), ("n2", "NEW2", "E3", 99.0, 90), ("n3", "NEW3", "E3", 99.0, 150)]   # slow-drip fan-in
    rows += [("early", "NEWX", "E3", 99.0, 5)]                  # before burn-in -> not a seed
    tx = _tx(rows)
    return tx, R.build_features(tx)


def test_novelty_seeds_respect_burn_in_and_group_slow_drip_fans_by_hub():
    tx, F = _novelty_inputs()
    g = C.detect_novelty_groups(tx, F, burn_in=10, seed_gap=30, hub_gap=150, min_seeds=1)
    ids = set().union(*[c["tx"] for c in g])
    assert "early" not in ids
    fan = [c for c in g if {"n1", "n2", "n3"} <= c["tx"]]
    assert len(fan) == 1 and "slow_drip_fan_in" in fan[0]["patterns"] and fan[0]["creation_day"] == 20


def test_hub_gap_limit_splits_groups_and_min_seeds_delays_creation():
    tx, F = _novelty_inputs()
    g = C.detect_novelty_groups(tx, F, burn_in=10, seed_gap=30, hub_gap=60, min_seeds=1)
    assert not [c for c in g if {"n1", "n2", "n3"} <= c["tx"]]
    g2 = C.detect_novelty_groups(tx, F, burn_in=10, seed_gap=30, hub_gap=150, min_seeds=2)
    fan = [c for c in g2 if {"n1", "n2"} <= c["tx"]][0]
    assert fan["creation_day"] == 90                             # created when the 2nd seed arrives


def test_sender_only_mode_drops_first_receiver_seeds_and_bad_mode_is_rejected():
    tx, F = _novelty_inputs()
    extra = pd.concat([tx, pd.DataFrame([("r1", "E5", "NEWR", 10.0, 25)], columns=tx.columns)]).sort_values("day", kind="mergesort").reset_index(drop=True)
    F2 = R.build_features(extra)
    either = C.detect_novelty_groups(extra, F2, burn_in=10, mode="either")
    sender = C.detect_novelty_groups(extra, F2, burn_in=10, mode="sender")
    assert any("r1" in c["tx"] for c in either) and not any("r1" in c["tx"] for c in sender)
    with pytest.raises(ValueError):
        C.detect_novelty_groups(extra, F2, burn_in=10, mode="bogus")


def test_novelty_builder_rejects_label_columns():
    tx, F = _novelty_inputs()
    with pytest.raises(AssertionError):
        C.detect_novelty_groups(tx, F.assign(label=0), burn_in=10)


# ------------------------------------------------------------------ evaluation
def test_candidate_quality_metrics_and_lead_on_a_toy_case():
    tx = pd.DataFrame({"transaction_id": ["a", "b", "c", "d", "e", "f"], "day": [130, 135, 140, 150, 151, 152],
                       "label": [1, 1, 1, 0, 0, 0]})
    rings = pd.DataFrame([dict(ring_id="R1", typology="cycle", first_day=130, last_day=140, observable_day=140,
                               observable_tx="c", n_tx=3, tx_ids=["a", "b", "c"])])
    ring_of = {"a": "R1", "b": "R1", "c": "R1"}
    label_of, day_of = dict(zip(tx.transaction_id, tx.label)), dict(zip(tx.transaction_id, tx.day))
    cands = [dict(tx={"a", "b", "d"}, nodes={"x", "y"}, creation_day=135),      # created on day 135, holds ring tx a (day 130) and b
             dict(tx={"e", "f"}, nodes={"p", "q"}, creation_day=152)]           # pure background
    s, pr = C.evaluate_candidate_set("t", cands, tx, rings, ring_of, label_of, day_of, burn_in=120, max_day=160)
    assert s["n_candidates"] == 2 and s["candidates_with_any_ring_tx"] == 1
    assert s["ring_transactions_in_candidates"] == 2 and s["evidence_transactions"] == 5
    assert s["distinct_ring_tx_covered"] == 2
    r = pr.iloc[0]
    assert r["warning_day"] == 135 and r["lead_days"] == 5 and r["lead_vs_first_tx_days"] == -5 and bool(r["evaluable"])


def test_pre_burn_in_candidates_are_excluded_from_every_set():
    tx = pd.DataFrame({"transaction_id": ["a"], "day": [50], "label": [1]})
    rings = pd.DataFrame([dict(ring_id="R1", typology="cycle", first_day=50, last_day=50, observable_day=50,
                               observable_tx="a", n_tx=1, tx_ids=["a"])])
    s, pr = C.evaluate_candidate_set("t", [dict(tx={"a"}, nodes={"x"}, creation_day=50)], tx, rings, {"a": "R1"},
                                     {"a": 1}, {"a": 50}, burn_in=120, max_day=200)
    assert s["n_candidates"] == 0 and not bool(pr.iloc[0]["evaluable"])


def test_v1_creation_day_is_the_second_structural_event():
    c = dict(trajectory=dict(pattern_sequence=["rapid_pass_through", "fan_in", "rapid_pass_through", "layering"],
                             event_window_ids=[3, 5, 6, 9]))
    assert C.v1_creation_day(c) == 9


# ------------------------------------------------------------------ schema compatibility with YOUR RingCandidate
def test_exported_rows_can_build_your_RingCandidate():
    tx = _tx(_cycle("c", list("ABCDE"), [1, 2, 3, 4, 5]))
    cands = C.detect_structures(tx)
    rows, meta = C.to_schema(cands, tx, pd.Timestamp("2017-01-01"), "V2-")
    assert rows and set(rows[0]) == set(C.SCHEMA_FIELDS) and meta[0]["source"] == "cycle_closure"
    try:
        from src.ring.ring_candidate_engine import RingCandidate
    except Exception:
        pytest.skip("project RingCandidate not importable here")
    names = {f.name for f in dataclasses.fields(RingCandidate)}
    assert set(rows[0]) <= names                                   # no extra keys that would break RingCandidate(**row)
    RingCandidate(**rows[0])


# ------------------------------------------------------------------ patcher
def _load_patcher():
    spec = importlib.util.spec_from_file_location("patch_id_dtypes", ROOT / "scripts" / "patch_id_dtypes.py")
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m


def test_patcher_adds_dtype_only_to_unprotected_single_line_calls():
    P = _load_patcher()
    new, why = P.patch_line('    df = pd.read_csv(clean_path, parse_dates=["timestamp"])\n')
    assert why is None and 'dtype={"transaction_id": str' in new and new.endswith(")\n")
    new2, _ = P.patch_line('    ft = pd.read_csv(features_path) if features_path.exists() else None\n')
    assert 'pd.read_csv(features_path, dtype={"account_id": str}) if' in new2
    assert P.patch_line('    df = pd.read_csv(clean_path, dtype={"sender": str})\n') == (None, None)    # already protected
    assert P.patch_line('    x = pd.read_csv(other_file)\n') == (None, None)                               # unrelated file
    assert P.patch_line('    df = pd.read_csv(clean_path,\n')[1] is not None                               # multi-line: reported, not edited
