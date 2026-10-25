"""
The score calculation card (ADDITIVE): for every candidate, how its risk score was worked out, quoted from the scoring code's own constants
and from the inputs the scorer recorded, so the card cannot drift from what was actually computed.
"""
from __future__ import annotations

import math

from src.pipeline_v2 import core
from src.pipeline_v2.export import iso

LABEL = {"behavioural": "Behavioural", "network": "Network", "fund_flow": "Fund flow", "persistence": "Persistence"}


def _pattern_line(pats):
    parts = []
    for p in sorted(set(pats)):
        name = (core.old_names([p]) or ["first-time account activity"])[0].replace("_", " ")
        parts.append((name, core.PATTERN_WEIGHT.get(p, 0.5)))
    return parts


def explain(entry, s) -> dict:
    comp, w, inp = entry["components"], s.weights, entry["inputs"]
    R = core.NETWORK_RULES
    if inp["kind"] == "closed_cycle":
        net = f"A closed cycle of money scores {R['closed_cycle']:.0f}."
    elif inp["kind"] == "partial_cycle":
        net = f"A chain of transfers that has not closed into a cycle yet scores {R['partial_cycle']:.0f}."
    else:
        pats = entry["patterns"]
        bonus = [f"+{R['slow_drip_bonus']} for a fan that builds over time" for _ in [0] if any(p.startswith("slow_drip") for p in pats)] + \
                [f"+{R['new_account_chain_bonus']} for a chain of new accounts" for _ in [0] if "new_account_chain" in pats]
        net = f"{R['per_first_time_transfer']} for each of the {inp['n_first_time_transfers']} first-time transfers" + (", " + ", ".join(bonus) if bonus else "") + f", capped at {R['cap']}."
    parts = _pattern_line(entry["patterns"])
    total_w = sum(wt for _, wt in parts)
    P = core.PERSISTENCE_RULE
    how = {
        "behavioural": (f"Average, over this candidate's {inp['n_accounts_scored']} accounts, of where each account's model score ranks among all active accounts "
                        f"(highest: account {inp['top_account']} at the {inp['top_percentile']:.0f}th percentile). The model was trained only on earlier data."),
        "network": net,
        "fund_flow": (f"Patterns present: {', '.join(f'{n} (weight {wt:g})' for n, wt in parts)}. Their weights add up to {total_w:g} out of a possible {core.MAX_PATTERN_WEIGHT:g}, "
                      f"so {total_w:g} / {core.MAX_PATTERN_WEIGHT:g} x 100 = {comp['fund_flow']:.1f}."),
        "persistence": (f"{P['scale']} x ln(1 + {P['factor']} x {entry['n_tx']} evidence transactions / {entry['n_nodes']} accounts) = {comp['persistence']:.1f}, capped at {P['cap']:.0f}."),
    }
    steps = [{"component": k, "label": LABEL[k], "how": how[k], "value": comp[k], "weight": w[k], "points": round(comp[k] * w[k], 4)} for k in w]
    total = round(sum(comp[k] * w[k] for k in w), 2)                      # exactly the score; per-step points are shown rounded, so they can add up to 0.01 away
    return {"day": int(entry["day"]), "score": float(entry["score"]), "level": entry["level"], "alert_threshold": s.alert_threshold, "alert": bool(entry["score"] >= s.alert_threshold),
            "steps": steps, "total_points": total,
            "formula": "score = " + " + ".join(f"{w[k]:.2f} x {LABEL[k].lower()}" for k in w),
            "level_bands": s.thresholds}


def build_all(cands, history, index, day0, s) -> dict:
    if any("inputs" not in h for hist in history for h in hist):
        raise SystemExit("The saved scores were written by an older version and do not record their inputs. "
                         "Run `python scripts/rebuild_v2.py scoring` (about a minute) and then `python scripts/rebuild_v2.py export`.")
    out = {}
    for ci, hist in enumerate(history):
        ad = core.alert_day(hist, s.alert_threshold)
        out[index[ci]] = {
            "calculation": explain(hist[-1], s), "alert_day": None if ad is None else int(ad), "first_date": iso(day0, 0),
            "steps": [{"day": int(h["day"]), "date": iso(day0, h["day"]), "score": float(h["score"]), "level": h["level"], "components": h["components"],
                       "patterns": core.old_names(h["patterns"]), "n_tx": int(h["n_tx"]), "n_nodes": int(h["n_nodes"])} for h in hist]}
    return out
