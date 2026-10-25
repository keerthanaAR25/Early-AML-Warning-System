import React from "react";
import { api } from "../api.js";
import { Loading, ErrorBox, useApi } from "../components/ui.jsx";

// Every number on this page comes from /api/ring-early-warning (files written by scripts/run_ring_lead_time.py,
// scripts/run_candidates_v2.py and scripts/run_account_window_eval.py). Missing values render as an em dash.
const DASH = "\u2014";
const isNum = (x) => x !== null && x !== undefined && Number.isFinite(Number(x));
const num = (x, d = 1) => (isNum(x) ? Number(x).toFixed(d) : DASH);
const pct = (x, d = 0) => (isNum(x) ? `${(Number(x) * 100).toFixed(d)}%` : DASH);
const range = (r, d = 1) => (Array.isArray(r) && isNum(r[0]) && isNum(r[1]) ? `${num(r[0], d)} to ${num(r[1], d)}` : "n too small");

function Section({ title, children, note }) {
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
            <tr key={i} className="border-t border-border">
              {r.map((c, j) => <td key={j} className="px-3 py-2">{c}</td>)}
            </tr>
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

  const rl = data?.ring_lead_time;
  const cq = data?.candidate_quality;
  const aw = data?.account_window;

  if (!data?.available) {
    return (
      <div className="space-y-4">
        <h1 className="text-xl font-bold">Ring Early Warning</h1>
        <div className="rounded-lg border border-border p-4 text-sm">
          No ring-level evaluation results are loaded. Generate them, then reload this page:
          <pre className="mt-2 text-xs">python scripts/run_ring_lead_time.py{"\n"}python scripts/run_candidates_v2.py{"\n"}python scripts/run_account_window_eval.py</pre>
        </div>
      </div>
    );
  }

  const hm = rl?.parameters?.headline_model;
  const hk = String(rl?.parameters?.headline_alerts_per_day ?? "");
  const head = rl?.results?.[hm]?.[hk];
  const typology = head ? Object.entries(head.summary || {}) : [];
  const fs = head?.flag_stats || {};

  const budgetRows = [];
  Object.entries(rl?.results || {}).forEach(([model, byK]) =>
    Object.entries(byK).forEach(([k, v]) => {
      const a = v?.summary?.all || {};
      budgetRows.push([
        model, k, a.n_evaluable_rings ?? DASH, pct(a.detection_rate), pct(a.warned_before_observable_rate),
        num(a.lead_days_median), num(v?.flag_stats?.false_alerts_per_day, 2), pct(v?.flag_stats?.precision_of_flags),
      ]);
    })
  );

  const cqSets = cq?.results || [];
  const awRows = aw?.results || [];
  const dash = aw?.dashboard_baseline_from_model_comparison_json;

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-xl font-bold">Ring Early Warning</h1>
        <p className="text-sm text-muted mt-1">
          Ring-level lead time, candidate quality and a leakage-safe account-window evaluation. Every statistic shows its sample size.
        </p>
      </div>

      <div className="rounded-lg border border-amber-500/40 bg-amber-500/10 p-4 text-sm leading-relaxed">
        <b>Read before citing.</b> These are exploratory, simulator-specific results.
        {(rl?.caveats || []).slice(0, 2).map((c, i) => <div key={i} className="mt-2 text-xs">{c}</div>)}
      </div>

      {rl && (
        <Section
          title={`Ring-level early warning: ${hm ?? DASH}, ${hk || DASH} alerts per day`}
        >
          <Table
            head={["Typology", "N rings", "Detected", "Warned before observable", "Median lead (days)", "Median 95% CI", "Lead IQR", "Min / Max", "N for lead stats"]}
            rows={typology.map(([t, g]) => [
              t, g.n_evaluable_rings, `${g.n_detected} (${pct(g.detection_rate)})`,
              `${g.n_warned_before_observable} (${pct(g.warned_before_observable_rate)})`, num(g.lead_days_median),
              range(g.lead_days_median_ci95), `${num(g.lead_days_q25)} to ${num(g.lead_days_q75)}`,
              `${num(g.lead_days_min, 0)} / ${num(g.lead_days_max, 0)}`, g.n_for_lead_stats,
            ])}
          />
          <div className="text-sm">
            False alerts per day <b>{num(fs.false_alerts_per_day, 2)}</b> | precision of flags <b>{pct(fs.precision_of_flags)}</b> | share of true flags that are a
            first-ever sender <b>{pct(fs.share_of_true_flags_that_are_first_ever_sender)}</b>
          </div>
          <ul className="text-xs text-muted list-disc pl-5 space-y-1">
            {Object.entries(rl?.definitions || {}).map(([k, v]) => <li key={k}><b>{k}</b>: {v}</li>)}
          </ul>
        </Section>
      )}

      {rl && (
        <Section
          title="Controls across alert budgets"
          note="Compare the headline model with the same-day-only model, the two-bit newness rule and random before drawing conclusions."
        >
          <Table head={["Model", "Alerts/day", "N rings", "Detected", "Warned before observable", "Median lead (days)", "False alerts/day", "Precision of flags"]} rows={budgetRows} />
        </Section>
      )}

      {cq && (
        <Section
          title={`Candidate quality (candidates created on or after day ${cq?.parameters?.burn_in ?? DASH})`}
          note="Ring-transaction share = fraction of a candidate set's evidence transactions that are AMLSim ring transactions. Labels are used only to evaluate, never to build candidates."
        >
          <Table
            head={["Candidate set", "Candidates", "Evidence tx", "Ring-tx share", "Enrichment", "With ring tx / majority ring", "False candidates/day", "Ring-tx recall", "Rings with a tx (N)", "Warned before observable", "Median lead (days)"]}
            rows={cqSets.map((r) => {
              const a = r?.by_typology?.all || {};
              return [
                r.candidate_set, r.n_candidates, r.evidence_transactions, pct(r.ring_tx_share_of_evidence, 1),
                isNum(r.enrichment_vs_background) ? `${num(r.enrichment_vs_background)}x` : DASH,
                `${r.candidates_with_any_ring_tx} / ${r.candidates_majority_ring}`, num(r.false_candidates_per_day, 2), pct(r.ring_tx_recall, 1),
                `${a.n_with_any_tx_in_candidate ?? DASH} of ${a.n_evaluable_rings ?? DASH}`, a.n_warned_before_observable ?? DASH, num(a.lead_days_median),
              ];
            })}
          />
        </Section>
      )}

      {aw && (
        <Section
          title="Account-window evaluation (leakage-safe protocol)"
          note="The forecast horizon changes the task, so every horizon is reported. Gains at longer horizons come mainly from a better-posed task and protocol, not a better model. The PR-AUC range resamples whole accounts and is not a confidence interval."
        >
          <Table
            head={["Model", "Horizon (days)", "Test positives (accounts)", "PR-AUC", "PR-AUC bootstrap range", "Precision (Wilson 95%)", "TP / FP", "Positive accounts caught (Wilson 95%)", "False-positive rate"]}
            rows={[
              ...(dash ? [["Dashboard model (as shown)", 2, `${dash.n_positive}`, num(dash.pr_auc, 3), DASH, num(dash.precision, 3), DASH, DASH, isNum(dash.false_warning_rate) ? Number(dash.false_warning_rate).toExponential(1) : DASH]] : []),
              ...awRows.map((r) => [
                r.name, r.horizon_days, `${r.n_test_pos} (${r.n_test_pos_accounts})`, num(r.pr_auc, 3), range(r.pr_auc_bootstrap_range_2p5_97p5, 3),
                `${num(r.precision, 2)} (${range(r.precision_wilson95, 2)})`, `${r.tp} / ${r.fp}`,
                `${r.positive_accounts_caught}/${r.n_test_pos_accounts} (${range(r.recall_by_account_wilson95, 2)})`,
                isNum(r.false_positive_rate) ? Number(r.false_positive_rate).toExponential(1) : DASH,
              ]),
            ]}
          />
        </Section>
      )}
    </div>
  );
}
