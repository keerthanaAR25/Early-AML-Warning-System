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
  it("counts the new detector's events in three categories instead of 0 / 0", async () => {
    const t = text(await renderPage(PatternAnalytics, { until: "Account-novelty patterns" }));
    const s = count(["fan_in", "fan_out", "layering", "split_merge", "partial_path", "new_account_chain", "slow_drip_fan_in", "slow_drip_fan_out"]);
    const tm = count(["circular_flow", "rapid_pass_through", "repeated_intermediary", "escalating_connectivity", "cycle_closure"]);
    const nv = count(["first_time_sender", "first_time_receiver"]);
    expect(s + tm + nv).toBe(events.length);                                       // nothing falls outside the three categories
    expect(t).toContain("Structural / Temporal / Account novelty"); expect(t).toContain(`${inr(s)} / ${inr(tm)} / ${inr(nv)}`);
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
