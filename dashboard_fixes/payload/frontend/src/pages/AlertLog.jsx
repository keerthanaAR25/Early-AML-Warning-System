import React from "react";
import { Link } from "react-router-dom";
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "../api.js";
import { Loading, ErrorBox, useApi } from "../components/ui.jsx";
import { Stat, Panel, Unavailable, BUILD_COMMAND, num, pct, dateOf, isNum, DASH } from "../components/warnings.jsx";

// Alerts and ring completions per week, from the daily series.
function weekly(daily) {
  const out = [];
  for (let i = 0; i < (daily || []).length; i += 7) {
    const chunk = daily.slice(i, i + 7);
    out.push({ week: dateOf(chunk[0].date), alerts: chunk.reduce((s, d) => s + d.alerts, 0), rings: chunk.reduce((s, d) => s + d.ring_completions, 0) });
  }
  return out;
}

export default function AlertLog() {
  const { data: w, loading, error } = useApi(() => api.warnings(), []);
  const [filter, setFilter] = React.useState("all");
  if (loading) return <Loading text="Loading alerts..." />;
  if (error) return <ErrorBox error={error} />;
  if (!w?.alerts) return <Unavailable title="Alert Log" command={BUILD_COMMAND} />;

  const S = w.summary, thr = w.protocol?.alert_threshold;
  const days = (w.protocol?.last_day ?? 0) - (w.protocol?.scored_from_day ?? 0) + 1;
  const rows = w.alerts.filter((a) => filter === "all" || (filter === "ring" ? a.contains_ring_tx : !a.contains_ring_tx));
  const stillHigh = w.alerts.filter((a) => a.final_score >= thr).length;
  const data = weekly(w.daily);

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-xl font-bold">Alert Log</h1>
        <p className="text-sm text-muted mt-1">Every alert that was given: the day, the score, the evidence at that moment, and what it turned out to be.</p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
        <Stat label="Alerts given" value={S.n_alerts} sub={`over ${days} scored days (one per ${num(days / Math.max(S.n_alerts, 1), 0)} days)`} />
        <Stat label="Alert precision" value={pct(S.alerts_with_ring_tx / Math.max(S.n_alerts, 1))} sub={`${S.alerts_with_ring_tx} contain ring transactions`} />
        <Stat label="False alerts" value={S.false_alerts} sub={`${num(S.false_alerts / days, 4)} per day`} />
        <Stat label="Alert given after creation" value={`${num(S.median_days_creation_to_alert, 0)} days`} sub="median days from candidate creation to alert" />
        <Stat label="First alert" value={dateOf(S.first_alert_date)} />
        <Stat label="Latest alert" value={dateOf(S.last_alert_date)} />
        <Stat label="Still at or above threshold" value={stillHigh} sub={`${S.n_alerts - stillHigh} have since fallen below ${thr}`} />
        <Stat label="Alert threshold" value={thr} sub="risk score, 0 to 100" />
      </div>

      <Panel title="Alerts given and rings completed, per week">
        <div style={{ width: "100%", height: 240 }} data-testid="weekly-chart">
          <ResponsiveContainer>
            <BarChart data={data}>
              <CartesianGrid strokeDasharray="3 3" opacity={0.2} />
              <XAxis dataKey="week" tick={{ fontSize: 10 }} interval={Math.ceil(data.length / 10)} />
              <YAxis allowDecimals={false} tick={{ fontSize: 10 }} />
              <Tooltip />
              <Legend />
              <Bar dataKey="alerts" name="Alerts given" fill="#f97316" />
              <Bar dataKey="rings" name="Rings completed (evaluable)" fill="#94a3b8" />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </Panel>

      <Panel title="Every alert" note="The score changes every day a candidate gains evidence, so the current score can be lower than the score at the alert; the alert stays on record. Ring fields are AMLSim ground truth, used only to evaluate.">
        <div className="flex items-center gap-2 text-sm">
          <label htmlFor="outcome-filter" className="text-muted">Outcome</label>
          <select id="outcome-filter" value={filter} onChange={(e) => setFilter(e.target.value)} className="rounded-md border border-border bg-transparent px-2 py-1">
            <option value="all">All alerts</option><option value="ring">Contains ring transactions</option><option value="false">No ring transactions</option>
          </select>
          <span className="text-xs text-muted">{rows.length} of {w.alerts.length} alerts</span>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-muted text-left"><tr>
              {["Alert date", "Candidate", "Score at alert", "Current score", "Patterns", "Accounts", "Evidence transactions", "Days after creation", "Outcome"].map((h) => <th key={h} className="px-3 py-2 font-medium">{h}</th>)}
            </tr></thead>
            <tbody>
              {rows.map((a) => (
                <tr key={a.candidate_ring_id} className="border-t border-border">
                  <td className="px-3 py-2 whitespace-nowrap">{dateOf(a.alert_date)}</td>
                  <td className="px-3 py-2"><Link className="underline text-accent" to={`/rings?id=${a.candidate_ring_id}`}>{a.candidate_ring_id}</Link></td>
                  <td className="px-3 py-2"><div className="flex items-center gap-2"><div className="h-2 w-16 rounded bg-white/10"><div className="h-2 rounded bg-orange-500" style={{ width: `${Math.min(100, a.score_at_alert)}%` }} /></div>{num(a.score_at_alert)}</div></td>
                  <td className="px-3 py-2">{num(a.final_score)}{a.final_score < thr && <span className="text-xs text-muted"> (below {thr})</span>}</td>
                  <td className="px-3 py-2">{(a.patterns || []).join(", ").replace(/_/g, " ")}</td>
                  <td className="px-3 py-2">{a.n_accounts}</td>
                  <td className="px-3 py-2">{a.n_transactions}</td>
                  <td className="px-3 py-2">{a.days_creation_to_alert}</td>
                  <td className="px-3 py-2">{a.contains_ring_tx
                    ? <>Ring {a.ring_id} ({a.ring_type}){isNum(a.lead_days) ? <>, <b>{num(a.lead_days, 0)} d</b> {Number(a.lead_days) > 0 ? "before" : Number(a.lead_days) === 0 ? "at" : "after"} completion</> : ", ring not evaluable"}</>
                    : <span className="text-red-500">No ring transactions (false alert)</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>
    </div>
  );
}
