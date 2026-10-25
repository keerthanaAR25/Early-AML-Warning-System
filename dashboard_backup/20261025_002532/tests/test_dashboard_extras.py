"""Tests for backend/api/extras.py (the endpoints that replaced numbers typed into dashboard pages). Run: pytest tests/test_dashboard_extras.py -v"""
import json
import sys
from datetime import datetime
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
_CURRENT_DB = {}

from backend.api import extras  # noqa: E402
from backend.database.models import Account, Base, GraphWindow, PatternEventRow, RingCandidateRow, Transaction  # noqa: E402
from backend.database.session import get_db  # noqa: E402


@pytest.fixture()
def client(tmp_path, monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    t0 = datetime(2017, 1, 1)
    db.add_all([Account(account_id=a, is_ring_member=False, dataset_source="amlsim") for a in "ABCD"])
    db.add_all([
        Transaction(transaction_id="1", sender="A", receiver="B", amount=1.0, timestamp=t0, label=0, dataset_source="amlsim"),
        Transaction(transaction_id="2", sender="B", receiver="C", amount=2.0, timestamp=t0, label=1, dataset_source="amlsim"),
        Transaction(transaction_id="3", sender="A", receiver="C", amount=3.0, timestamp=t0, label=1, dataset_source="amlsim"),
    ])
    db.add_all([GraphWindow(window_id=0, window_start=t0, window_end=datetime(2017, 1, 2)),
                GraphWindow(window_id=1, window_start=datetime(2017, 1, 2), window_end=datetime(2017, 1, 3))])
    db.add_all([PatternEventRow(pattern_type="fan_in", window_id=0), PatternEventRow(pattern_type="fan_in", window_id=1),
                PatternEventRow(pattern_type="layering", window_id=1)])
    db.add(RingCandidateRow(candidate_ring_id="RING001"))
    db.commit()
    (tmp_path / "results").mkdir()
    monkeypatch.setattr(extras, "ROOT", tmp_path)
    app = FastAPI()
    app.include_router(extras.router, prefix="/api")
    app.dependency_overrides[get_db] = lambda: db
    _CURRENT_DB["fn"] = lambda: db
    yield TestClient(app), tmp_path / "results"
    db.close()


def test_pipeline_stats_are_counted_from_the_database_not_typed(client):
    c, results = client
    (results / "trajectories.json").write_text(json.dumps([{}, {}, {}, {}]))
    r = c.get("/api/pipeline-stats").json()
    assert r["n_transactions"] == 3 and r["n_accounts_total"] == 4 and r["n_accounts_with_transactions"] == 3
    assert r["n_graph_windows"] == 2 and r["n_pattern_events"] == 3 and r["n_candidates"] == 1
    assert r["n_alert_transactions"] == 2 and r["dataset_source"] == "amlsim"
    assert r["window_days"] == 1.0 and r["first_window_start"].startswith("2017-01-01") and r["last_window_end"].startswith("2017-01-03")
    assert r["n_trajectories"] == 4


def test_missing_trajectory_file_gives_null_not_a_number(client):
    c, _ = client
    assert c.get("/api/pipeline-stats").json()["n_trajectories"] is None


def test_evaluation_context_comes_from_model_comparison_json(client):
    c, results = client
    assert c.get("/api/evaluation-context").json()["n_test"] is None                 # no file -> nulls
    (results / "model_comparison.json").write_text(json.dumps(
        {"proposed_gradient_boosting": {"test": {"n_samples": 1000, "n_positive": 5, "n_negative": 995, "threshold": 0.8}}}))
    r = c.get("/api/evaluation-context").json()
    assert r["n_test"] == 1000 and r["n_positive"] == 5 and r["positive_rate"] == pytest.approx(0.005)


def test_ring_early_warning_reports_unavailable_then_serves_files_and_survives_corruption(client):
    c, results = client
    assert c.get("/api/ring-early-warning").json()["available"] is False
    (results / "ring_lead_time_summary.json").write_text(json.dumps({"parameters": {"headline_model": "m"}}))
    (results / "candidate_quality_v2.json").write_text("{ this is not json")
    r = c.get("/api/ring-early-warning").json()
    assert r["available"] is True and r["ring_lead_time"]["parameters"]["headline_model"] == "m"
    assert r["candidate_quality"] is None and r["account_window"] is None            # corrupt/missing -> null, no crash


def test_the_real_app_serves_the_extra_routes(client):
    """Call the three endpoints on the real application (only the database is swapped), not a private test app."""
    from backend.main import app as real_app
    _, results = client
    real_app.dependency_overrides[get_db] = _CURRENT_DB["fn"]
    try:
        c = TestClient(real_app)
        for path in ("/api/pipeline-stats", "/api/evaluation-context", "/api/ring-early-warning"):
            assert c.get(path).status_code == 200, path
        assert c.get("/api/pipeline-stats").json()["n_transactions"] == 3
    finally:
        real_app.dependency_overrides.pop(get_db, None)
