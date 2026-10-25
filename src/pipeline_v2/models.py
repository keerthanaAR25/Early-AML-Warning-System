"""The four model families evaluated under ONE leakage-safe protocol (ADDITIVE). Output matches results/model_comparison.json."""
from __future__ import annotations

import numpy as np

from src.evaluation import account_window_eval as AW

FAMILIES = {
    "static_graph_anomaly_isolation_forest": (["out_to_date", "in_to_date", "cp_to_date", "age"], "isolation_forest"),
    "behavioural_logistic_regression": (["n_today", "out_today", "in_today"], "logistic"),
    "temporal_random_forest": (["n_today", "out_today", "in_today", "n_7d", "n_30d", "idle"], "random_forest"),
    "proposed_gradient_boosting": (AW.FEATURES_HISTORY, "xgboost"),
}


NOISE_DECIMALS = 10      # scores that differ by less than this are ties; guards against floating-point noise (e.g. parallel tree summation)


def metrics_at(y, s, thr):
    from sklearn.metrics import average_precision_score, roc_auc_score
    sr = np.round(s, NOISE_DECIMALS)                                 # thresholding and ranking use noise-free scores; PR-AUC uses the raw ones
    pred = sr >= round(float(thr), NOISE_DECIMALS)
    tp, fp = int((pred & (y == 1)).sum()), int((pred & (y == 0)).sum())
    P, N = int(y.sum()), int((y == 0).sum())
    fn, tn = P - tp, N - fp
    prec = tp / (tp + fp) if tp + fp else 0.0
    rec = tp / P if P else 0.0
    top = np.argsort(-sr, kind="stable")
    return {"precision": prec, "recall": rec, "f1": 2 * prec * rec / (prec + rec) if prec + rec else 0.0,
            "roc_auc": float(roc_auc_score(y, s)) if 0 < P < len(y) else None,
            "pr_auc": float(average_precision_score(y, s)) if P else None,
            "false_warning_rate": fp / N if N else None, "n_samples": int(len(y)), "n_positive": P, "n_negative": N,
            "threshold": float(thr), "confusion_matrix": {"tp": tp, "fp": fp, "fn": fn, "tn": tn},
            "top_k_precision": {str(k): float(y[top[:k]].sum() / k) for k in (10, 20, 50)}}


def _subsample(X, y, n_neg, seed):
    rng = np.random.default_rng(seed)
    pos = np.flatnonzero(y == 1)
    neg = np.flatnonzero(y == 0)
    keep = np.concatenate([pos, rng.choice(neg, size=min(n_neg, len(neg)), replace=False)])
    return X[keep], y[keep]


def fit_scores(kind, Xtr, ytr, others, seed, n_estimators):
    if kind == "xgboost":
        return AW.fit_score(Xtr, ytr, others, seed, n_estimators)
    if kind == "isolation_forest":
        from sklearn.ensemble import IsolationForest
        rng = np.random.default_rng(seed)
        idx = rng.choice(len(Xtr), size=min(300_000, len(Xtr)), replace=False)
        m = IsolationForest(n_estimators=100, random_state=seed, n_jobs=2).fit(Xtr[idx])
        m.set_params(n_jobs=1)                                       # fixed summation order -> repeatable scores
        return [-m.score_samples(X) for X in others]
    X, y = _subsample(Xtr, ytr, 400_000 if kind == "logistic" else 300_000, seed)
    if kind == "logistic":
        from sklearn.linear_model import LogisticRegression
        from sklearn.pipeline import make_pipeline
        from sklearn.preprocessing import StandardScaler
        m = make_pipeline(StandardScaler(), LogisticRegression(class_weight="balanced", max_iter=300)).fit(np.log1p(X), y)
        return [m.predict_proba(np.log1p(Z))[:, 1] for Z in others]
    from sklearn.ensemble import RandomForestClassifier
    m = RandomForestClassifier(n_estimators=100, max_depth=10, min_samples_leaf=20, class_weight="balanced_subsample",
                               n_jobs=2, random_state=seed).fit(X, y)
    m.set_params(n_jobs=1)                                           # a fixed summation order makes predictions bit-for-bit repeatable
    return [m.predict_proba(Z)[:, 1] for Z in others]


def evaluate_family(state, Y, name, s):
    cols, kind = FAMILIES[name]
    b = AW.split_bounds(state["W"], s.horizon, s.burn_in)
    tr, va, te = (AW.make_rows(state, Y, cols, *b[k]) for k in ("train", "val", "test"))
    sv, st = fit_scores(kind, tr[0], tr[1], [va[0], te[0]], s.seed, 300)
    thr = AW.choose_threshold(va[1], sv)                               # validation only
    return {"val": metrics_at(va[1], sv, thr), "test": metrics_at(te[1], st, thr),
            "threshold_selection": {"rule": "max F1 on validation", "value": float(thr)},
            "protocol": {"model_family": kind, "features": cols, "horizon_days": s.horizon, "train_days": list(b["train"]),
                         "validation_days": list(b["val"]), "test_days": list(b["test"])}}
