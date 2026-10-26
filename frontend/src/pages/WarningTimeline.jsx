import React from "react";
import { Link } from "react-router-dom";
import { api } from "../api.js";
import { Loading, ErrorBox, useApi } from "../components/ui.jsx";
import { Stat, Panel, Unavailable, BUILD_COMMAND, num, pct, dateOf, isNum, DASH, STATUS_LABEL, ALERT_STATUS_LABEL, STATUS_TONE } from "../components/warnings.jsx";

const median = (xs) => {
  const a = xs.filter(isNum).map(Number).sort((p, q) => p - q);
  if (!a.length) return null;
  const m = Math.floor(a.length / 2);
  return a.length % 2 ? a[m] : (a[m - 1] + a[m]) / 2;
};

// Every evaluable ring, aligned at the day the ring is complete (x = 0). Left of 0 is before completion.
function AlignedChart({ rings }) {
  const W = 900, L = 170, R = 24, T = 34, ROW = 22;
  const dur = rings.map((r) => r.completion_day - r.first_day);
  const leads = rings.flatMap((r) => [r.queue.lead_days, r.alert.lead_days]).filter(isNum).map(Number);
  const minX = -(Math.max(1, ...dur, ...leads) + 1);
  const maxX = Math.max(0, ...leads.map((l) => -l)) + 1.5;
  const sc = (W - L - R) / (maxX - minX);
  const x = (v) => L + (v - minX) * sc;
  const H = T + rings.length * ROW + 34;
  const ticks = [];
  for (let t = Math.ceil(minX / 5) * 5; t <= maxX; t += 5) ticks.push(t);
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label="Warnings on every ring, aligned at ring completion" data-testid="aligned-chart">
      {ticks.map((t) => (
        <g key={t}>
          <line x1={x(t)} x2={x(t)} y1={T - 8} y2={H - 30} stroke="currentColor" opacity="0.08" />
          <text x={x(t)} y={T - 14} fontSize="10" textAnchor="middle" fill="currentColor" opacity="0.6">{t === 0 ? "complete" : `${t} d`}</text>
        </g>
      ))}
      <line x1={x(0)} x2={x(0)} y1={T - 8} y2={H - 30} stroke="currentColor" opacity="0.5" strokeDasharray="4 3" />
      {rings.map((r, i) => {
        const y = T + i * ROW + ROW / 2;
        const q = r.queue.lead_days, a = r.alert.lead_days;
        return (
          <g key={r.ring_id} data-ring={r.ring_id}>
            <text x={8} y={y + 4} fontSize="11" fill="currentColor">Ring {r.ring_id} · {r.type}</text>
            <line x1={x(-(r.completion_day - r.first_day))} x2={x(0)} y1={y} y2={y} stroke="currentColor" strokeWidth="3" opacity="0.35"><title>{`Ring ${r.ring_id}: first transaction ${dateOf(r.first_date)}, complete ${dateOf(r.completion_date)}`}</title></line>
            <polygon points={`${x(0)},${y - 5} ${x(0) + 5},${y} ${x(0)},${y + 5} ${x(0) - 5},${y}`} fill="currentColor" />
            {isNum(q) && <circle cx={x(-Number(q))} cy={y} r="4.5" fill="#3b82f6"><title>{`Queue warning ${dateOf(r.queue.warning_date)}: ${num(q, 0)} day(s) before completion`}</title></circle>}
            {isNum(a) && <polygon points={`${x(-Number(a))},${y - 6} ${x(-Number(a)) + 6},${y + 5} ${x(-Number(a)) - 6},${y + 5}`} fill="#f97316"><title>{`Alert ${dateOf(r.alert.warning_date)}: ${num(a, 0)} day(s) before completion`}</title></polygon>}
          </g>
        );
      })}
      <g fontSize="11" fill="currentColor">
        <polygon points={`${L},${H - 18} ${L + 5},${H - 13} ${L},${H - 8} ${L - 5},${H - 13}`} /><text x={L + 12} y={H - 9}>ring complete</text>
        <circle cx={L + 130} cy={H - 13} r="4.5" fill="#3b82f6" /><text x={L + 140} y={H - 9}>candidate warning (queue)</text>
        <polygon points={`${L + 330},${H - 19} ${L + 336},${H - 8} ${L + 324},${H - 8}`} fill="#f97316" /><text x={L + 344} y={H - 9}>alert (risk at or above threshold)</text>
      </g>
    </svg>
  );
}

export default function WarningTimeline() {
  const { data: w, loading, error } = useApi(() => api.warnings(), []);
  const [filter, setFilter] = React.useState("all");
  if (loading) return <Loading text="Loading warnings..." />;
  if (error) return <ErrorBox error={error} />;
  if (!w?.rings) return <Unavailable title="Warning Timeline" command={BUILD_COMMAND} />;

  const S = w.summary, thr = w.protocol?.alert_threshold;
  const ev = w.rings.filter((r) => r.evaluable).sort((a, b) => a.completion_day - b.completion_day);
  const shown = ev.filter((r) => filter === "all" || r.alert.status === filter);
  const n = S.n_evaluable;
  const medQ = median(ev.map((r) => r.queue.lead_days)), medA = median(ev.map((r) => r.alert.lead_days));
  const life = median(ev.map((r) => r.completion_day - r.first_day));

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-xl font-bold">Warning Timeline</h1>
        <p className="text-sm text-muted mt-1">Where the early warning and the alert were given on every ring, aligned at the day the ring is complete.</p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
        <Stat label="Rings in the data" value={S.n_rings} sub={`${n} can be evaluated (they start in the scored period)`} />
        <Stat label="Seen by the queue" value={`${n - S.queue.not_seen} of ${n}`} sub={`ring-transaction coverage ${pct(S.mean_tx_coverage?.queue)}`} />
        <Stat label="Seen by alerts" value={`${n - S.alert.not_seen} of ${n}`} sub={`ring-transaction coverage ${pct(S.mean_tx_coverage?.alert)}`} />
        <Stat label="Ring lifetime" value={`${num(life, 0)} days`} sub="median, first transaction to completion" />
      </div>

      <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
        <Stat label="Warned before completion" value={S.alert.before} sub={`by alerts; the queue: ${S.queue.before} of ${n}`} />
        <Stat label="Warned at completion" value={S.alert.at} sub={`by alerts; the queue: ${S.queue.at}`} />
        <Stat label="Warned after completion" value={S.alert.after} sub={`by alerts; the queue: ${S.queue.after}`} />
        <Stat label="No alert given" value={S.alert.not_seen} sub={`rings the queue never saw: ${S.queue.not_seen}`} />
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        <Stat label="Median lead of the queue" value={`${num(medQ)} days`} sub="candidate created, before the ring completes" />
        <Stat label="Median lead of alerts" value={`${num(medA)} days`} sub={`risk score reached ${thr}, before the ring completes`} />
      </div>

      <Panel title="Where each warning falls on its ring" note="Rings are aligned at completion (the dashed line). A marker left of it came before the ring was complete. Blue is the first day a candidate holding the ring's transactions existed; orange is the day such a candidate reached the alert threshold. Hover a marker for the date. Ring fields are AMLSim ground truth, used only to evaluate.">
        <AlignedChart rings={ev} />
      </Panel>

      <Panel title="Every evaluable ring">
        <div className="flex items-center gap-2 text-sm">
          <label htmlFor="alert-filter" className="text-muted">Alert status</label>
          <select id="alert-filter" value={filter} onChange={(e) => setFilter(e.target.value)} className="rounded-md border border-border bg-transparent px-2 py-1">
            <option value="all">All</option>
            {Object.entries(ALERT_STATUS_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
          <span className="text-xs text-muted">{shown.length} of {ev.length} rings</span>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-muted text-left"><tr>
              {["Ring", "Type", "First transaction", "Complete", "Queue warning (lead)", "Alert (lead)", "Alert status", "Coverage (queue / alert)"].map((h) => <th key={h} className="px-3 py-2 font-medium">{h}</th>)}
            </tr></thead>
            <tbody>
              {shown.map((r) => (
                <tr key={r.ring_id} className="border-t border-border">
                  <td className="px-3 py-2">{r.ring_id}</td>
                  <td className="px-3 py-2">{r.type}</td>
                  <td className="px-3 py-2">{dateOf(r.first_date)}</td>
                  <td className="px-3 py-2">{dateOf(r.completion_date)}</td>
                  <td className="px-3 py-2">{r.queue.seen ? <>{dateOf(r.queue.warning_date)} ({num(r.queue.lead_days, 0)} d) {r.queue.candidate && <Link className="underline text-accent" to={`/rings?id=${r.queue.candidate}`}>{r.queue.candidate}</Link>}</> : DASH}</td>
                  <td className="px-3 py-2">{r.alert.seen ? <>{dateOf(r.alert.warning_date)} ({num(r.alert.lead_days, 0)} d) {r.alert.candidate && <Link className="underline text-accent" to={`/rings?id=${r.alert.candidate}`}>{r.alert.candidate}</Link>}</> : DASH}</td>
                  <td className={`px-3 py-2 ${STATUS_TONE[r.alert.status] || ""}`}>{ALERT_STATUS_LABEL[r.alert.status]}</td>
                  <td className="px-3 py-2">{pct(r.queue.tx_coverage)} / {pct(r.alert.tx_coverage)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>

      <Panel title="Rings that cannot be evaluated" note="A ring is evaluable only if all of its transactions fall in the scored period. The others are listed here with the reason; nothing is hidden.">
        <Table2 head={["Ring type", "Rings", "Evaluable", "Seen by the queue", "Seen by alerts"]}
          rows={Object.entries(S.by_type).map(([t, b]) => [t, b.rings, b.evaluable, b.evaluable ? `${b.queue_seen} of ${b.evaluable}` : DASH, b.evaluable ? `${b.alert_seen} of ${b.evaluable}` : DASH])} />
        <ul className="text-xs text-muted list-disc pl-5 space-y-1">
          {Object.entries(S.not_evaluable_reasons || {}).map(([k, v]) => <li key={k}>{v} rings: {k}</li>)}
        </ul>
      </Panel>
    </div>
  );
}

function Table2({ head, rows }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead className="text-muted text-left"><tr>{head.map((h) => <th key={h} className="px-3 py-2 font-medium">{h}</th>)}</tr></thead>
        <tbody>{rows.map((r, i) => <tr key={i} className="border-t border-border">{r.map((c, j) => <td key={j} className="px-3 py-2">{c}</td>)}</tr>)}</tbody>
      </table>
    </div>
  );
}
