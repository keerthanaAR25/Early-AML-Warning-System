import React from "react";
import { api } from "../api.js";
import { Loading, ErrorBox, useApi } from "../components/ui.jsx";

// Ablations and controls: research comparisons that support the production result on the Lead-Time page. They use the same
// rings and the same protocol (scored period from day 240, 120-day warm-up), so they cannot contradict it.
const DASH = "\u2014";
const isNum = (x) => x !== null && x !== undefined && Number.isFinite(Number(x));
const num = (x, d = 1) => (isNum(x) ? Number(x).toFixed(d) : DASH);
const pct = (x, d = 0) => (isNum(x) ? `${(Number(x) * 100).toFixed(d)}%` : DASH);
const range = (r, d = 2) => (Array.isArray(r) && isNum(r[0]) && isNum(r[1]) ? `${num(r[0], d)} to ${num(r[1], d)}` : "n too small");
const rate = (x) => (isNum(x) ? (Number(x) > 0 && Number(x) < 0.0001 ? Number(x).toExponential(1) : Number(x).toFixed(4)) : DASH);

const SOURCE_LABELS = {
  v1_pattern_trajectory: "v1 pattern-trajectory candidates (baseline)",
  structure_only: "Structure only (unordered cycles, paths)",
  novelty_only: "First-time-account groups only",
  production_all: "Production queue (structure + first-time-account groups)",
  production_alerted: "Production alerts (risk at or above the alert threshold)",
};

function Section({ title, note, children }) {
  return (
    <div className="rounded-lg border border-border p-4 space-y-3">
      <div className="text-xs font-semibold uppercase tracking-wide">{title}</div>
      {children}
      {note && <p className="text-xs text-muted leading-relaxed">{note}</p>}
    </div>
  );
}

function Table({ head, rows }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead className="text-muted text-left">
          <tr>{head.map((h) => <th key={h} className="px-3 py-2 font-medium">{h}</th>)}</tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} className="border-t border-border">{r.map((c, j) => <td key={j} className="px-3 py-2">{c}</td>)}</tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function RingEarlyWarning() {
  const { data, loading, error } = useApi(() => api.ringEarlyWarning(), []);
  if (loading) return <Loading />;
  if (error) return <ErrorBox error={error} />;

  const pe = data?.production_evaluation;
  const rl = data?.ring_lead_time;
  const aw = data?.account_window;

  if (!data?.available) {
    return (
      <div className="space-y-4">
        <h1 className="text-xl font-bold">Ablations and Controls</h1>
        <div className="rounded-lg border border-border p-4 text-sm">
          No comparison results are loaded. Generate them, then reload this page:
          <pre className="mt-2 text-xs">python scripts/rebuild_v2.py all{"\n"}python scripts/run_ring_lead_time.py{"\n"}python scripts/run_account_window_eval.py</pre>
        </div>
      </div>
    );
  }

  const sources = pe ? Object.entries(SOURCE_LABELS).map(([k, label]) => [label, pe.ablations?.[k]]).filter(([, r]) => r) : [];
  const controlRows = [];
  Object.entries(rl?.results || {}).forEach(([model, byK]) =>
    Object.entries(byK).forEach(([k, v]) => {
      const a = v?.summary?.all || {};
      controlRows.push([model, k, a.n_evaluable_rings ?? DASH, pct(a.detection_rate), pct(a.warned_before_observable_rate), num(a.lead_days_median), num(v?.flag_stats?.false_alerts_per_day, 2), pct(v?.flag_stats?.precision_of_flags)]);
    })
  );
  const awRows = aw?.results || [];
  const primaryH = aw?.parameters?.horizons ? Math.max(...aw.parameters.horizons) : null;

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-xl font-bold">Ablations and Controls</h1>
        <p className="text-sm text-muted mt-1">
          Research comparisons that support the production result on the Lead-Time page. They use the same rings and the same protocol, so they cannot contradict it.
        </p>
      </div>

      {sources.length > 0 && (
        <Section
          title="Candidate sources on the same rings (ablation)"
          note="Every row is evaluated identically on the same labelled rings. Lead is measured against ring completion (the closing edge for cycles). The first-time-account sources use a signal specific to AMLSim (ring members are otherwise-dormant accounts); the structure source uses graph structure only. Labels are used only to evaluate."
        >
          <Table
            head={["Candidate source", "Candidates", "Ring-transaction share", "Rings seen (N)", "Warned before completion", "Median lead (days)", "Median lead vs first transaction (days)", "False candidates / day"]}
            rows={sources.map(([label, r]) => {
              const g = r.by_typology?.all || {};
              return [label, r.n_candidates, pct(r.ring_tx_share_of_evidence, 1), `${g.n_with_any_tx_in_candidate ?? DASH} of ${g.n_evaluable_rings ?? DASH}`, g.n_warned_before_observable ?? DASH,
                      num(g.lead_days_median), num(g.lead_vs_first_tx_median), num(r.false_candidates_per_day, 2)];
            })}
          />
        </Section>
      )}

      {rl && (
        <Section
          title="Controls: is the model needed?"
          note="A transaction is flagged when it ranks in the top K scores of its day. The newness rule is a two-bit rule (first-ever sender or receiver), xgb_without_novelty sees same-day information only, and random is a control. If the model does not clearly beat the newness rule, it adds nothing beyond the simulator shortcut."
        >
          <Table head={["Model", "Alerts / day", "N rings", "Detected", "Warned before completion", "Median lead (days)", "False alerts / day", "Precision of flags"]} rows={controlRows} />
        </Section>
      )}

      {awRows.length > 0 && (
        <Section
          title="Sensitivity to the forecast horizon"
          note={`The forecast horizon changes the task, so rows with different horizons are not comparable with each other. The primary run, shown on the Model Performance page, is the ${primaryH}-day horizon with account history. Wilson intervals are approximate because rows of one account are correlated.`}
        >
          <Table
            head={["Model", "Horizon (days)", "Test positives (accounts)", "PR-AUC", "Precision (Wilson 95%)", "TP / FP", "False-positive rate"]}
            rows={awRows.map((r) => [r.name, r.horizon_days, `${r.n_test_pos} (${r.n_test_pos_accounts})`, num(r.pr_auc, 3), `${num(r.precision, 2)} (${range(r.precision_wilson95)})`, `${r.tp} / ${r.fp}`, rate(r.false_positive_rate)])}
          />
        </Section>
      )}
    </div>
  );
}
