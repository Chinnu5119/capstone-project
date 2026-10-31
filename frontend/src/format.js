export const usd = (n, d = 0) =>
  n == null ? "–" : new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: d, minimumFractionDigits: d }).format(n);

export const pct = (n, d = 1) => (n == null ? "–" : `${n > 0 ? "+" : ""}${n.toFixed(d)}%`);

export const shortDate = (iso) => {
  const d = new Date(iso + "T00:00:00Z");
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "UTC" });
};

export const monthLabel = (ym) => {
  const d = new Date(ym + "-01T00:00:00Z");
  return d.toLocaleDateString("en-US", { month: "short", year: "2-digit", timeZone: "UTC" });
};

export const ago = (iso) => {
  if (!iso) return "never";
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  return `${Math.floor(s / 86400)} d ago`;
};

export const PROVIDER_LABEL = { aws: "AWS", azure: "Azure", gcp: "GCP" };
export const label = (k) => PROVIDER_LABEL[k] || (k ? k.charAt(0).toUpperCase() + k.slice(1).replace(/_/g, " ") : k);

// Fixed colours per provider; fallback palette for other dimensions.
export const PROVIDER_COLOR = { aws: "#e8892b", azure: "#3b82c4", gcp: "#4aa36b", Other: "#98a2b3", total: "#344054" };
export const PALETTE = ["#4f6bed", "#e8892b", "#3aa6a0", "#c14f8f", "#7a8b3a", "#8a63d2", "#d1584a", "#4d97d6", "#98a2b3"];
export const colorFor = (key, i) => PROVIDER_COLOR[key] || PALETTE[i % PALETTE.length];
