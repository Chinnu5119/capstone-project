const BASE = import.meta.env.VITE_API_URL || "";

async function request(path, { method = "GET", params, body } = {}) {
  const qs = new URLSearchParams();
  Object.entries(params || {}).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== "" && v !== "all") qs.set(k, v);
  });
  const url = `${BASE}/api${path}${qs.toString() ? `?${qs}` : ""}`;
  const res = await fetch(url, {
    method,
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const j = await res.json();
      detail = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail);
    } catch { /* not json */ }
    throw new Error(detail);
  }
  return res.status === 204 ? null : res.json();
}

export const api = {
  filters: () => request("/filters"),
  summary: (p) => request("/costs/summary", { params: p }),
  timeseries: (p) => request("/costs/timeseries", { params: p }),
  breakdown: (p) => request("/costs/breakdown", { params: p }),
  monthly: (p) => request("/costs/monthly", { params: p }),
  anomalies: (p) => request("/costs/anomalies", { params: p }),
  resources: (p) => request("/resources", { params: p }),
  utilSummary: (p) => request("/utilization/summary", { params: p }),
  utilSeries: (p) => request("/utilization/timeseries", { params: p }),
  optimization: (p) => request("/optimization", { params: p }),
  rules: () => request("/alerts/rules"),
  ruleTypes: () => request("/alerts/rule-types"),
  createRule: (body) => request("/alerts/rules", { method: "POST", body }),
  updateRule: (id, body) => request(`/alerts/rules/${id}`, { method: "PUT", body }),
  deleteRule: (id) => request(`/alerts/rules/${id}`, { method: "DELETE" }),
  events: (p) => request("/alerts/events", { params: p }),
  channels: () => request("/alerts/channels"),
  testNotification: () => request("/alerts/test", { method: "POST" }),
  providerStatus: () => request("/providers/status"),
  testProvider: (p) => request(`/providers/${p}/test`, { method: "POST" }),
  collect: (body) => request("/collect", { method: "POST", body: body || {} }),
  runs: () => request("/collection/runs"),
};
