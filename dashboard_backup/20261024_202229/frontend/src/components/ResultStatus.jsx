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

function Tile({ label, value, sub }) {
  return (
    <div className="rounded-lg border border-border p-3">
      <div className="text-xs text-muted uppercase tracking-wide">{label}</div>
      <div className="text-xl font-bold mt-1">{value}</div>
      {sub && <div className="text-xs text-muted mt-1">{sub}</div>}
    </div>
  );
}

export function RingLevelHeadline({ ew }) {
  const s = pickStatus(ew);
  if (!s.all) return null;
  const a = s.all;
  const lo = a.lead_days_median_ci95?.[0];
  const hi = a.lead_days_median_ci95?.[1];
  return (
    <div className="rounded-lg border border-border p-4 space-y-3" data-testid="ring-level-headline">
      <div className="text-xs font-semibold uppercase tracking-wide">
        Ring-level early warning (validated evaluation): {s.hm}, {s.hk} alerts per day
      </div>
      <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
        <Tile label="Evaluable rings (N)" value={a.n_evaluable_rings} sub="all transactions fall in the scored period" />
        <Tile label="Warned before observable" value={`${a.n_warned_before_observable} of ${a.n_evaluable_rings}`} sub={pct(a.warned_before_observable_rate, 0)} />
        <Tile
          label="Median lead (days)"
          value={num(a.lead_days_median)}
          sub={isNum(lo) && isNum(hi) ? `95% CI ${num(lo)} to ${num(hi)}` : "interval: n too small"}
        />
        <Tile label="False alerts per day" value={num(s.flags?.false_alerts_per_day, 2)} sub={`precision of flags ${pct(s.flags?.precision_of_flags, 0)}`} />
      </div>
      <p className="text-xs text-muted leading-relaxed">
        {(s.rl?.caveats || [])[0]} Only cycle rings are fully evaluable in this dataset.{" "}
        <Link to="/early-warning" className="text-accent underline">Details, controls and candidate quality</Link>
      </p>
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
      <Link to="/early-warning" className="text-accent underline">See candidate sources that do better</Link>
    </div>
  );
}

export function LeakageSafeTable({ ew }) {
  const aw = ew?.account_window;
  if (!aw?.results?.length) return null;
  const longest = Math.max(...aw.results.map((r) => Number(r.horizon_days)));
  const best = aw.results.find((r) => Number(r.horizon_days) === longest && String(r.name).startsWith("activity"));
  const base = aw.dashboard_baseline_from_model_comparison_json;
  return (
    <div className="rounded-lg border border-border p-4 space-y-3" data-testid="leakage-safe-table">
      <div className="text-xs font-semibold uppercase tracking-wide">Leakage-safe evaluation (validated protocol)</div>
      {best && base && (
        <p className="text-sm leading-relaxed">
          At a {best.horizon_days}-day horizon, precision at the validation-chosen threshold is <b>{num(best.precision, 2)}</b> (Wilson 95%{" "}
          {num(best.precision_wilson95?.[0], 2)} to {num(best.precision_wilson95?.[1], 2)}) with <b>{best.fp}</b> false alarms in {Number(best.n_test).toLocaleString("en-US")}{" "}
          test rows, against {num(base.precision, 3)} in the original 2-day run. Recall stays limited:{" "}
          {best.positive_accounts_caught} of {best.n_test_pos_accounts} positive accounts caught.
        </p>
      )}
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="text-muted text-left">
            <tr>
              {["Model", "Horizon (days)", "Test positives (accounts)", "PR-AUC", "Precision (Wilson 95%)", "TP / FP", "False-positive rate"].map((h) => (
                <th key={h} className="px-3 py-2 font-medium">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
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
        The forecast horizon changes the task, so every horizon is shown. Gains at longer horizons come mainly from a better-posed task and protocol, not a better model.
        Wilson intervals are approximate because rows of one account are correlated.
      </p>
    </div>
  );
}
