import React, { useState } from "react";
import { api } from "../api.js";
import { useFetch } from "../hooks.js";
import { toParams } from "../components/FilterBar.jsx";
import { Badge, Card, Empty, ErrorBanner, Kpi, Loading } from "../components/ui.jsx";
import { label, usd } from "../format.js";

const TYPE_HELP = {
  unattached: "Volumes attached to nothing",
  idle: "Running but doing no work",
  rightsize: "Larger than the workload needs",
  schedule: "Non-production running 24/7",
  commitment: "Steady load, eligible for a discount (needs a purchase decision)",
  overused: "Running hot: a reliability risk, not a saving",
};

export default function Optimization({ filters }) {
  const [type, setType] = useState("all");
  const p = toParams(filters, { range: false });
  const dep = JSON.stringify(p);
  const { data, error, loading } = useFetch(() => api.optimization(p), [dep], 60000);

  const s = data?.summary;
  const recs = (data?.recommendations || []).filter((r) => type === "all" || r.type === type);
  return (
    <>
      <ErrorBanner error={error} />
      <div className="grid kpis">
        <Kpi title="Quick wins / month" value={s ? usd(s.quick_wins_monthly) : "…"} tone="delta-down"
          note={s && `${s.quick_wins_pct_of_tracked}% of tracked run cost · no purchase needed`} />
        <Kpi title="Commitment discounts / month" value={s ? usd(s.commitment_monthly) : "…"} note="Savings Plans / RIs / CUDs (estimate)" />
        <Kpi title="Potential per year" value={s ? usd(s.total_annual) : "…"} note="Quick wins + commitments" />
        <Kpi title="Recommendations" value={s ? s.count : "…"} note="One per resource, no double counting" />
      </div>

      <div className="grid three">
        {(s?.by_type || []).map((t) => (
          <button key={t.type} className="card" onClick={() => setType(type === t.type ? "all" : t.type)} aria-pressed={type === t.type}
            style={{ textAlign: "left", cursor: "pointer", borderColor: type === t.type ? "var(--accent)" : undefined }}>
            <h3>{label(t.type)} · {t.count}</h3>
            <div className="num" style={{ fontSize: 20, fontWeight: 650 }}>{t.type === "overused" ? "Risk" : `${usd(t.monthly_savings)}/mo`}</div>
            <div className="muted" style={{ fontSize: 12 }}>{TYPE_HELP[t.type]}</div>
          </button>
        ))}
      </div>

      <Card title={type === "all" ? "All recommendations" : `${label(type)} recommendations`}
        sub="Savings are estimates from list prices and 14-day utilisation. Review before acting."
        actions={type !== "all" && <button className="btn small" onClick={() => setType("all")}>Show all</button>}>
        {loading && !data ? <Loading h={260} /> : !recs.length ? <Empty>Nothing to recommend for these filters.</Empty> : (
          <div className="tablewrap">
            <table>
              <thead><tr><th>Recommendation</th><th>Resource</th><th>Env</th><th className="r">CPU avg / peak</th><th className="r">Now / month</th><th className="r">Saves / month</th><th>Confidence</th></tr></thead>
              <tbody>
                {recs.map((r) => (
                  <tr key={r.id}>
                    <td style={{ maxWidth: 380 }}><div className="rec-title">{r.title}</div><div>{r.action}</div><div className="rec-detail">{r.detail}</div></td>
                    <td><div style={{ fontWeight: 600 }}>{r.name}</div><div className="muted mono">{label(r.provider)} · {r.size}</div></td>
                    <td>{label(r.environment)}</td>
                    <td className="r num">{r.avg_cpu_pct != null ? `${r.avg_cpu_pct}% / ${r.peak_cpu_pct}%` : "–"}</td>
                    <td className="r num">{usd(r.monthly_cost)}</td>
                    <td className="r num" style={{ fontWeight: 600 }}>{r.type === "overused" ? "–" : usd(r.estimated_monthly_savings)}</td>
                    <td><Badge kind={r.confidence} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </>
  );
}
