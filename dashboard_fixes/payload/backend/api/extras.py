"""
Extra read-only endpoints (ADDITIVE). They replace numbers that were typed into the dashboard pages as literals
(Overview "Detection Pipeline", Model Performance "evaluation context", Alert Queue "of 142") and serve the new
ring-level evaluation results. Every value is counted from the database or read from a results file; when something is
missing the field is null and the page shows an em dash -- never a made-up number.
"""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, Depends
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from backend.database.models import Account, GraphWindow, PatternEventRow, RingCandidateRow, Transaction
from backend.database.session import get_db

ROOT = Path(__file__).resolve().parents[2]
router = APIRouter()


def _read_json(name: str):
    p = ROOT / "results" / name
    try:
        with open(p) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


@router.get("/pipeline-stats")
def pipeline_stats(db: Session = Depends(get_db)):
    trajectories = _read_json("trajectories.json")
    active = db.execute(text(
        "SELECT COUNT(*) FROM (SELECT sender AS a FROM transactions UNION SELECT receiver FROM transactions)")).scalar()
    first = db.query(GraphWindow).order_by(GraphWindow.window_id.asc()).first()
    last = db.query(GraphWindow).order_by(GraphWindow.window_id.desc()).first()
    window_days = None
    if first is not None and first.window_start is not None and first.window_end is not None:
        window_days = (first.window_end - first.window_start).total_seconds() / 86400.0
    return {
        "window_days": window_days,
        "first_window_start": first.window_start.isoformat() if first is not None and first.window_start else None,
        "last_window_end": last.window_end.isoformat() if last is not None and last.window_end else None,
        "n_transactions": db.query(func.count(Transaction.transaction_id)).scalar(),
        "n_alert_transactions": db.query(func.count(Transaction.transaction_id)).filter(Transaction.label == 1).scalar(),
        "dataset_source": (db.query(Transaction.dataset_source).filter(Transaction.dataset_source.isnot(None)).limit(1).scalar()
                           or db.query(Account.dataset_source).filter(Account.dataset_source.isnot(None)).limit(1).scalar()),
        "n_accounts_total": db.query(func.count(Account.account_id)).scalar(),
        "n_accounts_with_transactions": active,
        "n_graph_windows": db.query(func.count(GraphWindow.window_id)).scalar(),
        "n_pattern_events": db.query(func.count(PatternEventRow.id)).scalar()
        if hasattr(PatternEventRow, "id") else db.query(PatternEventRow).count(),
        "n_trajectories": len(trajectories) if isinstance(trajectories, list) else None,
        "n_candidates": db.query(func.count(RingCandidateRow.candidate_ring_id)).scalar(),
    }


@router.get("/evaluation-context")
def evaluation_context():
    """Test-set size / positives of the account-window evaluation, taken from results/model_comparison.json."""
    mc = _read_json("model_comparison.json")
    test = ((mc or {}).get("proposed_gradient_boosting") or {}).get("test") or {}
    n, p = test.get("n_samples"), test.get("n_positive")
    return {"n_test": n, "n_positive": p, "n_negative": test.get("n_negative"),
            "positive_rate": (p / n) if n and p is not None else None, "threshold": test.get("threshold"),
            "protocol": _read_json("protocol.json")}


@router.get("/warnings")
def warnings_log():
    """Every alert that was given and where it falls on each ground-truth ring (results/warnings.json, written by scripts/rebuild_v2.py)."""
    w = _read_json("warnings.json")
    return w if w is not None else {"available": False}


@router.get("/score-calculation/{ring_id}")
def score_calculation(ring_id: str):
    """How one candidate's risk score was calculated (results/score_calculation.json, written by scripts/rebuild_v2.py)."""
    data = _read_json("score_calculation.json")
    entry = data.get(ring_id) if isinstance(data, dict) else None
    return entry if entry is not None else {"available": False}


@router.get("/supporting-patterns")
def supporting_patterns_endpoint():
    """Other patterns the original detectors saw on each candidate's accounts, for context only (results/supporting_patterns.json)."""
    p = _read_json("supporting_patterns.json")
    return p if p is not None else {"available": False}


@router.get("/pattern-evidence")
def pattern_evidence_endpoint():
    """How the number and kind of patterns relate to the risk score and the alerts (results/pattern_evidence.json)."""
    p = _read_json("pattern_evidence.json")
    return p if p is not None else {"available": False}


@router.get("/ring-early-warning")
def ring_early_warning():
    """Research comparisons shown on the Ablations and Controls page. The production result is /api/lead-time.
    All three files share one protocol (scored period from day 240, 120-day burn-in), so they cannot disagree with the production result."""
    out = {
        "production_evaluation": _read_json("production_evaluation.json"),     # candidate-source ablation, same rings as the production result
        "ring_lead_time": _read_json("ring_lead_time_summary.json"),           # controls: newness rule, same-day-only model, random
        "account_window": _read_json("account_window_eval_v2.json"),           # sensitivity to the forecast horizon
    }
    out["available"] = any(v is not None for v in out.values())
    return out
