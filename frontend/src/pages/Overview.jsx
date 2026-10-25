import React from "react";
import { api } from "../api.js";
import {
  Card,
  Loading,
  ErrorBox,
  useApi,
} from "../components/ui.jsx";
import { ProductionNote } from "../components/ResultStatus.jsx";
import { WarningCards } from "../components/warnings.jsx";

export default function Overview() {
  const {
    data,
    loading,
    error,
  } = React.useMemo(
    () => ({
      data: null,
      loading: false,
      error: null,
    }),
    []
  );

  const summaryState = React.useState(null);
  const [summary, setSummary] = summaryState;

  const [summaryLoading, setSummaryLoading] = React.useState(true);
  const [summaryError, setSummaryError] = React.useState(null);

  React.useEffect(() => {
    let active = true;

    api.summary()
      .then((result) => {
        if (active) {
          setSummary(result);
          setSummaryLoading(false);
        }
      })
      .catch((err) => {
        if (active) {
          setSummaryError(err);
          setSummaryLoading(false);
        }
      });

    return () => {
      active = false;
    };
  }, []);

  const [pipeline, setPipeline] = React.useState(null);

  React.useEffect(() => {
    let active = true;
    api.pipelineStats()
      .then((r) => { if (active) setPipeline(r); })
      .catch(() => {});            // a failed call leaves the pipeline cards at an em dash; no numbers are invented
    return () => { active = false; };
  }, []);

  const { data: lt } = useApi(() => api.leadTime(), []);
  const { data: warn } = useApi(() => api.warnings(), []);

  if (summaryLoading) {
    return <Loading text="Loading executive overview..." />;
  }

  if (summaryError) {
    return (
      <ErrorBox
        error={summaryError}
        title="Unable to load executive overview"
      />
    );
  }

  const transactions =
    Number(summary?.total_transactions ?? summary?.transactions ?? summary?.transaction_count ?? NaN);

  const accounts =
    Number(summary?.total_accounts ?? summary?.accounts ?? summary?.account_count ?? NaN);

  const candidates =
    Number(
      summary?.ring_candidates ??
        summary?.candidate_rings ??
        summary?.candidates ??
        NaN
    );

  const critical =
    Number(
      summary?.critical_candidates ??
        summary?.critical_risk ??
        summary?.critical ??
        NaN
    );

  const high =
    Number(
      summary?.high_risk ??
        summary?.high_candidates ??
        summary?.high ??
        NaN
    );

  const moderate =
    Number(
      summary?.moderate_risk ??
        summary?.moderate_candidates ??
        summary?.moderate ??
        NaN
    );

  const averageRisk =
    Number(
      summary?.average_risk_score ??
        summary?.avg_risk_score ??
        NaN
    );

  // safe formatter: a missing value shows an em dash, never "NaN" and never a remembered number
  const show = (n) => (Number.isFinite(n) ? n.toLocaleString("en-IN") : "—");

  return (
    <div className="space-y-6">

      {/* HEADER */}
      <div>
        <h1 className="text-2xl font-bold">
          Executive Overview
        </h1>

        <p className="text-sm text-muted mt-1">
          Formation-stage money-laundering analytics using temporal
          transaction-network evidence.
        </p>
      </div>

      {/* DATASET SUMMARY */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">

        <div className="rounded-lg border border-border p-4">
          <div className="text-xs text-muted uppercase tracking-wide">
            Total Transactions
          </div>

          <div className="text-2xl font-bold mt-1">
            {show(transactions)}
          </div>
        </div>

        <div className="rounded-lg border border-border p-4">
          <div className="text-xs text-muted uppercase tracking-wide">
            Total Accounts
          </div>

          <div className="text-2xl font-bold mt-1">
            {show(accounts)}
          </div>
        </div>

        <div className="rounded-lg border border-border p-4">
          <div className="text-xs text-muted uppercase tracking-wide">
            Candidate Rings
          </div>

          <div className="text-2xl font-bold mt-1">
            {show(candidates)}
          </div>

          <div className="text-xs text-muted mt-1">
            analytical candidates for investigation
          </div>
        </div>

        <div className="rounded-lg border border-border p-4">
          <div className="text-xs text-muted uppercase tracking-wide">
            Critical Candidates
          </div>

          <div className="text-2xl font-bold mt-1">
            {show(critical)}
          </div>

          <div className="text-xs text-muted mt-1">
            risk score ≥ 75
          </div>
        </div>

      </div>

      <ProductionNote lt={lt} />
      <WarningCards warn={warn} />

      {/* RISK DISTRIBUTION */}
      <Card title="Candidate Risk Distribution">

        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">

          <div className="rounded-lg border border-border p-4">
            <div className="text-xs text-muted uppercase tracking-wide">
              Critical
            </div>

            <div className="text-2xl font-bold mt-1">
              {show(critical)}
            </div>

            <div className="text-xs text-muted mt-1">
              ≥ 75
            </div>
          </div>

          <div className="rounded-lg border border-border p-4">
            <div className="text-xs text-muted uppercase tracking-wide">
              High
            </div>

            <div className="text-2xl font-bold mt-1">
              {show(high)}
            </div>

            <div className="text-xs text-muted mt-1">
              50–74
            </div>
          </div>

          <div className="rounded-lg border border-border p-4">
            <div className="text-xs text-muted uppercase tracking-wide">
              Moderate
            </div>

            <div className="text-2xl font-bold mt-1">
              {show(moderate)}
            </div>

            <div className="text-xs text-muted mt-1">
              25–49
            </div>
          </div>

        </div>

      </Card>

      {/* AVERAGE RISK */}
      <Card title="Average Candidate Risk Score">

        <div className="text-3xl font-bold">
          {Number.isFinite(averageRisk) ? averageRisk.toFixed(2) : "—"}
        </div>

        <p className="text-sm text-muted mt-2">
          Average analytical risk score across the {show(candidates)} generated
          candidate rings.
        </p>

      </Card>

      {/* DETECTION PIPELINE */}
      <Card title="Detection Pipeline">

        <div className="grid grid-cols-1 md:grid-cols-5 gap-3">

          <div className="rounded-lg border border-border p-4">
            <div className="text-xs text-muted">
              INPUT
            </div>

            <div className="text-xl font-bold mt-1">
              {show(transactions)}
            </div>

            <div className="text-xs text-muted mt-1">
              Transactions
            </div>
          </div>

          <div className="rounded-lg border border-border p-4">
            <div className="text-xs text-muted">
              TEMPORAL GRAPH
            </div>

            <div className="text-xl font-bold mt-1">
              {show(pipeline?.n_graph_windows)}
            </div>

            <div className="text-xs text-muted mt-1">
              Graph windows
            </div>
          </div>

          <div className="rounded-lg border border-border p-4">
            <div className="text-xs text-muted">
              PATTERN DETECTION
            </div>

            <div className="text-xl font-bold mt-1">
              {show(pipeline?.n_pattern_events)}
            </div>

            <div className="text-xs text-muted mt-1">
              Pattern events
            </div>
          </div>

          <div className="rounded-lg border border-border p-4">
            <div className="text-xs text-muted">
              TRAJECTORY
            </div>

            <div className="text-xl font-bold mt-1">
              {show(pipeline?.n_trajectories)}
            </div>

            <div className="text-xs text-muted mt-1">
              Temporal trajectories
            </div>
          </div>

          <div className="rounded-lg border border-border p-4">
            <div className="text-xs text-muted">
              INVESTIGATION
            </div>

            <div className="text-xl font-bold mt-1">
              {show(candidates)}
            </div>

            <div className="text-xs text-muted mt-1">
              Candidate rings
            </div>
          </div>

        </div>

      </Card>

      {/* SYSTEM PURPOSE */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">

        <Card title="Temporal Analytics">
          <p className="text-sm text-muted leading-6">
            Models financial activity as an evolving transaction network
            rather than treating each transaction independently. Suspicious
            patterns are examined across temporal graph windows.
          </p>
        </Card>

        <Card title="Explainable Risk">
          <p className="text-sm text-muted leading-6">
            Candidate risk combines behavioural, network, fund-flow and
            persistence evidence into a 0–100 analytical score.
          </p>
        </Card>

        <Card title="Forensic Investigation">
          <p className="text-sm text-muted leading-6">
            Candidate scores are linked to accounts, transaction IDs,
            suspicious patterns, temporal trajectories and evidence
            subgraphs for investigator review.
          </p>
        </Card>

      </div>

      {/* RESEARCH CONTRIBUTION */}
      <Card title="Research Contribution">

        <div className="rounded-lg border border-border bg-panel px-5 py-5">

          <div className="font-semibold text-base">
            Formation-stage temporal AML analysis
          </div>

          <p className="text-sm text-muted mt-3 leading-6">
            The proposed framework integrates formation-stage temporal
            suspicious-pattern trajectories, ring-level candidate
            construction, explainable multi-dimensional risk scoring,
            forensic evidence-subgraph extraction and explicit early-warning
            evaluation into a single investigator-oriented AML pipeline.
          </p>

          <p className="text-sm text-muted mt-3 leading-6">
            Temporal graphs and lead-time evaluation are therefore treated
            as components of the overall contribution rather than being
            claimed individually as new techniques.
          </p>

        </div>

      </Card>

      {/* SYSTEM PURPOSE */}
      <Card title="Research Objective">

        <p className="text-sm text-muted leading-6">
          The objective is to identify suspicious financial-ring formation
          at an earlier analytical stage, explain why a candidate is
          prioritized, preserve the underlying transaction evidence, and
          evaluate whether the detected candidate becomes actionable before
          a corresponding known AML event.
        </p>

      </Card>

      {/* DISCLAIMER */}
      <div className="rounded-lg border border-border px-4 py-3">

        <div className="text-xs font-semibold uppercase tracking-wide">
          Important interpretation
        </div>

        <p className="text-xs text-muted mt-1 leading-relaxed">
          Candidate rings are analytical investigation hypotheses, not
          confirmed laundering rings. Risk scores represent analytical
          prioritization and should be interpreted together with the
          underlying transaction, temporal and network evidence.
        </p>

      </div>

    </div>
  );
}