import { $ } from "../dom.js";
import { api } from "../api.js";
import { esc } from "../escape.js";
import { toast } from "../toast.js";
import { openModal } from "../modal.js";
import { streamNlToDsl } from "../streams.js";
import { setRuleChatScratch } from "./rules.js";

export function initDslTester() {
  // no-op (button wired in boot)
}

export function nlToDslLab() {
  const text = $("#dslLabNl").value;
  const statusEl = $("#dslLabNlStatus");
  $("#dslTester").value = "";
  statusEl.textContent = "";
  streamNlToDsl(text, {
    onStatus: (msg) => (statusEl.textContent = msg || ""),
    onToken: (chunk) => {
      $("#dslTester").value += chunk;
    },
    onCompleted: (dslText) => {
      if (dslText) $("#dslTester").value = dslText;
      statusEl.textContent = "完成";
      setRuleChatScratch($("#dslTester").value);
    },
    onError: (err) => {
      statusEl.textContent = err.message;
      toast(`NL→DSL 串流失敗：${err.message}`, "bad");
    },
  });
}

export async function runDslValidateOnly() {
  const dsl_text = $("#dslTester").value;
  const r = await api("/api/rules/validate", { method: "POST", body: JSON.stringify({ dsl_text }) });
  const el = $("#dslTesterStatus");
  if (r.ok) {
    el.textContent = "驗證：PASS";
    toast("驗證通過", "good");
  } else {
    el.textContent = `驗證：FAIL\n${(r.issues || []).join("\n")}`;
    toast("驗證失敗", "bad");
  }
}

export async function runDslLabReverse() {
  const payload = {
    dsl_text: $("#dslTester").value,
    system_prompt: $("#dslPrompt").value,
  };
  const r = await api("/api/rules/dsl_to_nl", { method: "POST", body: JSON.stringify(payload) });
  const pieces = [];
  if (r.source) pieces.push(`來源：${r.source}`);
  if (r.prompt_applied) pieces.push("已套用 System Prompt");
  const statusLine = pieces.join(" · ");
  $("#dslTesterStatus").textContent = statusLine || "";
  const warnLine = (r.warnings || []).join("；");
  if (warnLine) $("#dslTesterStatus").textContent += (statusLine ? "；" : "") + warnLine;
  openModal({
    title: "反向翻譯結果",
    bodyHtml: `<pre style="white-space:pre-wrap;margin:0;">${esc(r.text || "")}</pre>`,
    onOk: async () => {},
  });
}

export async function runDslLabValidate() {
  await runDslValidateOnly();
}
