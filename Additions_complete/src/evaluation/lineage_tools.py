"""
Data-lineage checks and an opt-in ID repair (ADDITIVE module -- touches nothing unless --fix is given,
and then backs up every file/database first as <name>.bak).

Problem it addresses: pandas upcasts integer IDs to floats during some merges, so a few account /
transaction IDs end up stored as "49066.0" instead of "49066". Such IDs fail to join back to the source
transactions, which silently drops evidence edges (e.g. 7 transaction IDs but only 6 graph edges).

Checks
------
* float-formatted IDs ("123.0") anywhere in results/*.json and in every TEXT column of the SQLite DB;
* lineage: every candidate / evidence transaction ID exists in transactions_clean.csv, every account
  exists as a sender or receiver, and evidence contains every transaction its candidate lists.
"""
from __future__ import annotations

import json
import re
import shutil
import sqlite3
from pathlib import Path

import pandas as pd

FLOAT_ID = re.compile(r"^\d+\.0$")
QUOTED_FLOAT_ID = re.compile(r'"(\d+)\.0"')
JSON_FILES = ["pattern_events.json", "ring_candidates.json", "evidence.json", "forensic_explanations.json"]


# ---------------------------------------------------------------- normalisation
def norm_id(v):
    return v[:-2] if isinstance(v, str) and FLOAT_ID.match(v) else v


def normalize_obj(o):
    """'123.0' -> '123' everywhere. In a list, an element that was CHANGED by normalisation and now duplicates an
    element already present is dropped (e.g. ['14', '14.0'] -> ['14']). Unchanged repeats such as a pass-through
    chain ['A', 'B', 'A'] are left alone."""
    if isinstance(o, dict):
        return {k: normalize_obj(v) for k, v in o.items()}
    if isinstance(o, list):
        out, from_changed = [], set()
        for v in o:
            nv = normalize_obj(v)
            changed = isinstance(v, str) and nv != v
            if isinstance(nv, str) and nv in out and (changed or nv in from_changed):
                continue                                   # a float/int twin of an ID already present, in either order
            out.append(nv)
            if changed:
                from_changed.add(nv)
        return out
    return norm_id(o)


def count_float_duplicates(o) -> int:
    """How many list elements are float/int duplicates of an ID already in the same list (inflated counts)."""
    if isinstance(o, dict):
        return sum(count_float_duplicates(v) for v in o.values())
    if isinstance(o, list):
        n = len(o) - len(normalize_obj(o)) if all(isinstance(v, str) for v in o) else 0
        return n + sum(count_float_duplicates(v) for v in o if isinstance(v, (dict, list)))
    return 0


def fix_text(v: str) -> str:
    """Repair one TEXT cell: a bare float-ID, or JSON containing float-IDs (parsed, normalised, re-dumped)."""
    if FLOAT_ID.match(v):
        return norm_id(v)
    if QUOTED_FLOAT_ID.search(v):
        try:
            return json.dumps(normalize_obj(json.loads(v)))
        except ValueError:
            return normalize_json_text(v)
    return v


def normalize_json_text(text: str) -> str:
    return QUOTED_FLOAT_ID.sub(r'"\1"', text)


def count_float_ids(o, examples=None, limit=5) -> int:
    n = 0
    if isinstance(o, dict):
        for v in o.values():
            n += count_float_ids(v, examples, limit)
    elif isinstance(o, list):
        for v in o:
            n += count_float_ids(v, examples, limit)
    elif isinstance(o, str) and FLOAT_ID.match(o):
        n = 1
        if examples is not None and len(examples) < limit:
            examples.append(o)
    return n


# ---------------------------------------------------------------- source
def load_source(clean_csv):
    tx = pd.read_csv(clean_csv, dtype={"transaction_id": str, "sender": str, "receiver": str},
                     usecols=["transaction_id", "sender", "receiver", "amount", "timestamp"])
    return tx


# ---------------------------------------------------------------- checks
def _load(path):
    with open(path) as f:
        return json.load(f)


def check_results(results_dir, tx: pd.DataFrame) -> dict:
    results_dir = Path(results_dir)
    ids, accts = set(tx["transaction_id"]), set(tx["sender"]) | set(tx["receiver"])
    report = {"float_ids": {}, "lineage": []}
    for name in JSON_FILES:
        p = results_dir / name
        if not p.exists():
            report["float_ids"][name] = None
            continue
        ex = []
        report["float_ids"][name] = {"count": count_float_ids(_load(p), ex), "examples": ex}
    cp, ep = results_dir / "ring_candidates.json", results_dir / "evidence.json"
    cands = _load(cp) if cp.exists() else []
    evid = {e["candidate_ring_id"]: e for e in _load(ep)} if ep.exists() else {}
    for c in cands:
        cid = c["candidate_ring_id"]
        dup = count_float_duplicates({"a": c.get("accounts", []), "t": c.get("transaction_ids", [])})
        c_tx = list(dict.fromkeys(norm_id(t) for t in c.get("transaction_ids", [])))      # unique, order kept
        c_ac = list(dict.fromkeys(norm_id(a) for a in c.get("accounts", [])))
        issue = {"candidate": cid}
        if dup: issue["inflated_by_float_duplicates"] = dup
        bad_tx = [t for t in c_tx if t not in ids]
        bad_ac = [a for a in c_ac if a not in accts]
        if bad_tx: issue["tx_not_in_source"] = bad_tx[:5]
        if bad_ac: issue["accounts_not_in_source"] = bad_ac[:5]
        e = evid.get(cid)
        if e is not None:
            e_tx = {norm_id(t["transaction_id"]) for t in e.get("transactions", [])}
            missing = [t for t in c_tx if t not in e_tx]
            if missing: issue["tx_missing_from_evidence"] = missing[:5]
            n_edges = len(e.get("evidence_subgraph", {}).get("edges", []))
            if n_edges != len(c_tx): issue["edges_vs_candidate_tx"] = [n_edges, len(c_tx)]
        if len(issue) > 1:
            report["lineage"].append(issue)
    report["n_candidates_checked"] = len(cands)
    return report


def check_db(db_path) -> dict:
    con = sqlite3.connect(str(db_path))
    out = {}
    for (tbl,) in con.execute("SELECT name FROM sqlite_master WHERE type='table'"):
        for _, col, typ, *_ in con.execute(f'PRAGMA table_info("{tbl}")').fetchall():
            if not any(t in (typ or "").upper() for t in ("CHAR", "TEXT", "CLOB")):
                continue
            n = 0
            for (v,) in con.execute(f'SELECT "{col}" FROM "{tbl}" WHERE "{col}" LIKE \'%.0%\''):
                if isinstance(v, str) and (FLOAT_ID.match(v) or QUOTED_FLOAT_ID.search(v)):
                    n += 1
            if n:
                out[f"{tbl}.{col}"] = n
    con.close()
    return out


# ---------------------------------------------------------------- fixes (opt-in)
def _backup(p: Path):
    b = p.with_name(p.name + ".bak")
    if not b.exists():
        shutil.copy2(p, b)


def fix_results(results_dir) -> dict:
    changed = {}
    for name in JSON_FILES:
        p = Path(results_dir) / name
        if not p.exists():
            continue
        data = _load(p)
        n = count_float_ids(data)
        if n:
            _backup(p)
            with open(p, "w") as f:
                json.dump(normalize_obj(data), f, indent=2)
        changed[name] = n
    return changed


def fix_db(db_path) -> dict:
    db_path = Path(db_path)
    _backup(db_path)
    con = sqlite3.connect(str(db_path))
    changed = {}
    for (tbl,) in con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall():
        for _, col, typ, *_ in con.execute(f'PRAGMA table_info("{tbl}")').fetchall():
            if not any(t in (typ or "").upper() for t in ("CHAR", "TEXT", "CLOB")):
                continue
            upd = []
            for rid, v in con.execute(f'SELECT rowid, "{col}" FROM "{tbl}" WHERE "{col}" LIKE \'%.0%\'').fetchall():
                if not isinstance(v, str):
                    continue
                nv = fix_text(v)
                if nv != v:
                    upd.append((nv, rid))
            if upd:
                con.executemany(f'UPDATE "{tbl}" SET "{col}"=? WHERE rowid=?', upd)
                changed[f"{tbl}.{col}"] = len(upd)
    con.commit(); con.close()
    return changed


def _evidence_from_source(tx_idx: pd.DataFrame, ids, extra_accounts):
    rows = tx_idx.loc[[i for i in ids if i in tx_idx.index]]
    txs = [{"transaction_id": i, "sender": r.sender, "receiver": r.receiver, "amount": float(r.amount),
            "timestamp": str(r.timestamp)} for i, r in rows.iterrows()]
    nodes = {a: {"id": a, "label": a} for a in sorted(set(rows.sender) | set(rows.receiver) | set(extra_accounts))}
    edges = [{"id": t["transaction_id"], "source": t["sender"], "target": t["receiver"],
              "amount": t["amount"], "timestamp": t["timestamp"]} for t in txs]
    return txs, {"nodes": list(nodes.values()), "edges": edges}


def rebuild_evidence(results_dir, tx: pd.DataFrame, db_path=None) -> dict:
    """Re-derive transactions + evidence subgraph for candidates whose evidence lacks transactions the
    candidate lists (the symptom of the float-ID join failure). Source of truth: transactions_clean.csv."""
    results_dir = Path(results_dir)
    cp, ep = results_dir / "ring_candidates.json", results_dir / "evidence.json"
    if not (cp.exists() and ep.exists()):
        return {}
    ids = set(tx["transaction_id"])
    tx_idx = tx.drop_duplicates("transaction_id").set_index("transaction_id")
    cands = {c["candidate_ring_id"]: c for c in _load(cp)}
    evid = _load(ep)
    fixed = {}
    for e in evid:
        c = cands.get(e["candidate_ring_id"])
        if c is None:
            continue
        want = list(dict.fromkeys(norm_id(t) for t in c["transaction_ids"]))
        have = {norm_id(t["transaction_id"]) for t in e.get("transactions", [])}
        if set(want) - have and set(want) <= ids:
            txs, sub = _evidence_from_source(tx_idx, want, [norm_id(a) for a in c["accounts"]])
            e["transactions"], e["evidence_subgraph"] = txs, sub
            e["accounts"] = sorted({n["id"] for n in sub["nodes"]})
            fixed[e["candidate_ring_id"]] = dict(edges=len(sub["edges"]), nodes=len(sub["nodes"]))
    if fixed:
        _backup(ep)
        with open(ep, "w") as f:
            json.dump(evid, f, indent=2)
        if db_path and Path(db_path).exists():
            con = sqlite3.connect(str(db_path))
            cols = {r[1] for r in con.execute('PRAGMA table_info("evidence")')}
            if {"transactions_json", "evidence_subgraph_json", "accounts_json", "candidate_ring_id"} <= cols:
                by_id = {e["candidate_ring_id"]: e for e in evid}
                for cid in fixed:
                    e = by_id[cid]
                    con.execute('UPDATE evidence SET transactions_json=?, evidence_subgraph_json=?, accounts_json=? '
                                'WHERE candidate_ring_id=?', (json.dumps(e["transactions"]),
                                json.dumps(e["evidence_subgraph"]), json.dumps(e["accounts"]), cid))
                con.commit()
            con.close()
    return fixed
