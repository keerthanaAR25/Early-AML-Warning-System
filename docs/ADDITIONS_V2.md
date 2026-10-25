# ADDITIONS V2 -- candidate quality, second candidate source, ID repair

Everything here is a **new file**. Your pipeline, scores, models, database schema and dashboard are untouched, and nothing is
rebuilt from scratch. `Additions_complete.zip` contains 11 files (it supersedes `Additions.zip`; extracting over it is harmless).

| File | Purpose |
|---|---|
| `src/evaluation/candidates_v2.py` | Second candidate source (unordered cycles, partial paths, novelty-seeded groups) + candidate-quality metrics |
| `scripts/run_candidates_v2.py` | Compares your v1 candidates with v2 on identical metrics; writes a report |
| `scripts/patch_id_dtypes.py` | Opt-in fix for the ROOT CAUSE of float IDs (dry run by default) |
| `src/evaluation/lineage_tools.py`, `scripts/check_lineage.py` | Detect/repair float IDs **and the duplicate IDs they create** |
| `src/evaluation/ring_lead_time.py`, `scripts/run_ring_lead_time.py` | Ring-level lead time with controls |
| `tests/test_additions.py`, `tests/test_candidates_v2.py` | 11 + 17 tests |

## Commands (PowerShell, project root)

```powershell
Expand-Archive Additions_complete.zip -DestinationPath . -Force
python -m pytest tests/test_additions.py tests/test_candidates_v2.py -q      # expect 28 passed

# 1. Repair lineage (makes .bak copies; repairs results/*.json and data/aml.db if present). Restart the API afterwards.
python scripts/check_lineage.py                                # report only
python scripts/check_lineage.py --fix --rebuild-evidence
python scripts/patch_id_dtypes.py                              # dry run: shows the read_csv lines that cause it
python scripts/patch_id_dtypes.py --apply                      # optional; re-running detectors then stays clean

# 2. New evidence (about 20 s and 30 s)
python scripts/run_ring_lead_time.py        # reports\ring_lead_time_report.html
python scripts/run_candidates_v2.py         # reports\candidate_quality_report.html
```

Optional, only if you want the stored risk scores refreshed after the repair (these are existing scripts, not a full rebuild):
`python scripts/compute_risk_scores.py` then `python scripts/build_evidence.py`.

## What the review found, and the repair

* 91 of 142 candidates had broken lineage (758 float IDs in pattern events, 373 in candidates). Evidence graphs were missing
  1-3 transactions each.
* **The float IDs also inflated counts.** RING056 listed account 14 twice (`14` and `14.0`), so its "7 linked accounts" was really 6.
  61 of 142 candidates had such duplicates. The repair removes only duplicates created by normalisation; a genuine repeat such
  as a pass-through chain A,B,A is kept.
* After `--fix --rebuild-evidence` on a copy of your project: lineage issues 91 -> 0; RING056 = 6 accounts, 7 transactions,
  6 evidence nodes, 7 edges.
* The stored risk scores of the 61 affected candidates used the inflated account counts (events per account). Recompute them
  (optional step above) before quoting individual scores.
* Root cause: single-line `pd.read_csv` calls in `detect_patterns.py` (lines 33, 39), `extract_features.py` (30),
  `detect_patterns_chunked.py` (115) and `extract_features_chunked.py` (129) read IDs without a string dtype.

## Candidate quality, your data (burn-in 120 days; candidates created on or after day 120)

| Candidate set | Candidates | Ring-tx share of evidence | Enrichment vs background | False candidates/day | Ring-tx recall |
|---|---|---|---|---|---|
| v1 pattern-trajectory (yours) | 95 | 0.35% | 1.2x | 0.15 | 1.1% |
| v2 structure only (unordered cycles, whole-SCC test) | 25 | 89.6% | 305x | 0.01 | 31.5% |
| v2 novelty, first-ever sender only | 95 | 100% | 340x | 0.00 | 61.1% |
| v2 novelty, sender or receiver, >=1 seed | 512 | 18.9% (108 of 512 candidates contain a ring tx) | 64x | 0.67 | 86.0% |
| v2 novelty, sender or receiver, >=2 seeds | 365 | 19.4% | 66x | 0.46 | 81.9% |

Ring-level (N = 39 rings that start after the burn-in and complete inside the data: 36 cycle, 3 fan-out, 0 fan-in):

| Candidate set | Rings with a transaction in a candidate | Warned before observable | Median lead (days) |
|---|---|---|---|
| v1 | 0 / 39 | 0 | none |
| v2 structure | 21 / 39 (all cycles) | 7 | 0 (95% CI 0-1); fires at cycle closure |
| v2 novelty sender-only | 36 / 39 | 36 | 9.5 (95% CI 6.5-12) |
| v2 novelty either-side, >=1 seed | 39 / 39 | 39 | 12 (cycles); fan-out 158 (N=3, no CI) |

## CORRECTION (if you ran an earlier copy of `candidates_v2.py`)

An earlier build of the structure detector had two bugs, found by reading its own output rather than trusting the report:

1. **Blob merging.** A new structure was merged into any earlier candidate sharing an account, forever. One candidate created on
   day 2 ended up holding 40,999 transactions over 1,370 accounts and absorbed later rings, which were then dropped from the
   post-burn-in evaluation. Merging is now limited to candidates that are still active, younger than 2 windows and under 40 accounts.
2. **Background cycles.** It accepted any small cycle through the new edge, which finds thousands in a dense graph (the blob had hidden
   this). It now accepts a cycle only if the *whole strongly connected component* is 4-12 nodes and nearly a simple cycle.

The earlier "v2 structure: 7 candidates, 100%, lead 4 days" row was an artifact of these bugs. **Re-extract the zip (`-Force`) and re-run
`python scripts/run_candidates_v2.py` (about 70 s).** The novelty rows are unaffected.

## How to read this

1. Your v1 candidates are essentially background (1.2x enrichment after warm-up, none of the evaluable rings present). Threshold or
   matching changes cannot fix that; the detectors behind v1 find motifs normal AMLSim traffic also produces.
2. **The v2 gains are real arithmetic but simulator-specific.** The novelty sets use AMLSim's dormant-account construction (ring
   members are accounts with no prior activity). The 100% precision of the sender-only set is that shortcut in its purest form.
   The structure-only set is label-free graph structure and the more defensible comparison with v1: 89.6% of its evidence is ring
   transactions (305x background) at 0.01 false candidates per day, and it recovers 21 of 36 cycle rings. **But it fires when the cycle
   closes, so its median lead is 0 days** (7 rings are warned slightly earlier through partial paths). Real early warning in this table
   comes only from the novelty signal. Its precision also benefits from ring members being isolated accounts.
3. A real bank onboards new accounts constantly, so novelty-seeded candidates would produce many more false candidates there.
4. N is small: only 3 fan-out and 0 fan-in rings are evaluable without truncation, so fan lead times are not reliable
   (the 158-day figure rests on 3 rings). Cycle results rest on N=36.
5. v1's warning day is approximated as the window of its second structural event (the engine's own minimum). v1 has no ring
   transactions in these rings, so the result does not depend on that choice.

Suggested thesis wording: *"The pattern-trajectory candidates were no more enriched for laundering transactions than background
(1.2x). Unordered-cycle structure candidates were 89.6% ring transactions and recovered 21 of 36 cycle rings at closure. Candidates
seeded from account-history novelty covered 86% of ring transactions and warned a median 12 days before cycle closure, but this reflects AMLSim's dormant-account construction and is not evidence of general
early-warning capability."*

## Exported candidates

`results/ring_candidates_v2.json` has exactly the fields of your `RingCandidate` (a test builds your class from it);
extras (source, creation day, signal type) are in `results/ring_candidates_v2_meta.json`. Existing scripts read
`results/ring_candidates.json`, so nothing consumes v2 until you choose to copy it over. Back up the original first.
