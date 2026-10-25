#!/usr/bin/env python3
"""
OPT-IN fix for the root cause of float-formatted IDs ("49066.0"): pd.read_csv infers numeric-looking IDs as integers, and a later
merge upcasts them to floats. This adds a string dtype to single-line pd.read_csv calls that read the transactions / feature /
pattern-event files. DRY RUN by default; --apply writes <file>.bak first. Multi-line calls are reported, never edited.

  python scripts/patch_id_dtypes.py            # show what would change
  python scripts/patch_id_dtypes.py --apply
"""
import argparse
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TX = '{"transaction_id": str, "sender": str, "receiver": str, "scenario_id": str, "ring_id": str}'
RULES = [  # (substrings that identify the file being read, dtype to add)
    (("transactions_clean", "clean_path"), TX),
    (("features.csv", "features_path", "PARTIAL_PATH"), '{"account_id": str}'),
    (("pattern_events.csv",), '{"central_account": str}'),
]


def matching_paren(s: str, open_idx: int):
    depth = 0
    for i in range(open_idx, len(s)):
        depth += (s[i] == "(") - (s[i] == ")")
        if depth == 0:
            return i
    return None


def patch_line(line: str):
    i = line.find("pd.read_csv(")
    if i < 0 or "dtype" in line:
        return None, None
    for keys, dtype in RULES:
        if any(k in line for k in keys):
            j = matching_paren(line, i + len("pd.read_csv"))
            if j is None:
                return None, "multi-line call (edit by hand)"
            return line[:j] + f", dtype={dtype}" + line[j:], None
    return None, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dirs", nargs="*", default=["scripts"])
    a = ap.parse_args()
    n = 0
    for d in a.dirs:
        for p in sorted((ROOT / d).glob("*.py")):
            if p.name == Path(__file__).name:
                continue
            src = p.read_text().splitlines(keepends=True)
            new, changed = [], False
            for ln, line in enumerate(src, 1):
                nl, why = patch_line(line)
                if why:
                    print(f"SKIP {p.relative_to(ROOT)}:{ln}  {why}")
                if nl is not None:
                    changed = True; n += 1
                    print(f"{p.relative_to(ROOT)}:{ln}\n  - {line.strip()[:150]}\n  + {nl.strip()[:150]}")
                new.append(nl if nl is not None else line)
            if changed and a.apply:
                shutil.copy2(p, p.with_name(p.name + ".bak"))
                p.write_text("".join(new))
    print(f"\n{n} line(s) {'patched' if a.apply else 'would be patched (dry run; use --apply)'}.")
    if a.apply and n:
        print("Backups written as <file>.bak. Re-run the affected pipeline stages, then scripts/check_lineage.py.")
    sys.exit(0)


if __name__ == "__main__":
    main()
