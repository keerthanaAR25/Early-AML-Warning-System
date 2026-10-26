# NEW PAGES AND WARNING CARDS

Everything comes from two files written by `python scripts/rebuild_v2.py export`: `results/warnings.json` and `results/pattern_evidence.json`,
served by `/api/warnings` and `/api/pattern-evidence`. They are built from the same candidates and scores as the rest of the dashboard, and tests check that they agree
with the Lead-Time page (alerts given, rings evaluable, rings seen, rings warned before completion, per-ring lead).

| Page | What it answers |
|---|---|
| **Warning Timeline** | Where the early warning and the alert were given on every ring. Rings are aligned at the day they are complete; a blue dot is the first day a candidate holding the ring existed, an orange triangle the day such a candidate reached the alert threshold. Cards: rings seen, warned before / at / after completion, not seen, median leads, coverage, ring lifetime; a table of every evaluable ring with a status filter; why the other rings cannot be evaluated. |
| **Alert Log** | Every alert given: date, candidate, score at alert and now, patterns, accounts, evidence at the time, days after creation, and (evaluation only) the ring it holds and the lead. A weekly chart of alerts against ring completions. Filter by outcome. |
| **Pattern Evidence** | The pattern investigation (see PATTERN_INVESTIGATION.md): candidates by number and kind of pattern, what makes up the score, what each pattern adds, pattern count against evidence size, and every multi-pattern candidate. |

Also changed: **Ring Investigation** has a "Warning given" card with the alert date, the score history against the threshold, and (evaluation only) the ring and the lead;
**Alert Queue** has an "Alerts given" card and an Alert column; **Overview** has four warning cards. The Investigate buttons now open the candidate you clicked
(they used to open the top-ranked one whatever you clicked).

Ring fields (id, type, first transaction, completion, lead, coverage) are AMLSim ground truth and are used only to evaluate; they never enter a candidate or a score.


## Score calculation card (Temporal Evolution)

For the selected candidate it shows how the 0-100 risk score was worked out: each of the four components with the way its value came from **this candidate's own evidence**
(for example "35 x ln(1 + 3 x 7 evidence transactions / 7 accounts) = 48.5"), its weight, the points it adds, and the total, which is exactly the score. It states whether the score
is at or above the alert threshold, and if an alert was given earlier and the score has since fallen it says so. Below that, the same calculation is shown for every day the candidate
gained evidence (with the day of the alert highlighted), so you can see the score move as evidence accumulates.

The calculation is written by the scoring code itself (`results/score_calculation.json`) from its own constants and the inputs it recorded, and tests recompute the persistence and fund-flow
values independently for all 171 candidates. The behavioural value comes from a model trained only on earlier data, so its inputs are not shown. It needs `python scripts/rebuild_v2.py scoring`
once (about a minute) so the scorer records its inputs; the export tells you if you forget.


## Patterns visible

* **Alert Queue** lists **every candidate** (171), not the top 100, so no candidate is hidden. Filters: by pattern, "2 or more patterns", "Alert given". Under a candidate's own patterns
  it shows, in grey, **"Also seen on these accounts"**: other patterns the original detectors saw on the candidate's accounts (marked "not in the score").
* **Ring Investigation** has an **"Other patterns seen on these accounts"** panel: for the selected candidate, each other pattern with its events, accounts involved, first and last seen,
  and whether the candidate's own detector also found it. The window is 7 days before the candidate's first evidence to its latest evidence.
* **Pattern Evidence** has a section measuring whether these patterns separate rings from normal traffic.

These context patterns come from the original detectors' events (kept in `results/v1_backup/pattern_events.json`). They are never used to build a candidate or a score (a test checks the
scoring code does not read them). On this data they show up on 170 of 171 candidates, but candidates that contain ring transactions show **fewer** of them than the others
(2.1 types against 2.6 on average), and a ring transaction's sender shows one less often than a normal transaction's (43% against 56%). So they make several patterns visible, but they are
context and not evidence of a ring, and the panel says so with those numbers.

## The alert on every candidate page

The Alert Queue's **"Alert 31 Jan 2018 / score 62.1 at alert"** (or "No alert") is now shown on the pages that focus on one candidate: **Ring Investigation** and **Why Flagged**
(under the risk score), and **Temporal Evolution** (in the summary). In all three candidate pickers, a candidate that raised an alert has an orange mark (hover for the date and score); in
Temporal Evolution's drop-down the alert date is written beside the candidate. Nothing is shown until the warnings have loaded, so a page never says "No alert" by mistake. A test checks the badge
says exactly what the Alert Queue says for the same candidate.
