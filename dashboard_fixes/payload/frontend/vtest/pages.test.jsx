import { describe, it, expect } from "vitest";
import fx from "./fixtures/api.json";
import Overview from "../src/pages/Overview.jsx";
import AlertQueue from "../src/pages/AlertQueue.jsx";
import RingInvestigation from "../src/pages/RingInvestigation.jsx";
import TemporalEvolution from "../src/pages/TemporalEvolution.jsx";
import PatternAnalytics from "../src/pages/PatternAnalytics.jsx";
import LeadTimeAnalytics from "../src/pages/LeadTimeAnalytics.jsx";
import ModelPerformance from "../src/pages/ModelPerformance.jsx";
import RingEarlyWarning from "../src/pages/RingEarlyWarning.jsx";
import DataExplorer from "../src/pages/DataExplorer.jsx";
import WarningTimeline from "../src/pages/WarningTimeline.jsx";
import AlertLog from "../src/pages/AlertLog.jsx";
import PatternEvidence from "../src/pages/PatternEvidence.jsx";
import { fireEvent } from "@testing-library/react";
import { dateOf } from "../src/components/warnings.jsx";
import { renderPage, text } from "./helpers.jsx";

// Every expected value below is READ FROM THE FIXTURES (real API responses of the rebuilt pipeline); none is typed in.
const S = fx["/api/summary"], P = fx["/api/pipeline-stats"], LT = fx["/api/lead-time"], CTX = fx["/api/evaluation-context"], RID = fx.__rid__;
const inr = (n) => Number(n).toLocaleString("en-IN");
const NO_LT = { "/api/lead-time": {} };

describe("Overview", () => {
  it("shows the API's counts and the pipeline funnel", async () => {
    const t = text(await renderPage(Overview, { until: "Detection Pipeline" }));
    for (const v of [inr(S.total_transactions), inr(S.total_accounts), inr(S.candidate_rings), inr(P.n_graph_windows), inr(P.n_pattern_events), inr(P.n_trajectories), Number(S.average_risk_score).toFixed(2)]) expect(t).toContain(v);
  });
  it("shows an em dash, never a remembered number, when the API sends nothing", async () => {
    const t = text(await renderPage(Overview, { override: { "/api/summary": {}, "/api/pipeline-stats": "error", ...NO_LT }, until: "Detection Pipeline" }));
    for (const v of [inr(S.total_transactions), inr(P.n_pattern_events), inr(P.n_trajectories), "NaN"]) expect(t).not.toContain(v);
    expect(t).toContain("\u2014");
  });
  it("describes the production candidates from the evaluation, and shows nothing without it", async () => {
    const t = text(await renderPage(Overview, { until: "candidates were built from the scored period" }));
    for (const v of [String(LT.all_candidates.n_candidates), String(LT.alerted_candidates.n_alerted), `${LT.all_candidates.rings_seen} of ${LT.rings.n_evaluable}`, "AMLSim-specific"]) expect(t).toContain(v);
    const t2 = text(await renderPage(Overview, { override: NO_LT, until: "Detection Pipeline" }));
    expect(t2).not.toContain("candidates were built from the scored period");
  });
});

describe("Alert Queue", () => {
  it("takes the total from the API and explains the candidates", async () => {
    const t = text(await renderPage(AlertQueue, { until: "candidates shown" }));
    expect(t).toContain(`of ${S.candidate_rings}`); expect(t).toContain("candidates were built from the scored period");
  });
  it("shows an em dash if the total is unknown", async () => {
    const t = text(await renderPage(AlertQueue, { override: { "/api/summary": {}, ...NO_LT }, until: "candidates shown" }));
    expect(t).toContain("of \u2014");
  });
});

describe("Ring Investigation (top-ranked candidate)", () => {
  const comp = fx[`/api/rings/${RID}/explanation`].score_components;
  it("shows the four score components", async () => {
    const t = text(await renderPage(RingInvestigation, { until: "Accounts in evidence graph" }));
    for (const k of ["behavioural", "network", "fund_flow", "persistence"]) expect(t).toContain(Number(comp[k]).toFixed(1));
  });
  it("shows role and flows for each evidence account", async () => {
    const t = text(await renderPage(RingInvestigation, { until: "Accounts in evidence graph" }));
    expect(t).toContain("Role in evidence"); expect(t).toContain("Flows (out / in)"); expect(t).not.toMatch(/\d\.0\b(?=[^%\d])\s*(?:Sender|Receiver)/);
  });
});

describe("Temporal Evolution", () => {
  const ids = fx[`/api/rings/${RID}`].trajectory.event_window_ids;
  const day = (w) => new Date(new Date(P.first_window_start).getTime() + w * P.window_days * 86400000).toISOString().slice(0, 10);
  it("translates the window ids into calendar dates from the database's window length", async () => {
    const t = text(await renderPage(TemporalEvolution, { until: day(Math.max(...ids)) }));
    expect(t).toContain(day(Math.min(...ids))); expect(t).toContain(`one window = ${P.window_days} calendar day(s)`);
  });
  it("says so when the window length is unknown", async () => {
    const t = text(await renderPage(TemporalEvolution, { override: { "/api/pipeline-stats": "error" }, until: "The window length is not available" }));
    expect(t).toContain("The window length is not available in the loaded results.");
  });
});

describe("Pattern Analytics", () => {
  const events = fx["/api/patterns?limit=50000"];
  const count = (types) => events.filter((e) => types.includes(e.pattern_type)).length;
  const OLD = ["fan_in", "fan_out", "layering", "split_merge", "circular_flow", "rapid_pass_through", "repeated_intermediary", "escalating_connectivity"];
  it("shows only the original pattern names and counts every event as structural or temporal", async () => {
    const t = text(await renderPage(PatternAnalytics, { until: "Pattern Interpretation" }));
    expect(events.length).toBeGreaterThan(0);
    expect(events.every((e) => OLD.includes(e.pattern_type))).toBe(true);                  // no internal or invented pattern name reaches the page
    const s = count(["fan_in", "fan_out", "layering", "split_merge"]);
    const tm = count(["circular_flow", "rapid_pass_through", "repeated_intermediary", "escalating_connectivity"]);
    expect(s + tm).toBe(events.length);
    expect(t).toContain("Structural / Temporal"); expect(t).toContain(`${inr(s)} / ${inr(tm)}`); expect(t).not.toContain("Account novelty");
    for (const name of new Set(events.map((e) => e.pattern_type))) expect(t).toContain({ fan_in: "Fan-in", fan_out: "Fan-out", layering: "Layering", circular_flow: "Circular Flow" }[name]);
  });
});

describe("Lead-Time page (one evaluation)", () => {
  it("shows the protocol, alerts, queue and rings from /api/lead-time", async () => {
    const t = text(await renderPage(LeadTimeAnalytics, { until: "Operating points" }));
    const r = LT.rings, a = LT.alerted_candidates;
    for (const v of [`${r.n_seen} of ${r.n_evaluable}`, String(a.n_alerted), `${a.alerted_containing_ring_tx} of ${a.n_alerted} contain ring transactions`, String(LT.protocol.alert_threshold),
                     "The whole queue", "Ranking quality of the queue", "Important interpretation"]) expect(t).toContain(v);
  });
  it("lists every operating point and marks the configured one", async () => {
    const t = text(await renderPage(LeadTimeAnalytics, { until: "Operating points" }));
    expect(t).toContain(`${LT.protocol.alert_threshold} (configured)`);
    for (const f of LT.frontier) expect(t).toContain(String(f.threshold));
  });
  it("states the first-transaction caveat only when the data supports it", async () => {
    const t = text(await renderPage(LeadTimeAnalytics, { until: "Operating points" }));
    expect(Number(LT.rings.lead_vs_first_tx_median)).toBeLessThanOrEqual(0); expect(t).toContain("Warnings arrive with a ring's first transactions");
    const pos = JSON.parse(JSON.stringify(LT)); pos.rings.lead_vs_first_tx_median = 4;
    const t2 = text(await renderPage(LeadTimeAnalytics, { override: { "/api/lead-time": pos }, until: "Operating points" }));
    expect(t2).not.toContain("Warnings arrive with a ring's first transactions");
  });
  it("shows the retraining ranges from the data, and no stability section without them", async () => {
    const st = LT.stability;
    expect(st.n_retrainings).toBeGreaterThan(1);
    const t = text(await renderPage(LeadTimeAnalytics, { until: "Stability across model retrainings" }));
    expect(t).toContain(`retrained ${st.n_retrainings} times`); expect(t).toContain(`${st.metrics.alerts.min} to ${st.metrics.alerts.max}`);
    expect(t).toContain("Quote the ranges, not a single value");
    const none = JSON.parse(JSON.stringify(LT)); none.stability = null;
    const t2 = text(await renderPage(LeadTimeAnalytics, { override: { "/api/lead-time": none }, until: "Ranking quality of the queue" }));
    expect(t2).not.toContain("Stability across model retrainings");
  });
  it("asks for the build when no evaluation exists, and invents nothing", async () => {
    const t = text(await renderPage(LeadTimeAnalytics, { override: NO_LT, until: "No evaluation results are loaded" }));
    expect(t).toContain("python scripts/rebuild_v2.py all"); expect(t).not.toContain("NaN");
  });
  it("contains no result typed into the page", async () => {
    const fs = await import("node:fs"); const path = await import("node:path");
    const src = fs.readFileSync(path.join(process.cwd(), "src/pages/LeadTimeAnalytics.jsx"), "utf8");
    expect(src).not.toMatch(/\?\?\s*-?\d/);                                           // no numeric fallbacks
  });
});

describe("Model Performance (one protocol)", () => {
  const M = fx["/api/metrics"], prop = M.proposed_gradient_boosting.test;
  it("shows the protocol and the evaluation context from the data", async () => {
    const t = text(await renderPage(ModelPerformance, { until: "Evaluation protocol" }));
    for (const v of [`${CTX.protocol.horizon_days}</b>`.replace("</b>", ""), CTX.protocol.threshold_rule, Number(CTX.n_test).toLocaleString("en-US"), String(CTX.n_positive)]) expect(t).toContain(v);
  });
  it("shows all four models, and says 'no flags' for a model that flags nothing", async () => {
    const t = text(await renderPage(ModelPerformance, { until: "Held-Out Test Performance" }));
    for (const name of Object.keys(M)) expect(t).toContain(name);
    const silent = Object.values(M).filter((m) => m.test.confusion_matrix.tp + m.test.confusion_matrix.fp === 0).length;
    expect((t.match(/no flags/g) || []).length).toBe(silent * 3);                      // precision, recall and F1 of each such model
    expect(t).toContain(Number(prop.pr_auc).toFixed(4));
  });
  it("says 'no flags' for a model whose threshold flags no test rows, instead of a misleading 0.0000", async () => {
    const quiet = JSON.parse(JSON.stringify(M));
    quiet.temporal_random_forest.test.confusion_matrix = { tp: 0, fp: 0, fn: quiet.temporal_random_forest.test.n_positive, tn: quiet.temporal_random_forest.test.n_negative };
    const t = text(await renderPage(ModelPerformance, { override: { "/api/metrics": quiet }, until: "Held-Out Test Performance" }));
    expect((t.match(/no flags/g) || []).length).toBe(3);
  });
  it("shows an em dash when the metrics are empty", async () => {
    const t = text(await renderPage(ModelPerformance, { override: { "/api/metrics": {}, "/api/evaluation-context": {} }, until: "Investigator-Oriented Ranking" }));
    expect(t).not.toContain("NaN"); expect(t).not.toContain("Evaluation protocol");
  });
});

describe("Ablations and Controls", () => {
  const EW = fx["/api/ring-early-warning"];
  it("compares the candidate sources, the controls and the horizon sensitivity", async () => {
    const t = text(await renderPage(RingEarlyWarning, { until: "Sensitivity to the forecast horizon" }));
    for (const v of ["v1 pattern-trajectory candidates (baseline)", "Production alerts", "Controls: is the model needed?", "newness_rule", "random", "The primary run, shown on the Model Performance page"]) expect(t).toContain(v);
  });
  it("uses the same rings as the production result", async () => {
    const t = text(await renderPage(RingEarlyWarning, { until: "Sensitivity to the forecast horizon" }));
    const n = EW.production_evaluation.ablations.production_alerted.by_typology.all.n_evaluable_rings;
    expect(n).toBe(LT.rings.n_evaluable); expect(t).toContain(`of ${n}`);
  });
  it("explains how to generate the results when none are loaded", async () => {
    const t = text(await renderPage(RingEarlyWarning, { override: { "/api/ring-early-warning": { available: false } }, until: "No comparison results are loaded" }));
    expect(t).toContain("python scripts/rebuild_v2.py all");
  });
});

describe("Data Explorer", () => {
  it("counts alert transactions from the database", async () => {
    const t = text(await renderPage(DataExplorer, { until: "Forensic interpretation" }));
    expect(t).toContain(inr(P.n_alert_transactions)); expect(t).toContain("Not in an alert");
  });
});


// ---------------------------------------------------------------------------------------------- warnings, alert log, pattern evidence
const WN = fx["/api/warnings"], PE = fx["/api/pattern-evidence"], RID2 = fx.__rid2__;
const NO_WARN = { "/api/warnings": { available: false } };

describe("Warning Timeline", () => {
  const S = WN.summary, ev = WN.rings.filter((r) => r.evaluable);
  it("shows every evaluable ring once, with one queue marker and one alert marker where a warning was given", async () => {
    const r = await renderPage(WarningTimeline, { until: "Where each warning falls on its ring" });
    expect(r.container.querySelectorAll("[data-ring]").length).toBe(S.n_evaluable);
    expect(r.container.querySelectorAll('circle[fill="#3b82f6"]').length).toBe(ev.filter((x) => x.queue.lead_days !== null).length + 1);      // +1: the legend
    expect(r.container.querySelectorAll('polygon[fill="#f97316"]').length).toBe(ev.filter((x) => x.alert.lead_days !== null).length + 1);
  });
  it("shows the warning counts and coverage from the data", async () => {
    const t = text(await renderPage(WarningTimeline, { until: "Every evaluable ring" }));
    for (const v of [`${S.n_evaluable - S.queue.not_seen} of ${S.n_evaluable}`, `${S.n_evaluable - S.alert.not_seen} of ${S.n_evaluable}`, `${S.queue.before} of ${S.n_evaluable}`, "Warned before completion", "Rings that cannot be evaluated"]) expect(t).toContain(v);
    for (const [k, v] of Object.entries(S.not_evaluable_reasons)) expect(t).toContain(`${v} rings: ${k}`);
  });
  it("filters the table by alert status", async () => {
    const r = await renderPage(WarningTimeline, { until: "Every evaluable ring" });
    const rows = () => r.container.querySelectorAll("tbody tr").length;
    const sel = r.container.querySelector("#alert-filter");
    fireEvent.change(sel, { target: { value: "before" } });
    expect(r.container.textContent).toContain(`${S.alert.before} of ${ev.length} rings`);
    fireEvent.change(sel, { target: { value: "not_seen" } });
    expect(r.container.textContent).toContain(`${S.alert.not_seen} of ${ev.length} rings`);
  });
  it("asks for the build when nothing is loaded", async () => {
    const t = text(await renderPage(WarningTimeline, { override: NO_WARN, until: "No results are loaded" }));
    expect(t).toContain("python scripts/rebuild_v2.py all"); expect(t).not.toContain("NaN");
  });
});

describe("Alert Log", () => {
  const S = WN.summary, thr = WN.protocol.alert_threshold;
  it("lists every alert and the cards agree with the list", async () => {
    const r = await renderPage(AlertLog, { until: "Every alert" });
    expect(r.container.querySelectorAll("tbody tr").length).toBe(WN.alerts.length);
    const t = text(r);
    for (const v of [String(S.n_alerts), `${S.alerts_with_ring_tx} contain ring transactions`, "Alerts given", "Still at or above threshold", String(thr)]) expect(t).toContain(v);
    expect(S.n_alerts).toBe(WN.alerts.length); expect(WN.daily.reduce((s, d) => s + d.alerts, 0)).toBe(S.n_alerts);
  });
  it("marks alerts whose score has since fallen below the threshold, and labels false alerts", async () => {
    const t = text(await renderPage(AlertLog, { until: "Every alert" }));
    const fallen = WN.alerts.filter((a) => a.final_score < thr).length;
    expect((t.match(new RegExp(`\\(below ${thr}\\)`, "g")) || []).length).toBe(fallen);
    expect((t.match(/false alert/g) || []).length).toBe(S.false_alerts);
  });
  it("filters by outcome", async () => {
    const r = await renderPage(AlertLog, { until: "Every alert" });
    fireEvent.change(r.container.querySelector("#outcome-filter"), { target: { value: "false" } });
    expect(r.container.querySelectorAll("tbody tr").length).toBe(S.false_alerts);
    fireEvent.change(r.container.querySelector("#outcome-filter"), { target: { value: "ring" } });
    expect(r.container.querySelectorAll("tbody tr").length).toBe(S.alerts_with_ring_tx);
  });
  it("asks for the build when nothing is loaded", async () => {
    expect(text(await renderPage(AlertLog, { override: NO_WARN, until: "No results are loaded" }))).toContain("rebuild_v2.py");
  });
});

describe("Pattern Evidence", () => {
  it("answers the pattern question from the data", async () => {
    const t = text(await renderPage(PatternEvidence, { until: "Candidates with several patterns" }));
    const total = PE.by_count.reduce((s, r) => s + r.candidates, 0);
    expect(total).toBe(PE.n_candidates);                                                   // every candidate is in exactly one group
    for (const v of [`${PE.single_pattern_candidates} of ${PE.n_candidates} candidates show a single pattern`, "Pattern count vs score", `rho ${Number(PE.spearman_count_vs_score.rho).toFixed(2)}`, "What each pattern adds to the score", "the largest candidates"]) expect(t).toContain(v);
    expect(PE.single_pattern_candidates + PE.multi_pattern_candidates).toBe(PE.n_candidates);
  });
  it("lists every candidate with several patterns, with its alert if one was given", async () => {
    const r = await renderPage(PatternEvidence, { until: "Candidates with several patterns" });
    const t = text(r);
    for (const m of PE.multi_pattern) expect(t).toContain(m.candidate_ring_id);
    expect(t).toContain("No alert");
  });
  it("asks for the build when nothing is loaded", async () => {
    expect(text(await renderPage(PatternEvidence, { override: { "/api/pattern-evidence": { available: false } }, until: "No results are loaded" }))).toContain("rebuild_v2.py");
  });
});

describe("Warning given on a candidate, and the Investigate links", () => {
  it("shows the alert for the selected candidate with its date and score", async () => {
    const a = WN.alerts.find((x) => x.candidate_ring_id === RID2);
    const t = text(await renderPage(RingInvestigation, { url: `/rings?id=${RID2}`, until: "Warning given" }));
    expect(t).toContain(`Alert given on ${dateOf(a.alert_date)}`); expect(t).toContain(Number(a.score_at_alert).toFixed(1));
    expect(t).toContain("All alerts given");
  });
  it("opens the candidate named in the link instead of always the top-ranked one", async () => {
    const r = await renderPage(RingInvestigation, { url: `/rings?id=${RID2}`, until: "Warning given" });
    const btn = (id) => [...r.container.querySelectorAll("button")].find((b) => b.textContent.trim() === id);
    expect(btn(RID2)).toBeTruthy(); expect(btn(RID)).toBeTruthy();
    expect(btn(RID2).className).not.toBe(btn(RID).className);                              // the linked candidate is highlighted, the top-ranked one is not
  });
  it("says so when no alert was given for the selected candidate", async () => {
    const none = JSON.parse(JSON.stringify(WN)); none.alerts = none.alerts.filter((a) => a.candidate_ring_id !== RID2);
    const t = text(await renderPage(RingInvestigation, { url: `/rings?id=${RID2}`, override: { "/api/warnings": none }, until: "Warning given" }));
    expect(t).toContain("No alert given"); expect(t).not.toContain("Alert given on");
  });
  it("shows the alert in the queue, the alerts card, and the warning cards on the overview", async () => {
    const q = await renderPage(AlertQueue, { until: "Alerts given" });
    const shownIds = fx["/api/alerts?limit=1000"].map((x) => x.candidate_ring_id);
    expect(q.container.querySelectorAll('[data-testid="alert-cell"]').length).toBe(WN.alerts.filter((a) => shownIds.includes(a.candidate_ring_id)).length);
    expect(text(q)).toContain(String(WN.summary.n_alerts));
    const o = text(await renderPage(Overview, { until: "Alerts given" }));
    expect(o).toContain(`${WN.summary.alert.before} of ${WN.summary.n_evaluable}`);
  });
  it("navigation lists the three new pages and routes them", async () => {
    const src = (await import("node:fs")).readFileSync((await import("node:path")).join(process.cwd(), "src/main.jsx"), "utf8");
    for (const [path, label] of [["/warning-timeline", "Warning Timeline"], ["/alert-log", "Alert Log"], ["/pattern-evidence", "Pattern Evidence"]]) {
      expect(src).toContain(`["${path}", "${label}"]`); expect(src).toContain(`path="${path}"`);
    }
  });
});

// ---------------------------------------------------------------------------------------------- score calculation card
import ScoreCalculationCard from "../src/components/ScoreCalculation.jsx";
import { render } from "@testing-library/react";
const CALC = fx[`/api/score-calculation/${fx.__rid__}`], CALC_F = fx[`/api/score-calculation/${fx.__ridfallen__}`];

describe("Score calculation card", () => {
  it("Temporal Evolution shows how the selected candidate's score was calculated, from the data", async () => {
    const r = await renderPage(TemporalEvolution, { until: "Score calculation" });
    const t = text(r), c = CALC.calculation;
    for (const v of ["Score calculation", c.formula, ...c.steps.map((s) => s.label), ...c.steps.map((s) => s.how)]) expect(t).toContain(v);
    expect(r.container.querySelector('[data-testid="score-total"]').textContent).toContain(Number(c.total_points).toFixed(2));
    expect(c.total_points).toBe(c.score);
  });
  it("the points of the four components add up to the score within rounding", async () => {
    const r = await renderPage(TemporalEvolution, { until: "Score calculation" });
    const pts = [...r.container.querySelectorAll("[data-step]")].map((row) => Number(row.lastChild.textContent));
    expect(pts.length).toBe(4);
    expect(Math.abs(pts.reduce((a, b) => a + b, 0) - CALC.calculation.score)).toBeLessThan(0.021);
  });
  it("shows every day of the history and marks the alert day, for a candidate whose score later fell", () => {
    const r = render(<ScoreCalculationCard calc={CALC_F} />);
    expect(r.container.querySelectorAll("[data-day-row]").length).toBe(CALC_F.steps.length);
    expect(r.container.querySelectorAll('[data-alert-row="true"]').length).toBe(1);
    const t = r.container.textContent;
    expect(t).toContain("an alert was given on"); expect(t).toContain("The alert stays on record"); expect(CALC_F.calculation.alert).toBe(false);
  });
  it("says no alert has been given when none was", () => {
    const none = JSON.parse(JSON.stringify(CALC_F)); none.alert_day = null;
    const t = render(<ScoreCalculationCard calc={none} />).container.textContent;
    expect(t).toContain("so no alert has been given"); expect(t).not.toContain("The alert stays on record");
  });
  it("shows nothing, and the page still works, when no calculation is available", async () => {
    const t = text(await renderPage(TemporalEvolution, { override: { [`/api/score-calculation/${fx.__rid__}`]: { available: false } }, until: "Suspicious Pattern Sequence" }));
    expect(t).not.toContain("Score calculation"); expect(t).toContain("Formation Stage");
  });
});

// ---------------------------------------------------------------------------------------------- patterns visible
import { SupportingPatternsCard } from "../src/components/SupportingPatterns.jsx";
const SP = fx["/api/supporting-patterns"], QUEUE = fx["/api/alerts?limit=1000"];
const NO_SP = { "/api/supporting-patterns": { available: false } };

describe("Patterns visible", () => {
  const rowsOf = (r) => r.container.querySelectorAll("tbody tr").length;
  it("the Alert Queue lists every candidate, including those below rank 100", async () => {
    const r = await renderPage(AlertQueue, { until: "candidates" });
    expect(QUEUE.length).toBeGreaterThan(100); expect(rowsOf(r)).toBe(QUEUE.length);
    for (const m of PE.multi_pattern) expect(text(r)).toContain(m.candidate_ring_id);                   // RING0050 and RING0001 used to be hidden
  });
  it("the Alert Queue asks the API for every candidate, not for the first 100", async () => {
    const fs = await import("node:fs"), path = await import("node:path");
    const src = fs.readFileSync(path.join(process.cwd(), "src/pages/AlertQueue.jsx"), "utf8");
    expect(src).toMatch(/api\.alerts\(\{ limit: 1000 \}\)/); expect(src).not.toMatch(/api\.alerts\(\{ limit: 100 \}\)/);
  });
  it("the '2 or more patterns' filter shows exactly the candidates with several patterns", async () => {
    const r = await renderPage(AlertQueue, { until: "candidates" });
    fireEvent.click(r.container.querySelector("#multi-filter"));
    expect(rowsOf(r)).toBe(PE.multi_pattern_candidates); expect(rowsOf(r)).toBe(QUEUE.filter((q) => q.patterns.length >= 2).length);
  });
  it("the pattern filter and the alert filter narrow the queue", async () => {
    const r = await renderPage(AlertQueue, { until: "candidates" });
    const name = [...new Set(QUEUE.flatMap((q) => q.patterns))].sort()[0];
    fireEvent.change(r.container.querySelector("#pattern-filter"), { target: { value: name } });
    expect(rowsOf(r)).toBe(QUEUE.filter((q) => q.patterns.includes(name)).length);
    fireEvent.change(r.container.querySelector("#pattern-filter"), { target: { value: "all" } });
    fireEvent.click(r.container.querySelector("#alert-only-filter"));
    expect(rowsOf(r)).toBe(WN.summary.n_alerts);
  });
  it("the queue shows the other patterns seen on each candidate's accounts, and says they are not in the score", async () => {
    const r = await renderPage(AlertQueue, { until: "candidates" });
    const withExtra = QUEUE.filter((q) => (SP.candidates[q.candidate_ring_id]?.types || []).some((t) => !t.also_in_candidate)).length;
    expect(r.container.querySelectorAll('[data-testid="supporting-line"]').length).toBe(withExtra);
    expect(text(r)).toContain("(not in the score)");
  });
  it("Ring Investigation lists the other patterns seen on the selected candidate, from the data", async () => {
    const r = await renderPage(RingInvestigation, { until: "Other patterns seen on these accounts" });
    const t = text(r), c = SP.candidates[RID];
    expect(r.container.querySelectorAll("[data-supporting]").length).toBe(c.types.length);
    for (const v of ["not used in the score", `Seen on ${SP.summary.with_any_supporting_pattern} of ${SP.summary.n_candidates} candidates`, "They are context, not evidence of a ring"]) expect(t).toContain(v);
  });
  it("shows a candidate with no other patterns honestly", () => {
    const empty = { ...SP, candidates: { X: { n_types: 0, types: [] } } };
    expect(render(<SupportingPatternsCard sp={empty} id="X" />).container.textContent).toContain("No other patterns were seen on these accounts");
  });
  it("Pattern Evidence reports whether these patterns separate rings, from the measured numbers", async () => {
    const t = text(await renderPage(PatternEvidence, { until: "Other patterns seen around the candidates" }));
    const S = SP.summary;
    expect(t).toContain(`${S.with_any_supporting_pattern} of ${S.n_candidates}`);
    const sep = S.auc_types_vs_ring_containing > 0.6 && S.mannwhitney_p_more_types_in_ring_containing < 0.05;
    expect(t).toContain(sep ? "show more of these patterns than the others" : "which is why they are shown but not scored");
  });
  it("hides all of it, and the pages still work, when the original events are not available", async () => {
    const q = await renderPage(AlertQueue, { override: NO_SP, until: "candidates" });
    expect(q.container.querySelectorAll('[data-testid="supporting-line"]').length).toBe(0); expect(rowsOf(q)).toBe(QUEUE.length);
    const r = await renderPage(RingInvestigation, { override: NO_SP, until: "Warning given" });
    expect(text(r)).not.toContain("Other patterns seen on these accounts");
  });
});
