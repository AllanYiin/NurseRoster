import { $ } from "../dom.js";
import { api } from "../api.js";
import { esc } from "../escape.js";
import { toast } from "../toast.js";
import { state } from "../state.js";
import { openModal } from "../modal.js";
import { streamNlToDsl, streamRuleVersionFromNl } from "../streams.js";

export function buildRuleQuery() {
  const params = new URLSearchParams();
  params.set("project_id", state.project.id);
  if (state.ruleFilters.scope_type) params.set("scope_type", state.ruleFilters.scope_type);
  if (state.ruleFilters.scope_id) params.set("scope_id", state.ruleFilters.scope_id);
  if (state.ruleFilters.type) params.set("type", state.ruleFilters.type);
  if (state.ruleFilters.q) params.set("q", state.ruleFilters.q);
  return params.toString();
}

export function syncRuleFiltersFromUI() {
  state.ruleFilters.scope_type = $("#ruleFilterScopeType")?.value || "";
  state.ruleFilters.scope_id = $("#ruleFilterScopeId")?.value.trim() || "";
  state.ruleFilters.type = $("#ruleFilterType")?.value || "";
  state.ruleFilters.q = $("#ruleFilterQ")?.value.trim() || "";
}

export function resetRuleFilters() {
  state.ruleFilters = { scope_type: "", scope_id: "", type: "", q: "" };
  if ($("#ruleFilterScopeType")) $("#ruleFilterScopeType").value = "";
  if ($("#ruleFilterScopeId")) $("#ruleFilterScopeId").value = "";
  if ($("#ruleFilterType")) $("#ruleFilterType").value = "";
  if ($("#ruleFilterQ")) $("#ruleFilterQ").value = "";
}

export async function loadRules() {
  const rows = await api(`/api/rules?${buildRuleQuery()}`);
  const tbody = $("#rulesTable tbody");
  tbody.innerHTML = rows
    .map((r) => {
      const checked = r.is_enabled ? "checked" : "";
      const dt = (r.updated_at || r.created_at || "").toString().replace("T", " ").slice(0, 19);
      return `
        <tr data-id="${r.id}">
          <td>${esc(r.title)}</td>
          <td><input type="checkbox" class="ruleEnabled" ${checked}></td>
          <td class="muted">${esc(dt)}</td>
          <td>
            <button class="btn btn--sm" data-act="edit">編輯</button>
            <button class="btn btn--sm" data-act="versions">版本</button>
            <button class="btn btn--sm" data-act="del">刪除</button>
          </td>
        </tr>
      `;
    })
    .join("");

  tbody.querySelectorAll(".ruleEnabled").forEach((cb) => {
    cb.addEventListener("change", async (e) => {
      const tr = e.target.closest("tr");
      const id = tr.dataset.id;
      const r = rows.find((x) => String(x.id) === String(id));
      try {
        await api(`/api/rules/${id}`, {
          method: "PUT",
          body: JSON.stringify({
            title: r.title,
            nl_text: r.nl_text,
            dsl_text: r.dsl_text,
            is_enabled: e.target.checked,
          }),
        });
        toast("已更新", "good");
      } catch (err) {
        toast(`更新失敗：${err.message}`, "bad");
        e.target.checked = !e.target.checked;
      }
    });
  });

  tbody.querySelectorAll("button[data-act]").forEach((btn) => {
    btn.addEventListener("click", async (e) => {
      const tr = e.target.closest("tr");
      const id = tr.dataset.id;
      const act = e.target.dataset.act;
      const r = rows.find((x) => String(x.id) === String(id));
      if (!r) return;
      if (act === "edit") return openRuleEditor(r);
      if (act === "versions") return openRuleVersions(r);
      if (act === "del") {
        if (!confirm("確定要刪除這條規則？")) return;
        await api(`/api/rules/${id}`, { method: "DELETE" });
        toast("已刪除", "good");
        await loadRules();
      }
    });
  });
}

function openRuleEditor(rule) {
  const isNew = !rule;
  openModal({
    title: isNew ? "新增規則" : "編輯規則",
    bodyHtml: `
      <label class="field full"><span>標題</span><input id="ruleTitle" value="${esc(rule?.title || "")}" placeholder="例如：急診每日人力"></label>
      <label class="field full"><span>自然語言</span><textarea id="ruleNL" rows="4">${esc(rule?.nl_text || "")}</textarea></label>
      <label class="field full"><span>DSL（JSON）</span><textarea id="ruleDSL" rows="10">${esc(rule?.dsl_text || "")}</textarea></label>
      <label class="field"><span>啟用</span><input type="checkbox" id="ruleEnabled" ${rule?.is_enabled ? "checked" : ""}></label>
    `,
    onOk: async () => {
      const payload = {
        title: $("#ruleTitle").value.trim() || "(未命名)",
        nl_text: $("#ruleNL").value,
        dsl_text: $("#ruleDSL").value,
        is_enabled: $("#ruleEnabled").checked,
      };
      if (isNew) {
        await api(`/api/rules?project_id=${state.project.id}`, { method: "POST", body: JSON.stringify(payload) });
      } else {
        await api(`/api/rules/${rule.id}`, { method: "PUT", body: JSON.stringify(payload) });
      }
      toast(isNew ? "已建立" : "已更新", "good");
      await loadRules();
    },
  });
}

export function runNlToDslStream() {
  const nl = $("#nlInput").value;
  $("#dslOutput").value = "";
  $("#nlStatus").textContent = "";

  streamNlToDsl(nl, {
    onStatus: (msg) => {
      $("#nlStatus").textContent = msg || "";
    },
    onToken: (chunk) => {
      $("#dslOutput").value += chunk;
    },
    onCompleted: (dslText) => {
      if (dslText) $("#dslOutput").value = dslText;
      $("#nlStatus").textContent = "完成";
    },
    onError: (err) => {
      $("#nlStatus").textContent = err.message;
      toast(`轉譯失敗：${err.message}`, "bad");
    },
  });
}

function formatValidationStatus(status) {
  if (status === "PASS") return "PASS";
  if (status === "WARN") return "WARN";
  if (status === "FAIL") return "FAIL";
  if (status === "PENDING") return "PENDING";
  return status || "";
}

function renderValidationReport(report) {
  if (!report) return '<div class="muted">尚無驗證資訊</div>';
  const issues = (report.issues || []).map((x) => `<li>${esc(x)}</li>`).join("");
  const warnings = (report.warnings || []).map((x) => `<li>${esc(x)}</li>`).join("");
  return `
    ${issues ? `<div class="strong">錯誤</div><ul>${issues}</ul>` : `<div class="muted">沒有錯誤</div>`}
    ${warnings ? `<div class="strong" style="margin-top:8px;">警告</div><ul>${warnings}</ul>` : ""}
  `;
}

function openRuleVersionCompare(rule, version) {
  openModal({
    title: `版本比對：V${version.version}`,
    bodyHtml: `
      <div class="grid2">
        <div class="subcard">
          <div class="subcard__title">目前規則</div>
          <div class="muted">標題：${esc(rule.title)}</div>
          <div class="strong" style="margin-top:8px;">自然語言</div>
          <pre style="white-space:pre-wrap;margin:6px 0 0;">${esc(rule.nl_text || "")}</pre>
          <div class="strong" style="margin-top:8px;">DSL</div>
          <pre style="white-space:pre-wrap;margin:6px 0 0;">${esc(rule.dsl_text || "")}</pre>
        </div>
        <div class="subcard">
          <div class="subcard__title">版本 V${esc(version.version)}（${esc(formatValidationStatus(version.validation_status))}）</div>
          <div class="muted">建立：${esc((version.created_at || "").toString().replace("T", " ").slice(0, 19))}</div>
          <div class="strong" style="margin-top:8px;">自然語言</div>
          <pre style="white-space:pre-wrap;margin:6px 0 0;">${esc(version.nl_text || "")}</pre>
          <div class="strong" style="margin-top:8px;">DSL</div>
          <pre style="white-space:pre-wrap;margin:6px 0 0;">${esc(version.dsl_text || "")}</pre>
        </div>
      </div>
    `,
    onOk: async () => {},
  });
  $("#modalOk").textContent = "關閉";
}

function openRuleVersions(rule) {
  openModal({
    title: `規則版本管理：${rule.title}`,
    bodyHtml: `
      <div class="grid2">
        <div class="subcard">
          <div class="subcard__title">版本列表</div>
          <div class="muted" style="margin-bottom:8px;">選擇版本可預覽、比對或採用。</div>
          <div id="ruleVersionList"></div>
          <div class="row" style="margin-top:10px;">
            <button class="btn" id="btnReloadVersions">重新整理版本</button>
          </div>
        </div>
        <div class="subcard">
          <div class="subcard__title">版本內容</div>
          <div id="ruleVersionDetail" class="muted">尚未選擇版本</div>
        </div>
      </div>
      <div class="subcard" style="margin-top:12px;">
        <div class="subcard__title">自然語言 → 新版本（含草稿狀態）</div>
        <label class="field full">
          <span>規則描述</span>
          <textarea id="ruleVersionNl" rows="4" placeholder="輸入自然語言描述，系統會建立草稿版本並驗證。"></textarea>
        </label>
        <div class="row" style="margin-top:8px;">
          <button class="btn btn--primary" id="btnRuleVersionStream">開始轉譯</button>
          <button class="btn" id="btnRuleVersionClear">清除</button>
        </div>
        <label class="field full" style="margin-top:10px;">
          <span>DSL 結果（草稿）</span>
          <textarea id="ruleVersionDsl" rows="6" readonly></textarea>
        </label>
        <div class="muted" id="ruleVersionStatus" style="white-space:pre-wrap;"></div>
        <div class="row" style="margin-top:8px;">
          <button class="btn" id="btnRuleVersionActivate" disabled>採用此版本</button>
        </div>
      </div>
    `,
    onOk: async () => {},
  });
  $("#modalOk").textContent = "關閉";

  let latestVersionId = null;
  let activeController = null;

  const renderVersionDetail = (version) => {
    const report = version.validation_report || {};
    const detail = $("#ruleVersionDetail");
    detail.innerHTML = `
      <div class="strong">版本 V${esc(version.version)}（${esc(formatValidationStatus(version.validation_status))}）</div>
      <div class="muted">建立：${esc((version.created_at || "").toString().replace("T", " ").slice(0, 19))}</div>
      <div class="strong" style="margin-top:8px;">自然語言</div>
      <pre style="white-space:pre-wrap;margin:6px 0 0;">${esc(version.nl_text || "")}</pre>
      <div class="strong" style="margin-top:8px;">DSL</div>
      <pre style="white-space:pre-wrap;margin:6px 0 0;">${esc(version.dsl_text || "")}</pre>
      <div class="strong" style="margin-top:8px;">反向翻譯</div>
      <pre style="white-space:pre-wrap;margin:6px 0 0;">${esc(version.reverse_translation || "")}</pre>
      <div class="strong" style="margin-top:8px;">驗證結果</div>
      ${renderValidationReport(report)}
      <div class="row" style="margin-top:10px;">
        <button class="btn" data-version-act="compare" data-version-id="${version.id}">比對目前版本</button>
        <button class="btn btn--primary" data-version-act="activate" data-version-id="${version.id}">採用此版本</button>
      </div>
    `;
    detail.querySelectorAll("[data-version-act]").forEach((btn) => {
      btn.addEventListener("click", async (e) => {
        const target = e.currentTarget;
        const act = target.dataset.versionAct;
        if (act === "compare") return openRuleVersionCompare(rule, version);
        if (act === "activate") {
          await api(`/api/rules/${rule.id}/activate/${version.id}`, { method: "POST" });
          toast("已採用版本", "good");
          await loadRules();
          await loadVersions();
        }
      });
    });
  };

  const loadVersions = async () => {
    const versions = await api(`/api/rules/${rule.id}/versions`);
    if (!versions.length) {
      $("#ruleVersionList").innerHTML = `<div class="muted">尚無版本</div>`;
      $("#ruleVersionDetail").textContent = "尚未選擇版本";
      return;
    }
    $("#ruleVersionList").innerHTML = versions
      .map((v) => {
        const dt = (v.created_at || "").toString().replace("T", " ").slice(0, 19);
        return `
          <div class="table" style="margin-bottom:8px;">
            <div style="display:flex; align-items:center; justify-content:space-between; padding:8px 10px;">
              <div>
                <div class="strong">V${esc(v.version)} · ${esc(formatValidationStatus(v.validation_status))}</div>
                <div class="muted">${esc(dt)}</div>
              </div>
              <div style="display:flex; gap:6px; flex-wrap:wrap;">
                <button class="btn btn--sm" data-version-act="preview" data-version-id="${v.id}">預覽</button>
                <button class="btn btn--sm" data-version-act="compare" data-version-id="${v.id}">比對</button>
                <button class="btn btn--sm" data-version-act="activate" data-version-id="${v.id}">採用</button>
              </div>
            </div>
          </div>
        `;
      })
      .join("");

    $("#ruleVersionList").querySelectorAll("[data-version-act]").forEach((btn) => {
      btn.addEventListener("click", async (e) => {
        const target = e.currentTarget;
        const act = target.dataset.versionAct;
        const versionId = target.dataset.versionId;
        const version = versions.find((x) => String(x.id) === String(versionId));
        if (!version) return;
        if (act === "preview") return renderVersionDetail(version);
        if (act === "compare") return openRuleVersionCompare(rule, version);
        if (act === "activate") {
          await api(`/api/rules/${rule.id}/activate/${version.id}`, { method: "POST" });
          toast("已採用版本", "good");
          await loadRules();
          await loadVersions();
          return;
        }
      });
    });

    renderVersionDetail(versions[0]);
  };

  $("#btnReloadVersions").addEventListener("click", () => loadVersions().catch((e) => toast(`載入失敗：${e.message}`, "bad")));
  $("#btnRuleVersionClear").addEventListener("click", () => {
    $("#ruleVersionNl").value = "";
    $("#ruleVersionDsl").value = "";
    $("#ruleVersionStatus").textContent = "";
    $("#btnRuleVersionActivate").disabled = true;
    latestVersionId = null;
  });

  $("#btnRuleVersionActivate").addEventListener("click", async () => {
    if (!latestVersionId) return;
    await api(`/api/rules/${rule.id}/activate/${latestVersionId}`, { method: "POST" });
    toast("已採用版本", "good");
    await loadRules();
    await loadVersions();
  });

  $("#btnRuleVersionStream").addEventListener("click", async () => {
    const text = $("#ruleVersionNl").value.trim();
    if (!text) {
      toast("請先輸入自然語言描述", "warn");
      return;
    }
    if (activeController) activeController.abort();
    activeController = new AbortController();
    $("#ruleVersionDsl").value = "";
    $("#ruleVersionStatus").textContent = "建立草稿中...";
    $("#btnRuleVersionActivate").disabled = true;
    latestVersionId = null;

    try {
      await streamRuleVersionFromNl(rule.id, text, {
        signal: activeController.signal,
        onDraft: (data) => {
          latestVersionId = data.rule_version_id || null;
          $("#ruleVersionStatus").textContent = `草稿版本已建立（V${data.version}）`;
        },
        onToken: (data) => {
          $("#ruleVersionDsl").value += data.text || "";
        },
        onCompleted: (data) => {
          if (data.dsl_text) $("#ruleVersionDsl").value = data.dsl_text;
          $("#ruleVersionStatus").textContent = "轉譯完成，等待驗證結果...";
        },
        onValidated: async (data) => {
          const issues = (data.issues || []).join("\n");
          const warnings = (data.warnings || []).join("\n");
          let statusText = `驗證：${data.status || "完成"}`;
          if (issues) statusText += `\n錯誤：\n${issues}`;
          if (warnings) statusText += `\n警告：\n${warnings}`;
          $("#ruleVersionStatus").textContent = statusText;
          $("#btnRuleVersionActivate").disabled = !latestVersionId;
          await loadVersions();
        },
        onError: (data) => {
          const message = data?.message || "轉譯失敗";
          $("#ruleVersionStatus").textContent = message;
          toast(message, "bad");
        },
      });
    } catch (err) {
      if (err.name === "AbortError") return;
      $("#ruleVersionStatus").textContent = err.message || "轉譯失敗";
      toast(`轉譯失敗：${err.message}`, "bad");
    }
  });

  loadVersions().catch((e) => toast(`載入失敗：${e.message}`, "bad"));
}

export async function runValidateDsl() {
  const dsl_text = $("#dslOutput").value;
  const r = await api("/api/rules/validate", { method: "POST", body: JSON.stringify({ dsl_text }) });
  if (r.ok) {
    $("#dslStatus").textContent = "驗證：PASS";
    toast("驗證通過", "good");
  } else {
    $("#dslStatus").textContent = `驗證：FAIL\n${(r.issues || []).join("\n")}`;
    toast("驗證失敗", "bad");
  }
}

export async function runDslToNl() {
  const dsl_text = $("#dslOutput").value;
  const r = await api("/api/rules/dsl_to_nl", { method: "POST", body: JSON.stringify({ dsl_text }) });
  toast("已產生反向翻譯", r.prompt_applied ? "good" : "info");
  const warnings = (r.warnings || []).map((w) => `<div class="muted">${esc(w)}</div>`).join("");
  const source = r.source ? `來源：${r.source}${r.prompt_applied ? "（套用 System Prompt）" : ""}` : "";
  openModal({
    title: "DSL → 自然語言",
    bodyHtml: `
      <pre style="white-space:pre-wrap;margin:0;">${esc(r.text || "")}</pre>
      ${source ? `<div class="muted" style="margin-top:6px;">${esc(source)}</div>` : ""}
      ${warnings ? `<div class="muted" style="margin-top:4px;">${warnings}</div>` : ""}
    `,
    onOk: async () => {},
  });
}

export async function saveRuleFromPanel() {
  const title = ($("#nlInput").value || "").trim().slice(0, 30) || "規則";
  await api(`/api/rules?project_id=${state.project.id}`, {
    method: "POST",
    body: JSON.stringify({
      title,
      nl_text: $("#nlInput").value,
      dsl_text: $("#dslOutput").value,
      is_enabled: true,
    }),
  });
  toast("已存成規則", "good");
  await loadRules();
}

export function renderRuleChatLog() {
  const box = $("#ruleChatLog");
  if (!box) return;
  if (!state.ruleChat.length) {
    box.innerHTML = `<div class="muted">尚未開始對話，請先輸入想調整的規則。</div>`;
    return;
  }
  box.innerHTML = state.ruleChat
    .map((m) => {
      const role = m.role === "user" ? "使用者" : "系統 DSL";
      const badge = `<span class="pill pill--${m.role === "user" ? "user" : "bot"}">${esc(role)}</span>`;
      return `
        <div class="chatmsg chatmsg--${m.role === "user" ? "user" : "bot"}">
          <div class="chatmsg__meta">${badge}<span class="muted">${esc(m.time || "")}</span></div>
          <pre class="chatmsg__body">${esc(m.text || "") || "(空白)"}</pre>
        </div>
      `;
    })
    .join("");
}

export function setRuleChatScratch(text) {
  state.ruleChatScratch = text || "";
  const el = $("#ruleChatScratch");
  if (el) el.value = state.ruleChatScratch;
}

function pushRuleChatMessage(msg) {
  state.ruleChat.push({
    id: msg.id || Date.now().toString(),
    role: msg.role || "user",
    text: msg.text || "",
    time: msg.time || new Date().toLocaleTimeString(),
  });
  renderRuleChatLog();
}

function updateRuleChatMessage(id, text) {
  const m = state.ruleChat.find((x) => String(x.id) === String(id));
  if (m) {
    m.text = text;
    renderRuleChatLog();
  }
}

function updateChatStatus(msg) {
  const el = $("#chatStatus");
  if (el) el.textContent = msg || "";
}

export function sendRuleChat() {
  const input = ($("#chatInput").value || "").trim();
  if (!input) return toast("請輸入想調整的規則描述", "warn");
  const placeholderId = `${Date.now()}_bot`;
  pushRuleChatMessage({ role: "user", text: input });
  pushRuleChatMessage({ id: placeholderId, role: "bot", text: "串流中..." });
  setRuleChatScratch("");
  updateChatStatus("轉譯中（SSE）...");

  let buffer = "";
  streamNlToDsl(input, {
    onStatus: (msg) => updateChatStatus(msg || "轉譯中..."),
    onToken: (chunk) => {
      buffer += chunk;
      updateRuleChatMessage(placeholderId, buffer);
      setRuleChatScratch(buffer);
    },
    onCompleted: (dslText) => {
      const finalText = dslText || buffer || "(未產生 DSL)";
      updateRuleChatMessage(placeholderId, finalText);
      setRuleChatScratch(finalText);
      updateChatStatus("完成，可套用到底稿");
      toast("已完成轉譯，請檢視右側底稿。", "good");
    },
    onError: (err) => {
      updateRuleChatMessage(placeholderId, `[失敗] ${err.message}`);
      updateChatStatus(err.message);
    },
  });
}

export function applyScratchToDsl(target) {
  const text = state.ruleChatScratch || "";
  if (!text) return toast("目前底稿為空，請先轉譯一段規則", "warn");
  if (target === "editor") {
    $("#dslOutput").value = text;
    toast("已帶入 DSL 編輯器", "good");
  } else if (target === "tester") {
    $("#dslTester").value = text;
    toast("已帶入 DSL 測試台", "good");
  }
}

export async function loadRuleConflicts() {
  if (!state.project) return;
  const wrap = $("#conflictList");
  if (wrap) wrap.innerHTML = `<div class="muted">載入中...</div>`;
  const params = new URLSearchParams({ project_id: state.project.id });
  const start = $("#conflictStart")?.value;
  const end = $("#conflictEnd")?.value;
  if (start) params.set("start", start);
  if (end) params.set("end", end);
  const rows = await api(`/api/schedule/conflicts?${params.toString()}`);
  if (!wrap) return;
  if (!rows.length) {
    wrap.innerHTML = `<div class="muted">目前區間內沒有規則衝突。</div>`;
    return;
  }
  wrap.innerHTML = rows
    .map(
      (c) => `
      <div class="conflict conflict--${esc(c.severity || "warn")}">
        <div class="conflict__title">${esc(c.rule_title || "規則")}</div>
        <div class="conflict__meta">${esc(c.date || "")} ${esc(c.shift_code || "")} ${esc(c.nurse_staff_no || "")}</div>
        <div class="conflict__msg">${esc(c.message || "")}</div>
      </div>
    `
    )
    .join("");
}
