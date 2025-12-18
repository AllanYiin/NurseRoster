/*
  Nurse Scheduler v1 (no-build frontend)
  - Pure JS SPA
  - Matches templates/index.html
  - Backend: FastAPI under /api
*/

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

function esc(s) {
  return (s ?? "").toString().replace(/[&<>"']/g, (c) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    "\"": "&quot;",
    "'": "&#39;",
  })[c]);
}

async function api(path, opts = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  const payload = await res.json().catch(() => null);
  if (!payload) throw new Error(`回應不是 JSON（${res.status}）`);
  if (!res.ok || payload.ok === false) {
    const msg = (payload.error && (payload.error.message || payload.error.code)) || payload.error || payload.detail || `HTTP ${res.status}`;
    throw new Error(msg);
  }
  return payload.data;
}

function toast(msg, kind = "info") {
  const el = $("#toast");
  if (!el) {
    // fallback
    alert(msg);
    return;
  }
  el.textContent = msg;
  el.classList.remove("good", "warn", "bad");
  if (kind === "good") el.classList.add("good");
  if (kind === "warn") el.classList.add("warn");
  if (kind === "bad") el.classList.add("bad");
  el.classList.add("show");
  clearTimeout(toast._t);
  toast._t = setTimeout(() => el.classList.remove("show"), 2400);
}

function isoDate(d) {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${dd}`;
}

function addDays(d, n) {
  const x = new Date(d);
  x.setDate(x.getDate() + n);
  return x;
}

function startOfWeek(d) {
  const x = new Date(d);
  const day = (x.getDay() + 6) % 7; // Mon=0
  x.setDate(x.getDate() - day);
  x.setHours(0, 0, 0, 0);
  return x;
}

const state = {
  project: null,
  currentView: "calendar",
  masterKind: "nurses",
  modal: {
    onOk: null,
  },
};

function setView(view) {
  state.currentView = view;
  $$(".nav__item").forEach((b) => b.classList.toggle("is-active", b.dataset.view === view));
  $$(".view").forEach((v) => v.classList.toggle("is-hidden", v.id !== `view-${view}`));

  const titleMap = {
    calendar: ["排班總覽", "週檢視（v1）"],
    rules: ["規則維護", "自然語言 ↔ DSL（v1）"],
    master: ["資料維護", "主檔 CRUD（v1）"],
    opt: ["最佳化", "OR-Tools（v1，簡化）"],
    dsl: ["DSL 測試台", "只做驗證（v1）"],
  };
  const [t, s] = titleMap[view] || ["", ""];
  $("#viewTitle").textContent = t;
  $("#viewSub").textContent = s;

  // load
  if (view === "calendar") loadCalendar().catch((e) => toast(`載入失敗：${e.message}`, "bad"));
  if (view === "rules") loadRules().catch((e) => toast(`載入失敗：${e.message}`, "bad"));
  if (view === "master") loadMaster(state.masterKind).catch((e) => toast(`載入失敗：${e.message}`, "bad"));
  if (view === "opt") loadOptimization().catch((e) => toast(`載入失敗：${e.message}`, "bad"));
  if (view === "dsl") initDslTester();
}

// ===== Modal (index.html 固定按鈕) =====
function openModal({ title, bodyHtml, onOk }) {
  $("#modalTitle").textContent = title || "";
  $("#modalBody").innerHTML = bodyHtml || "";
  state.modal.onOk = onOk || null;
  $("#modal").classList.remove("is-hidden");
}

function closeModal() {
  $("#modal").classList.add("is-hidden");
  state.modal.onOk = null;
}

function wireModal() {
  $("#modalClose").addEventListener("click", closeModal);
  $("#modalCancel").addEventListener("click", closeModal);
  $("#modal").addEventListener("click", (e) => {
    if (e.target && e.target.id === "modal") closeModal();
  });
  $("#modalOk").addEventListener("click", async () => {
    if (!state.modal.onOk) return closeModal();
    try {
      await state.modal.onOk();
      closeModal();
    } catch (e) {
      toast(`操作失敗：${e.message}`, "bad");
    }
  });
}

// ===== Calendar =====
async function loadCalendar() {
  const startEl = $("#calStart");
  if (!startEl.value) {
    const ws = startOfWeek(new Date());
    startEl.value = isoDate(ws);
  }
  const start = new Date(startEl.value + "T00:00:00");
  const days = Array.from({ length: 7 }, (_, i) => isoDate(addDays(start, i)));

  const [nurses, shifts, assignments] = await Promise.all([
    api("/api/master/nurses"),
    api("/api/master/shift_codes"),
    api(`/api/calendar/assignments?project_id=${state.project.id}&start=${days[0]}&end=${days[6]}`),
  ]);

  const shiftMap = new Map(shifts.map((s) => [s.code, s]));
  const key = (staffNo, day) => `${staffNo}__${day}`;
  const asgMap = new Map(assignments.map((a) => [key(a.nurse_staff_no, a.day), a]));

  // header
  const grid = $("#calendarGrid");
  let html = "";
  html += `<div class="cal">`;
  html += `<div class="cal__head">`;
  html += `<div class="cal__corner">護理師</div>`;
  for (const d of days) html += `<div class="cal__day">${esc(d)}</div>`;
  html += `</div>`;

  html += `<div class="cal__body">`;
  for (const n of nurses) {
    html += `<div class="cal__row">`;
    html += `<div class="cal__nurse">`;
    html += `<div class="strong">${esc(n.name)}</div>`;
    html += `<div class="muted">${esc(n.staff_no)} · ${esc(n.department_code)} · ${esc(n.job_level_code)}</div>`;
    html += `</div>`;
    for (const d of days) {
      const a = asgMap.get(key(n.staff_no, d));
      const sc = a?.shift_code || "";
      const note = a?.note || "";
      const bg = shiftMap.get(sc)?.color || "#ffffff";
      html += `<button class="cell" data-staff="${esc(n.staff_no)}" data-day="${esc(d)}" style="background:${esc(bg)}">`;
      html += `<div class="cell__code">${esc(sc)}</div>`;
      if (note) html += `<div class="cell__note">${esc(note)}</div>`;
      html += `</button>`;
    }
    html += `</div>`;
  }
  html += `</div></div>`;

  grid.innerHTML = html;
  $$(".cell", grid).forEach((btn) => {
    btn.addEventListener("click", () => openAssignmentEditor(btn.dataset.staff, btn.dataset.day, shifts));
  });
}

function openAssignmentEditor(staffNo, day, shifts) {
  const opts = shifts
    .filter((s) => s.is_active)
    .map((s) => `<option value="${esc(s.code)}">${esc(s.code)} · ${esc(s.name)}</option>`)
    .join("");

  openModal({
    title: "編輯班別",
    bodyHtml: `
      <div class="form">
        <div class="field full"><span>護理師</span><div class="muted">${esc(staffNo)}</div></div>
        <div class="field full"><span>日期</span><div class="muted">${esc(day)}</div></div>
        <label class="field full">
          <span>班別</span>
          <select id="asgShift">
            <option value="">（空白）</option>
            ${opts}
          </select>
        </label>
        <label class="field full">
          <span>備註</span>
          <textarea id="asgNote" rows="3" placeholder="例如：支援、教育、不能排夜"></textarea>
        </label>
      </div>
    `,
    onOk: async () => {
      const shift = $("#asgShift").value;
      const note = $("#asgNote").value;
      await api("/api/calendar/assignments/batch_upsert", {
        method: "POST",
        body: JSON.stringify([
          {
            project_id: state.project.id,
            day,
            nurse_staff_no: staffNo,
            shift_code: shift,
            note,
          },
        ]),
      });
      toast("已儲存", "good");
      await loadCalendar();
    },
  });
}

// ===== Rules =====
async function loadRules() {
  const rows = await api(`/api/rules?project_id=${state.project.id}`);
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
          <td><button class="btn btn--sm" data-act="edit">編輯</button> <button class="btn btn--sm" data-act="del">刪除</button></td>
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

function runNlToDslStream() {
  const nl = $("#nlInput").value;
  $("#dslOutput").value = "";
  $("#nlStatus").textContent = "";

  const url = `/api/rules/nl_to_dsl_stream?text=${encodeURIComponent(nl || "")}`;
  const es = new EventSource(url);

  es.addEventListener("status", (e) => {
    try {
      const d = JSON.parse(e.data);
      $("#nlStatus").textContent = d.message || "";
    } catch {
      $("#nlStatus").textContent = e.data;
    }
  });

  es.addEventListener("token", (e) => {
    try {
      const d = JSON.parse(e.data);
      $("#dslOutput").value += d.text || "";
    } catch {
      $("#dslOutput").value += e.data;
    }
  });

  es.addEventListener("completed", (e) => {
    try {
      const d = JSON.parse(e.data);
      if (d.dsl_text) $("#dslOutput").value = d.dsl_text;
    } catch {
      // ignore
    }
    $("#nlStatus").textContent = "完成";
    es.close();
  });

  es.addEventListener("error", () => {
    $("#nlStatus").textContent = "串流中斷（可能是後端錯誤或連線中斷）";
    es.close();
  });
}

async function runValidateDsl() {
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

async function runDslToNl() {
  const dsl_text = $("#dslOutput").value;
  const r = await api("/api/rules/dsl_to_nl", { method: "POST", body: JSON.stringify({ dsl_text }) });
  toast("已產生反向翻譯", "good");
  openModal({ title: "DSL → 自然語言", bodyHtml: `<pre style="white-space:pre-wrap;margin:0;">${esc(r.text || "")}</pre>`, onOk: async () => {} });
}

async function saveRuleFromPanel() {
  const title = (($("#nlInput").value || "").trim().slice(0, 30) || "規則");
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

// ===== Master Data =====
const MASTER = {
  nurses: {
    title: "護理師",
    endpoint: "/api/master/nurses",
    columns: [
      { key: "staff_no", label: "員工編號", type: "text", required: true },
      { key: "name", label: "姓名", type: "text", required: true },
      { key: "department_code", label: "科別代碼", type: "text" },
      { key: "job_level_code", label: "職級代碼", type: "text" },
      { key: "skills_csv", label: "技能(逗號)", type: "text" },
      { key: "is_active", label: "啟用", type: "bool" },
    ],
  },
  departments: {
    title: "科別",
    endpoint: "/api/master/departments",
    columns: [
      { key: "code", label: "代碼", type: "text", required: true },
      { key: "name", label: "名稱", type: "text", required: true },
      { key: "is_active", label: "啟用", type: "bool" },
    ],
  },
  shift: {
    title: "班別",
    endpoint: "/api/master/shift_codes",
    columns: [
      { key: "code", label: "代碼", type: "text", required: true },
      { key: "name", label: "名稱", type: "text", required: true },
      { key: "start_time", label: "開始", type: "text" },
      { key: "end_time", label: "結束", type: "text" },
      { key: "color", label: "顏色", type: "text" },
      { key: "is_active", label: "啟用", type: "bool" },
    ],
  },
  levels: {
    title: "職級",
    endpoint: "/api/master/job_levels",
    columns: [
      { key: "code", label: "代碼", type: "text", required: true },
      { key: "name", label: "名稱", type: "text", required: true },
      { key: "priority", label: "優先序", type: "number" },
      { key: "is_active", label: "啟用", type: "bool" },
    ],
  },
  skills: {
    title: "技能",
    endpoint: "/api/master/skill_codes",
    columns: [
      { key: "code", label: "代碼", type: "text", required: true },
      { key: "name", label: "名稱", type: "text", required: true },
      { key: "is_active", label: "啟用", type: "bool" },
    ],
  },
};

async function loadMaster(kind) {
  state.masterKind = kind;
  const meta = MASTER[kind];
  if (!meta) return;

  $("#masterTitle").textContent = meta.title;

  const rows = await api(meta.endpoint);
  const wrap = $("#masterTableWrap");

  const ths = meta.columns.map((c) => `<th>${esc(c.label)}</th>`).join("");
  const trs = rows
    .map((r) => {
      const tds = meta.columns
        .map((c) => {
          let v = r[c.key];
          if (c.type === "bool") v = v ? "是" : "否";
          return `<td>${esc(v)}</td>`;
        })
        .join("");
      return `<tr data-id="${r.id}">${tds}<td><button class="btn btn--sm" data-act="edit">編輯</button> <button class="btn btn--sm" data-act="del">刪除</button></td></tr>`;
    })
    .join("");

  wrap.innerHTML = `
    <table class="table">
      <thead><tr>${ths}<th></th></tr></thead>
      <tbody>${trs}</tbody>
    </table>
  `;

  wrap.querySelectorAll("button[data-act]").forEach((btn) => {
    btn.addEventListener("click", async (e) => {
      const tr = e.target.closest("tr");
      const id = tr.dataset.id;
      const act = e.target.dataset.act;
      const row = rows.find((x) => String(x.id) === String(id));
      if (!row) return;
      if (act === "edit") return openMasterEditor(kind, row);
      if (act === "del") {
        if (!confirm(`確定要刪除：${row.id}？`)) return;
        await api(`${meta.endpoint}/${id}`, { method: "DELETE" });
        toast("已刪除", "good");
        await loadMaster(kind);
      }
    });
  });
}

function openMasterEditor(kind, row) {
  const meta = MASTER[kind];
  const isNew = !row;
  const fields = meta.columns
    .map((c) => {
      const v = row ? row[c.key] : (c.type === "bool" ? true : "");
      if (c.type === "bool") {
        return `<label class="field"><span>${esc(c.label)}</span><input type="checkbox" id="f_${esc(c.key)}" ${v ? "checked" : ""}></label>`;
      }
      if (c.type === "number") {
        return `<label class="field full"><span>${esc(c.label)}</span><input type="number" id="f_${esc(c.key)}" value="${esc(v)}"></label>`;
      }
      return `<label class="field full"><span>${esc(c.label)}</span><input type="text" id="f_${esc(c.key)}" value="${esc(v)}"></label>`;
    })
    .join("");

  openModal({
    title: isNew ? `新增${meta.title}` : `編輯${meta.title}`,
    bodyHtml: `<div class="form">${fields}</div>`,
    onOk: async () => {
      const payload = { ...(row || {}) };
      for (const c of meta.columns) {
        const el = $("#f_" + c.key);
        if (c.type === "bool") payload[c.key] = el.checked;
        else if (c.type === "number") payload[c.key] = Number(el.value || 0);
        else payload[c.key] = el.value;
      }

      // basic required check
      for (const c of meta.columns) {
        if (c.required && !String(payload[c.key] || "").trim()) {
          throw new Error(`請填寫：${c.label}`);
        }
      }

      await api(meta.endpoint, { method: "POST", body: JSON.stringify(payload) });
      toast(isNew ? "已新增" : "已更新", "good");
      await loadMaster(kind);
    },
  });
}

// ===== Optimization =====
async function loadOptimization() {
  await loadJobs();
}

async function loadJobs() {
  const rows = await api(`/optimization/jobs?project_id=${state.project.id}`);
  const tbody = $("#jobsTable tbody");
  tbody.innerHTML = rows
    .map((j) => {
      const dt = (j.updated_at || j.created_at || "").toString().replace("T", " ").slice(0, 19);
      return `
        <tr data-id="${j.id}">
          <td>${j.id}</td>
          <td>${esc(j.status)}</td>
          <td>${esc(j.progress)}%</td>
          <td class="muted">${esc(dt)}</td>
          <td><button class="btn btn--sm" data-act="run">執行</button></td>
        </tr>
      `;
    })
    .join("");

  tbody.querySelectorAll("button[data-act='run']").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      const id = e.target.closest("tr").dataset.id;
      runJobStream(Number(id));
    });
  });
}

async function createAndRunJob() {
  const job = await api("/optimization/jobs", {
    method: "POST",
    body: JSON.stringify({ project_id: state.project.id, plan_id: String(state.project.id || "") }),
  });
  toast(`已建立 Job #${job.id}`, "good");
  await loadJobs();
  runJobStream(job.id);
}

function runJobStream(jobId) {
  const logEl = $("#optLog");
  const statusEl = $("#optStatus");
  const barEl = $("#optBar");
  logEl.textContent = "";
  statusEl.textContent = `執行中（Job #${jobId}）...`;
  barEl.style.width = "0%";

  const es = new EventSource(`/optimization/jobs/${jobId}/stream`);

  const pushLog = (line) => {
    logEl.textContent += line + "\n";
    logEl.scrollTop = logEl.scrollHeight;
  };

  es.addEventListener("phase", (e) => {
    try {
      const d = JSON.parse(e.data);
      const phaseMap = {
        compile_start: "開始解析規則與輸入...",
        compile_done: "編譯完成，準備求解...",
        solve_start: "開始求解...",
        solve_done: "求解完成，準備寫入...",
        persist_start: "寫入資料庫...",
        persist_done: "寫入完成",
      };
      if (d.phase && phaseMap[d.phase]) statusEl.textContent = phaseMap[d.phase];
      if (d.phase) pushLog(`[${d.phase}] ${phaseMap[d.phase] || ""}`.trim());
      if (d.report?.objective) pushLog(`目標值：${d.report.objective}`);
    } catch {
      pushLog(e.data);
    }
  });

  es.addEventListener("log", (e) => {
    try {
      const d = JSON.parse(e.data);
      if (d.message) pushLog(d.message);
    } catch {
      pushLog(e.data);
    }
  });

  es.addEventListener("metric", (e) => {
    try {
      const d = JSON.parse(e.data);
      const p = Number(d.progress || 0);
      if (!Number.isNaN(p)) barEl.style.width = `${Math.max(0, Math.min(100, p))}%`;
    } catch {
      // ignore
    }
  });

  es.addEventListener("result", async (e) => {
    try {
      const d = JSON.parse(e.data);
      pushLog(`完成：${d.status || ""}`);
    } catch {
      pushLog("完成");
    }
    statusEl.textContent = "完成";
    barEl.style.width = "100%";
    es.close();
    await loadJobs();
    if (state.currentView === "calendar") await loadCalendar();
    toast("最佳化完成（已寫入班表）", "good");
  });

  es.addEventListener("error", async (e) => {
    try {
      const d = e.data ? JSON.parse(e.data) : null;
      const msg = d?.error?.message || d?.error || "串流錯誤";
      pushLog(msg);
      statusEl.textContent = msg;
    } catch {
      pushLog("串流中斷（可能是後端錯誤或連線中斷）");
      statusEl.textContent = "中斷";
    }
    es.close();
    await loadJobs();
    toast("最佳化失敗或中斷（請查看 logs/）", "bad");
  });
}

// ===== DSL Tester =====
function initDslTester() {
  // no-op (button wired in boot)
}

async function runDslValidateOnly() {
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

// ===== Boot =====
async function boot() {
  wireModal();

  // nav
  $$(".nav__item").forEach((b) => b.addEventListener("click", () => setView(b.dataset.view)));
  $("#btnRefresh").addEventListener("click", () => setView(state.currentView));

  // calendar
  $("#btnLoadCalendar").addEventListener("click", () => loadCalendar().catch((e) => toast(`載入失敗：${e.message}`, "bad")));

  // rules actions
  $("#btnNlToDsl").addEventListener("click", runNlToDslStream);
  $("#btnValidate").addEventListener("click", () => runValidateDsl().catch((e) => toast(`驗證失敗：${e.message}`, "bad")));
  $("#btnDslToNl").addEventListener("click", () => runDslToNl().catch((e) => toast(`反向翻譯失敗：${e.message}`, "bad")));
  $("#btnSaveRule").addEventListener("click", () => saveRuleFromPanel().catch((e) => toast(`儲存失敗：${e.message}`, "bad")));
  $("#btnReloadRules").addEventListener("click", () => loadRules().catch((e) => toast(`載入失敗：${e.message}`, "bad")));

  // master tabs
  $$(".tab").forEach((t) => {
    t.addEventListener("click", () => {
      $$(".tab").forEach((x) => x.classList.remove("is-active"));
      t.classList.add("is-active");
      const kind = t.dataset.tab;
      loadMaster(kind).catch((e) => toast(`載入失敗：${e.message}`, "bad"));
    });
  });
  $("#btnReloadMaster").addEventListener("click", () => loadMaster(state.masterKind).catch((e) => toast(`載入失敗：${e.message}`, "bad")));
  $("#btnAddMaster").addEventListener("click", () => openMasterEditor(state.masterKind, null));

  // optimization
  $("#btnCreateJob").addEventListener("click", () => createAndRunJob().catch((e) => toast(`建立失敗：${e.message}`, "bad")));
  $("#btnReloadJobs").addEventListener("click", () => loadJobs().catch((e) => toast(`載入失敗：${e.message}`, "bad")));

  // dsl tester
  $("#btnDslValidateOnly").addEventListener("click", () => runDslValidateOnly().catch((e) => toast(`驗證失敗：${e.message}`, "bad")));

  // project pill
  try {
    state.project = await api("/api/projects/current");
    $("#projectPill").textContent = `專案：${state.project.name}（${state.project.month}）`;
  } catch (e) {
    $("#projectPill").textContent = "專案載入失敗";
    toast(`專案載入失敗：${e.message}`, "bad");
  }

  // initial view
  setView("calendar");
}

boot();
