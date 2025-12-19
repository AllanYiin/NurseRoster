import { apiUrl } from "./api.js";

export function streamNlToDsl(text, handlers = {}) {
  const { onStatus, onToken, onCompleted, onError } = handlers;
  const url = apiUrl(`/api/rules/nl_to_dsl_stream?text=${encodeURIComponent(text || "")}`);
  const es = new EventSource(url);
  let closed = false;

  es.addEventListener("status", (e) => {
    try {
      const d = JSON.parse(e.data);
      onStatus && onStatus(d.message || e.data || "");
    } catch {
      onStatus && onStatus(e.data);
    }
  });

  es.addEventListener("token", (e) => {
    try {
      const d = JSON.parse(e.data);
      onToken && onToken(d.text || e.data || "");
    } catch {
      onToken && onToken(e.data);
    }
  });

  es.addEventListener("completed", (e) => {
    closed = true;
    es.close();
    try {
      const d = JSON.parse(e.data);
      onCompleted && onCompleted(d.dsl_text || null);
    } catch {
      onCompleted && onCompleted(null);
    }
  });

  es.addEventListener("error", () => {
    if (!closed) {
      es.close();
      onError && onError(new Error("串流中斷（可能是後端錯誤或連線中斷）"));
    }
  });

  return () => es.close();
}

export async function streamRuleVersionFromNl(ruleId, text, handlers = {}) {
  const { onDraft, onStatus, onToken, onCompleted, onValidated, onError, signal } = handlers;
  const res = await fetch(apiUrl(`/api/rules/${ruleId}/versions:from_nl`), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
    signal,
  });
  if (!res.ok || !res.body) throw new Error(`HTTP ${res.status}`);

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  const emit = (eventName, rawData) => {
    let data = rawData;
    try {
      data = JSON.parse(rawData);
    } catch {
      // keep raw
    }
    if (eventName === "draft") onDraft && onDraft(data);
    if (eventName === "status") onStatus && onStatus(data);
    if (eventName === "token") onToken && onToken(data);
    if (eventName === "completed") onCompleted && onCompleted(data);
    if (eventName === "validated") onValidated && onValidated(data);
    if (eventName === "error") onError && onError(data);
  };

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const parts = buffer.split("\n\n");
    buffer = parts.pop() || "";
    for (const part of parts) {
      if (!part.trim()) continue;
      let eventName = "message";
      const dataLines = [];
      part.split("\n").forEach((line) => {
        if (line.startsWith("event:")) {
          eventName = line.replace("event:", "").trim();
        } else if (line.startsWith("data:")) {
          dataLines.push(line.replace("data:", "").trim());
        }
      });
      const payload = dataLines.join("\n");
      if (eventName && payload) emit(eventName, payload);
    }
  }
}
