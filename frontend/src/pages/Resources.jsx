import React, { useState } from "react";
import { api } from "../api.js";
import { useFetch } from "../hooks.js";
import { toParams } from "../components/FilterBar.jsx";
import { Badge, Card, CpuBar, Empty, ErrorBanner, Kpi, Loading } from "../components/ui.jsx";
import { ago, label, usd } from "../format.js";

export default function Resources({ filters }) {
  const [search, setSearch] = useState("");
  const [state, setState] = useState("all");
  const [sort, setSort] = useState("monthly_cost");
  const p = toParams(filters, { range: false });
  const dep = JSON.stringify(p);
  const summary = useFetch(() => api.utilSummary(p), [dep], 30000);
  const list = useFetch(() => api.resources({ ...p, search, state, sort }), [dep, search, state, sort], 30000);

  const s = summary.data;
  return (
    <>
      <ErrorBanner error={summary.error || list.error} />
      <div className="grid kpis">
        <Kpi title="Resources" value={s ? s.resource_count : "…"} note={s && `${s.running} running · ${s.unattached} unattached`} />
        <Kpi title="Avg CPU (running)" value={s?.avg_cpu_pct != null ? `${s.avg_cpu_pct}%` : "–"} note="Refreshes every 15 min" />
        <Kpi title="Over-utilised" value={s ? s.over_utilized : "…"} tone={s?.over_utilized ? "delta-up" : ""} note="CPU above 85%" />
        <Kpi title="Under-utilised" value={s ? s.under_utilized : "…"} note="CPU below 20%" />
        <Kpi title="Estimated monthly run cost" value={s ? usd(s.tracked_monthly_cost) : "…"} note="Estimated from instance sizes" />
      </div>

      <Card title="Inventory" sub="Costs here are estimates from list prices; billed spend is on Overview"
        actions={
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            <input aria-label="Search resources" placeholder="Search by name…" value={search} onChange={(e) => setSearch(e.target.value)}
              style={{ padding: "6px 9px", border: "1px solid var(--border)", borderRadius: 8, background: "var(--surface)" }} />
            <select aria-label="State" value={state} onChange={(e) => setState(e.target.value)} style={{ padding: "6px 9px", border: "1px solid var(--border)", borderRadius: 8, background: "var(--surface)" }}>
              <option value="all">Any state</option><option value="running">Running</option><option value="stopped">Stopped</option><option value="unattached">Unattached</option>
            </select>
            <select aria-label="Sort" value={sort} onChange={(e) => setSort(e.target.value)} style={{ padding: "6px 9px", border: "1px solid var(--border)", borderRadius: 8, background: "var(--surface)" }}>
              <option value="monthly_cost">Sort: cost</option><option value="cpu">Sort: CPU</option><option value="name">Sort: name</option>
            </select>
          </div>
        }>
        {list.loading && !list.data ? <Loading h={300} /> : !list.data?.length ? <Empty>No resources match these filters.</Empty> : (
          <div className="tablewrap">
            <table>
              <thead><tr><th>Name</th><th>Cloud</th><th>Type</th><th>Size</th><th>Env</th><th>Region</th><th>State</th><th>CPU now</th><th className="r">Est. / month</th><th>Seen</th></tr></thead>
              <tbody>
                {list.data.map((r) => (
                  <tr key={r.provider + r.resource_id}>
                    <td><div style={{ fontWeight: 600 }}>{r.name}</div><div className="muted mono">{r.service}</div></td>
                    <td>{label(r.provider)}</td><td>{label(r.resource_type)}</td><td className="mono">{r.size}</td>
                    <td>{label(r.environment)}</td><td className="muted">{r.region}</td><td><Badge kind={r.state} /></td>
                    <td><CpuBar value={r.cpu_pct} /></td><td className="r num">{usd(r.monthly_cost)}</td><td className="muted">{ago(r.last_seen)}</td>
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
