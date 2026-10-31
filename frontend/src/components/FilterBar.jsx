import React from "react";
import { label } from "../format.js";

const RANGES = [["7", "Last 7 days"], ["30", "Last 30 days"], ["90", "Last 90 days"], ["custom", "Custom range"]];

function Select({ name, value, options, onChange, all = "All" }) {
  return (
    <div className="field">
      <label htmlFor={`f-${name}`}>{name.replace("_", " ")}</label>
      <select id={`f-${name}`} value={value} onChange={(e) => onChange(e.target.value)}>
        <option value="all">{all}</option>
        {options.map((o) => <option key={o} value={o}>{label(o)}</option>)}
      </select>
    </div>
  );
}

/** Shared filter bar. `showRange` hides the date controls on pages that show current state only. */
export default function FilterBar({ filters, setFilters, options, showRange = true }) {
  const set = (k) => (v) => setFilters((f) => ({ ...f, [k]: v }));
  return (
    <div className="filterbar">
      <Select name="provider" value={filters.provider} options={options?.providers || []} onChange={set("provider")} all="All clouds" />
      <Select name="environment" value={filters.environment} options={options?.environments || []} onChange={set("environment")} />
      <Select name="resource_type" value={filters.resource_type} options={options?.resource_types || []} onChange={set("resource_type")} />
      {showRange && (
        <>
          <div className="field">
            <label htmlFor="f-range">Period</label>
            <select id="f-range" value={filters.range} onChange={(e) => set("range")(e.target.value)}>
              {RANGES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </select>
          </div>
          {filters.range === "custom" && (
            <>
              <div className="field">
                <label htmlFor="f-start">From</label>
                <input id="f-start" type="date" value={filters.start} min={options?.first_date} max={filters.end || options?.last_date}
                  onChange={(e) => set("start")(e.target.value)} />
              </div>
              <div className="field">
                <label htmlFor="f-end">To</label>
                <input id="f-end" type="date" value={filters.end} min={filters.start || options?.first_date} max={options?.last_date}
                  onChange={(e) => set("end")(e.target.value)} />
              </div>
            </>
          )}
        </>
      )}
      <div className="spacer" />
      <button className="btn" onClick={() => setFilters((f) => ({ ...f, provider: "all", environment: "all", resource_type: "all", range: "30" }))}>
        Reset
      </button>
    </div>
  );
}

/** Convert UI filter state to API query params. */
export function toParams(f, { range = true } = {}) {
  const p = { provider: f.provider, environment: f.environment, resource_type: f.resource_type };
  if (range) {
    if (f.range === "custom") {
      if (f.start) p.start = f.start;
      if (f.end) p.end = f.end;
    } else {
      p.days = f.range;
    }
  }
  return p;
}
