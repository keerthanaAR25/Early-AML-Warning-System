import React from "react";
import { ScoreSpark, dateOf, num, pct, isNum, DASH } from "./warnings.jsx";

// "Score calculation": how one candidate's risk score was worked out. Everything is read from /api/score-calculation/{id}
// (results/score_calculation.json), which the scoring code writes from its own constants and the inputs it actually used.
export default function ScoreCalculationCard({ calc }) {
  const c = calc?.calculation;
  if (!c?.steps?.length) return null;
  const steps = calc.steps || [];
  const last = steps[steps.length - 1];
  const alertStep = isNum(calc.alert_day) ? steps.find((s) => Number(s.day) === Number(calc.alert_day)) : null;
  const bands = Object.entries(c.level_bands || {}).map(([k, [lo, hi]]) => `${k.toUpperCase()} ${lo}\u2013${hi}`).join(", ");
  return (
    <div className="rounded-lg border border-border p-4 space-y-4" data-testid="score-calculation">
      <div className="text-xs font-semibold uppercase tracking-wide">Score calculation</div>
      <p className="text-sm leading-relaxed">
        How this candidate's risk score of <b>{num(c.score, 2)}</b> was worked out with the evidence available on {dateOf(last?.date)}: <code className="text-xs">{c.formula}</code>.
        Each component is on a 0 to 100 scale.
      </p>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="text-muted text-left"><tr>
            {["Component", "How it was calculated for this candidate", "Value", "Weight", "Points"].map((h) => <th key={h} className="px-3 py-2 font-medium">{h}</th>)}
          </tr></thead>
          <tbody>
            {c.steps.map((st) => (
              <tr key={st.component} className="border-t border-border align-top" data-step={st.component}>
                <td className="px-3 py-2 font-medium whitespace-nowrap">{st.label}</td>
                <td className="px-3 py-2 text-xs leading-relaxed">{st.how}</td>
                <td className="px-3 py-2">{num(st.value, 1)}</td>
                <td className="px-3 py-2">{pct(st.weight)}</td>
                <td className="px-3 py-2">{num(st.points, 2)}</td>
              </tr>
            ))}
            <tr className="border-t border-border font-semibold" data-testid="score-total">
              <td className="px-3 py-2">Risk score</td>
              <td className="px-3 py-2 text-xs font-normal">{c.level} ({bands})</td>
              <td className="px-3 py-2" colSpan={2}></td>
              <td className="px-3 py-2">{num(c.total_points, 2)}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <p className="text-sm leading-relaxed">
        {c.alert
          ? <>The score is at or above the alert threshold of <b>{c.alert_threshold}</b>, so an alert is given.</>
          : alertStep
          ? <>The score is below the alert threshold of {c.alert_threshold} now, but <b>an alert was given on {dateOf(alertStep.date)}</b>, when it reached {num(alertStep.score, 2)}. The alert stays on record.</>
          : <>The score is below the alert threshold of {c.alert_threshold}, so no alert has been given.</>}
      </p>
      <div>
        <div className="text-xs text-muted uppercase tracking-wide mb-1">The same calculation on each day the candidate gained evidence</div>
        <ScoreSpark history={steps.map((s) => [s.day, s.score])} threshold={c.alert_threshold} alertDay={calc.alert_day} firstDate={calc.first_date} />
        <div className="overflow-x-auto mt-2">
          <table className="w-full text-sm">
            <thead className="text-muted text-left"><tr>
              {["Date", "Score", "Behavioural", "Network", "Fund flow", "Persistence", "Patterns", "Evidence transactions", "Accounts"].map((h) => <th key={h} className="px-3 py-2 font-medium">{h}</th>)}
            </tr></thead>
            <tbody>
              {steps.map((s) => (
                <tr key={s.day} className={`border-t border-border ${Number(s.day) === Number(calc.alert_day) ? "bg-orange-500/10" : ""}`} data-day-row={s.day} data-alert-row={Number(s.day) === Number(calc.alert_day) ? "true" : undefined}>
                  <td className="px-3 py-2 whitespace-nowrap">{dateOf(s.date)}{Number(s.day) === Number(calc.alert_day) && <span className="ml-2 text-xs font-semibold text-orange-500">alert</span>}</td>
                  <td className="px-3 py-2">{num(s.score, 2)}</td>
                  <td className="px-3 py-2">{num(s.components?.behavioural, 1)}</td>
                  <td className="px-3 py-2">{num(s.components?.network, 1)}</td>
                  <td className="px-3 py-2">{num(s.components?.fund_flow, 1)}</td>
                  <td className="px-3 py-2">{num(s.components?.persistence, 1)}</td>
                  <td className="px-3 py-2">{(s.patterns || []).join(", ").replace(/_/g, " ") || DASH}</td>
                  <td className="px-3 py-2">{s.n_tx}</td>
                  <td className="px-3 py-2">{s.n_nodes}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
      <p className="text-xs text-muted leading-relaxed">
        Weights, level bands and the alert threshold come from configs/config.yaml. Each row recomputes the score using only the evidence up to that day. The behavioural value comes from a
        model trained only on earlier data, so it is the one component whose inputs are not shown. Points are shown rounded to two decimals and can add up to 0.01 away from the total.
      </p>
    </div>
  );
}
