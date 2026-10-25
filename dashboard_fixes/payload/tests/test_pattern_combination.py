"""Small unit tests for the pattern-combination experiment's helpers (the experiment itself needs a finished rebuild)."""
import importlib.util
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
spec = importlib.util.spec_from_file_location("pc", ROOT / "scripts" / "test_pattern_combination.py")
pc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pc)


def test_account_ids_with_float_suffix_are_normalised():
    assert pc.norm("49066.0") == "49066" and pc.norm(14) == "14" and pc.norm("A7") == "A7"


def test_the_original_pattern_weights_are_found():
    w = pc.v1_weights()
    assert w["circular_flow"] > 0


def test_cluster_bootstrap_of_an_identical_score_has_a_zero_difference():
    rng = np.random.default_rng(0)
    y = (rng.random(300) < 0.3).astype(int)
    s = rng.random(300)
    lo, hi = pc.boot_delta(y, s, s, list(range(300)), n=200)
    assert lo == 0.0 and hi == 0.0


def test_auc_of_a_perfect_score_is_one_and_of_a_single_class_is_nan():
    y = np.array([0, 0, 1, 1])
    assert pc.auc(y, np.array([0.1, 0.2, 0.8, 0.9])) == 1.0 and np.isnan(pc.auc(np.zeros(4), np.arange(4)))
