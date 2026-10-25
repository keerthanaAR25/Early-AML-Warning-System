import React, { useMemo } from "react";
import { api } from "../api.js";
import { Loading, ErrorBox, RiskBadge, useApi } from "../components/ui.jsx";
import { ProductionNote } from "../components/ResultStatus.jsx";
import { dateOf, num } from "../components/warnings.jsx";
import { extraTypes, nameOf } from "../components/SupportingPatterns.jsx";
import { Link } from "react-router-dom";

function riskBar(score) {
  const value = Number(score);
  if (!Number.isFinite(value)) return null;

  return (
    <div className="w-24">
      <div className="h-1.5 rounded-full bg-border overflow-hidden">
        <div
          className="h-full rounded-full"
          style={{ width: `${Math.min(100, Math.max(0, value))}%` }}
        />
      </div>
    </div>
  );
}

function StageBadge({ stage }) {
  const styles = {
    OBSERVABLE_RING: "bg-red-500/10 text-red-400 border-red-500/20",
    EMERGING: "bg-orange-500/10 text-orange-400 border-orange-500/20",
    FORMING: "bg-yellow-500/10 text-yellow-400 border-yellow-500/20",
    WATCH: "bg-blue-500/10 text-blue-400 border-blue-500/20",
  };

  const label = stage || "UNKNOWN";

  return (
    <span
      className={`inline-flex items-center rounded-md border px-2 py-1 text-xs font-medium ${
        styles[label] || "bg-muted/10 text-muted border-border"
      }`}
    >
      {label.replaceAll("_", " ")}
    </span>
  );
}

function Priority({ score }) {
  const value = Number(score);

  if (!Number.isFinite(value)) {
    return <span className="text-muted text-xs">—</span>;
  }

  if (value >= 75) {
    return (
      <span className="text-xs font-semibold text-red-400">
        CRITICAL
      </span>
    );
  }

  if (value >= 50) {
    return (
      <span className="text-xs font-semibold text-orange-400">
        HIGH
      </span>
    );
  }

  if (value >= 25) {
    return (
      <span className="text-xs font-semibold text-yellow-400">
        MODERATE
      </span>
    );
  }

  return (
    <span className="text-xs font-semibold text-muted">
      LOW
    </span>
  );
}

export default function AlertQueue() {
  const { data, loading, error } = useApi(
    () => api.alerts({ limit: 1000 }),
    []
  );
  const { data: summaryData } = useApi(() => api.summary(), []);
  const { data: lt } = useApi(() => api.leadTime(), []);
  const { data: warn } = useApi(() => api.warnings(), []);
  const alertOf = React.useMemo(() => Object.fromEntries((warn?.alerts || []).map((a) => [a.candidate_ring_id, a])), [warn]);
  const { data: sp } = useApi(() => api.supportingPatterns(), []);
  const [patternFilter, setPatternFilter] = React.useState("all");
  const [multiOnly, setMultiOnly] = React.useState(false);
  const [alertOnly, setAlertOnly] = React.useState(false);

  const alerts = useMemo(() => {
    if (!Array.isArray(data)) return [];

    return [...data].sort(
      (a, b) => Number(b.risk_score || 0) - Number(a.risk_score || 0)
    );
  }, [data]);

  if (loading) return <Loading />;
  if (error) return <ErrorBox error={error} />;

  // the queue lists every candidate; these filters narrow it without changing any score
  const patternNames = [...new Set(alerts.flatMap((r) => (Array.isArray(r.patterns) ? r.patterns : [])))].sort();
  const rows = alerts.filter((r) => {
    const p = Array.isArray(r.patterns) ? r.patterns : [];
    return (patternFilter === "all" || p.includes(patternFilter)) && (!multiOnly || p.length >= 2) && (!alertOnly || Boolean(alertOf[r.candidate_ring_id]));
  });

  const highCount = alerts.filter(
    (r) => Number(r.risk_score) >= 50
  ).length;

  const criticalCount = alerts.filter(
    (r) => Number(r.risk_score) >= 75
  ).length;

  return (
    <div className="space-y-5">

      {/* Header */}
      <div>
        <div className="flex items-center justify-between gap-4">
          <div>
            <h1 className="text-xl font-bold">
              Investigator Alert Queue
            </h1>

            <p className="text-sm text-muted mt-1">
              Prioritized suspicious-ring candidates requiring
              investigator review.
            </p>
          </div>

          <div className="text-right">
            <div className="text-2xl font-bold">
               {rows.length} <span className="text-sm font-normal text-muted">of {Number.isFinite(Number(summaryData?.candidate_rings)) ? Number(summaryData.candidate_rings) : "—"}</span>
            </div>
            <div className="text-xs text-muted">
                candidates shown
            </div>
          </div>
        </div>
      </div>

      <ProductionNote lt={lt} />

      {/* Summary cards */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
        <div className="rounded-lg border border-border p-4" data-testid="alerts-given-card">
          <div className="text-xs text-muted uppercase tracking-wide">Alerts given</div>
          <div className="text-2xl font-bold mt-1">{warn?.summary ? warn.summary.n_alerts : "\u2014"}</div>
          <div className="text-xs text-muted mt-1">score reached {warn?.protocol?.alert_threshold ?? "\u2014"} at some point (see Alert Log)</div>
        </div>

        <div className="rounded-lg border border-border p-4">
          <div className="text-xs text-muted uppercase tracking-wide">
            High / Critical
          </div>

          <div className="text-2xl font-bold mt-1">
            {highCount}
          </div>

          <div className="text-xs text-muted mt-1">
            prioritized for investigation
          </div>
        </div>

        <div className="rounded-lg border border-border p-4">
          <div className="text-xs text-muted uppercase tracking-wide">
            Critical
          </div>

          <div className="text-2xl font-bold mt-1">
            {criticalCount}
          </div>

          <div className="text-xs text-muted mt-1">
            risk score ≥ 75
          </div>
        </div>

        <div className="rounded-lg border border-border p-4">
          <div className="text-xs text-muted uppercase tracking-wide">
            Queue purpose
          </div>

          <div className="text-sm font-medium mt-2">
            Evidence-led triage
          </div>

          <div className="text-xs text-muted mt-1">
            Candidates are analytical signals, not confirmed laundering.
          </div>
        </div>

      </div>

      {/* Investigator note */}
      <div className="rounded-lg border border-border bg-muted/5 px-4 py-3">
        <div className="text-xs font-semibold uppercase tracking-wide">
          Investigation guidance
        </div>

        <p className="text-xs text-muted mt-1 leading-relaxed">
          Start with higher-risk candidates and review their transaction
          evidence, suspicious patterns, temporal trajectory and network
          relationships before making an investigative decision.
        </p>
      </div>

      {/* Filters */}
      <div className="flex flex-wrap items-center gap-4 rounded-lg border border-border p-3 text-sm" data-testid="queue-filters">
        <label className="flex items-center gap-2">
          <span className="text-muted">Pattern</span>
          <select id="pattern-filter" value={patternFilter} onChange={(e) => setPatternFilter(e.target.value)} className="rounded-md border border-border bg-transparent px-2 py-1">
            <option value="all">All patterns</option>
            {patternNames.map((p) => <option key={p} value={p}>{nameOf(p)}</option>)}
          </select>
        </label>
        <label className="flex items-center gap-2"><input id="multi-filter" type="checkbox" checked={multiOnly} onChange={(e) => setMultiOnly(e.target.checked)} /> 2 or more patterns</label>
        <label className="flex items-center gap-2"><input id="alert-only-filter" type="checkbox" checked={alertOnly} onChange={(e) => setAlertOnly(e.target.checked)} /> Alert given</label>
        <span className="text-xs text-muted">{rows.length} of {alerts.length} candidates</span>
      </div>

      {/* Queue */}
      <div className="rounded-lg border border-border overflow-hidden">

        <div className="overflow-x-auto">

          <table className="w-full text-sm">

            <thead className="bg-muted/5 text-muted text-left">
              <tr>
                <th className="px-4 py-3 font-medium">
                  Ring Candidate
                </th>

                <th className="px-4 py-3 font-medium">
                  Risk
                </th>

                <th className="px-4 py-3 font-medium">
                  Priority
                </th>

                <th className="px-4 py-3 font-medium">
                  Stage
                </th>

                <th className="px-4 py-3 font-medium">
                  Accounts
                </th>

                <th className="px-4 py-3 font-medium">
                  Patterns
                </th>

                <th className="px-4 py-3 font-medium">
                  Alert
                </th>

                <th className="px-4 py-3 font-medium">
                  Investigation
                </th>
              </tr>
            </thead>

            <tbody>

              {rows.map((r) => {

                const score = Number(r.risk_score);

                const patternList = Array.isArray(r.patterns)
                  ? r.patterns
                  : [];

                const patternCount =
                  r.pattern_diversity ??
                  r.pattern_count ??
                  patternList.length;

                return (
                  <tr
                    key={r.candidate_ring_id}
                    className="border-t border-border hover:bg-muted/5 transition-colors"
                  >

                    {/* Ring */}
                    <td className="px-4 py-3">

                      <Link
                        className="font-semibold text-accent hover:underline"
                        to={`/rings?id=${r.candidate_ring_id}`}
                      >
                        {r.candidate_ring_id}
                      </Link>

                      <div className="text-xs text-muted mt-1">
                        {r.evidence_event_count
                          ? `${r.evidence_event_count} evidence events`
                          : "Review evidence"}
                      </div>

                    </td>

                    {/* Risk */}
                    <td className="px-4 py-3">

                      <div className="flex items-center gap-3">

                        <div>
                          <div className="font-semibold">
                            {Number.isFinite(score)
                              ? score.toFixed(1)
                              : "—"}
                          </div>

                          <div className="text-xs text-muted">
                            / 100
                          </div>
                        </div>

                        {riskBar(score)}

                      </div>

                    </td>

                    {/* Priority */}
                    <td className="px-4 py-3">
                      <Priority score={score} />
                    </td>

                    {/* Stage */}
                    <td className="px-4 py-3">
                      <StageBadge
                        stage={r.formation_stage}
                      />
                    </td>

                    {/* Accounts */}
                    <td className="px-4 py-3">
                      <div className="font-medium">
                        {r.n_accounts ?? "—"}
                      </div>

                      <div className="text-xs text-muted">
                        linked accounts
                      </div>
                    </td>

                    {/* Patterns */}
                    <td className="px-4 py-3 max-w-xs">

                      <div className="flex flex-wrap gap-1">

                        {patternList.length > 0 ? (
                          patternList.map((pattern) => (
                            <span
                              key={pattern}
                              className="rounded-md border border-border px-2 py-0.5 text-[11px]"
                            >
                              {pattern.replaceAll("_", " ")}
                            </span>
                          ))
                        ) : (
                          <span className="text-muted">
                            No pattern details
                          </span>
                        )}

                      </div>

                      {patternCount > 0 && (
                        <div className="text-xs text-muted mt-1">
                          {patternCount} pattern type
                          {patternCount !== 1 ? "s" : ""}
                        </div>
                      )}

                      {extraTypes(sp, r.candidate_ring_id).length > 0 && (
                        <div className="text-[11px] text-muted mt-1" data-testid="supporting-line">
                          Also seen on these accounts: {extraTypes(sp, r.candidate_ring_id).map(nameOf).join(", ")} (not in the score)
                        </div>
                      )}

                    </td>

                    {/* Alert given */}
                    <td className="px-4 py-3 text-xs">
                      {alertOf[r.candidate_ring_id] ? (
                        <div data-testid="alert-cell">
                          <div className="font-semibold text-orange-500">Alert {dateOf(alertOf[r.candidate_ring_id].alert_date)}</div>
                          <div className="text-muted">score {num(alertOf[r.candidate_ring_id].score_at_alert)} at alert</div>
                        </div>
                      ) : (
                        <span className="text-muted">No alert</span>
                      )}
                    </td>

                    {/* Investigation */}
                    <td className="px-4 py-3">

                      <Link
                        to={`/rings?id=${r.candidate_ring_id}`}
                        className="inline-flex items-center rounded-md border border-border px-3 py-1.5 text-xs font-medium hover:bg-muted/10"
                      >
                        Investigate →
                      </Link>

                    </td>

                  </tr>
                );
              })}

              {rows.length === 0 && (
                <tr>
                  <td
                    className="px-4 py-8 text-center text-muted"
                    colSpan={8}
                  >
                    No high-risk candidates are currently available.
                  </td>
                </tr>
              )}

            </tbody>

          </table>

        </div>

      </div>

      {/* Footer disclaimer */}
      <div className="text-xs text-muted leading-relaxed">
        Risk scores represent analytical prioritization based on observed
        behavioural, network, fund-flow and persistence signals. Formation
        stages describe evidence maturity and do not constitute legal
        confirmation of money laundering.
      </div>

    </div>
  );
}