import React, { useEffect, useState } from "react";
import { api } from "./api.js";
import { useFetch } from "./hooks.js";
import FilterBar from "./components/FilterBar.jsx";
import Overview from "./pages/Overview.jsx";
import Trends from "./pages/Trends.jsx";
import Resources from "./pages/Resources.jsx";
import Optimization from "./pages/Optimization.jsx";
import Alerts from "./pages/Alerts.jsx";
import Sources from "./pages/Sources.jsx";

const PAGES = [
  ["overview", "Overview", Overview, true],
  ["trends", "Trends", Trends, true],
  ["resources", "Resources", Resources, false],
  ["optimization", "Optimization", Optimization, false],
  ["alerts", "Alerts", Alerts, false],
  ["sources", "Data sources", Sources, false],
];

const useHash = () => {
  const get = () => window.location.hash.replace(/^#\/?/, "") || "overview";
  const [h, setH] = useState(get);
  useEffect(() => {
    const on = () => setH(get());
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  return h;
};

export default function App() {
  const hash = useHash();
  const [filters, setFilters] = useState({ provider: "all", environment: "all", resource_type: "all", range: "30", start: "", end: "" });
  const options = useFetch(api.filters, [], 60000);
  const page = PAGES.find((p) => p[0] === hash) || PAGES[0];
  const Page = page[2];
  const hasFilters = ["overview", "trends", "resources", "optimization"].includes(page[0]);
  const last = options.data?.last_date;

  return (
    <div className="shell">
      <header className="topbar">
        <div className="brand">Cloud<span>Cost</span> Monitor</div>
        <nav className="nav" aria-label="Main">
          {PAGES.map(([id, name]) => (
            <a key={id} href={`#/${id}`} className={page[0] === id ? "active" : ""} aria-current={page[0] === id ? "page" : undefined}>{name}</a>
          ))}
        </nav>
        <div className="spacer" />
        <span className="live"><span className="dot" />{last ? `Data through ${last}` : "Waiting for first collection…"}</span>
      </header>

      {options.error && <div className="banner err" role="alert">Cannot reach the API: {options.error.message}</div>}
      {options.data && !options.data.last_date && (
        <div className="banner warn">No data yet. The first collection runs on startup; refresh in a few seconds, or trigger one from Data sources.</div>
      )}
      {hasFilters && <FilterBar filters={filters} setFilters={setFilters} options={options.data} showRange={page[3]} />}
      <main><Page filters={filters} options={options.data} /></main>
    </div>
  );
}
