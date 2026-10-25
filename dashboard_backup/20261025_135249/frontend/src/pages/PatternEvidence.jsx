import React from "react";
import { Link } from "react-router-dom";
import { api } from "../api.js";
import { Loading, ErrorBox, useApi } from "../components/ui.jsx";
import { Stat, Panel, Unavailable, BUILD_COMMAND, num, pct, dateOf, isNum, DASH } from "../components/warnings.jsx";

const label = (arr) => (arr || []).join(" + ").replace(/_/g, " ");

function Table({ head, rows }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead className="text-muted text-left"><tr>{head.map((h) => <th key={h} className="px-3 py-2 font-medium">{h}</th>)}</tr></thead>
        <tbody>{rows.map((r, i) => <tr key={i} className="border-t border-border">{r.map((c, j) => <td key={j} className="px-3 py-2">{c}</td>)}</tr>)}</tbody>
      </table>
    </div>
  );
}

export default function PatternEvidence() {
  const { data: P, loading, error } = useApi(() => api.patternEvidence(), []);
  if (loading) return <Loading text="Loading pattern evidence..." />;
  if (error) return <ErrorBox error={error} />;
  if (!P?.by_count) return <Unavailable title="Pattern Evidence" command={BUILD_COMMAND} />;

  const n = P.n_candidates, W = P.component_weights || {};
  const sp = P.spearman_count_vs_score;
  const top = (P.by_set || [])[0];
  const multiRows = (P.by_count || []).filter((r) => r.n_patterns >= 2);
  const multiTx = multiRows.reduce((s, r) => s + r.mean_evidence_tx * r.candidates, 0) / Math.max(1, multiRows.reduce((s, r) => s + r.candidates, 0));
  const single = (P.by_count || []).find((r) => r.n_patterns === 1);
  const highSingle = single?.high ?? 0;
  const highAll = (P.by_count || []).reduce((s, r) => s + r.high + r.critical, 0);
  const contrib = P.pattern_contributions || [];
  const addMin = Math.min(...contrib.map((c) => c.score_points)), addMax = Math.max(...contrib.map((c) => c.score_points));
  const beh = (P.by_set || []).map((r) => r.mean_behavioural).filter(isNum);
  const behPoints = beh.length ? (Math.max(...beh) - Math.min(...beh)) * (W.behavioural ?? 0) : null;
  const multiContain = (P.multi_pattern || []).filter((m) => m.contains_ring_tx).length;

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-xl font-bold">Pattern Evidence</h1>
        <p className="text-sm text-muted mt-1">How the number and kind of patterns relate to the risk score and to the alerts that were given.</p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
        <Stat label="One pattern" value={P.single_pattern_candidates} sub={`${pct(P.single_pattern_candidates / n, 1)} of ${n} candidates`} />
        <Stat label="Two or more patterns" value={P.multi_pattern_candidates} sub={`${pct(P.multi_pattern_candidates / n, 1)} of the candidates`} />
        <Stat label="Alerts on one pattern" value={`${P.alerts_on_single_pattern} of ${P.alerts_on_single_pattern + P.alerts_on_multi_pattern}`} sub={`${P.alerts_on_multi_pattern} on candidates with several patterns`} />
        <Stat label="Pattern count vs score" value={isNum(sp?.rho) ? `rho ${num(sp.rho, 2)}` : DASH} sub={isNum(sp?.p) ? `Spearman, p = ${num(sp.p, 2)}` : "not available"} />
      </div>

      <Panel title="What the data says">
        <ul className="text-sm leading-relaxed list-disc pl-5 space-y-2">
          <li>{P.single_pattern_candidates} of {n} candidates show a single pattern, and {highSingle} of the {highAll} candidates scoring {P.alert_threshold} or more are among them.
            An alert is therefore normally given on one pattern.</li>
          <li>The number of patterns does not drive the score{isNum(sp?.rho) ? ` (Spearman ${num(sp.rho, 2)}, p = ${num(sp.p, 2)})` : ""}. What drives it is <b>which</b> pattern: {top ? <>the highest-scoring type is <b>{label(top.patterns)}</b> (mean {num(top.mean_score)}, {top.alerts_given} alerts).</> : DASH}</li>
          <li>A further pattern adds only {num(addMin)} to {num(addMax)} score points (fund-flow component), while the behavioural component moves the score by up to {num(behPoints)} points between pattern types.
            That is why candidates with several patterns can score lower than a single closed cycle.</li>
          <li>{multiContain} of the {P.multi_pattern_candidates} candidates with several patterns contain ring transactions, but they are also the largest candidates (mean {num(multiTx)} evidence transactions against {num(single?.mean_evidence_tx)}),
            so with this few cases pattern count and size cannot be separated. This is a lead to test on more data, not a rule.</li>
          <li>{(P.notes || [])[1]}</li>
        </ul>
      </Panel>

      <Panel title="By number of patterns" note="Ring-transaction fields are AMLSim ground truth, used only to evaluate.">
        <Table head={["Patterns", "Candidates", "Mean score", "Score range", "Alerts given", "HIGH", "MODERATE", "Contain ring transactions", "Mean evidence transactions"]}
          rows={P.by_count.map((r) => [r.n_patterns, r.candidates, num(r.mean_score), `${num(r.min_score)} to ${num(r.max_score)}`, r.alerts_given, r.high + r.critical, r.moderate,
            `${r.contain_ring_tx} (${pct(r.share_containing_ring_tx)})`, num(r.mean_evidence_tx)])} />
      </Panel>

      <Panel title="By pattern type: what makes up the score" note="Mean of each score component (0 to 100). The component weights are shown in the header.">
        <Table head={["Patterns", "Candidates", "Mean score", "Alerts given", `Behavioural (${pct(W.behavioural)})`, `Network (${pct(W.network)})`, `Fund flow (${pct(W.fund_flow)})`, `Persistence (${pct(W.persistence)})`, "Contain ring transactions"]}
          rows={P.by_set.map((r) => [label(r.patterns), r.candidates, num(r.mean_score), r.alerts_given, num(r.mean_behavioural), num(r.mean_network), num(r.mean_fund_flow), num(r.mean_persistence), `${r.contain_ring_tx} (${pct(r.share_containing_ring_tx)})`])} />
      </Panel>

      <Panel title="What each pattern adds to the score" note="Weights come from the scoring engine. A pattern's points are its weight divided by the sum of all weights, scaled to 100, times the fund-flow weight. A closed cycle also scores 100 on the network component.">
        <Table head={["Pattern", "Weight", "Fund-flow points (of 100)", "Score points"]}
          rows={contrib.map((c) => [String(c.pattern).replace(/_/g, " "), num(c.weight), num(c.fund_flow_points), `+${num(c.score_points)}`])} />
      </Panel>

      <Panel title="Pattern count and evidence size" note="Larger candidates are more likely to contain a ring transaction whatever their patterns, so the two groups should be compared at the same size.">
        <Table head={["Evidence size", "One pattern: candidates", "One pattern: contain ring tx", "Several patterns: candidates", "Several patterns: contain ring tx"]}
          rows={P.by_size.map((r) => [r.size, r.single_pattern, `${r.single_contain} (${pct(r.single_pattern ? r.single_contain / r.single_pattern : null)})`, r.multi_pattern, r.multi_pattern ? `${r.multi_contain} (${pct(r.multi_contain / r.multi_pattern)})` : DASH])} />
      </Panel>

      <Panel title="Candidates with several patterns" note="Alert date and score at alert are shown where an alert was given; the current score can be lower because scores are recomputed as evidence accumulates.">
        <Table head={["Candidate", "Patterns", "Current score", "Level", "Alert given", "Evidence transactions", "Behavioural", "Network", "Fund flow", "Persistence", "Contains ring tx"]}
          rows={(P.multi_pattern || []).map((m) => [<Link key={m.candidate_ring_id} className="underline text-accent" to={`/rings?id=${m.candidate_ring_id}`}>{m.candidate_ring_id}</Link>, label(m.patterns), num(m.current_score), m.current_level,
            m.alert_date ? `${dateOf(m.alert_date)} (score ${num(m.score_at_alert)})` : "No alert", m.n_tx, num(m.components.behavioural), num(m.components.network), num(m.components.fund_flow), num(m.components.persistence), m.contains_ring_tx ? "Yes" : "No"])} />
      </Panel>
    </div>
  );
}
