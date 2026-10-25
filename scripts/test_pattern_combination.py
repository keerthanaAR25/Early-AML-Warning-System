#!/usr/bin/env python3
"""
Does combining INDEPENDENT pattern types help rank candidates?  (experiment; ring labels are used only to evaluate)

Independent pattern events = the original (v1) pattern engine's events (results/v1_backup/pattern_events.json). They are computed from
transactions only and never decide which candidates exist. For a candidate on day d we collect the distinct v1 pattern types whose events
(on or before d, within the last W days) involve any of the candidate's accounts as of d. Fixed in advance: W=7 (1 and 14 are sensitivity only).
They enter the score exactly like the candidate's own patterns: added to the fund-flow numerator with the project's existing weights, capped at 100.
Nothing is re-weighted or tuned.

  python scripts/test_pattern_combination.py            (needs a finished `python scripts/rebuild_v2.py all`)
"""
import importlib.util
import json
import pickle
import sys
from collections import Counter, defaultdict
from pathlib import Path
from types import SimpleNamespace

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.evaluation import candidates_v2 as C  # noqa: E402
from src.evaluation.ring_lead_time import ring_table  # noqa: E402
from src.pipeline_v2 import core  # noqa: E402

spec = importlib.util.spec_from_file_location("rebuild_v2", ROOT / "scripts" / "rebuild_v2.py")
rb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rb)

PRIMARY_W, SENSITIVITY_W = 7, (1, 14)
THRESHOLDS = (40, 45, 50, 55)


def v1_weights():
    for mod in ("src.scoring.risk_engine", "src.temporal.trajectory"):
        m = __import__(mod, fromlist=["x"])
        for k, v in vars(m).items():
            if isinstance(v, dict) and "circular_flow" in v and all(isinstance(x, (int, float)) for x in v.values()):
                return dict(v)
    raise SystemExit("could not find the original pattern weights")


def norm(a):
    try:
        return str(int(float(a)))
    except (TypeError, ValueError):
        return str(a)


def auc(y, s):
    from sklearn.metrics import roc_auc_score
    return float(roc_auc_score(y, s)) if 0 < y.sum() < len(y) else float("nan")


def boot_delta(y, sa, sb, cluster, n=2000, seed=42):
    rng = np.random.default_rng(seed)
    groups = defaultdict(list)
    for i, c in enumerate(cluster):
        groups[c].append(i)
    keys = list(groups)
    out = []
    for _ in range(n):
        idx = np.concatenate([groups[keys[j]] for j in rng.integers(0, len(keys), len(keys))])
        if 0 < y[idx].sum() < len(idx):
            out.append(auc(y[idx], sb[idx]) - auc(y[idx], sa[idx]))
    return float(np.percentile(out, 2.5)), float(np.percentile(out, 97.5))


def main():
    s = core.load_settings(ROOT)
    a = SimpleNamespace(clean=str(ROOT / "data/processed/transactions_clean.csv"), alerts=str(ROOT / "data/raw/amlsim/alert_transactions.csv"))
    tx, day0, at, tx_nl, F, info, flags, day_of = rb.prepare(a, s)
    cands = pickle.load(open(rb.WORK / "candidates.pkl", "rb"))["cands"]
    hist = pickle.load(open(rb.WORK / "scoring.pkl", "rb"))["history"]
    v1_path = ROOT / "results" / "v1_backup" / "pattern_events.json"
    if not v1_path.exists():
        raise SystemExit("results/v1_backup/pattern_events.json not found (it is created by the rebuild)")
    events = json.load(open(v1_path))
    W1 = v1_weights()
    S, R = info["S"], info["R"]
    idx = defaultdict(list)
    for e in events:
        for acc in e["accounts"]:
            idx[norm(acc)].append((int(float(e["window_id"])), e["pattern_type"]))
    print(f"independent pattern events: {len(events):,} across {len(idx):,} accounts; types: {dict(Counter(e['pattern_type'] for e in events))}")

    def indep(nodes, d, W):
        return {t for acc in nodes for (day, t) in idx.get(acc, ()) if d - W < day <= d}

    # ---- ground truth facts used to interpret the result
    rings = ring_table(at, k=s.observable_k)
    ring_of = dict(zip(at["transaction_id"], at["alert_id"].astype(str)))
    label_of = dict(zip(tx["transaction_id"], tx["label"]))
    typ = dict(zip(rings["ring_id"].astype(str), rings["typology"]))
    print("\nAMLSim ring typologies:", dict(Counter(typ.values())), "(one typology per alert)")
    acc_rings = defaultdict(set)
    for t, rid in ring_of.items():
        acc_rings[S[t]].add(rid); acc_rings[R[t]].add(rid)
    multi = [x for x, r in acc_rings.items() if len(r) > 1]
    mixed = [x for x in multi if len({typ.get(r) for r in acc_rings[x]}) > 1]
    print(f"accounts in more than one ring: {len(multi)} of {len(acc_rings)}; in rings of different typologies: {len(mixed)}")

    # ---- does a ring account show independent patterns more often than a normal account? (all scored days, no candidates involved)
    scored = tx[tx["day"] >= s.scored_from]
    ring_tx, norm_tx = scored[scored["label"] == 1], scored[scored["label"] == 0].sample(30000, random_state=s.seed)
    for W in (PRIMARY_W,):
        fr = [indep({S[t]}, day_of[t], W) for t in ring_tx["transaction_id"]]
        fn = [indep({S[t]}, day_of[t], W) for t in norm_tx["transaction_id"]]
        pr, pn = np.mean([len(x) > 0 for x in fr]), np.mean([len(x) > 0 for x in fn])
        print(f"\nsender shows >=1 independent pattern in the last {W} days:  ring transactions {100 * pr:.1f}%  (n={len(fr)})   normal transactions {100 * pn:.1f}%  (n={len(fn)})   lift {pr / pn if pn else float('nan'):.2f}x")
        print(f"mean distinct independent types:  ring {np.mean([len(x) for x in fr]):.2f}   normal {np.mean([len(x) for x in fn]):.2f}")

    # ---- candidates: base vs with independent patterns
    contains = np.array([any(label_of.get(t, 0) == 1 for t in c["tx"]) for c in cands])
    cluster = []
    for i, c in enumerate(cands):
        rr = Counter(ring_of[t] for t in c["tx"] if t in ring_of and label_of.get(t, 0) == 1)
        cluster.append(("ring", rr.most_common(1)[0][0]) if rr else ("n", i))

    def variant(W):
        out = []
        for ci, c in enumerate(cands):
            new = []
            for h in hist[ci]:
                nodes = {x for t in c["tx"] if day_of[t] <= h["day"] for x in (S[t], R[t])}
                ind = indep(nodes, h["day"], W)
                comp = dict(h["components"])
                own = sum(core.PATTERN_WEIGHT.get(p, 0.5) for p in set(h["patterns"]))
                comp["fund_flow"] = round(min(100.0, (own + sum(W1.get(t, 0.5) for t in ind)) / core.MAX_PATTERN_WEIGHT * 100), 2)
                new.append({**h, "components": comp, "score": core.combine(comp, s.weights), "indep": sorted(ind)})
            out.append(new)
        return out

    def summarize(name, H):
        fin = np.array([h[-1]["score"] for h in H])
        order = np.argsort(-fin, kind="stable")
        row = {"name": name, "auc": auc(contains, fin), **{f"p@{k}": float(contains[order[:k]].mean()) for k in (10, 20, 50)}}
        for thr in THRESHOLDS:
            ad = [core.alert_day(h, thr) for h in H]
            lst = [{"tx": set(c["tx"]), "nodes": set(c["nodes"]), "creation_day": d} for c, d in zip(cands, ad) if d is not None]
            idxs = [i for i, d in enumerate(ad) if d is not None]
            if not lst:
                row[thr] = None; continue
            sm, _ = C.evaluate_candidate_set("t", lst, tx, rings, ring_of, label_of, day_of, s.scored_from, int(tx["day"].max()), s.seed)
            g = sm["by_typology"]["all"]
            row[thr] = dict(alerts=len(idxs), precision=float(contains[idxs].mean()), seen=g["n_with_any_tx_in_candidate"], early=g["n_warned_before_observable"],
                            lead=g["lead_days_median"], false_per_day=float((len(idxs) - contains[idxs].sum()) / (int(tx["day"].max()) - s.scored_from + 1)))
        return row, fin

    base_row, base_fin = summarize("base (as shipped)", hist)
    results = {"base": base_row}
    variants = {}
    for W in (PRIMARY_W,) + SENSITIVITY_W:
        H = variant(W)
        row, fin = summarize(f"+ independent patterns, W={W}", H)
        lo, hi = boot_delta(contains, base_fin, fin, cluster)
        row["delta_auc_ci"] = (lo, hi)
        results[f"W{W}"] = row; variants[W] = (H, fin)
    # standalone signal: how many distinct independent types alone
    H7 = variants[PRIMARY_W][0]
    cnt = np.array([len(h[-1]["indep"]) for h in H7], dtype=float)
    print(f"\ncandidates with >=1 independent pattern type (W=7, final day): ring-containing {100 * np.mean(cnt[contains] > 0):.0f}%  vs others {100 * np.mean(cnt[~contains] > 0):.0f}%"
          f"   | mean distinct types: ring-containing {cnt[contains].mean():.2f}  vs others {cnt[~contains].mean():.2f}   | standalone AUC of the count: {auc(contains, cnt):.3f}")
    from scipy.stats import mannwhitneyu
    print("Mann-Whitney p (count higher in ring-containing candidates):", f"{mannwhitneyu(cnt[contains], cnt[~contains], alternative='greater').pvalue:.3g}")

    print(f"\n{len(cands)} candidates, {int(contains.sum())} contain ring transactions\n")
    print(f"{'variant':34s} {'AUC':>6s} {'P@10':>6s} {'P@20':>6s} {'P@50':>6s}   change in AUC (95% CI, ring-clustered)")
    for k, r in results.items():
        d = r.get("delta_auc_ci")
        print(f"{r['name']:34s} {r['auc']:6.3f} {r['p@10']:6.2f} {r['p@20']:6.2f} {r['p@50']:6.2f}   " + (f"{r['auc'] - base_row['auc']:+.3f} ({d[0]:+.3f} to {d[1]:+.3f})" if d else "-"))
    print(f"\nalerts at each threshold  (alerts / precision / rings seen of 30 / warned early / median lead / false per day)")
    for thr in THRESHOLDS:
        for k in ("base", f"W{PRIMARY_W}"):
            r = results[k][thr]
            print(f"  thr {thr}  {results[k]['name'][:30]:30s} " + ("none" if r is None else f"{r['alerts']:>3d} / {r['precision']:.2f} / {r['seen']:>2d} / {r['early']:>2d} / {str(r['lead']):>4s} / {r['false_per_day']:.3f}"))
    json.dump({k: {kk: vv for kk, vv in v.items()} for k, v in results.items()}, open(ROOT / "results" / "pattern_combination_test.json", "w"), indent=1, default=str)


if __name__ == "__main__":
    main()
