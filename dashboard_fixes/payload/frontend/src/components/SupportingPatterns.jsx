import React from "react";
import { dateOf, num, pct, isNum, DASH } from "./warnings.jsx";

// Other patterns the ORIGINAL detectors saw on a candidate's accounts. Context only: not used in any candidate or score.
// Everything is read from /api/supporting-patterns (results/supporting_patterns.json).
export const nameOf = (p) => String(p).replace(/_/g, " ");

export function supportingFor(sp, id) {
  return sp?.candidates?.[id] || null;
}

// the types worth showing next to a candidate's own patterns in a list
export function extraTypes(sp, id) {
  return (supportingFor(sp, id)?.types || []).filter((t) => !t.also_in_candidate).map((t) => t.pattern);
}

export function SupportingCaption({ sp }) {
  const S = sp?.summary;
  if (!S) return null;
  return (
    <p className="text-xs text-muted leading-relaxed" data-testid="supporting-caption">
      Seen on {S.with_any_supporting_pattern} of {S.n_candidates} candidates, so their presence says little. Candidates that contain ring transactions show {num(S.mean_types?.ring_containing, 1)} types on average,
      against {num(S.mean_types?.others, 1)} for the others, and a ring transaction's sender shows one {pct(S.sender_level?.share_ring)} of the time, against {pct(S.sender_level?.share_normal)} for a normal transaction
      (AMLSim ground truth, used only to evaluate). They are context, not evidence of a ring.
    </p>
  );
}

export function SupportingPatternsCard({ sp, id }) {
  if (!sp?.candidates || !id) return null;
  const c = supportingFor(sp, id);
  return (
    <div className="rounded-lg border border-border p-4 space-y-3" data-testid="supporting-patterns">
      <div className="text-xs font-semibold uppercase tracking-wide">Other patterns seen on these accounts</div>
      <p className="text-sm leading-relaxed">
        Seen by the original detectors on this candidate's accounts, {sp.protocol?.window}. Shown for context; <b>not used in the score</b>.
      </p>
      {c && c.types.length ? (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-muted text-left"><tr>
              {["Pattern", "Events", "Accounts involved", "First seen", "Last seen", "Also found by this candidate's own detector"].map((h) => <th key={h} className="px-3 py-2 font-medium">{h}</th>)}
            </tr></thead>
            <tbody>
              {c.types.map((t) => (
                <tr key={t.pattern} className="border-t border-border" data-supporting={t.pattern}>
                  <td className="px-3 py-2 font-medium">{nameOf(t.pattern)}</td>
                  <td className="px-3 py-2">{t.events}</td>
                  <td className="px-3 py-2">{t.accounts_involved}</td>
                  <td className="px-3 py-2">{dateOf(t.first_date)}</td>
                  <td className="px-3 py-2">{dateOf(t.last_date)}</td>
                  <td className="px-3 py-2">{t.also_in_candidate ? "Yes" : "No"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="text-sm">No other patterns were seen on these accounts.</p>
      )}
      <SupportingCaption sp={sp} />
    </div>
  );
}
