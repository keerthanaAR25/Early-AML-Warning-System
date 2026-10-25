#!/usr/bin/env python3
"""
Check (and optionally repair) float-formatted IDs and evidence lineage. Read-only unless --fix is given.
Never re-runs the pipeline. Backups are written as <file>.bak before any change.

  python scripts/check_lineage.py                      # report only
  python scripts/check_lineage.py --fix --rebuild-evidence
"""
import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.evaluation import lineage_tools as L  # noqa: E402


def default_db():
    url = os.environ.get("DATABASE_URL", "")
    if url.startswith("sqlite:///"):
        p = Path(url.replace("sqlite:///", "", 1))
        return p if p.is_absolute() else ROOT / p
    return ROOT / "data" / "aml.db"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--clean", default=str(ROOT / "data/processed/transactions_clean.csv"))
    ap.add_argument("--results-dir", default=str(ROOT / "results"))
    ap.add_argument("--db", default=str(default_db()))
    ap.add_argument("--fix", action="store_true", help="normalise '123.0' -> '123' (makes .bak backups)")
    ap.add_argument("--rebuild-evidence", action="store_true",
                    help="re-derive evidence transactions/subgraph from the source where they are incomplete")
    a = ap.parse_args()

    tx = L.load_source(a.clean)
    print(f"source: {len(tx):,} transactions")
    rep = L.check_results(a.results_dir, tx)
    print("\nFloat-formatted IDs in results/*.json:")
    for k, v in rep["float_ids"].items():
        print(f"  {k:28s}", "missing file" if v is None else f"{v['count']} {v['examples'][:3]}")
    db_exists = Path(a.db).exists()
    if db_exists:
        d = L.check_db(a.db)
        print(f"\nFloat-formatted IDs in DB ({a.db}):", d if d else "none")
    print(f"\nLineage issues over {rep['n_candidates_checked']} candidates: {len(rep['lineage'])}")
    for i in rep["lineage"][:10]:
        print("  ", i)

    if a.fix:
        print("\nFixing JSON files:", L.fix_results(a.results_dir))
        if db_exists:
            print("Fixing DB       :", L.fix_db(a.db))
        if a.rebuild_evidence:
            print("Rebuilt evidence:", L.rebuild_evidence(a.results_dir, tx, a.db if db_exists else None))
        rep = L.check_results(a.results_dir, tx)
        print(f"\nAfter fix -> lineage issues: {len(rep['lineage'])}",
              "(restart the API so it re-reads the database)" if db_exists else "")
    sys.exit(1 if rep["lineage"] and not a.fix else 0)


if __name__ == "__main__":
    main()
