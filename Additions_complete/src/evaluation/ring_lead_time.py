"""
Ring-level lead-time evaluation (ADDITIVE module -- does not modify any existing file).

What it does
------------
* Builds CAUSAL per-transaction features from data/processed/transactions_clean.csv
  (every feature uses only days strictly BEFORE the transaction's day, except the explicit
  same-day counts, which are available at an end-of-day batch run).
* Trains / scores with ROLLING-ORIGIN, RING-GROUPED validation (train only on the past;
  rings that have any transaction in the scored block are removed from that block's training set).
* Converts scores to warnings with an investigator DAILY BUDGET (top-K transactions per day),
  so the threshold is never tuned on the scored period.
* Evaluates ALL labelled AMLSim rings (not matched candidates): per ring it records
  first transaction, observable_time, warning_time and lead time, then summarises per typology
  with N and bootstrap confidence intervals.

Ground-truth labels are used ONLY (a) as training targets for rows strictly before the scored
block and (b) to evaluate. They never enter the feature set (see FORBIDDEN_FEATURE_NAMES).

Operational definitions (fixed before looking at results)
---------------------------------------------------------
observable_time : cycle  -> day of the ring's last (closing) edge
                  fan_in / fan_out -> day the k-th DISTINCT counterparty has transacted (k=4);
                  if a ring has fewer than k counterparties, its last transaction day.
warning_time    : earliest day on which any transaction of the ring is flagged by the daily budget
                  (only out-of-sample days are scored).
lead_time       : observable_time - warning_time, in DAYS (windows are one day in this dataset).
                  lead > 0 means the warning came BEFORE the ring became observable.
"""
from __future__ import annotations

import hashlib
import html
import json
import platform
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

BASE_FEATURES = ["amount", "s_out_today", "r_in_today"]          # same-day information only: NO account history
NOVELTY_FEATURES = [
    "s_out", "r_in",                            # prior outgoing / incoming counts (s_out==0 IS the first-ever-sender signal)
    "edge_is_new", "pair", "rev_pair",          # edge novelty / history
    "s_first_out", "r_first_in",                # first-ever outgoing / incoming activity
    "s_age", "r_age",                           # days since the account was first seen
    "s_idle", "r_idle",                         # days since the account's previous active day
]
FORBIDDEN_FEATURE_NAMES = {
    "label", "alert_id", "ring_id", "scenario_id", "is_sar", "prior_sar_count", "alert_type", "sar",
}
XGB_SPECS = {
    "xgb_with_novelty": BASE_FEATURES + NOVELTY_FEATURES,
    "xgb_without_novelty": BASE_FEATURES,
}
BASELINES = ("newness_rule", "random")
ALL_MODELS = tuple(XGB_SPECS) + BASELINES


# ----------------------------------------------------------------------------------------------
# loading
# ----------------------------------------------------------------------------------------------
def load_transactions(path):
    tx = pd.read_csv(path, dtype={"transaction_id": str, "sender": str, "receiver": str})
    ts = pd.to_datetime(tx["timestamp"], utc=True).dt.tz_localize(None)
    day0 = ts.min().normalize()
    tx["day"] = (ts.dt.normalize() - day0).dt.days.astype(int)
    if "label" not in tx.columns:
        raise ValueError("transactions file needs a 'label' column (used for evaluation / training targets only)")
    tx = tx.sort_values("day", kind="mergesort").reset_index(drop=True)
    return tx[["transaction_id", "sender", "receiver", "amount", "label", "day"]], day0


def load_alert_transactions(path, tx):
    at = pd.read_csv(path, dtype={"tran_id": str, "orig_acct": str, "bene_acct": str})
    at = at.rename(columns={"tran_id": "transaction_id"})
    at = at.merge(tx[["transaction_id", "day"]], on="transaction_id", how="left")
    n_missing = int(at["day"].isna().sum())
    if n_missing:
        raise ValueError(f"{n_missing} alert transactions are not present in the transactions file "
                         "(ID mismatch -- run scripts/check_lineage.py)")
    at["day"] = at["day"].astype(int)
    return at


# ----------------------------------------------------------------------------------------------
# causal features
# ----------------------------------------------------------------------------------------------
def _prior_counts(left: pd.DataFrame, left_keys, daily: pd.DataFrame, right_keys) -> np.ndarray:
    """Number of events in `daily` (columns right_keys + ['day','n']) on days STRICTLY BEFORE each left row's day."""
    d = daily.sort_values("day", kind="mergesort").copy()
    d["cum"] = d.groupby(right_keys)["n"].cumsum()
    l = left[list(left_keys) + ["day"]].copy()
    l.columns = list(right_keys) + ["day"]
    l["_ord"] = np.arange(len(l))
    l = l.sort_values("day", kind="mergesort")
    m = pd.merge_asof(l, d[list(right_keys) + ["day", "cum"]], on="day", by=list(right_keys),
                      allow_exact_matches=False)
    return m.sort_values("_ord")["cum"].fillna(0).to_numpy()


def build_features(tx: pd.DataFrame) -> pd.DataFrame:
    """Causal per-transaction feature frame aligned with `tx` row order. Contains NO label columns."""
    out_daily = tx.groupby(["sender", "day"]).size().rename("n").reset_index()
    in_daily = tx.groupby(["receiver", "day"]).size().rename("n").reset_index()
    pair_daily = tx.groupby(["sender", "receiver", "day"]).size().rename("n").reset_index()

    F = pd.DataFrame({"transaction_id": tx["transaction_id"].values, "day": tx["day"].values})
    F["amount"] = tx["amount"].values.astype(float)
    F["s_out"] = _prior_counts(tx, ["sender"], out_daily, ["sender"])
    F["r_in"] = _prior_counts(tx, ["receiver"], in_daily, ["receiver"])
    F["s_out_today"] = tx.groupby(["sender", "day"])["day"].transform("size").values
    F["r_in_today"] = tx.groupby(["receiver", "day"])["day"].transform("size").values
    F["pair"] = _prior_counts(tx, ["sender", "receiver"], pair_daily, ["sender", "receiver"])
    F["rev_pair"] = _prior_counts(tx, ["receiver", "sender"], pair_daily, ["sender", "receiver"])
    F["edge_is_new"] = (F["pair"] == 0).astype(int)
    F["s_first_out"] = (F["s_out"] == 0).astype(int)
    F["r_first_in"] = (F["r_in"] == 0).astype(int)

    act = pd.concat([
        tx[["sender", "day"]].set_axis(["a", "day"], axis=1),
        tx[["receiver", "day"]].set_axis(["a", "day"], axis=1),
    ], ignore_index=True).drop_duplicates().sort_values(["a", "day"], kind="mergesort")
    act["prev"] = act.groupby("a")["day"].shift(1)
    first = act.groupby("a")["day"].min()
    prev_map = act.set_index(["a", "day"])["prev"]
    for role, col in (("s", "sender"), ("r", "receiver")):
        F[f"{role}_age"] = tx["day"].values - tx[col].map(first).to_numpy()
        idx = pd.MultiIndex.from_arrays([tx[col].values, tx["day"].values])
        F[f"{role}_idle"] = tx["day"].values - prev_map.reindex(idx).to_numpy()
    return F


# ----------------------------------------------------------------------------------------------
# rings
# ----------------------------------------------------------------------------------------------
def ring_table(at: pd.DataFrame, k: int = 4) -> pd.DataFrame:
    rows = []
    for aid, g in at.groupby("alert_id"):
        g = g.sort_values(["day", "transaction_id"], kind="mergesort")
        typ = str(g["alert_type"].iloc[0])
        obs_day, obs_tx = int(g["day"].iloc[-1]), g["transaction_id"].iloc[-1]
        if typ != "cycle":
            cp = g["orig_acct"] if typ == "fan_in" else g["bene_acct"]
            seen = set()
            for txid, day, c in zip(g["transaction_id"], g["day"], cp):
                seen.add(c)
                if len(seen) >= k:
                    obs_day, obs_tx = int(day), txid
                    break
        rows.append(dict(ring_id=str(aid), typology=typ, first_day=int(g["day"].iloc[0]),
                         last_day=int(g["day"].iloc[-1]), observable_day=obs_day, observable_tx=obs_tx,
                         n_tx=len(g), tx_ids=list(g["transaction_id"])))
    return pd.DataFrame(rows)


# ----------------------------------------------------------------------------------------------
# scoring (rolling origin, ring grouped)
# ----------------------------------------------------------------------------------------------
def _fit_predict_xgb(Xtr, ytr, Xte, seed, n_estimators):
    import xgboost as xgb
    pos = int(ytr.sum()); neg = len(ytr) - pos
    m = xgb.XGBClassifier(n_estimators=n_estimators, max_depth=4, learning_rate=0.05, subsample=0.8,
                          colsample_bytree=0.8, scale_pos_weight=max(neg / max(pos, 1), 1.0),
                          random_state=seed, eval_metric="aucpr", tree_method="hist", n_jobs=2, verbosity=0)
    m.fit(Xtr, ytr)
    return m.predict_proba(Xte)[:, 1].astype(float)


def score_rolling(tx, F, rings, model, eval_start, block_len, burn_in, seed, n_estimators=200, min_train_pos=5):
    """Return (scored_df, block_info). Only rows with day >= eval_start are scored, each by a model that
    never saw that day or any ring that continues into the block."""
    assert not (set(F.columns) & FORBIDDEN_FEATURE_NAMES), "label-like column leaked into feature frame"
    day = F["day"].values
    y = (tx["label"].values == 1).astype(int)
    idx_of = {t: i for i, t in enumerate(F["transaction_id"].values)}
    ring_last = np.full(len(F), -1)
    for _, r in rings.iterrows():
        for t in r["tx_ids"]:
            ring_last[idx_of[t]] = r["last_day"]
    rng = np.random.default_rng(seed)
    scores = np.full(len(F), np.nan)
    info = []
    start, max_day = eval_start, int(day.max())
    while start <= max_day:
        end = min(start + block_len, max_day + 1)
        te = (day >= start) & (day < end)
        if model in XGB_SPECS:
            cols = XGB_SPECS[model]
            tr = (day >= burn_in) & (day < start) & ~(ring_last >= start)
            npos = int(y[tr].sum())
            if npos < min_train_pos:
                info.append(dict(block=[start, end], n_train=int(tr.sum()), n_train_pos=npos, scored=False))
            else:
                scores[te] = _fit_predict_xgb(F.loc[tr, cols], y[tr], F.loc[te, cols], seed, n_estimators)
                info.append(dict(block=[start, end], n_train=int(tr.sum()), n_train_pos=npos, scored=True))
        elif model == "newness_rule":
            scores[te] = F.loc[te, "s_first_out"].values * 1.0 + F.loc[te, "r_first_in"].values * 0.5
            info.append(dict(block=[start, end], scored=True, note="rule, no training"))
        elif model == "random":
            scores[te] = rng.random(int(te.sum()))
            info.append(dict(block=[start, end], scored=True, note="random control"))
        else:
            raise ValueError(model)
        start = end
    ok = ~np.isnan(scores)
    scored = pd.DataFrame({"transaction_id": F["transaction_id"].values[ok], "day": day[ok],
                           "label": y[ok], "score": scores[ok], "s_first_out": F["s_first_out"].values[ok]})
    return scored, info


# ----------------------------------------------------------------------------------------------
# evaluation
# ----------------------------------------------------------------------------------------------
def bootstrap_ci(values, stat=np.median, n_boot=2000, seed=0, min_n=5):
    v = np.asarray(values, dtype=float)
    v = v[~np.isnan(v)]
    if len(v) < min_n:
        return [None, None]
    rng = np.random.default_rng(seed)
    boots = [stat(rng.choice(v, size=len(v), replace=True)) for _ in range(n_boot)]
    return [float(np.percentile(boots, 2.5)), float(np.percentile(boots, 97.5))]


def _f(x):
    return None if x is None or (isinstance(x, float) and np.isnan(x)) else float(x)


def evaluate_budget(scored: pd.DataFrame, rings: pd.DataFrame, k: int, eval_start: int, seed: int = 0):
    """Flag the top-k scored transactions per day; evaluate each ring."""
    s = scored.copy()
    rng = np.random.default_rng(seed)
    s["_tb"] = s["score"].astype(float) + rng.random(len(s)) * 1e-9
    s["flag"] = s.groupby("day")["_tb"].rank(method="first", ascending=False) <= k
    fl = s[s["flag"]].set_index("transaction_id")
    last_scored_day = int(s["day"].max()) if len(s) else -1

    rows = []
    for _, r in rings.iterrows():
        hit = fl.reindex(r["tx_ids"]).dropna(subset=["day"]).sort_values("day", kind="mergesort")
        in_period = bool(eval_start <= r["observable_day"] <= last_scored_day)
        # primary: EVERY transaction of the ring is scorable, so a warning is not truncated by the start of scoring
        evaluable = bool(in_period and r["first_day"] >= eval_start)
        warn_day = int(hit["day"].iloc[0]) if len(hit) else None
        rows.append(dict(
            ring_id=r["ring_id"], typology=r["typology"], n_tx=r["n_tx"], first_day=r["first_day"],
            observable_day=r["observable_day"], observable_tx=r["observable_tx"], evaluable=evaluable,
            observable_in_scored_period=in_period,
            detected=warn_day is not None, warning_day=warn_day,
            warning_tx=hit.index[0] if len(hit) else None,
            warning_score=_f(hit["score"].iloc[0]) if len(hit) else None,
            lead_days=(r["observable_day"] - warn_day) if warn_day is not None else None))
    per_ring = pd.DataFrame(rows)

    n_days = int(s["day"].nunique())
    flagged = s[s["flag"]]
    tp = int(flagged["label"].sum()); nfl = int(len(flagged))
    flag_stats = dict(alerts_per_day_budget=k, scored_days=n_days, n_flags=nfl, true_flags=tp,
                      false_flags=nfl - tp, false_alerts_per_day=(nfl - tp) / n_days if n_days else None,
                      precision_of_flags=tp / nfl if nfl else None,
                      share_of_true_flags_that_are_first_ever_sender=_f(flagged.loc[flagged["label"] == 1, "s_first_out"].mean())
                      if tp else None)
    return per_ring, flag_stats


def summarize(per_ring: pd.DataFrame, seed: int = 0, col: str = "evaluable") -> dict:
    ev = per_ring[per_ring[col]]
    out = {}
    groups = [("all", ev)] + [(t, g) for t, g in ev.groupby("typology")]
    for name, g in groups:
        n = len(g)
        det = g[g["detected"]]
        leads = det["lead_days"].astype(float)
        out[name] = dict(
            n_evaluable_rings=n, n_detected=int(len(det)),
            detection_rate=len(det) / n if n else None,
            n_warned_before_observable=int((det["lead_days"] > 0).sum()),
            warned_before_observable_rate=float((det["lead_days"] > 0).sum() / n) if n else None,
            lead_days_median=_f(leads.median()) if len(leads) else None,
            lead_days_mean=_f(leads.mean()) if len(leads) else None,
            lead_days_q25=_f(leads.quantile(.25)) if len(leads) else None,
            lead_days_q75=_f(leads.quantile(.75)) if len(leads) else None,
            lead_days_min=_f(leads.min()) if len(leads) else None,
            lead_days_max=_f(leads.max()) if len(leads) else None,
            lead_days_median_ci95=bootstrap_ci(leads, seed=seed),
            n_for_lead_stats=int(len(leads)))
    return out


def tx_level_metrics(scored: pd.DataFrame) -> dict:
    from sklearn.metrics import average_precision_score, roc_auc_score
    y = scored["label"].values
    if y.sum() == 0 or y.sum() == len(y):
        return dict(n_scored_tx=int(len(y)), n_positive=int(y.sum()), pr_auc=None, roc_auc=None)
    return dict(n_scored_tx=int(len(y)), n_positive=int(y.sum()), prevalence=float(y.mean()),
                pr_auc=float(average_precision_score(y, scored["score"])),
                roc_auc=float(roc_auc_score(y, scored["score"])))


def _sha256(path, chunk=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(chunk), b""):
            h.update(b)
    return h.hexdigest()


# ----------------------------------------------------------------------------------------------
# orchestration
# ----------------------------------------------------------------------------------------------
def run_evaluation(tx_path, alerts_path, out_dir, report_dir, burn_in=120, eval_start=240, block_len=120,
                   ks=(1, 3, 5, 10), headline_k=5, headline_model="xgb_with_novelty", observable_k=4,
                   seed=42, n_estimators=200, models=ALL_MODELS, verbose=True):
    if not (0 <= burn_in < eval_start):
        raise ValueError("need 0 <= burn_in < eval_start")
    t0 = time.time()
    log = (lambda *a: print(*a, flush=True)) if verbose else (lambda *a: None)
    tx, day0 = load_transactions(tx_path)
    at = load_alert_transactions(alerts_path, tx)
    rings = ring_table(at, k=observable_k)
    log(f"transactions={len(tx):,} days={tx['day'].max() + 1} rings={len(rings)} "
        f"(types: {rings['typology'].value_counts().to_dict()})")
    F = build_features(tx)
    log(f"features built in {time.time() - t0:.1f}s")

    results, all_rows, info_by_model, txm = {}, [], {}, {}
    for model in models:
        scored, info = score_rolling(tx, F, rings, model, eval_start, block_len, burn_in, seed, n_estimators)
        info_by_model[model] = info
        txm[model] = tx_level_metrics(scored)
        results[model] = {}
        for k in ks:
            per_ring, flag_stats = evaluate_budget(scored, rings, k, eval_start, seed)
            per_ring.insert(0, "model", model); per_ring.insert(1, "alerts_per_day", k)
            all_rows.append(per_ring)
            results[model][str(k)] = dict(summary=summarize(per_ring, seed), flag_stats=flag_stats,
                                          summary_observable_in_period=summarize(per_ring, seed, "observable_in_scored_period"))
        log(f"  scored {model:20s} ({time.time() - t0:.0f}s)")

    all_df = pd.concat(all_rows, ignore_index=True)
    all_df["observable_date"] = (day0 + pd.to_timedelta(all_df["observable_day"], unit="D")).dt.date.astype(str)
    all_df["warning_date"] = [None if pd.isna(d) else str((day0 + pd.Timedelta(days=int(d))).date()) for d in all_df["warning_day"]]
    out_dir = Path(out_dir); out_dir.mkdir(parents=True, exist_ok=True)
    report_dir = Path(report_dir); report_dir.mkdir(parents=True, exist_ok=True)
    all_df.to_csv(out_dir / "ring_lead_time_rings_all_configs.csv", index=False)
    head = all_df[(all_df.model == headline_model) & (all_df.alerts_per_day == headline_k)]
    head.to_csv(out_dir / "ring_lead_time_rings.csv", index=False)

    summary = dict(
        generated_at=datetime.now(timezone.utc).isoformat(), runtime_seconds=round(time.time() - t0, 1),
        parameters=dict(burn_in_days=burn_in, first_scored_day=eval_start, block_len_days=block_len,
                        alerts_per_day_values=list(ks), headline_alerts_per_day=headline_k,
                        headline_model=headline_model, observable_k=observable_k, seed=seed,
                        n_estimators=n_estimators),
        definitions=dict(
            observable_time="cycle: day of last (closing) edge; fan_in/fan_out: day the k-th distinct counterparty has transacted (k=observable_k), else last transaction day",
            warning_time="earliest day any transaction of the ring is flagged by the daily budget (out-of-sample days only)",
            lead_time="observable_day - warning_day, in days; >0 means warned before the ring became observable",
            evaluable_ring="ALL transactions of the ring fall inside the scored period (first_day >= first scored day) and its observable_day is scored; "
                           "this avoids right-truncating warnings. The JSON also keeps summary_observable_in_period (only observable_day in the scored period), which is truncated for slow rings."),
        data=dict(n_transactions=int(len(tx)), n_days=int(tx["day"].max() + 1), day0=str(day0.date()),
                  n_rings=int(len(rings)), rings_by_type=rings["typology"].value_counts().to_dict(),
                  transactions_sha256=_sha256(tx_path), alerts_sha256=_sha256(alerts_path)),
        environment=dict(python=platform.python_version(), pandas=pd.__version__, numpy=np.__version__),
        training_blocks=info_by_model, tx_level_out_of_sample_metrics=txm, results=results,
        caveats=[
            "AMLSim-specific shortcut: ring members are drawn from otherwise-dormant accounts, so 'first-ever sender' "
            "transactions are almost always ring transactions after a warm-up. xgb_without_novelty uses same-day information only "
            "(no account history); newness_rule is a two-bit rule (first-ever sender / first-ever receiver); random is a control. "
            "If xgb_with_novelty does not clearly beat newness_rule, the model adds nothing beyond the shortcut.",
            "Labels are used only as training targets for rows before each scored block and for evaluation.",
            "Rings that continue into a scored block are excluded from that block's training set (ring-grouped split).",
            "Daily timestamps: a flag on the same day as observable_time gives lead 0 (not early).",
            "Evaluable ring counts are small for some typologies; read N and the confidence intervals."])
    with open(out_dir / "ring_lead_time_summary.json", "w") as f:
        json.dump(summary, f, indent=2, default=str)
    render_report(summary, head, Path(report_dir) / "ring_lead_time_report.html")
    log(f"done in {time.time() - t0:.0f}s")
    return summary, head


# ----------------------------------------------------------------------------------------------
# HTML report (self-contained)
# ----------------------------------------------------------------------------------------------
def _fmt(x, nd=1, pct=False):
    if x is None:
        return "&mdash;"
    return f"{100 * x:.0f}%" if pct else f"{x:.{nd}f}"


def render_report(summary: dict, head: pd.DataFrame, path: Path) -> None:
    p = summary["parameters"]
    hm, hk = p["headline_model"], str(p["headline_alerts_per_day"])
    S = summary["results"][hm][hk]
    css = ("body{font-family:Segoe UI,Arial,sans-serif;margin:24px;color:#1a1a2e;background:#f7f8fb}"
           "table{border-collapse:collapse;background:#fff;margin:8px 0 20px}th,td{border:1px solid #e3e6ef;padding:6px 10px;font-size:13px;text-align:left}"
           "th{background:#eef1fa}.warn{background:#fff4e5;border:1px solid #f5c26b;padding:10px 14px;margin:12px 0;border-radius:6px}"
           ".note{color:#667;font-size:12px}h2{margin-top:28px}")
    rows = []
    for name, g in S["summary"].items():
        lo, hi = g["lead_days_median_ci95"]
        ci = "n too small" if lo is None else f"[{lo:.1f}, {hi:.1f}]"
        rows.append(f"<tr><td>{html.escape(name)}</td><td>{g['n_evaluable_rings']}</td>"
                    f"<td>{g['n_detected']} ({_fmt(g['detection_rate'], pct=True)})</td>"
                    f"<td>{g['n_warned_before_observable']} ({_fmt(g['warned_before_observable_rate'], pct=True)})</td>"
                    f"<td>{_fmt(g['lead_days_median'])}</td><td>{ci}</td>"
                    f"<td>{_fmt(g['lead_days_q25'])} &ndash; {_fmt(g['lead_days_q75'])}</td>"
                    f"<td>{_fmt(g['lead_days_min'], 0)} / {_fmt(g['lead_days_max'], 0)}</td><td>{g['n_for_lead_stats']}</td></tr>")
    fs = S["flag_stats"]
    abl = []
    for m in summary["results"]:
        for k, v in summary["results"][m].items():
            a = v["summary"].get("all", {})
            abl.append(f"<tr><td>{html.escape(m)}</td><td>{k}</td><td>{a.get('n_evaluable_rings', 0)}</td>"
                       f"<td>{_fmt(a.get('detection_rate'), pct=True)}</td><td>{_fmt(a.get('warned_before_observable_rate'), pct=True)}</td>"
                       f"<td>{_fmt(a.get('lead_days_median'))}</td><td>{_fmt(v['flag_stats']['false_alerts_per_day'], 2)}</td>"
                       f"<td>{_fmt(v['flag_stats']['precision_of_flags'], pct=True)}</td></tr>")
    ring_rows = []
    for _, r in head.sort_values(["typology", "ring_id"]).iterrows():
        ring_rows.append("<tr>" + "".join(f"<td>{html.escape(str(r[c]))}</td>" for c in
                         ["ring_id", "typology", "evaluable", "observable_date", "observable_tx", "warning_date", "warning_tx", "lead_days"]) + "</tr>")
    tx_m = summary["tx_level_out_of_sample_metrics"][hm]
    html_doc = f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>Ring-level lead-time evaluation</title><style>{css}</style></head><body>
<h1>Ring-level early-warning evaluation</h1>
<p class="note">Generated {summary['generated_at']} &middot; {summary['data']['n_transactions']:,} transactions &middot; {summary['data']['n_rings']} labelled rings {html.escape(str(summary['data']['rings_by_type']))}</p>
<div class="warn"><b>Read before citing.</b> AMLSim draws ring members from otherwise-dormant accounts, so "first-ever sender" is an unusually strong signal here.
Always compare the headline model with the <i>without novelty</i>, <i>newness rule</i> and <i>random</i> rows below. This is an exploratory, simulator-specific result, not evidence of general early-warning performance.</div>
<h2>Headline: {html.escape(hm)}, budget {p['headline_alerts_per_day']} alerts/day (N = evaluable rings)</h2>
<table><tr><th>Typology</th><th>N rings</th><th>Detected</th><th>Warned before observable</th><th>Median lead (days)</th><th>Median 95% CI</th><th>Lead IQR</th><th>Min / Max</th><th>N (lead stats)</th></tr>{''.join(rows)}</table>
<p>False alerts per day: <b>{_fmt(fs['false_alerts_per_day'], 2)}</b> &middot; precision of flags: <b>{_fmt(fs['precision_of_flags'], pct=True)}</b> &middot; share of true flags that are a first-ever sender: <b>{_fmt(fs['share_of_true_flags_that_are_first_ever_sender'], pct=True)}</b>
&middot; out-of-sample transaction-level PR-AUC {_fmt(tx_m.get('pr_auc'), 3)} (prevalence {_fmt(tx_m.get('prevalence'), 4)}).</p>
<h2>Operational definitions</h2><ul>{''.join(f'<li><b>{html.escape(k)}</b>: {html.escape(v)}</li>' for k, v in summary['definitions'].items())}</ul>
<p class="note">Burn-in {p['burn_in_days']} days &middot; first scored day {p['first_scored_day']} &middot; blocks of {p['block_len_days']} days &middot; rolling-origin, ring-grouped training &middot; observable k = {p['observable_k']} &middot; seed {p['seed']}</p>
<h2>Ablation and controls across alert budgets</h2>
<table><tr><th>Model</th><th>Alerts/day</th><th>N rings</th><th>Detected</th><th>Warned before observable</th><th>Median lead (days)</th><th>False alerts/day</th><th>Precision of flags</th></tr>{''.join(abl)}</table>
<h2>Per-ring evidence (headline configuration)</h2>
<table><tr><th>Ring</th><th>Type</th><th>Evaluable</th><th>Observable date</th><th>Observable tx</th><th>Warning date</th><th>Warning tx</th><th>Lead (days)</th></tr>{''.join(ring_rows)}</table>
<h2>Caveats</h2><ul>{''.join(f'<li>{html.escape(c)}</li>' for c in summary['caveats'])}</ul></body></html>"""
    Path(path).write_text(html_doc, encoding="utf-8")
