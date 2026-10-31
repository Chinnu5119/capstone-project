import React from "react";
import { label } from "../format.js";

export function Kpi({ title, value, note, tone }) {
  return (
    <div className="card kpi">
      <h3>{title}</h3>
      <div className={`value num ${tone || ""}`}>{value}</div>
      {note && <div className="note">{note}</div>}
    </div>
  );
}

export function Card({ title, sub, actions, children }) {
  return (
    <div className="card">
      {(title || actions) && (
        <div className="card-head">
          <div>
            {title && <h3 style={{ marginBottom: 0 }}>{title}</h3>}
            {sub && <div className="sub" style={{ marginBottom: 0 }}>{sub}</div>}
          </div>
          {actions}
        </div>
      )}
      {children}
    </div>
  );
}

export function Seg({ value, options, onChange }) {
  return (
    <div className="seg" role="group">
      {options.map((o) => (
        <button key={o} className={o === value ? "on" : ""} onClick={() => onChange(o)} aria-pressed={o === value}>
          {label(o)}
        </button>
      ))}
    </div>
  );
}

export function Loading({ h = 220 }) {
  return <div className="skeleton" style={{ height: h }} aria-busy="true" />;
}

export function ErrorBanner({ error }) {
  return error ? <div className="banner err" role="alert">Could not load data: {error.message}</div> : null;
}

export function Empty({ children }) {
  return <div className="empty">{children}</div>;
}

const TONES = { critical: "b-bad", warning: "b-warn", info: "b-info", firing: "b-bad", resolved: "b-good",
  high: "b-good", medium: "b-warn", low: "b-mute", running: "b-good", stopped: "b-mute", unattached: "b-warn" };
export function Badge({ kind, children }) {
  return <span className={`badge ${TONES[kind] || "b-mute"}`}>{children ?? label(kind)}</span>;
}

export function CpuBar({ value }) {
  if (value == null) return <span className="muted">–</span>;
  const cls = value > 85 ? "hot" : value < 20 ? "low" : "";
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
      <div className="bar" style={{ width: 70 }}><i className={cls} style={{ width: `${Math.min(100, value)}%` }} /></div>
      <span className="num">{value.toFixed(0)}%</span>
    </div>
  );
}

export function Legend({ items }) {
  return (
    <div className="legend">
      {items.map(([name, color]) => <span key={name}><i style={{ background: color }} />{label(name)}</span>)}
    </div>
  );
}

export function ChartTip({ active, payload, label: lab, fmt, labelFmt }) {
  if (!active || !payload?.length) return null;
  const rows = payload.filter((p) => p.value != null);
  return (
    <div className="chart-tip">
      <div style={{ fontWeight: 600, marginBottom: 4 }}>{labelFmt ? labelFmt(lab) : lab}</div>
      {rows.map((p) => (
        <div className="row" key={p.dataKey}>
          <span><i style={{ display: "inline-block", width: 8, height: 8, background: p.color || p.fill, borderRadius: 2, marginRight: 6 }} />{label(p.name)}</span>
          <span className="num">{fmt ? fmt(p.value) : p.value}</span>
        </div>
      ))}
    </div>
  );
}
