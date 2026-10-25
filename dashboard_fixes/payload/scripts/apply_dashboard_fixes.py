#!/usr/bin/env python3
"""
Apply the dashboard fixes safely.  DRY RUN by default: nothing is written until you pass --apply.

For every file in dashboard_fixes/payload it checks your current copy against the version that was reviewed
(dashboard_fixes/manifest.json, SHA-256 with line endings normalised; a file may list several known previous versions) and reports:
  NEW              target does not exist yet                        -> will be created
  UPDATE           target is exactly the reviewed original          -> will be replaced (after a backup)
  ALREADY APPLIED  target already equals the fixed version          -> skipped
  CHANGED          you edited it since it was reviewed              -> skipped unless --force (then backed up and replaced)

Backups go to dashboard_backup/<timestamp>/<same relative path>.

  python scripts/apply_dashboard_fixes.py                 # dry run
  python scripts/apply_dashboard_fixes.py --apply
  python scripts/apply_dashboard_fixes.py --apply --force # also replace files you changed yourself (backed up first)
"""
import argparse
import hashlib
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "dashboard_fixes"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def classify(rel: str, meta: dict) -> str:
    target = ROOT / rel
    if not target.exists():
        return "NEW"
    h = sha(target)
    if h == meta["new_sha256"]:
        return "ALREADY APPLIED"
    origs = meta["original_sha256"] if isinstance(meta["original_sha256"], list) else [meta["original_sha256"]]
    if h in [o for o in origs if o]:
        return "UPDATE"
    return "CHANGED"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="write the changes (default is a dry run)")
    ap.add_argument("--force", action="store_true", help="also replace files that differ from the reviewed original (backed up first)")
    a = ap.parse_args()
    if not (FIX / "manifest.json").exists():
        sys.exit("dashboard_fixes/manifest.json not found -- run this from the project root after extracting the zip")
    manifest = json.load(open(FIX / "manifest.json"))
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_root = ROOT / "dashboard_backup" / stamp
    counts = {}
    print(f"{'status':16s} file")
    for rel, meta in sorted(manifest.items()):
        status = classify(rel, meta)
        counts[status] = counts.get(status, 0) + 1
        action = ""
        if a.apply and (status in ("NEW", "UPDATE") or (status == "CHANGED" and a.force)):
            target = ROOT / rel
            if target.exists():
                (backup_root / rel).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(target, backup_root / rel)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(FIX / "payload" / rel, target)
            action = "  -> written" + (" (old copy backed up)" if (backup_root / rel).exists() else "")
        elif status == "CHANGED":
            action = "  -> SKIPPED: differs from the reviewed version (use --force to replace; a backup is made)"
        print(f"{status:16s} {rel}{action}")
    print("\n" + ", ".join(f"{v} {k}" for k, v in sorted(counts.items())))
    if not a.apply:
        print("Dry run only. Re-run with --apply to write the changes.")
    else:
        print(f"Backups (if any): {backup_root}")
        print("Next: cd frontend && npm run build   then restart the API (uvicorn) and the frontend (npm run dev).")


if __name__ == "__main__":
    main()
