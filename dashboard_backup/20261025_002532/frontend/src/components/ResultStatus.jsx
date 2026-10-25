import React from "react";
import { Link } from "react-router-dom";

// Shared, data-driven result summaries. Everything comes from /api/ring-early-warning (files written by the evaluation
// scripts). When a file is missing the component renders nothing, never a remembered number.
const DASH = "\u2014";
const isNum = (x) => x !== null && x !== undefined && Number.isFinite(Number(x));
const pct = (x, d = 1) => (isNum(x) ? `${(Number(x) * 100).toFixed(d)}%` : DASH);
const num = (x, d = 1) => (isNum(x) ? Number(x).toFixed(d) : DASH);
const rate = (x) => (isNum(x) ? (Number(x) > 0 && Number(x) < 0.0001 ? Number(x).toExponential(1) : Number(x).toFixed(4)) : DASH);

export function pickStatus(ew) {
  const rl = ew?.ring_lead_time;
  const cq = ew?.candidate_quality;
  const aw = ew?.account_window;
  const hm = rl?.parameters?.headline_model;
  const hk = String(rl?.parameters?.headline_alerts_per_day ?? "");
  const head = rl?.results?.[hm]?.[hk];
  const v1 = (cq?.results || []).find((r) => r.candidate_set === "v1_pattern_trajectory");
  return { rl, cq, aw, hm, hk, head, all: head?.summary?.all, flags: head?.flag_stats, v1, v1all: v1?.by_typology?.all };
}

function Tile({ label, value, sub }) {  // kept for future use
  return (
    <div className="rounded-lg border border-border p-3">
      <div className="text-xs text-muted uppercase tracking-wide">{label}</div>
      <div className="text-xl font-bold mt-1">{value}</div>
      {sub && <div className="text-xs text-muted mt-1">{sub}</div>}
    </div>
  );
}

export function CandidateQualityNote({ ew }) {
  const s = pickStatus(ew);
  if (!s.v1) return null;
  const e = s.v1.enrichment_vs_background;
  return (
    <div className="rounded-lg border border-amber-500/40 bg-amber-500/10 p-3 text-sm leading-relaxed" data-testid="candidate-quality-note">
      Candidates on this page come from the v1 pattern-trajectory pipeline. After the warm-up, <b>{pct(s.v1.ring_tx_share_of_evidence)}</b> of their evidence
      transactions are AMLSim ring transactions ({isNum(e) ? `${num(e)}x` : DASH} the background rate), and{" "}
      <b>{s.v1all?.n_with_any_tx_in_candidate ?? DASH} of {s.v1all?.n_evaluable_rings ?? DASH}</b> evaluable rings appear in any of them.{" "}
      <Link to="/lead-time" className="text-accent underline">See every candidate source compared on the same rings</Link>
    </div>
  );
}

const SOURCES = [
  ["v1_pattern_trajectory", "v1 pattern-trajectory (the candidates in the queue)"],
  ["v2_structure", "v2 structure only (unordered cycles, paths)"],
  ["v2_novelty_sender_only", "v2 novelty: first-ever sender"],
  ["v2_novelty_min1_seed", "v2 novelty: first-ever sender or receiver"],
];

export function CandidateSourceComparison({ ew }) {
  const cq = ew?.candidate_quality;
  const rows = SOURCES.map(([key, label]) => [label, (cq?.results || []).find((r) => r.candidate_set === key)]).filter(([, r]) => r);
  if (!rows.length) return null;
  const n = rows[0][1]?.by_typology?.all?.n_evaluable_rings;
  const firstTx = rows.map(([, r]) => Number(r?.by_typology?.all?.lead_vs_first_tx_median)).filter((x) => Number.isFinite(x));
  const bestFirstTx = firstTx.length ? Math.max(...firstTx) : null;
  return (
    <div className="rounded-lg border border-border p-4 space-y-3" data-testid="candidate-source-comparison">
      <div className="text-xs font-semibold uppercase tracking-wide">Candidate sources compared on the same rings</div>
      <p className="text-sm leading-relaxed">
        Every row is evaluated identically: the {isNum(n) ? n : DASH} labelled rings that start after the warm-up and complete inside the data. A ring counts as seen when one of its
        transactions is inside a candidate. <b>Completion</b> is the ring's closing edge (cycles) or 4th counterparty (fans); <b>first transaction</b> is the ring's first AMLSim alert
        transaction, which was the original v1 definition. A positive lead means the warning came before that event.
      </p>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="text-muted text-left">
            <tr>
              {["Candidate source", "Candidates", "Ring-transaction share", "Rings seen (N)", "Warned before completion", "Median lead vs completion (days)", "Median lead vs first transaction (days)", "False candidates / day"].map((h) => (
                <th key={h} className="px-3 py-2 font-medium">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map(([label, r]) => {
              const a = r.by_typology?.all || {};
              return (
                <tr key={label} className="border-t border-border">
                  <td className="px-3 py-2">{label}</td>
                  <td className="px-3 py-2">{r.n_candidates}</td>
                  <td className="px-3 py-2">{pct(r.ring_tx_share_of_evidence)}</td>
                  <td className="px-3 py-2">{a.n_with_any_tx_in_candidate ?? DASH} of {a.n_evaluable_rings ?? DASH}</td>
                  <td className="px-3 py-2">{a.n_warned_before_observable ?? DASH}</td>
                  <td className="px-3 py-2">{num(a.lead_days_median)}</td>
                  <td className="px-3 py-2">{num(a.lead_vs_first_tx_median)}</td>
                  <td className="px-3 py-2">{num(r.false_candidates_per_day, 2)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="text-sm leading-relaxed">
        {bestFirstTx === null
          ? "Lead against the ring's first transaction is not available in the loaded results."
          : bestFirstTx <= 0
          ? `No candidate source warns before a ring's first transaction (best median ${num(bestFirstTx)} days): the novelty sources warn with it, and the others later. The positive leads above are measured against ring completion, so they say how long before a ring finishes it is flagged, not that it is caught before it starts.`
          : `The best median lead against a ring's first transaction is ${num(bestFirstTx)} days.`}
      </p>
      <p className="text-xs text-muted leading-relaxed">
        The novelty sources use a signal specific to AMLSim (ring members are otherwise-dormant accounts); the structure source uses graph structure only.
        Labels are used only to evaluate, never to build candidates.
      </p>
    </div>
  );
}

export function LeakageSafeTable({ ew }) {
  const aw = ew?.account_window;
  if (!aw?.results?.length) return null;
  const base = aw.dashboard_baseline_from_model_comparison_json;
  const h2 = aw.results.filter((r) => Number(r.horizon_days) === 2);
  const longer = aw.results.filter((r) => Number(r.horizon_days) > 2);
  const baseTp = base ? Math.round(Number(base.recall) * Number(base.n_positive)) : null;
  const baseFp = base && Number(base.precision) > 0 ? Math.round(baseTp / Number(base.precision) - baseTp) : null;
  const first = h2[0];
  const minFeatures = Math.min(...aw.results.map((r) => Number(r.features)));   // the run without account history has the fewest features
  const lo = first?.precision_wilson95?.[0];
  const hi = first?.precision_wilson95?.[1];
  const inside = base && isNum(lo) && isNum(hi) ? Number(base.precision) >= lo && Number(base.precision) <= hi : null;
  const horizons = [...new Set(longer.map((r) => r.horizon_days))].join(" and ");
  const longPos = [...new Set(longer.map((r) => r.n_test_pos))].join(" and ");
  const longPrec = longer.filter((r) => String(r.name).startsWith("activity")).map((r) => num(r.precision, 2)).join(" and ");
  return (
    <div className="rounded-lg border border-border p-4 space-y-3" data-testid="leakage-safe-table">
      <div className="text-xs font-semibold uppercase tracking-wide">Account-window evaluation: one protocol, every horizon</div>
      {base && h2.length > 0 && (
        <p className="text-sm leading-relaxed">
          <b>Like for like (the original 2-day task):</b> precision at the validation-chosen threshold is {h2.map((r) => `${num(r.precision, 2)} (${Number(r.features) > minFeatures ? "with account history" : "without"})`).join(" and ")},
          against {num(base.precision, 3)} in the original run ({h2[0].tp} against {baseTp} hits, with {h2[0].fp} against {baseFp} false alarms in the first case).
          {inside === null ? "" : inside ? " The original value lies inside the validated Wilson 95% interval, so this difference is within the uncertainty." : " The original value lies outside the validated Wilson 95% interval."}
        </p>
      )}
      {longer.length > 0 && (
        <p className="text-sm leading-relaxed">
          <b>Longer horizons are different, easier tasks</b> (the {horizons}-day windows have {longPos} positives instead of {first?.n_test_pos ?? DASH}). Their precision ({longPrec} without account history)
          is <b>not comparable</b> to the 2-day figure, and it comes from a better-posed task rather than a better model.
        </p>
      )}
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="text-muted text-left">
            <tr>
              {["Run", "Horizon (days)", "Test positives (accounts)", "PR-AUC", "Precision (Wilson 95%)", "TP / FP", "False-positive rate"].map((h) => (
                <th key={h} className="px-3 py-2 font-medium">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {base && (
              <tr className="border-t border-border bg-white/5">
                <td className="px-3 py-2">Original run (v1 protocol, threshold 0.8)</td>
                <td className="px-3 py-2">2</td>
                <td className="px-3 py-2">{base.n_positive}</td>
                <td className="px-3 py-2">{num(base.pr_auc, 3)}</td>
                <td className="px-3 py-2">{num(base.precision, 2)}</td>
                <td className="px-3 py-2">{baseTp} / {baseFp}</td>
                <td className="px-3 py-2">{rate(base.false_warning_rate)}</td>
              </tr>
            )}
            {aw.results.map((r, i) => (
              <tr key={i} className="border-t border-border">
                <td className="px-3 py-2">{r.name}</td>
                <td className="px-3 py-2">{r.horizon_days}</td>
                <td className="px-3 py-2">{r.n_test_pos} ({r.n_test_pos_accounts})</td>
                <td className="px-3 py-2">{num(r.pr_auc, 3)}</td>
                <td className="px-3 py-2">{num(r.precision, 2)} ({num(r.precision_wilson95?.[0], 2)} to {num(r.precision_wilson95?.[1], 2)})</td>
                <td className="px-3 py-2">{r.tp} / {r.fp}</td>
                <td className="px-3 py-2">{rate(r.false_positive_rate)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-xs text-muted leading-relaxed">
        The validated rows use a 120-day burn-in, purge gaps at every split, and a threshold chosen on validation data only. Wilson intervals are approximate because rows of one account are correlated.
        The baseline models (static, behavioural, temporal) were evaluated only in the original run, in the table below.
      </p>
    </div>
  );
}
