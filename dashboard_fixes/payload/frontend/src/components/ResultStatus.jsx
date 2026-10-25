import React from "react";
import { Link } from "react-router-dom";

// Shared, data-driven summaries. Everything comes from /api/lead-time and /api/evaluation-context. When a value is missing the
// component renders nothing (or an em dash), never a remembered number.
const DASH = "\u2014";
const isNum = (x) => x !== null && x !== undefined && Number.isFinite(Number(x));
const pct = (x, d = 0) => (isNum(x) ? `${(Number(x) * 100).toFixed(d)}%` : DASH);

export function ProductionNote({ lt }) {
  const r = lt?.rings;
  const a = lt?.alerted_candidates;
  const q = lt?.all_candidates;
  if (!r || !a || !q) return null;
  return (
    <div className="rounded-lg border border-amber-500/40 bg-amber-500/10 p-3 text-sm leading-relaxed" data-testid="production-note">
      <b>{q.n_candidates}</b> candidates were built from the scored period (day {lt.protocol?.scored_from_day} onward). <b>{a.n_alerted}</b> reach the alert
      threshold ({a.threshold}), and <b>{pct(a.alert_precision)}</b> of those contain AMLSim ring transactions. The whole queue covers <b>{q.rings_seen} of {r.n_evaluable}</b>{" "}
      evaluable rings. These results rest partly on an AMLSim-specific signal (ring members are otherwise-dormant accounts).{" "}
      <Link to="/lead-time" className="text-accent underline">See the evaluation</Link>
    </div>
  );
}

export function ProtocolNote({ ctx }) {
  const p = ctx?.protocol;
  const mp = p?.model_protocols || {};
  const first = Object.values(mp)[0];
  if (!p || !first) return null;
  return (
    <div className="rounded-lg border border-border p-4 space-y-2 text-sm leading-relaxed" data-testid="protocol-note">
      <div className="text-xs font-semibold uppercase tracking-wide">Evaluation protocol (the same for every model)</div>
      <p>
        A row is an account on a day. It is positive if the account is active that day and takes part in a ring transaction within the next <b>{p.horizon_days}</b> days.
        The first <b>{p.burn_in_days}</b> days (simulator warm-up) are excluded. Training uses days {first.train_days?.[0]} to {first.train_days?.[1]}; validation (days{" "}
        {first.validation_days?.[0]} to {first.validation_days?.[1]}) chooses each model's decision threshold ({p.threshold_rule}); test days {first.test_days?.[0]} to{" "}
        {first.test_days?.[1]} are scored once. A gap of {p.horizon_days} days separates the periods, so no label looks into the next period.
      </p>
      <details>
        <summary className="cursor-pointer text-xs text-muted">Feature set of each model</summary>
        <ul className="text-xs text-muted list-disc pl-5 mt-2 space-y-1">
          {Object.entries(mp).map(([name, m]) => (
            <li key={name}><b>{name}</b>: {(m.features || []).join(", ")}</li>
          ))}
        </ul>
      </details>
    </div>
  );
}
