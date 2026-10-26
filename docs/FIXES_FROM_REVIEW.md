# FIXES FROM THE FORENSIC REVIEW

Every item below was found by reading the 42 screenshots of the running dashboard. Each has a test, and each test fails on the previous version of the page.

| # | What was wrong | Fix |
|---|---|---|
| 1 | **Temporal Evolution showed the wrong day** (window 395 as 2018-01-30 instead of 31 Jan 2018). The window start has no timezone; read as local time in India (UTC+5:30) it shifted every date back a day | The window start is read as UTC |
| 2 | **Risk and component bars looked identical** (30 and 100 the same length). The coloured fill had no colour, so only the dark track showed | Fill is blue, track is light grey; widths were always proportional |
| 3 | **Warning Timeline said "Not seen"** for rings the queue had seen but no alert covered | The alert column says "No alert"; the card is "No alert given" |
| 4 | **Ablations showed 0.00 false candidates/day** for the alerts, while the true rate is 0.0042 | Rates under 0.01 are shown with four decimals |
| 5 | **Alert Log and Pattern Evidence counted circular-flow alerts differently** (5 and 6): RING0160 alerted as layering and later closed into a cycle | The log says "Patterns at alert" and shows "now: ..." when they differ; the pattern table says how it groups |
| 6 | **Lead-Time said alerts arrive "with" a ring's first transactions** beside a median of -3.0 days | The sentence now says alerts come about N days after a ring starts (computed from the data) |
| 7 | **One-day score history was a lone dot** (64 of 171 candidates) | A sentence: "Scored on one day only: 62.1 on 31 Jan 2018" |
| 8 | **Overview funnel read 179 events, then 188 trajectories** | Each stage says what it counts (episodes include single first-time transfers) |
| 9 | **Pattern Analytics described detectors that do not exist** here | It lists what is found and names the original patterns this pipeline does not detect |
| 10 | Raw labels such as `circular_flow` in the explanation lists | Shown as words |

## Why the date bug was not caught before
The page tests ran in UTC, where the bug does not appear. They now run in India time (a global setup sets the zone before the test workers start), and a guard test fails if
the environment is not really in that zone. With the previous pages, 11 tests fail, including the original date test.

## Not changed on purpose
The alert threshold stays at 50 and no score or alert rule changed. The review showed that lowering it to 45 would raise coverage (24 of 30 rings seen), but choosing it after seeing
the results would be tuning on the evaluation data.
