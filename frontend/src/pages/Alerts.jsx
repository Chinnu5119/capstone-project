import React, { useState } from "react";
import { api } from "../api.js";
import { useFetch } from "../hooks.js";
import { Badge, Card, Empty, ErrorBanner, Loading } from "../components/ui.jsx";
import { label } from "../format.js";

const BLANK = { name: "", rule_type: "daily_cost", provider: "", environment: "", resource_type: "", threshold: 500, severity: "warning", enabled: true, description: "" };
const SEL = { padding: "7px 9px", border: "1px solid var(--border)", borderRadius: 8, background: "var(--surface)" };

export default function Alerts() {
  const rules = useFetch(api.rules, [], 30000);
  const types = useFetch(api.ruleTypes, []);
  const events = useFetch(() => api.events({ limit: 30 }), [], 30000);
  const channels = useFetch(api.channels, []);
  const [form, setForm] = useState(null);       // null = closed; object = editing/creating
  const [editId, setEditId] = useState(null);
  const [msg, setMsg] = useState(null);
  const [busy, setBusy] = useState(false);

  const typeMeta = (t) => (types.data || []).find((x) => x.type === t);
  const open = (rule) => {
    setMsg(null);
    setEditId(rule ? rule.id : null);
    setForm(rule ? { ...BLANK, ...rule, provider: rule.provider || "", environment: rule.environment || "", resource_type: rule.resource_type || "" } : { ...BLANK });
  };
  const upd = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value }));

  const save = async (e) => {
    e.preventDefault();
    setBusy(true);
    const body = {
      name: form.name.trim(), rule_type: form.rule_type, threshold: Number(form.threshold), severity: form.severity,
      enabled: form.enabled, description: form.description,
      provider: form.provider || null, environment: form.environment || null, resource_type: form.resource_type || null,
    };
    try {
      if (editId) await api.updateRule(editId, body); else await api.createRule(body);
      setForm(null); rules.reload();
    } catch (err) { setMsg({ kind: "err", text: err.message }); } finally { setBusy(false); }
  };
  const remove = async (r) => {
    if (!window.confirm(`Delete rule "${r.name}"?`)) return;
    try { await api.deleteRule(r.id); rules.reload(); } catch (err) { setMsg({ kind: "err", text: err.message }); }
  };
  const toggle = async (r) => {
    try {
      await api.updateRule(r.id, { name: r.name, rule_type: r.rule_type, threshold: r.threshold, severity: r.severity, enabled: !r.enabled,
        description: r.description, provider: r.provider, environment: r.environment, resource_type: r.resource_type });
      rules.reload();
    } catch (err) { setMsg({ kind: "err", text: err.message }); }
  };
  const test = async () => {
    try { const r = await api.testNotification(); setMsg({ kind: r.delivered ? "ok" : "warn", text: r.delivered ? "Test notification sent." : "Channels are configured but delivery failed. Check the webhook URLs and backend logs." }); }
    catch (err) { setMsg({ kind: "warn", text: err.message }); }
  };

  const ch = channels.data;
  const firing = (rules.data || []).filter((r) => r.enabled && r.status?.breached).length;

  return (
    <>
      <ErrorBanner error={rules.error || events.error} />
      {msg && <div className={`banner ${msg.kind}`} role="status">{msg.text}</div>}

      <div className="grid two">
        <Card title="Notification channels" sub="Alerts flow: dashboard rule → Prometheus → Alertmanager → this API → Slack / Teams"
          actions={<button className="btn small" onClick={test}>Send test</button>}>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            <Badge kind={ch?.slack ? "high" : "low"}>Slack: {ch?.slack ? "configured" : "not configured"}</Badge>
            <Badge kind={ch?.teams ? "high" : "low"}>Teams: {ch?.teams ? "configured" : "not configured"}</Badge>
          </div>
          {ch && !ch.slack && !ch.teams && <p className="muted" style={{ marginBottom: 0 }}>Set <span className="mono">SLACK_WEBHOOK_URL</span> or <span className="mono">TEAMS_WEBHOOK_URL</span> in <span className="mono">.env</span>. Alerts are still recorded below without them.</p>}
        </Card>
        <Card title="Right now">
          <div className="kpi"><div className="value num">{rules.data ? firing : "…"}</div><div className="note">enabled rules currently over threshold, out of {rules.data?.filter((r) => r.enabled).length ?? "…"} enabled</div></div>
        </Card>
      </div>

      <div style={{ marginBottom: 14 }}>
        <Card title="Alert rules" sub="Evaluated live. Prometheus fires and Alertmanager notifies after the rule stays breached for 2 minutes."
          actions={<button className="btn primary small" onClick={() => open(null)}>New rule</button>}>
          {form && (
            <form onSubmit={save} className="card" style={{ background: "var(--surface-2)", marginBottom: 14 }}>
              <div className="form-grid">
                <div className="field wide"><label htmlFor="r-name">Name</label>
                  <input id="r-name" required maxLength={160} value={form.name} onChange={upd("name")} placeholder="e.g. AWS production spend above budget" /></div>
                <div className="field"><label htmlFor="r-type">Condition</label>
                  <select id="r-type" value={form.rule_type} onChange={(e) => { const t = typeMeta(e.target.value); setForm((f) => ({ ...f, rule_type: e.target.value, threshold: !editId && t ? t.default : f.threshold })); }}>
                    {(types.data || []).map((t) => <option key={t.type} value={t.type}>{t.label}</option>)}
                  </select></div>
                <div className="field"><label htmlFor="r-th">Threshold ({typeMeta(form.rule_type)?.unit})</label>
                  <input id="r-th" type="number" min="0" step="any" required value={form.threshold} onChange={upd("threshold")} /></div>
                <div className="field"><label htmlFor="r-sev">Severity</label>
                  <select id="r-sev" value={form.severity} onChange={upd("severity")}><option value="info">Info</option><option value="warning">Warning</option><option value="critical">Critical</option></select></div>
                <div className="field"><label htmlFor="r-prov">Cloud</label>
                  <select id="r-prov" value={form.provider} onChange={upd("provider")}><option value="">All</option><option value="aws">AWS</option><option value="azure">Azure</option><option value="gcp">GCP</option></select></div>
                <div className="field"><label htmlFor="r-env">Environment</label>
                  <select id="r-env" value={form.environment} onChange={upd("environment")}><option value="">All</option><option value="production">Production</option><option value="staging">Staging</option><option value="development">Development</option></select></div>
                <div className="field"><label htmlFor="r-rt">Resource type</label>
                  <select id="r-rt" value={form.resource_type} onChange={upd("resource_type")}><option value="">All</option><option value="compute">Compute</option><option value="database">Database</option><option value="storage">Storage</option><option value="network">Network</option></select></div>
                <div className="field wide"><span className="muted" style={{ fontSize: 12 }}>{typeMeta(form.rule_type)?.description} Cloud, environment and resource type narrow what is measured.</span></div>
              </div>
              <div style={{ display: "flex", gap: 8, marginTop: 12, alignItems: "center" }}>
                <button className="btn primary" disabled={busy}>{editId ? "Save changes" : "Create rule"}</button>
                <button type="button" className="btn" onClick={() => setForm(null)}>Cancel</button>
                <label style={{ marginLeft: "auto" }}><input type="checkbox" checked={form.enabled} onChange={upd("enabled")} /> Enabled</label>
              </div>
            </form>
          )}
          {rules.loading && !rules.data ? <Loading h={160} /> : !rules.data?.length ? <Empty>No rules yet. Create one to get alerted.</Empty> : (
            <div className="tablewrap">
              <table>
                <thead><tr><th>Rule</th><th>Scope</th><th className="r">Current</th><th className="r">Threshold</th><th>Status</th><th>Severity</th><th /></tr></thead>
                <tbody>
                  {rules.data.map((r) => (
                    <tr key={r.id} style={{ opacity: r.enabled ? 1 : 0.55 }}>
                      <td style={{ maxWidth: 340 }}><div style={{ fontWeight: 600 }}>{r.name}</div><div className="rec-detail">{r.status?.detail}</div></td>
                      <td className="muted">{[r.provider && label(r.provider), r.environment && label(r.environment), r.resource_type && label(r.resource_type)].filter(Boolean).join(" · ") || "Everything"}</td>
                      <td className="r num">{r.status?.value?.toLocaleString(undefined, { maximumFractionDigits: 1 })} {r.unit}</td>
                      <td className="r num">&gt; {r.threshold.toLocaleString()} {r.unit}</td>
                      <td>{!r.enabled ? <Badge kind="low">Disabled</Badge> : r.status?.breached ? <Badge kind="critical">Breached</Badge> : <Badge kind="high">OK</Badge>}</td>
                      <td><Badge kind={r.severity} /></td>
                      <td style={{ whiteSpace: "nowrap" }}>
                        <button className="btn small" onClick={() => toggle(r)}>{r.enabled ? "Disable" : "Enable"}</button>{" "}
                        <button className="btn small" onClick={() => open(r)}>Edit</button>{" "}
                        <button className="btn small danger" onClick={() => remove(r)}>Delete</button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      </div>

      <Card title="Alert history" sub="Received from Alertmanager">
        {!events.data ? <Loading h={100} /> : !events.data.length ? <Empty>No alerts have fired yet. Breached rules appear here after about 2 minutes.</Empty> : (
          <div className="tablewrap">
            <table>
              <thead><tr><th>Started</th><th>Alert</th><th>Severity</th><th>Status</th><th>Delivered</th></tr></thead>
              <tbody>
                {events.data.map((e) => (
                  <tr key={e.id}>
                    <td className="muted num">{new Date(e.starts_at).toLocaleString()}</td>
                    <td style={{ maxWidth: 480 }}><div style={{ fontWeight: 600 }}>{e.rule_name || e.alertname}</div><div className="rec-detail">{e.summary}</div></td>
                    <td><Badge kind={e.severity} /></td><td><Badge kind={e.status} /></td>
                    <td>{e.notified ? <Badge kind="high">Sent</Badge> : <Badge kind="low">Recorded only</Badge>}</td>
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
