import React from "react";
import { Link } from "react-router-dom";

// Shared pieces for the warning pages. Every number comes from /api/warnings or /api/pattern-evidence (files written by
// scripts/rebuild_v2.py). A missing value is an em dash, never a remembered number.
export const DASH = "\u2014";
export const isNum = (x) => x !== null && x !== undefined && Number.isFinite(Number(x));
export const num = (x, d = 1) => (isNum(x) ? Number(x).toFixed(d) : DASH);
export const pct = (x, d = 0) => (isNum(x) ? `${(Number(x) * 100).toFixed(d)}%` : DASH);
export const dateOf = (iso) => {
  const d = new Date(iso);
  return iso && !Number.isNaN(d.getTime()) ? d.toLocaleDateString("en-GB", { timeZone: "UTC", day: "2-digit", month: "short", year: "numeric" }) : DASH;
};
export const STATUS_LABEL = { before: "Before completion", at: "At completion", after: "After completion", not_seen: "Not seen" };
export const STATUS_TONE = { before: "text-emerald-500", at: "text-amber-500", after: "text-red-500", not_seen: "text-muted" };

export function Stat({ label, value, sub }) {
  return (
    <div className="rounded-lg border border-border p-4">
      <div className="text-xs text-muted uppercase tracking-wide">{label}</div>
      <div className="text-2xl font-bold mt-1">{value}</div>
      {sub && <div className="text-xs text-muted mt-1 leading-snug">{sub}</div>}
    </div>
  );
}

export function Panel({ title, children, note }) {
  return (
    <div className="rounded-lg border border-border p-4 space-y-3">
      <div className="text-xs font-semibold uppercase tracking-wide">{title}</div>
      {children}
      {note && <p className="text-xs text-muted leading-relaxed">{note}</p>}
    </div>
  );
}

export function Unavailable({ title, command }) {
  return (
    <div className="space-y-4">
      <h1 className="text-xl font-bold">{title}</h1>
      <div className="rounded-lg border border-border p-4 text-sm">
        No results are loaded. Build them, load the database and reload this page:
        <pre className="mt-2 text-xs">{command}</pre>
      </div>
    </div>
  );
}

export const BUILD_COMMAND = "python scripts/rebuild_v2.py all\npython scripts/load_database.py";

// Cards for the Overview: the warnings that were actually given.
export function WarningCards({ warn }) {
  const S = warn?.summary;
  if (!S) return null;
  const evN = S.n_evaluable;
  return (
    <div className="grid grid-cols-1 md:grid-cols-4 gap-3" data-testid="warning-cards">
      <Stat label="Alerts given" value={S.n_alerts} sub={`${S.alerts_with_ring_tx} contain ring transactions, ${S.false_alerts} do not`} />
      <Stat label="Rings warned before completion" value={`${S.alert.before} of ${evN}`} sub={`by alerts; the whole queue: ${S.queue.before} of ${evN}`} />
      <Stat label="First / latest alert" value={dateOf(S.first_alert_date)} sub={`latest ${dateOf(S.last_alert_date)}`} />
      <Stat label="Alert follows creation by" value={`${num(S.median_days_creation_to_alert, 0)} days`} sub="median days from candidate creation to alert" />
    </div>
  );
}

// Score of one candidate over time, with the alert threshold and the day the alert was given.
export function ScoreSpark({ history, threshold, alertDay, firstDate }) {
  const pts = (history || []).filter((h) => isNum(h?.[0]) && isNum(h?.[1]));
  if (!pts.length) return null;
  const W = 520, H = 120, P = 28;
  const days = pts.map((h) => Number(h[0]));
  const d0 = Math.min(...days), d1 = Math.max(...days);
  const top = Math.max(100, ...pts.map((h) => Number(h[1])));
  const x = (d) => P + (d1 === d0 ? (W - 2 * P) / 2 : ((d - d0) / (d1 - d0)) * (W - 2 * P));
  const y = (v) => H - P - (Number(v) / top) * (H - 2 * P);
  const path = pts.map((h, i) => `${i ? "L" : "M"}${x(h[0])},${y(h[1])}`).join(" ");
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full max-w-xl" role="img" aria-label="Risk score over time" data-testid="score-spark">
      <line x1={P} x2={W - P} y1={y(threshold)} y2={y(threshold)} stroke="#f97316" strokeDasharray="4 3" />
      <text x={W - P} y={y(threshold) - 4} fontSize="10" textAnchor="end" fill="#f97316">alert threshold {threshold}</text>
      <path d={path} fill="none" stroke="currentColor" strokeWidth="2" />
      {pts.map((h, i) => <circle key={i} cx={x(h[0])} cy={y(h[1])} r="3" fill="currentColor"><title>{`${dateOf(new Date(Date.parse(firstDate) + Number(h[0]) * 86400000).toISOString())}: score ${num(h[1])}`}</title></circle>)}
      {isNum(alertDay) && <circle cx={x(alertDay)} cy={y(pts.find((h) => Number(h[0]) === Number(alertDay))?.[1] ?? 0)} r="6" fill="none" stroke="#f97316" strokeWidth="2"><title>alert given</title></circle>}
      <text x={P} y={H - 6} fontSize="10" fill="currentColor" opacity="0.6">{dateOf(new Date(Date.parse(firstDate) + d0 * 86400000).toISOString())}</text>
      <text x={W - P} y={H - 6} fontSize="10" textAnchor="end" fill="currentColor" opacity="0.6">{dateOf(new Date(Date.parse(firstDate) + d1 * 86400000).toISOString())}</text>
    </svg>
  );
}

// "Warning given" for one candidate: was an alert raised, when, and (evaluation only) which ring it holds.
export function WarningGivenCard({ id, warn, evidence }) {
  if (!warn?.alerts || !id) return null;
  const thr = warn.protocol?.alert_threshold;
  const alert = warn.alerts.find((a) => a.candidate_ring_id === id);
  const hist = evidence?.risk_factors?.score_history;
  const best = hist?.length ? Math.max(...hist.map((h) => Number(h[1]))) : null;
  const current = hist?.length ? Number(hist[hist.length - 1][1]) : null;
  const hit = (warn.rings || []).find((r) => r.alert?.candidate === id || r.queue?.candidate === id);
  const lvl = hit ? (hit.alert?.candidate === id ? "alert" : "queue") : null;
  return (
    <div className="rounded-lg border border-border p-4 space-y-3" data-testid="warning-given">
      <div className="text-xs font-semibold uppercase tracking-wide">Warning given</div>
      {alert ? (
        <p className="text-sm leading-relaxed">
          <b className="text-orange-500">Alert given on {dateOf(alert.alert_date)}</b>, when the score reached <b>{num(alert.score_at_alert)}</b> (threshold {thr}),{" "}
          {alert.days_creation_to_alert} day(s) after the candidate was created on {dateOf(alert.created_date)}.
          {isNum(current) && current < thr ? ` The score has since fallen to ${num(current)} as evidence accumulated; the alert stays on record.` : ""}
        </p>
      ) : (
        <p className="text-sm leading-relaxed">
          <b>No alert given.</b> {isNum(best) ? `The highest score this candidate has reached is ${num(best)}, below the alert threshold of ${thr}.` : ""}
        </p>
      )}
      <ScoreSpark history={hist} threshold={thr} alertDay={alert?.alert_day} firstDate={warn.protocol?.first_date} />
      {hit && (
        <div className="rounded-md border border-border p-3 text-sm leading-relaxed bg-white/5">
          <div className="text-xs text-muted uppercase tracking-wide mb-1">AMLSim ground truth (used only to evaluate)</div>
          This candidate holds transactions of <b>ring {hit.ring_id}</b> ({hit.type}), which completes on {dateOf(hit.completion_date)}.{" "}
          {hit[lvl].warning_date ? <>The {lvl === "alert" ? "alert" : "candidate warning"} on {dateOf(hit[lvl].warning_date)} came <b>{num(hit[lvl].lead_days, 0)} day(s)</b> {Number(hit[lvl].lead_days) > 0 ? "before" : Number(hit[lvl].lead_days) === 0 ? "at" : "after"} completion.</> : null}
        </div>
      )}
      <p className="text-xs text-muted">
        <Link to="/alert-log" className="underline">All alerts given</Link> | <Link to="/warning-timeline" className="underline">Warnings on every ring</Link>
      </p>
    </div>
  );
}
