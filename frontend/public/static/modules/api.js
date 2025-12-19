export async function api(path, opts = {}) {
  const res = await fetch(path, {
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
