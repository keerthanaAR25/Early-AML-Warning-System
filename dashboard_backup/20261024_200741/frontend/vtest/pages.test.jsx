import { describe, it, expect } from "vitest";
import Overview from "../src/pages/Overview.jsx";
import RingInvestigation from "../src/pages/RingInvestigation.jsx";
import { renderPage, text } from "./helpers.jsx";

describe("Overview", () => {
  it("shows the values the API sends, including the pipeline counts", async () => {
    const t = text(await renderPage(Overview, { until: "Detection Pipeline" }));
    for (const v of ["1,97,905", "12,043", "142", "39,869", "3,460", "720", "52.08"]) expect(t).toContain(v);
  });
  it("shows an em dash (not a remembered number) when the API sends nothing", async () => {
    const t = text(await renderPage(Overview, { override: { "/api/summary": {}, "/api/pipeline-stats": "error" }, until: "Detection Pipeline" }));
    expect(t).not.toContain("1,97,905"); expect(t).not.toContain("39,869"); expect(t).not.toContain("3,460"); expect(t).not.toContain("52.08");
    expect(t).not.toContain("NaN"); expect(t).toContain("\u2014");
  });
});

describe("Ring Investigation (RING056)", () => {
  it("shows the four score components that used to be blank", async () => {
    const t = text(await renderPage(RingInvestigation, { until: "Accounts in evidence graph" }));
    for (const v of ["92.5", "97.9", "37.5", "28.9"]) expect(t).toContain(v);
  });
  it("shows role and flows instead of repeating the account id / an empty risk column", async () => {
    const t = text(await renderPage(RingInvestigation, { until: "Accounts in evidence graph" }));
    expect(t).toContain("Role in evidence"); expect(t).toContain("Flows (out / in)");
    expect(t).toContain("Sender and receiver");           // account 14 and 2762 both send and receive
    expect(t).toContain("1 out / 6 in");                  // account 14: sends to 2762, receives from 2762 (x2) and four others
    expect(t).not.toContain("49066.0");
  });
});

import ModelPerformance from "../src/pages/ModelPerformance.jsx";
describe("Model Performance", () => {
  it("evaluation context and Precision@K come from the API", async () => {
    const t = text(await renderPage(ModelPerformance, { until: "Investigator-Oriented Ranking" }));
    for (const v of ["653,487", "0.0049%", "40%", "25%", "14%", "4 of the top 10", "5 of the top 20", "7 of the top 50"]) expect(t).toContain(v);
  });
  it("shows an em dash, not remembered numbers, when the metrics are empty", async () => {
    const t = text(await renderPage(ModelPerformance, { override: { "/api/metrics": {} }, until: "Investigator-Oriented Ranking" }));
    expect(t).not.toContain("653,487"); expect(t).not.toContain("0.0049%"); expect(t).not.toContain("40%"); expect(t).not.toContain("NaN");
    expect(t).toContain("Not available in the loaded results.");
  });
});

import LeadTimeAnalytics from "../src/pages/LeadTimeAnalytics.jsx";
describe("Lead-Time page", () => {
  it("shows the API values, the real window length, and a heading that follows the data", async () => {
    const t = text(await renderPage(LeadTimeAnalytics, { until: "Ground-Truth Linkage" }));
    for (const v of ["1.0%", "0.0%", "98.9%", "-23", "Why the 98.9% Figure", "one graph window = 1 calendar day", "720 windows", "by 23 graph windows"]) expect(t).toContain(v);
    expect(t).not.toContain("should not automatically be interpreted as one calendar day");
  });
  it("shows an em dash instead of remembered numbers when the summary is empty", async () => {
    const t = text(await renderPage(LeadTimeAnalytics, { override: { "/api/lead-time": {}, "/api/pipeline-stats": "error" }, until: "Ground-Truth Linkage" }));
    for (const v of ["-23", "98.9%", "142", "89", "1.0%"]) expect(t).not.toContain(v);
    expect(t).not.toContain("NaN"); expect(t).toContain("No lead time is available");
  });
  it("does not claim 'no early detections' when the data says there are some", async () => {
    const t = text(await renderPage(LeadTimeAnalytics, { override: { "/api/lead-time": { n_early_detections: 5, n_candidates: 10 } }, until: "Ground-Truth Linkage" }));
    expect(t).not.toContain("No positive early-warning detections were established");
  });
});

import AlertQueue from "../src/pages/AlertQueue.jsx";
import DataExplorer from "../src/pages/DataExplorer.jsx";
import TemporalEvolution from "../src/pages/TemporalEvolution.jsx";
import RingEarlyWarning from "../src/pages/RingEarlyWarning.jsx";

describe("Alert Queue", () => {
  it("takes the total candidate count from the API", async () => {
    const t = text(await renderPage(AlertQueue, { until: "candidates shown" }));
    expect(t).toContain("of 142");
  });
  it("shows an em dash if the total is unknown", async () => {
    const t = text(await renderPage(AlertQueue, { override: { "/api/summary": {} }, until: "candidates shown" }));
    expect(t).not.toContain("of 142"); expect(t).toContain("of \u2014");
  });
});

describe("Data Explorer", () => {
  it("counts alert transactions from the database and no longer says 'Unlabelled'", async () => {
    const t = text(await renderPage(DataExplorer, { until: "Forensic interpretation" }));
    expect(t).toContain("671"); expect(t).toContain("Not in an alert"); expect(t).not.toContain("Unlabelled");
  });
  it("does not remember 671 when the count is unavailable", async () => {
    const t = text(await renderPage(DataExplorer, { override: { "/api/pipeline-stats": "error" }, until: "Forensic interpretation" }));
    expect(t).not.toContain("671"); expect(t).not.toContain("NaN");
  });
});

describe("Temporal Evolution", () => {
  it("translates window ids into calendar dates using the database's window length", async () => {
    const t = text(await renderPage(TemporalEvolution, { until: "2017-06-02" }));
    expect(t).toContain("one window = 1 calendar day(s)"); expect(t).toContain("2017-05-26"); expect(t).toContain("2017-06-02");
    expect(t).not.toContain("should not automatically be interpreted as");
  });
  it("says so when the window length is unknown", async () => {
    const t = text(await renderPage(TemporalEvolution, { override: { "/api/pipeline-stats": "error" }, until: "The window length is not available" }));
    expect(t).toContain("The window length is not available in the loaded results.");
  });
});

describe("Ring Early Warning", () => {
  it("shows N, medians and controls from the evaluation files", async () => {
    const t = text(await renderPage(RingEarlyWarning, { until: "Controls across alert budgets" }));
    for (const v of ["xgb_with_novelty", "N rings", "12.0", "newness_rule", "random", "v1_pattern_trajectory", "v2_structure", "Account-window evaluation", "Wilson 95%", "Read before citing"]) expect(t).toContain(v);
    expect(t).not.toContain("NaN");
  });
  it("explains how to generate the results when none are loaded", async () => {
    const t = text(await renderPage(RingEarlyWarning, { override: { "/api/ring-early-warning": { available: false } }, until: "No ring-level evaluation" }));
    expect(t).toContain("python scripts/run_ring_lead_time.py");
  });
});
