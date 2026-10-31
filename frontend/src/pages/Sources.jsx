import React, { useState } from "react";
import { api } from "../api.js";
import { useFetch } from "../hooks.js";
import { Badge, Card, Empty, ErrorBanner, Loading } from "../components/ui.jsx";
import { ago, label } from "../format.js";

const MODE_NOTE = {
  mock: "Synthetic demo data. No credentials needed.",
  live: "Reading from the real cloud account.",
  disabled: "Turned off in configuration.",
};

export default function Sources() {
  const status = useFetch(api.providerStatus, [], 10000);
  const runs = useFetch(api.runs, [], 10000);
  const [tests, setTests] = useState({});
  const [msg, setMsg] = useState(null);

  const test = async (p) => {
    setTests((t) => ({ ...t, [p]: { loading: true } }));
    try {
      const result = await api.testProvider(p);
      setTests((t) => ({ ...t, [p]: result }));
    } catch (e) { setTests((t) => ({ ...t, [p]: { ok: false, detail: e.message } })); }
  };
  const collect = async (provider) => {
    try { await api.collect(provider ? { provider } : {}); setMsg({ kind: "ok", text: "Collection started. Status updates below." }); setTimeout(() => { status.reload(); runs.reload(); }, 1500); }
    catch (e) { setMsg({ kind: "warn", text: e.message }); }
  };

  return (
    <>
      <ErrorBanner error={status.error} />
      {msg && <div className={`banner ${msg.kind}`} role="status">{msg.text}</div>}
      <div className="grid three">
        {(status.data || []).map((s) => {
          const t = tests[s.provider];
          return (
            <Card key={s.provider} title={label(s.provider)} sub={MODE_NOTE[s.mode]}
              actions={<Badge kind={s.mode === "live" ? "high" : s.mode === "mock" ? "info" : "low"}>{s.mode}</Badge>}>
              <div style={{ display: "grid", gap: 4, marginBottom: 10 }}>
                <div>Last run: {s.last_run_status ? <Badge kind={s.last_run_status === "success" ? "high" : s.last_run_status === "partial" ? "medium" : "critical"}>{s.last_run_status}</Badge> : "never"}</div>
                <div className="muted">Last success: {ago(s.last_success_at)}</div>
                <div className="muted">Cost rows: {s.cost_rows.toLocaleString()} {s.first_date && `(${s.first_date} to ${s.last_date})`}</div>
                {s.last_run_error && <div className="banner err" style={{ margin: "6px 0 0", fontSize: 12 }}>{s.last_run_error}</div>}
              </div>
              {t && !t.loading && <div className={`banner ${t.ok ? "ok" : "err"}`} style={{ fontSize: 12 }}>{t.detail}</div>}
              <div style={{ display: "flex", gap: 8 }}>
                <button className="btn small" disabled={t?.loading || s.mode === "disabled"} onClick={() => test(s.provider)}>{t?.loading ? "Testing…" : "Test connection"}</button>
                <button className="btn small" disabled={s.mode === "disabled"} onClick={() => collect(s.provider)}>Collect now</button>
              </div>
            </Card>
          );
        })}
      </div>
      <Card title="Collection history" actions={<button className="btn small" onClick={() => collect(null)}>Collect all now</button>}>
        {!runs.data ? <Loading h={120} /> : !runs.data.length ? <Empty>No runs yet.</Empty> : (
          <div className="tablewrap">
            <table>
              <thead><tr><th>Started</th><th>Cloud</th><th>Mode</th><th>What</th><th>Status</th><th className="r">Cost rows</th><th className="r">Resources</th><th className="r">Util rows</th><th>Error</th></tr></thead>
              <tbody>
                {runs.data.map((r) => (
                  <tr key={r.id}>
                    <td className="muted num">{new Date(r.started_at).toLocaleString()}</td><td>{label(r.provider)}</td><td>{r.mode}</td>
                    <td className="muted">{r.kinds.replace(/,/g, ", ")}</td>
                    <td><Badge kind={r.status === "success" ? "high" : r.status === "running" ? "info" : r.status === "partial" ? "medium" : "critical"}>{r.status}</Badge></td>
                    <td className="r num">{r.cost_rows}</td><td className="r num">{r.resource_rows}</td><td className="r num">{r.util_rows}</td>
                    <td className="muted" style={{ maxWidth: 300 }}>{r.error}</td>
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
