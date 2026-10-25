# PATTERN INVESTIGATION: why most rings show one pattern, and what changed

## The question
Almost every candidate shows one pattern and carries the highest scores. Only a few show two or three, and those are ranked MODERATE.
Is that a change from the old results, where the warning was built on several patterns?

## Short answer
1. **Yes, it is a change.** Every one of the 142 old candidates had 2 to 4 patterns, because the old pipeline needed several patterns to form a candidate at all.
   In the rebuilt pipeline 165 of 171 candidates have one pattern. An alert is now normally given on a single pattern: 12 of the 14 alerts.
2. **Pattern count never drove the score, in either pipeline.** Spearman correlation between number of patterns and score: old 0.007 (p = 0.94), new 0.009 (p = 0.90).
   What drives the score is *which* pattern and how unusual the accounts look, not how many patterns there are.
3. **A ring in AMLSim is one pattern.** Each of the 100 rings is a single cycle, fan-in or fan-out, and no account is in two rings. Requiring several patterns hides the real rings:
   the old candidates held only 17 ring transactions out of 2,295 evidence transactions (0.7%) and found none of the 30 evaluable rings.
4. **The six multi-pattern candidates are a lead, not a result.** All six contain ring transactions, but they are also the largest candidates, so pattern count and size cannot be separated with six cases.

## Old and new, side by side (candidates grouped by number of patterns)

| | Candidates | Mean score | HIGH | Contain ring transactions |
|---|---|---|---|---|
| **Old, 2 patterns** | 49 | 51.8 | 31 | 0 |
| **Old, 3 patterns** | 87 | 52.2 | 55 | 15 |
| **Old, 4 patterns** | 6 | 52.1 | 3 | 1 |
| **New, 1 pattern** | 165 | 41.5 | 10 | 41 (25%) |
| **New, 2 patterns** | 5 | 40.5 | 0 | 5 |
| **New, 3 patterns** | 1 | 43.8 | 0 | 1 |

The old table shows what the scoring did: the same mean score (about 52) whether a candidate had 2, 3 or 4 patterns. Old scores were high everywhere and told you little: 89 of 142 were HIGH, 16 contained a ring transaction.

## Why a single pattern can score higher than several

Mean score components by pattern type (new pipeline; the component weights are behavioural 35%, network 20%, fund flow 25%, persistence 20%):

| Patterns | Candidates | Mean score | Behavioural | Network | Fund flow | Persistence | Alerts |
|---|---|---|---|---|---|---|---|
| circular flow | 14 | 50.9 | 38.8 | 100 | 30 | 49.2 | 8 |
| layering | 16 | 46.1 | 49.0 | 76.9 | 20 | 42.8 | 3 |
| fan-in | 6 | 42.8 | 46.0 | 80.0 | 10 | 41.0 | 0 |
| fan-out | 129 | 39.9 | 36.2 | 81.9 | 10 | 41.6 | 1 |
| fan-out + layering | 3 | 41.1 | 12.0 | 100 | 30 | 47.2 | 1 |
| fan-in + fan-out | 2 | 39.6 | 15.5 | 100 | 20 | 45.7 | 0 |
| fan-in + fan-out + layering | 1 | 43.8 | 12.9 | 100 | 40 | 46.3 | 1 |

* A further pattern does add to the score, through the fund-flow component: **+7.5 points for circular flow, +5.0 for layering, +2.5 for a fan**.
* The behavioural component differs much more between candidates. The multi-pattern candidates score 8 to 20 on it, against 36 to 49 for the single-pattern types: a spread worth about **13 score points**, more than any extra pattern adds.
* A closed cycle gets the full network score (100) *and* the highest pattern weight, so one circular flow outranks two fans.

## The two multi-pattern alerts that looked like MODERATE

RING0050 (alert 2017-11-19) and RING0136 (alert 2018-07-30) both raised an alert, yet the queue showed them as MODERATE. Scores are recomputed each day a candidate gains evidence,
and these two later fell below 50. An alert is the first day the score reached the threshold, so it stays on record. The queue used to show only the current score, which contradicted the alert.
It now shows the alert (date and score at alert) beside the current score, and the Alert Log marks alerts whose score has since fallen.

## What this does and does not show

* It does not show that several patterns are useless. It shows that on AMLSim, whose rings are single-type, one strong pattern is the expected shape of a ring.
* All six multi-pattern candidates contain ring transactions (Fisher exact p = 0.0003 against all single-pattern candidates), but the candidates with several patterns are the largest (6 to 27 evidence
  transactions), and larger candidates contain ring transactions more often whatever their patterns (16% at 2-3 transactions, 32% at 4-6, 38% at 7-10 for single-pattern ones).
  Only one single-pattern candidate is as large, so a same-size comparison cannot be made.
* Adding the old detectors' events as extra independent patterns did not help (`python scripts/test_pattern_combination.py`).
* No rule was changed because of this: the six candidates were noticed after the results, so using them to tune the alert rule would be fitting to the data.
  A fair test needs a pre-declared rule and more rings, for example a simulator whose rings combine typologies.
