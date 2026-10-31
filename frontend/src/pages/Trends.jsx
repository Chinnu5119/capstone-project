import React, { useState } from "react";
import { Bar, BarChart, CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "../api.js";
import { useFetch } from "../hooks.js";
import { toParams } from "../components/FilterBar.jsx";
import { Badge, Card, ChartTip, Empty, ErrorBanner, Legend, Loading, Seg } from "../components/ui.jsx";
import { colorFor, monthLabel, pct, shortDate, usd } from "../format.js";

const UTIL_GROUPS = ["provider", "environment", "resource_type"];

export default function Trends({ filters }) {
  const [ugroup, setUgroup] = useState("provider");
  const p = toParams(filters);
  const dep = JSON.stringify(p);
  const monthly = useFetch(() => api.monthly({ ...p, months: 6 }), [dep]);
  const util = useFetch(() => api.utilSeries({ ...p, group_by: ugroup }), [dep, ugroup]);
  const total = useFetch(() => api.timeseries({ ...p, group_by: "none" }), [dep]);
  const services = useFetch(() => api.breakdown({ ...p, group_by: "service" }), [dep]);

  const m = monthly.data || [];
  const providers = [...new Set(m.flatMap((x) => Object.keys(x.by_provider)))];
  const chartM = m.map((x) => ({ month: x.month, ...x.by_provider }));
  const ukeys = util.data?.series || [];

  return (
    <>
      <ErrorBanner error={monthly.error || util.error} />
      <div className="grid two">
        <Card title="Monthly cost" sub="Stacked by cloud. The newest month may be partial.">
          {monthly.loading && !monthly.data ? <Loading /> : !m.length ? <Empty>No data</Empty> : (
            <>
              <ResponsiveContainer width="100%" height={240}>
                <BarChart data={chartM}>
                  <CartesianGrid stroke="var(--grid)" vertical={false} />
                  <XAxis dataKey="month" tickFormatter={monthLabel} tick={{ fontSize: 11, fill: "var(--muted)" }} axisLine={false} tickLine={false} />
                  <YAxis tickFormatter={(v) => usd(v)} tick={{ fontSize: 11, fill: "var(--muted)" }} width={56} axisLine={false} tickLine={false} />
                  <Tooltip content={<ChartTip fmt={(v) => usd(v)} labelFmt={monthLabel} />} cursor={{ fill: "var(--surface-2)" }} />
                  {providers.map((k, i) => <Bar key={k} dataKey={k} stackId="m" fill={colorFor(k, i)} />)}
                </BarChart>
              </ResponsiveContainer>
              <Legend items={providers.map((k, i) => [k, colorFor(k, i)])} />
            </>
          )}
        </Card>

        <Card title="Month-over-month" sub="Compared on average spend per day, so partial months are fair">
          {!m.length ? <Loading h={120} /> : (
            <div className="tablewrap">
              <table>
                <thead><tr><th>Month</th><th className="r">Total</th><th className="r">Avg / day</th><th className="r">Change</th></tr></thead>
                <tbody>
                  {[...m].reverse().map((x) => (
                    <tr key={x.month}>
                      <td>{monthLabel(x.month)} {x.partial && <Badge kind="info">{x.days_with_data} days</Badge>}</td>
                      <td className="r num">{usd(x.total)}</td><td className="r num">{usd(x.avg_daily)}</td>
                      <td className={`r num ${x.mom_change_pct > 5 ? "delta-up" : x.mom_change_pct < -5 ? "delta-down" : ""}`}>{pct(x.mom_change_pct)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      </div>

      <div className="grid two">
        <Card title="Total daily cost" sub="Selected period">
          {!total.data ? <Loading h={220} /> : (
            <ResponsiveContainer width="100%" height={220}>
              <LineChart data={total.data.data}>
                <CartesianGrid stroke="var(--grid)" vertical={false} />
                <XAxis dataKey="date" tickFormatter={shortDate} tick={{ fontSize: 11, fill: "var(--muted)" }} minTickGap={24} axisLine={false} tickLine={false} />
                <YAxis tickFormatter={(v) => usd(v)} tick={{ fontSize: 11, fill: "var(--muted)" }} width={56} axisLine={false} tickLine={false} domain={["auto", "auto"]} />
                <Tooltip content={<ChartTip fmt={(v) => usd(v, 2)} labelFmt={shortDate} />} />
                <Line type="monotone" dataKey="total" name="Total" stroke="var(--accent)" strokeWidth={2} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          )}
        </Card>

        <Card title="Average CPU utilisation" sub="Daily average across running resources"
          actions={<Seg value={ugroup} options={UTIL_GROUPS} onChange={setUgroup} />}>
          {util.loading && !util.data ? <Loading h={220} /> : !util.data?.data.length ? <Empty>No utilisation data</Empty> : (
            <>
              <ResponsiveContainer width="100%" height={220}>
                <LineChart data={util.data.data}>
                  <CartesianGrid stroke="var(--grid)" vertical={false} />
                  <XAxis dataKey="date" tickFormatter={shortDate} tick={{ fontSize: 11, fill: "var(--muted)" }} minTickGap={24} axisLine={false} tickLine={false} />
                  <YAxis tickFormatter={(v) => `${v}%`} domain={[0, 100]} tick={{ fontSize: 11, fill: "var(--muted)" }} width={44} axisLine={false} tickLine={false} />
                  <Tooltip content={<ChartTip fmt={(v) => `${v}%`} labelFmt={shortDate} />} />
                  {ukeys.map((k, i) => <Line key={k} type="monotone" dataKey={k} stroke={colorFor(k, i)} strokeWidth={2} dot={false} connectNulls />)}
                </LineChart>
              </ResponsiveContainer>
              <Legend items={ukeys.map((k, i) => [k, colorFor(k, i)])} />
            </>
          )}
        </Card>
      </div>

      <Card title="Cost by service" sub="Selected period">
        {!services.data ? <Loading h={120} /> : !services.data.length ? <Empty>No data</Empty> : (
          <div className="tablewrap">
            <table>
              <thead><tr><th>Service</th><th className="r">Cost</th><th className="r">Share</th><th style={{ width: "40%" }} /></tr></thead>
              <tbody>
                {services.data.map((s, i) => (
                  <tr key={s.key}><td>{s.key}</td><td className="r num">{usd(s.cost)}</td><td className="r num">{s.share_pct.toFixed(1)}%</td>
                    <td><div className="bar"><i style={{ width: `${s.share_pct}%`, background: colorFor(s.key, i) }} /></div></td></tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </>
  );
}
