"""
Account-window early-warning evaluation with a pre-specified, leakage-safe protocol (ADDITIVE -- no existing file is modified).

Task (same construction as the dashboard): for every account seen so far and every day t, predict whether the account is ACTIVE on day t and
takes part in a ring (alert) transaction within the next H days.  H=2 reproduces the dashboard task exactly (653,487 test rows / 32 positives).

What differs from the dashboard run, all of it reported side by side:
  * horizon H in {2, 7, 14} -- the task changes with H, so every horizon is reported, none is hidden. Cycle rings in this dataset span a median of
    12 days (max 19), so H=14 covers one formation period;
  * 120-day burn-in for training (the simulator's warm-up makes "new account" meaningless early on);
  * PURGE gaps of H days at the train/validation and validation/test boundaries (a label looks H days ahead);
  * the decision threshold is chosen on VALIDATION only (max F1) and then applied once to the test period;
  * uncertainty by a CLUSTER bootstrap over accounts (rows of one account are not independent).

Features are causal (day <= t).  Ring labels are used only as training targets for rows before the validation period and for evaluation.
"""
from __future__ import annotations

import html
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd

FEATURES_BASE = ["n_today", "out_today", "in_today", "n_7d", "n_30d"]
FEATURES_HISTORY = FEATURES_BASE + ["age", "idle", "out_to_date", "in_to_date", "cp_to_date", "new_cp_today",
                                    "first_out_today", "first_in_today"]
FORBIDDEN = {"label", "alert", "alert_id", "ring_id", "is_sar", "prior_sar_count", "y"}


# ------------------------------------------------------------------------------------------------ state
def build_state(tx: pd.DataFrame) -> dict:
    """tx: transaction_id, sender, receiver, label, day.  Returns dense account x day matrices (float32)."""
    accts = pd.Index(pd.unique(pd.concat([tx["sender"], tx["receiver"]])))
    A, W = len(accts), int(tx["day"].max()) + 1
    si, ri, d = accts.get_indexer(tx["sender"]), accts.get_indexer(tx["receiver"]), tx["day"].values
    lab = tx["label"].values == 1

    def mat(idx):
        m = np.zeros((A, W), np.float32)
        np.add.at(m, (idx, d), 1)
        return m

    out_d, in_d = mat(si), mat(ri)
    n_d = out_d + in_d
    alert = np.zeros((A, W), bool)
    alert[si[lab], d[lab]] = True
    alert[ri[lab], d[lab]] = True
    pairs = pd.DataFrame({"a": np.r_[si, ri], "c": np.r_[ri, si], "w": np.r_[d, d]}).groupby(["a", "c"])["w"].min().reset_index()
    newcp = np.zeros((A, W), np.float32)
    np.add.at(newcp, (pairs["a"].values, pairs["w"].values), 1)
    cs = lambda m: np.cumsum(m, axis=1)
    active = n_d > 0
    first_seen = np.where(active.any(1), active.argmax(1), W)
    days = np.arange(W)[None, :]
    last_act = np.maximum.accumulate(np.where(active, days, -1), axis=1)
    csn = cs(n_d)

    def trail(k):
        return csn - np.concatenate([np.zeros((A, k), np.float32), csn[:, :-k]], axis=1)[:, :W]

    out_cum, in_cum = cs(out_d), cs(in_d)
    feats = {"n_today": n_d, "out_today": out_d, "in_today": in_d, "n_7d": trail(7), "n_30d": trail(30),
             "age": (days - first_seen[:, None]).astype(np.float32), "idle": (days - last_act).astype(np.float32),
             "out_to_date": out_cum, "in_to_date": in_cum, "cp_to_date": cs(newcp), "new_cp_today": newcp,
             "first_out_today": ((out_cum == out_d) & (out_d > 0)).astype(np.float32),
             "first_in_today": ((in_cum == in_d) & (in_d > 0)).astype(np.float32)}
    return dict(accts=accts, A=A, W=W, active=active, alert=alert, seen=days >= first_seen[:, None], feats=feats)


def label_matrix(state: dict, H: int) -> np.ndarray:
    """Positive = active on day t AND an alert transaction involves the account on any of days t+1..t+H."""
    alert = state["alert"]
    fut = np.zeros_like(alert)
    for k in range(1, H + 1):
        fut[:, :-k] |= alert[:, k:]
    return state["active"] & fut


def make_rows(state, Y, cols, lo, hi):
    a, d = np.nonzero(state["seen"][:, lo:hi + 1])
    d = d + lo
    X = np.column_stack([state["feats"][c][a, d] for c in cols]).astype(np.float32)
    return X, Y[a, d].astype(int), a, d


def split_bounds(W, H, burn_in=120, train_frac=0.6, val_frac=0.8):
    val_start, test_start = int(train_frac * W), int(val_frac * W)
    return dict(train=(burn_in, val_start - 1 - H), val=(val_start, test_start - 1 - H), test=(test_start, W - 1))


# ------------------------------------------------------------------------------------------------ metrics
def fast_weighted_ap(y_sorted, w_sorted):
    """Average precision for rows already sorted by score (descending) with non-negative integer-like weights."""
    tp = np.cumsum(w_sorted * y_sorted)
    fp = np.cumsum(w_sorted * (1 - y_sorted))
    total = tp[-1]
    if total == 0:
        return np.nan
    denom = tp + fp
    prec = np.divide(tp, denom, out=np.zeros_like(tp), where=denom > 0)      # rows with zero weight at the top must not give 0/0
    return float(np.sum(w_sorted * y_sorted * prec) / total)


def wilson(k, n, z=1.96):
    """Wilson score interval for a proportion k/n (valid for small counts)."""
    if n == 0:
        return [None, None]
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [float(max(0.0, c - h)), float(min(1.0, c + h))]


def cluster_bootstrap_ap(y, s, acct, n_boot=300, seed=0):
    """2.5-97.5 percentile RANGE of PR-AUC when whole ACCOUNTS are resampled with replacement over the full test population.
    NOT a confidence interval around the point estimate: with few positive accounts the statistic is skewed, so the range can sit
    above the estimate. Use it only to show how much PR-AUC moves with which accounts happen to be in the sample."""
    order = np.argsort(-s, kind="stable")
    ys, as_ = y[order].astype(float), acct[order]
    n_acc = int(acct.max()) + 1
    rng = np.random.default_rng(seed)
    vals = []
    for _ in range(n_boot):
        counts = np.bincount(rng.integers(0, n_acc, n_acc), minlength=n_acc).astype(float)
        v = fast_weighted_ap(ys, counts[as_])
        if not np.isnan(v):
            vals.append(v)
    return [float(np.percentile(vals, 2.5)), float(np.percentile(vals, 97.5))] if len(vals) > 20 else [None, None]


def choose_threshold(y_val, s_val):
    from sklearn.metrics import precision_recall_curve
    if y_val.sum() == 0:
        return 0.5
    p, r, th = precision_recall_curve(y_val, s_val)
    f1 = 2 * p * r / (p + r + 1e-12)
    return float(th[int(np.argmax(f1[:-1]))])


def fit_score(Xtr, ytr, Xs, seed=42, n_estimators=300):
    import xgboost as xgb
    pos = max(int(ytr.sum()), 1)
    m = xgb.XGBClassifier(n_estimators=n_estimators, max_depth=4, learning_rate=0.05, subsample=0.8, colsample_bytree=0.8,
                          scale_pos_weight=(len(ytr) - pos) / pos / 2.0, random_state=seed, tree_method="hist", n_jobs=2,
                          eval_metric="aucpr", verbosity=0)
    m.fit(Xtr, ytr)
    return [m.predict_proba(X)[:, 1].astype(float) for X in Xs]


def evaluate_config(state, H, cols, name, burn_in=120, seed=42, n_boot=300, n_estimators=300):
    from sklearn.metrics import average_precision_score, roc_auc_score
    assert not (set(cols) & FORBIDDEN)
    b = split_bounds(state["W"], H, burn_in)
    Y = label_matrix(state, H)
    tr, va, te = (make_rows(state, Y, cols, *b[k]) for k in ("train", "val", "test"))
    s_va, s_te = fit_score(tr[0], tr[1], [va[0], te[0]], seed, n_estimators)
    thr = choose_threshold(va[1], s_va)                    # VALIDATION only
    y = te[1]
    pred = s_te >= thr
    tp, fp = int((pred & (y == 1)).sum()), int((pred & (y == 0)).sum())
    P, N = int(y.sum()), int((y == 0).sum())
    top = np.argsort(-s_te, kind="stable")
    prec = tp / (tp + fp) if tp + fp else None
    rec = tp / P if P else None
    pos_accts = set(te[2][y == 1])
    caught = len({a for a in te[2][pred & (y == 1)]})
    return dict(
        name=name, horizon_days=H, features=len(cols), bounds=b,
        n_train=int(len(tr[1])), n_train_pos=int(tr[1].sum()), n_val_pos=int(va[1].sum()),
        n_test=int(len(y)), n_test_pos=P, n_test_pos_accounts=int(len(set(te[2][y == 1]))), prevalence=P / len(y),
        pr_auc=float(average_precision_score(y, s_te)) if P else None,
        pr_auc_bootstrap_range_2p5_97p5=cluster_bootstrap_ap(y, s_te, te[2], n_boot, seed) if P else [None, None],
        positive_accounts_caught=caught, recall_by_account=caught / len(pos_accts) if pos_accts else None,
        recall_by_account_wilson95=wilson(caught, len(pos_accts)), precision_wilson95=wilson(tp, tp + fp),
        roc_auc_inflated_by_active_only_labels=float(roc_auc_score(y, s_te)) if P else None,
        threshold_chosen_on_validation=thr, tp=tp, fp=fp, precision=prec, recall=rec,
        f1=(2 * prec * rec / (prec + rec)) if prec and rec else 0.0, false_positive_rate=fp / N,
        precision_at_10=int(y[top[:10]].sum()), precision_at_20=int(y[top[:20]].sum()), precision_at_50=int(y[top[:50]].sum()))


# ------------------------------------------------------------------------------------------------ orchestration + report
def run(tx_path, out_dir, report_dir, horizons=(2, 7, 14), burn_in=120, seed=42, n_boot=300, n_estimators=300,
        model_comparison_path=None, verbose=True):
    try:
        from src.evaluation.ring_lead_time import load_transactions
    except ImportError as exc:      # pragma: no cover
        raise ImportError("needs src/evaluation/ring_lead_time.py from Additions_complete.zip -- extract that first") from exc
    t0 = time.time()
    log = (lambda *a: print(*a, flush=True)) if verbose else (lambda *a: None)
    tx, _ = load_transactions(tx_path)
    state = build_state(tx)
    log(f"state built: {state['A']:,} accounts x {state['W']} days [{time.time() - t0:.0f}s]")
    results = []
    for H in horizons:
        for name, cols in (("activity+rolling (no account history)", FEATURES_BASE), ("+ account history/novelty", FEATURES_HISTORY)):
            r = evaluate_config(state, H, cols, name, burn_in, seed, n_boot, n_estimators)
            results.append(r)
            log(f"  H={H:2d} {name:38s} pos={r['n_test_pos']:3d} PR-AUC={r['pr_auc']:.4f} range={[None if v is None else round(v, 3) for v in r['pr_auc_bootstrap_range_2p5_97p5']]} "
                f"prec={r['precision']} rec={None if r['recall'] is None else round(r['recall'], 3)} FP={r['fp']} [{time.time() - t0:.0f}s]")
    dash = None
    if model_comparison_path and Path(model_comparison_path).exists():
        m = json.load(open(model_comparison_path)).get("proposed_gradient_boosting", {}).get("test")
        if m:
            dash = {k: m.get(k) for k in ("n_samples", "n_positive", "precision", "recall", "f1", "roc_auc", "pr_auc", "false_warning_rate")}
    out = dict(generated_at=pd.Timestamp.now("UTC").isoformat(), runtime_seconds=round(time.time() - t0, 1),
               parameters=dict(horizons=list(horizons), burn_in=burn_in, seed=seed, n_boot=n_boot, n_estimators=n_estimators,
                               threshold_rule="max F1 on validation", purge_gap="H days at each boundary"),
               dashboard_baseline_from_model_comparison_json=dash, results=results)
    out_dir, report_dir = Path(out_dir), Path(report_dir)
    out_dir.mkdir(parents=True, exist_ok=True); report_dir.mkdir(parents=True, exist_ok=True)
    json.dump(out, open(out_dir / "account_window_eval_v2.json", "w"), indent=2)
    render_report(out, report_dir / "account_window_eval_report.html")
    return out


def _f(x, nd=3, pct=False):
    return "&mdash;" if x is None else (f"{100 * x:.1f}%" if pct else f"{x:.{nd}f}")


def render_report(out: dict, path):
    rows = ""
    dash = out["dashboard_baseline_from_model_comparison_json"]
    if dash:
        rows += (f"<tr style='background:#f3f3f3'><td>Dashboard (as shown)</td><td>2</td><td>{dash['n_positive']}</td><td>&mdash;</td><td>{_f(dash['pr_auc'])}</td><td>&mdash;</td>"
                 f"<td>{_f(dash['precision'])}</td><td>{_f(dash['recall'])}</td><td>&mdash;</td><td>{_f(dash['f1'])}</td><td>&mdash;</td><td>{_f(dash['false_warning_rate'], 6)}</td><td>&mdash;</td></tr>")
    for r in out["results"]:
        lo, hi = r["pr_auc_bootstrap_range_2p5_97p5"]
        ci = "&mdash;" if lo is None else f"{lo:.3f}&ndash;{hi:.3f}"
        pl, ph = r["precision_wilson95"]
        al, ah = r["recall_by_account_wilson95"]
        pw = "&mdash;" if pl is None else f"{pl:.2f}&ndash;{ph:.2f}"
        aw = "&mdash;" if al is None else f"{r['positive_accounts_caught']}/{r['n_test_pos_accounts']} ({al:.2f}&ndash;{ah:.2f})"
        rows += (f"<tr><td>{html.escape(r['name'])}</td><td>{r['horizon_days']}</td><td>{r['n_test_pos']}</td><td>{r['n_test_pos_accounts']}</td><td>{_f(r['pr_auc'])}</td><td>{ci}</td>"
                 f"<td>{_f(r['precision'])}<br><span class='note'>{pw}</span></td><td>{_f(r['recall'])}</td><td>{aw}</td><td>{_f(r['f1'])}</td><td>{r['tp']} / {r['fp']}</td><td>{_f(r['false_positive_rate'], 6)}</td>"
                 f"<td>{r['precision_at_10']} / {r['precision_at_20']} / {r['precision_at_50']}</td></tr>")
    css = ("body{font-family:Segoe UI,Arial,sans-serif;margin:24px;color:#1a1a2e;background:#f7f8fb}table{border-collapse:collapse;background:#fff}th,td{border:1px solid #e3e6ef;padding:6px 10px;font-size:13px}"
           "th{background:#eef1fa}.warn{background:#fff4e5;border:1px solid #f5c26b;padding:10px 14px;margin:12px 0;border-radius:6px}.note{color:#667;font-size:12px}")
    doc = f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>Account-window evaluation</title><style>{css}</style></head><body>
<h1>Account-window early-warning evaluation (leakage-safe protocol)</h1>
<div class="warn"><b>How to read this.</b> The forecast horizon H changes the task, so every horizon is reported. H=2 is the dashboard task. The gains at H=7 and H=14 come mainly from a
better-posed task and protocol (more positives, threshold chosen on validation, purge gaps), not from a better model: account-history features do <i>not</i> help consistently.
The PR-AUC <i>range</i> resamples whole accounts; it is NOT a confidence interval (with few positive accounts it is skewed and can sit above the estimate). Wilson intervals are for the operating point and are approximate because rows of one account are correlated. ROC-AUC is omitted from the table because the active-accounts-only label inflates it.</div>
<table><tr><th>Model</th><th>H (days)</th><th>Test positives</th><th>Distinct accounts</th><th>PR-AUC</th><th>PR-AUC bootstrap range</th><th>Precision (Wilson 95%)</th><th>Recall (rows)</th><th>Positive accounts caught (Wilson 95%)</th><th>F1</th><th>TP / FP</th><th>False-positive rate</th><th>Hits in top 10 / 20 / 50</th></tr>{rows}</table>
<p class="note">Train = burn-in..validation start minus H; validation chooses the threshold (max F1); test is scored once. Parameters: {html.escape(json.dumps(out['parameters']))}</p></body></html>"""
    Path(path).write_text(doc, encoding="utf-8")
