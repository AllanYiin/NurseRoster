const apiBase = (() => {
  const explicit = window.__API_BASE__ && String(window.__API_BASE__).trim();
  if (explicit) return explicit;
  const meta = document.querySelector('meta[name="api-base"]');
  return meta?.content?.trim() || "";
})();

export function apiUrl(path) {
  if (!apiBase) return path;
  if (/^https?:\/\//i.test(path)) return path;
  try {
    return new URL(path, apiBase).toString();
  } catch {
    return path;
  }
}

export async function api(path, opts = {}) {
  const res = await fetch(apiUrl(path), {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  const payload = await res.json().catch(() => null);
  if (!payload) throw new Error(`回應不是 JSON（${res.status}）`);
  if (!res.ok || payload.ok === false) {
    const msg =
      (payload.error && (payload.error.message || payload.error.code)) ||
      payload.error ||
      payload.detail ||
      `HTTP ${res.status}`;
    throw new Error(msg);
  }
  return payload.data;
}
