import React, { useState } from "react";
import { Area, AreaChart, Bar, BarChart, CartesianGrid, Cell, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "../api.js";
import { useFetch } from "../hooks.js";
import { toParams } from "../components/FilterBar.jsx";
import { Badge, Card, ChartTip, Empty, ErrorBanner, Kpi, Legend, Loading, Seg } from "../components/ui.jsx";
import { colorFor, label, pct, shortDate, usd } from "../format.js";

const GROUPS = ["provider", "environment", "resource_type", "service"];

export default function Overview({ filters }) {
  const [group, setGroup] = useState("provider");
  const p = toParams(filters);
  const dep = JSON.stringify(p);
  const summary = useFetch(() => api.summary(p), [dep], 60000);
  const series = useFetch(() => api.timeseries({ ...p, group_by: group }), [dep, group], 60000);
  const byProv = useFetch(() => api.breakdown({ ...p, group_by: "provider" }), [dep]);
  const byEnv = useFetch(() => api.breakdown({ ...p, group_by: "environment" }), [dep]);
  const byType = useFetch(() => api.breakdown({ ...p, group_by: "resource_type" }), [dep]);
  const anomalies = useFetch(() => api.anomalies(p), [dep], 60000);

  const s = summary.data;
  const changeTone = s?.change_pct == null ? "" : s.change_pct > 5 ? "delta-up" : s.change_pct < -5 ? "delta-down" : "";
  const keys = series.data?.series || [];

  return (
    <>
      <ErrorBanner error={summary.error || series.error} />
      <div className="grid kpis">
        <Kpi title="Spend in period" value={s ? usd(s.total_cost) : "…"}
          note={s && <span className={changeTone}>{s.change_pct == null ? "No prior period" : `${pct(s.change_pct)} vs previous ${s.days} days`}</span>} />
        <Kpi title="Month to date" value={s ? usd(s.month_to_date) : "…"} note={s && `${s.days_remaining} days left in month`} />
        <Kpi title="Projected month end" value={s ? usd(s.projected_month_end) : "…"} note={s && `at ${usd(s.daily_run_rate)}/day (7-day run rate)`} />
        <Kpi title="Latest day" value={s ? usd(s.latest_day_cost) : "…"} note={s && `avg ${usd(s.avg_daily_cost)}/day in period`} />
        <Kpi title="Top service" value={s?.top_service ? s.top_service.name : "–"} note={s?.top_service && usd(s.top_service.cost)} />
      </div>

      <div style={{ marginBottom: 14 }}>
        <Card title="Daily cost" sub="Stacked by the dimension you pick"
          actions={<Seg value={group} options={GROUPS} onChange={setGroup} />}>
          {series.loading && !series.data ? <Loading h={280} /> : !series.data?.data.length ? <Empty>No cost data for these filters.</Empty> : (
            <>
              <ResponsiveContainer width="100%" height={280}>
                <AreaChart data={series.data.data} margin={{ left: 0, right: 8, top: 8 }}>
                  <CartesianGrid stroke="var(--grid)" vertical={false} />
                  <XAxis dataKey="date" tickFormatter={shortDate} tick={{ fontSize: 11, fill: "var(--muted)" }} minTickGap={24} axisLine={false} tickLine={false} />
                  <YAxis tickFormatter={(v) => usd(v)} tick={{ fontSize: 11, fill: "var(--muted)" }} width={56} axisLine={false} tickLine={false} />
                  <Tooltip content={<ChartTip fmt={(v) => usd(v, 2)} labelFmt={shortDate} />} />
                  {keys.map((k, i) => (
                    <Area key={k} type="monotone" dataKey={k} stackId="1" stroke={colorFor(k, i)} fill={colorFor(k, i)} fillOpacity={0.75} strokeWidth={1} />
                  ))}
                </AreaChart>
              </ResponsiveContainer>
              <Legend items={keys.map((k, i) => [k, colorFor(k, i)])} />
            </>
          )}
        </Card>
      </div>

      <div className="grid three">
        <Share title="By cloud" data={byProv.data} loading={byProv.loading} donut />
        <Share title="By environment" data={byEnv.data} loading={byEnv.loading} />
        <Share title="By resource type" data={byType.data} loading={byType.loading} />
      </div>

      <Card title="Cost anomalies" sub="Days where spend is far above the service's recent baseline">
        {!anomalies.data ? <Loading h={80} /> : anomalies.data.length === 0 ? <Empty>No anomalies detected in the last 7 days.</Empty> : (
          <div className="tablewrap">
            <table>
              <thead><tr><th>Date</th><th>Cloud</th><th>Service</th><th>Env</th><th className="r">Cost</th><th className="r">Expected</th><th className="r">Over</th><th>Severity</th></tr></thead>
              <tbody>
                {anomalies.data.map((a) => (
                  <tr key={a.date + a.provider + a.service + a.environment}>
                    <td>{shortDate(a.date)}</td><td>{label(a.provider)}</td><td>{a.service}</td><td>{label(a.environment)}</td>
                    <td className="r num">{usd(a.cost, 2)}</td><td className="r num">{usd(a.expected, 2)}</td>
                    <td className="r num">+{usd(a.delta, 2)} ({a.pct_over.toFixed(0)}%)</td><td><Badge kind={a.severity} /></td>
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

function Share({ title, data, loading, donut }) {
  return (
    <Card title={title}>
      {loading && !data ? <Loading h={180} /> : !data?.length ? <Empty>No data</Empty> : donut ? (
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <ResponsiveContainer width={150} height={150}>
            <PieChart>
              <Pie data={data} dataKey="cost" nameKey="key" innerRadius={42} outerRadius={68} paddingAngle={2} stroke="none">
                {data.map((d, i) => <Cell key={d.key} fill={colorFor(d.key, i)} />)}
              </Pie>
              <Tooltip content={<ChartTip fmt={(v) => usd(v)} />} />
            </PieChart>
          </ResponsiveContainer>
          <Rows data={data} />
        </div>
      ) : <Rows data={data} bars />}
    </Card>
  );
}

function Rows({ data, bars }) {
  return (
    <div style={{ flex: 1, display: "grid", gap: 9 }}>
      {data.slice(0, 8).map((d, i) => (
        <div key={d.key}>
          <div style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
            <span><i style={{ display: "inline-block", width: 9, height: 9, borderRadius: 2, background: colorFor(d.key, i), marginRight: 6 }} />{label(d.key)}</span>
            <span className="num">{usd(d.cost)} <span className="muted">· {d.share_pct.toFixed(0)}%</span></span>
          </div>
          {bars && <div className="bar" style={{ marginTop: 4 }}><i style={{ width: `${d.share_pct}%`, background: colorFor(d.key, i) }} /></div>}
        </div>
      ))}
    </div>
  );
}
