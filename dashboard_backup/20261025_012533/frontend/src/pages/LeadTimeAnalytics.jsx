import React from "react";
import { api } from "../api.js";
import { Loading, ErrorBox, useApi } from "../components/ui.jsx";

// ONE evaluation of the production candidates against AMLSim ring ground truth. Every value comes from /api/lead-time
// (results/lead_time_summary.json written by scripts/rebuild_v2.py). A missing value is an em dash, never a remembered number.
const DASH = "\u2014";
const isNum = (x) => x !== null && x !== undefined && Number.isFinite(Number(x));
const num = (x, d = 1) => (isNum(x) ? Number(x).toFixed(d) : DASH);
const pct = (x, d = 0) => (isNum(x) ? `${(Number(x) * 100).toFixed(d)}%` : DASH);
const ci = (r) => (Array.isArray(r) && isNum(r[0]) && isNum(r[1]) ? `95% CI ${num(r[0])} to ${num(r[1])}` : "interval: n too small");

function Tile({ label, value, sub }) {
  return (
    <div className="rounded-lg border border-border p-3">
      <div className="text-xs text-muted uppercase tracking-wide">{label}</div>
      <div className="text-xl font-bold mt-1">{value}</div>
      {sub && <div className="text-xs text-muted mt-1">{sub}</div>}
    </div>
  );
}

function Section({ title, children }) {
  return (
    <div className="rounded-lg border border-border p-4 space-y-3">
      <div className="text-xs font-semibold uppercase tracking-wide">{title}</div>
      {children}
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
            <tr key={i} className={`border-t border-border ${r.highlight ? "bg-white/5" : ""}`}>
              {r.cells.map((c, j) => <td key={j} className="px-3 py-2">{c}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function LeadTimeAnalytics() {
  const { data, loading, error } = useApi(() => api.leadTime(), []);
  if (loading) return <Loading text="Loading early-warning evaluation..." />;
  if (error) return <ErrorBox error={error} />;

  const lt = data || {};
  if (!lt.rings) {
    return (
      <div className="space-y-4">
        <h1 className="text-xl font-bold">Early-Warning Evaluation</h1>
        <div className="rounded-lg border border-border p-4 text-sm">
          No evaluation results are loaded. Build them, load the database and reload this page:
          <pre className="mt-2 text-xs">python scripts/rebuild_v2.py all{"\n"}python scripts/load_database.py</pre>
        </div>
      </div>
    );
  }

  const r = lt.rings;
  const a = lt.alerted_candidates || {};
  const q = lt.all_candidates || {};
  const p = lt.protocol || {};
  const rk = lt.ranking || {};
  const pk = rk.precision_at_k || {};
  const typology = Object.entries(lt.by_typology || {});
  const startWarn = isNum(r.lead_vs_first_tx_median) && Number(r.lead_vs_first_tx_median) <= 0;

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-xl font-bold">Early-Warning Evaluation</h1>
        <p className="text-sm text-muted mt-1">One evaluation of the production candidates against AMLSim ring ground truth.</p>
      </div>

      <Section title="Protocol">
        <p className="text-sm leading-relaxed">
          Candidates are built from day <b>{p.scored_from_day}</b> onward (the first <b>{p.burn_in_days}</b> days are simulator warm-up). A candidate's risk score is computed only from the evidence
          available on that day, using a model trained on earlier data. A candidate becomes an <b>alert</b> when its score reaches <b>{p.alert_threshold}</b>. The evaluation uses the{" "}
          <b>{r.n_evaluable}</b> of {r.n_labelled} labelled rings whose transactions all fall in the scored period.
        </p>
      </Section>

      <Section title={`Alerts: risk score at or above ${p.alert_threshold}`}>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          <Tile label="Alerts raised" value={a.n_alerted ?? DASH} sub={`${a.scored_days ?? DASH} scored days`} />
          <Tile label="Alert precision" value={pct(a.alert_precision)} sub={`${a.alerted_containing_ring_tx ?? DASH} of ${a.n_alerted ?? DASH} contain ring transactions`} />
          <Tile label="False alerts per day" value={num(a.false_alerts_per_day, 3)} />
          <Tile label="Rings seen (N)" value={`${r.n_seen} of ${r.n_evaluable}`} sub={pct(r.ring_recall)} />
          <Tile label="Warned before completion" value={`${r.n_warned_before_completion} of ${r.n_evaluable}`} sub={pct(r.warned_before_completion_rate)} />
          <Tile label="Median lead (days)" value={num(r.lead_days_median)} sub={ci(r.lead_days_median_ci95)} />
        </div>
      </Section>

      <Section title="The whole queue (every candidate, ranked by risk)">
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          <Tile label="Candidates" value={q.n_candidates ?? DASH} />
          <Tile label="Ring-transaction share" value={pct(q.ring_tx_share_of_evidence, 1)} sub={isNum(q.enrichment_vs_background) ? `${num(q.enrichment_vs_background)}x the background rate` : ""} />
          <Tile label="Rings seen (N)" value={`${q.rings_seen ?? DASH} of ${r.n_evaluable}`} />
          <Tile label="Warned before completion" value={q.warned_before_completion ?? DASH} />
          <Tile label="Median lead (days)" value={num(q.lead_days_median)} />
          <Tile label="False candidates per day" value={num(q.false_candidates_per_day, 2)} sub={`ring-transaction recall ${pct(q.ring_tx_recall, 1)}`} />
        </div>
      </Section>

      <Section title="Operating points: the same evaluation at other alert thresholds">
        <Table
          head={["Alert threshold", "Alerts", "Alert precision", "False alerts / day", "Rings seen (N)", "Warned before completion", "Median lead (days)"]}
          rows={(lt.frontier || []).map((f) => ({
            highlight: f.configured,
            cells: f.n_alerted
              ? [`${f.threshold}${f.configured ? " (configured)" : ""}`, f.n_alerted, pct(f.alert_precision), num(f.false_alerts_per_day, 3), `${f.rings_seen} of ${f.n_evaluable_rings}`, f.warned_before_completion, num(f.lead_days_median)]
              : [f.threshold, 0, DASH, DASH, DASH, DASH, DASH],
          }))}
        />
        <p className="text-xs text-muted leading-relaxed">
          A lower threshold catches more rings and warns earlier but raises more false alerts; a higher one does the opposite. The configured threshold was set before this evaluation, not tuned to it.
        </p>
      </Section>

      <Section title="Ranking quality of the queue">
        <p className="text-sm leading-relaxed">
          Ranked by risk score, <b>{pct(pk["10"])}</b> of the top 10 candidates, <b>{pct(pk["20"])}</b> of the top 20 and <b>{pct(pk["50"])}</b> of the top 50 contain AMLSim ring transactions
          (AUC {num(rk.auc_score_vs_contains_ring_tx, 2)} over {rk.n_candidates ?? DASH} candidates, {rk.n_containing_ring_tx ?? DASH} of which contain ring transactions).
        </p>
      </Section>

      <Section title="By ring type (alerts)">
        <Table
          head={["Type", "Evaluable rings (N)", "Rings seen", "Warned before completion", "Median lead (days)", "Median 95% CI"]}
          rows={typology.map(([t, g]) => ({
            cells: [t, g.n_evaluable_rings, `${g.n_with_any_tx_in_candidate} (${pct(g.ring_recall)})`, g.n_warned_before_observable, num(g.lead_days_median), ci(g.lead_days_median_ci95).replace("95% CI ", "")],
          }))}
        />
        {startWarn && (
          <p className="text-sm leading-relaxed">
            Warnings arrive with a ring's first transactions (median {num(r.lead_vs_first_tx_median)} days against the ring's first transaction), so the lead above is measured against ring
            completion, not against a ring's start.
          </p>
        )}
      </Section>

      <Section title="Definitions and caveats">
        <ul className="text-xs text-muted list-disc pl-5 space-y-1">
          {Object.entries(lt.definitions || {}).map(([k, v]) => <li key={k}><b>{k}</b>: {v}</li>)}
          {(lt.caveats || []).map((c, i) => <li key={`c${i}`}>{c}</li>)}
        </ul>
      </Section>

      <div className="rounded-lg border border-border px-4 py-3">
        <div className="text-xs font-semibold uppercase tracking-wide">Important interpretation</div>
        <p className="text-xs text-muted mt-1 leading-relaxed">
          Lead-time results are experimental evaluation metrics for the current AMLSim configuration. They should not be interpreted as evidence that the system has achieved production-ready
          early warning or as legal confirmation of suspicious activity. Risk scores indicate investigative priority and do not establish criminal guilt.
        </p>
      </div>
    </div>
  );
}
