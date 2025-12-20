import { $, $$ } from "../dom.js";
import { api } from "../api.js";
import { toast } from "../toast.js";
import { state } from "../state.js";
import { openModal } from "../modal.js";
import { projectMonthRange } from "../project.js";
import { isoDate } from "../date.js";

const STEPS = [1, 2, 3, 4, 5, 6];

function initWizardState() {
  if (!state.ruleBundleWizard) {
    state.ruleBundleWizard = {
      step: 1,
      period: null,
      lawRuleIds: [],
      hospitalRuleIds: [],
      templateId: null,
      nursePrefPeriodId: null,
      nursePrefMode: "CLONE_AS_IS",
      bundle: null,
      initialized: false,
      templates: [],
    };
  }
}

function setStep(step) {
  initWizardState();
  state.ruleBundleWizard.step = step;
  $$(".wizard__step").forEach((btn) => btn.classList.toggle("is-active", Number(btn.dataset.step) === step));
  $$(".wizard__panel").forEach((panel) => panel.classList.toggle("is-active", Number(panel.dataset.step) === step));
}

function renderRuleList(targetId, rules, selectedIds) {
  const wrap = $(targetId);
  if (!wrap) return;
  if (!rules.length) {
    wrap.innerHTML = `<div class="muted">目前沒有可選規則</div>`;
    return;
  }
  wrap.innerHTML = rules
    .map(
      (r) => `
        <label class="wizard__list-item">
          <input type="checkbox" data-rule-id="${r.id}" ${selectedIds.includes(r.id) ? "checked" : ""} />
          <div>
            <div class="strong">${r.title || "(未命名規則)"}</div>
            <div class="muted">#${r.id} / ${r.scope_type} / ${r.rule_type}</div>
          </div>
        </label>
      `
    )
    .join("");
}

async function loadDepartments() {
  const deps = await api("/api/master/departments");
  const select = $("#wizardDepartment");
  if (!select) return;
  select.innerHTML = deps.map((d) => `<option value="${d.id}">${d.code}｜${d.name}</option>`).join("");
  return deps;
}

async function loadLawRules() {
  if (!state.project?.id) return;
  const rules = await api(`/api/rules?project_id=${state.project.id}&scope_type=GLOBAL&type=HARD`);
  if (!state.ruleBundleWizard.lawRuleIds.length) {
    state.ruleBundleWizard.lawRuleIds = rules.map((r) => r.id);
  }
  renderRuleList("#wizardLawRules", rules, state.ruleBundleWizard.lawRuleIds);
  $("#wizardLawRules")?.querySelectorAll("input[type=checkbox]").forEach((cb) => {
    cb.addEventListener("change", (e) => {
      const id = Number(e.target.dataset.ruleId);
      state.ruleBundleWizard.lawRuleIds = toggleSelected(state.ruleBundleWizard.lawRuleIds, id, e.target.checked);
    });
  });
}

async function loadHospitalRules() {
  if (!state.project?.id) return;
  const hospitalId = Number($("#wizardHospitalId")?.value) || null;
  if (!hospitalId) {
    $("#wizardHospitalRules").innerHTML = `<div class="muted">請先輸入院區 ID。</div>`;
    $("#wizardHospitalImportStatus").textContent = "尚未匯入預設規則";
    return;
  }
  const rules = await api(`/api/rules?project_id=${state.project.id}&scope_type=HOSPITAL&scope_id=${hospitalId}&type=HARD`);
  if (!state.ruleBundleWizard.hospitalRuleIds.length) {
    state.ruleBundleWizard.hospitalRuleIds = rules.map((r) => r.id);
  }
  $("#wizardHospitalImportStatus").textContent = rules.length ? `已載入 ${rules.length} 條規則` : "尚未匯入預設規則";
  renderRuleList("#wizardHospitalRules", rules, state.ruleBundleWizard.hospitalRuleIds);
  $("#wizardHospitalRules")?.querySelectorAll("input[type=checkbox]").forEach((cb) => {
    cb.addEventListener("change", (e) => {
      const id = Number(e.target.dataset.ruleId);
      state.ruleBundleWizard.hospitalRuleIds = toggleSelected(state.ruleBundleWizard.hospitalRuleIds, id, e.target.checked);
    });
  });
}

async function importHospitalHardRules() {
  if (!state.project?.id) return;
  const hospitalId = Number($("#wizardHospitalId")?.value) || null;
  if (!hospitalId) return toast("請先輸入院區 ID", "warn");
  const payload = { hospital_id: hospitalId };
  const created = await api(`/api/rules:seed-hospital-hard?project_id=${state.project.id}`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
  $("#wizardHospitalImportStatus").textContent = created.length ? `已匯入 ${created.length} 條規則` : "已匯入（無新增規則）";
  state.ruleBundleWizard.hospitalRuleIds = [];
  await loadHospitalRules();
  toast("已匯入醫院硬規則", "good");
}

async function loadTemplates() {
  const hospitalId = Number($("#wizardHospitalId")?.value) || null;
  const departmentId = Number($("#wizardDepartment")?.value) || null;
  const params = new URLSearchParams();
  if (hospitalId) params.set("hospital_id", hospitalId);
  if (departmentId) params.set("department_id", departmentId);
  const templates = await api(`/api/templates?${params.toString()}`);
  state.ruleBundleWizard.templates = templates;
  const select = $("#wizardTemplateSelect");
  if (!select) return;
  select.innerHTML = `<option value="">請選擇公版</option>` + templates.map((t) => `<option value="${t.id}">${t.name}</option>`).join("");
  if (state.ruleBundleWizard.templateId) {
    select.value = String(state.ruleBundleWizard.templateId);
  }
  return templates;
}

async function loadTemplateRules() {
  const templateId = Number($("#wizardTemplateSelect")?.value) || null;
  state.ruleBundleWizard.templateId = templateId;
  if (!templateId) {
    $("#wizardTemplateRules").innerHTML = `<div class="muted">請先選擇公版。</div>`;
    $("#wizardTemplateStatus").textContent = "尚未載入公版";
    return;
  }
  const allRules = await api(`/api/rules?project_id=${state.project.id}`);
  const candidateRules = allRules.filter((r) => r.scope_type !== "NURSE");
  const links = await api(`/api/templates/${templateId}/rules`);
  const includedIds = links.filter((l) => l.included).map((l) => l.rule_id);
  renderRuleList("#wizardTemplateRules", candidateRules, includedIds);
  $("#wizardTemplateStatus").textContent = `已載入 ${candidateRules.length} 條規則`;
}

async function saveTemplateRules() {
  const templateId = Number($("#wizardTemplateSelect")?.value) || null;
  if (!templateId) return toast("請先選擇公版", "warn");
  const selectedIds = [];
  $("#wizardTemplateRules")
    ?.querySelectorAll("input[type=checkbox]")
    .forEach((cb) => {
      if (cb.checked) selectedIds.push(Number(cb.dataset.ruleId));
    });
  const payload = {
    items: selectedIds.map((id) => ({ rule_id: id, included: true })),
  };
  await api(`/api/templates/${templateId}/rules`, { method: "PUT", body: JSON.stringify(payload) });
  toast("已儲存公版規則", "good");
}

async function loadPreviousPeriods() {
  const period = state.ruleBundleWizard.period;
  if (!period?.id) return;
  const departmentId = Number($("#wizardDepartment")?.value) || null;
  const params = new URLSearchParams();
  if (departmentId) params.set("department_id", departmentId);
  const rows = await api(`/api/schedule-periods/${period.id}/previous-periods?${params.toString()}`);
  const select = $("#wizardNursePrefPeriod");
  select.innerHTML = `<option value="">不載入</option>` + rows.map((p) => `<option value="${p.id}">${p.name}</option>`).join("");
  if (!state.ruleBundleWizard.nursePrefPeriodId && rows.length) {
    state.ruleBundleWizard.nursePrefPeriodId = rows[0].id;
    select.value = String(rows[0].id);
    $("#wizardNursePrefStatus").textContent = `預設上一期：${rows[0].name}`;
  }
}

function toggleSelected(list, id, checked) {
  const set = new Set(list);
  if (checked) set.add(id);
  else set.delete(id);
  return Array.from(set);
}

async function createPeriod() {
  const name = $("#wizardPeriodName").value.trim() || "未命名排班期";
  const startDate = $("#wizardStartDate").value;
  const endDate = $("#wizardEndDate").value;
  const departmentId = Number($("#wizardDepartment").value) || null;
  const hospitalId = Number($("#wizardHospitalId").value) || null;
  if (!startDate || !endDate || !departmentId) {
    return toast("請完整填寫科別與日期", "warn");
  }
  const payload = {
    name,
    start_date: startDate,
    end_date: endDate,
    project_id: state.project?.id || null,
    hospital_id: hospitalId,
    department_id: departmentId,
  };
  const period = await api("/api/schedule-periods", { method: "POST", body: JSON.stringify(payload) });
  state.ruleBundleWizard.period = period;
  $("#wizardPeriodStatus").textContent = `已建立排班期 #${period.id}`;
  await loadPreviousPeriods();
  toast("排班期已建立", "good");
}

async function generateBundle(validateOnly) {
  const period = state.ruleBundleWizard.period;
  if (!period?.id) return toast("請先建立排班期", "warn");
  const hospitalId = Number($("#wizardHospitalId").value) || null;
  const departmentId = Number($("#wizardDepartment").value) || null;
  const payload = {
    period_id: period.id,
    project_id: state.project?.id,
    hospital_id: hospitalId,
    department_id: departmentId,
    law: { include_rule_ids: state.ruleBundleWizard.lawRuleIds },
    hospital: { include_rule_ids: state.ruleBundleWizard.hospitalRuleIds },
    template: { template_id: state.ruleBundleWizard.templateId },
    nurse_pref: {
      from_period_id: state.ruleBundleWizard.nursePrefPeriodId,
      mode: state.ruleBundleWizard.nursePrefMode,
    },
    options: { validate_only: validateOnly },
  };
  const bundle = await api("/api/rule-bundles:generate", { method: "POST", body: JSON.stringify(payload) });
  state.ruleBundleWizard.bundle = bundle;
  $("#wizardValidationBadge").textContent = `VALIDATION: ${bundle.validation_status || "PENDING"}`;
  const items = await api(`/api/rule-bundles/${bundle.id}/items`);
  renderBundleSummary(bundle, items);
  renderBundlePreview(items);
  if (!validateOnly) {
    await api(`/api/rule-bundles/${bundle.id}/activate`, { method: "POST", body: JSON.stringify({ create_snapshot: true }) });
    toast("已生成並套用規則集", "good");
  }
}

function renderBundleSummary(bundle, items) {
  const counts = items.reduce(
    (acc, it) => {
      acc[it.layer] = (acc[it.layer] || 0) + 1;
      return acc;
    },
    { LAW: 0, HOSPITAL: 0, TEMPLATE: 0, NURSE_PREF: 0 }
  );
  $("#wizardBundleSummary").innerHTML = `
    <div><strong>Bundle</strong> #${bundle.id}</div>
    <div>SHA: ${bundle.bundle_sha256?.slice(0, 8)}…</div>
    <div>LAW：${counts.LAW} 條</div>
    <div>HOSPITAL：${counts.HOSPITAL} 條</div>
    <div>TEMPLATE：${counts.TEMPLATE} 條</div>
    <div>NURSE_PREF：${counts.NURSE_PREF} 條</div>
    <div>狀態：${bundle.validation_status}</div>
  `;
}

function renderBundlePreview(items) {
  const wrap = $("#wizardBundlePreview");
  wrap.innerHTML = items
    .map(
      (it) => `
      <div class="wizard__list-item">
        <div class="strong">${it.layer}</div>
        <div class="muted">rule #${it.rule_id} / v${it.rule_version_id} / ${it.rule_type} / priority ${it.priority_at_time}</div>
      </div>
    `
    )
    .join("");
}

function bindTemplateCrud() {
  $("#wizardTemplateCreate").addEventListener("click", () => openTemplateModal());
  $("#wizardTemplateEdit").addEventListener("click", () => openTemplateModal(true));
  $("#wizardTemplateDelete").addEventListener("click", async () => {
    const templateId = Number($("#wizardTemplateSelect").value) || null;
    if (!templateId) return toast("請先選擇公版", "warn");
    if (!confirm("確定要刪除該公版？")) return;
    await api(`/api/templates/${templateId}`, { method: "DELETE" });
    toast("已刪除公版", "good");
    await loadTemplates();
  });
}

function openTemplateModal(isEdit = false) {
  const templateId = Number($("#wizardTemplateSelect").value) || null;
  const selected = (state.ruleBundleWizard.templates || []).find((t) => t.id === templateId);
  const currentName = selected?.name || "";
  const currentDesc = selected?.description || "";
  openModal({
    title: isEdit ? "編輯公版" : "新增公版",
    bodyHtml: `
      <label class="field full"><span>名稱</span><input id="tplName" value="${isEdit ? currentName : ""}" /></label>
      <label class="field full"><span>描述</span><textarea id="tplDesc" rows="3">${isEdit ? currentDesc : ""}</textarea></label>
    `,
    onOk: async () => {
      const payload = {
        name: $("#tplName").value.trim() || "未命名公版",
        description: $("#tplDesc").value.trim(),
        hospital_id: Number($("#wizardHospitalId").value) || null,
        department_id: Number($("#wizardDepartment").value) || null,
      };
      if (isEdit && templateId) {
        await api(`/api/templates/${templateId}`, { method: "PUT", body: JSON.stringify(payload) });
      } else {
        await api("/api/templates", { method: "POST", body: JSON.stringify(payload) });
      }
      await loadTemplates();
      toast(isEdit ? "已更新公版" : "已新增公版", "good");
    },
  });
}

function bindWizardNav() {
  $$(".wizard__step").forEach((btn) => btn.addEventListener("click", () => setStep(Number(btn.dataset.step))));
  $("#wizardPrev").addEventListener("click", () => {
    const idx = Math.max(0, STEPS.indexOf(state.ruleBundleWizard.step) - 1);
    setStep(STEPS[idx]);
  });
  $("#wizardNext").addEventListener("click", async () => {
    const idx = Math.min(STEPS.length - 1, STEPS.indexOf(state.ruleBundleWizard.step) + 1);
    if (STEPS[idx] === 2) await loadLawRules();
    if (STEPS[idx] === 3) await loadHospitalRules();
    if (STEPS[idx] === 4) await loadTemplates();
    if (STEPS[idx] === 5) await loadPreviousPeriods();
    setStep(STEPS[idx]);
  });
}

export async function loadRuleBundleWizard() {
  initWizardState();
  setStep(state.ruleBundleWizard.step || 1);
  await loadDepartments();
  if (state.project?.month) {
    const range = projectMonthRange();
    if (range) {
      $("#wizardStartDate").value = isoDate(range[0]);
      $("#wizardEndDate").value = isoDate(range[1]);
      $("#wizardPeriodName").value = `${state.project.name} ${state.project.month} 排班期`;
    }
  }
  if (!state.ruleBundleWizard.initialized) {
    bindWizardNav();

    $("#wizardCreatePeriod").addEventListener("click", () => createPeriod().catch((e) => toast(`建立失敗：${e.message}`, "bad")));
    $("#wizardHospitalId").addEventListener("change", () => loadHospitalRules().catch((e) => toast(`載入失敗：${e.message}`, "bad")));
    $("#wizardImportHospitalHardRules").addEventListener("click", () => importHospitalHardRules().catch((e) => toast(`匯入失敗：${e.message}`, "bad")));
    $("#wizardTemplateReload").addEventListener("click", () => loadTemplates().catch((e) => toast(`載入失敗：${e.message}`, "bad")));
    $("#wizardTemplateSelect").addEventListener("change", () => loadTemplateRules().catch((e) => toast(`載入失敗：${e.message}`, "bad")));
    $("#wizardTemplateSaveRules").addEventListener("click", () => saveTemplateRules().catch((e) => toast(`儲存失敗：${e.message}`, "bad")));
    $("#wizardNursePrefPeriod").addEventListener("change", (e) => {
      state.ruleBundleWizard.nursePrefPeriodId = e.target.value ? Number(e.target.value) : null;
      $("#wizardNursePrefStatus").textContent = e.target.value ? `來源期別 #${e.target.value}` : "未載入上一期";
    });
    $("#wizardNursePrefMode").addEventListener("change", (e) => {
      state.ruleBundleWizard.nursePrefMode = e.target.value;
    });
    $("#wizardValidateBundle").addEventListener("click", () => generateBundle(true).catch((e) => toast(`驗證失敗：${e.message}`, "bad")));
    $("#wizardGenerateBundle").addEventListener("click", () => generateBundle(false).catch((e) => toast(`生成失敗：${e.message}`, "bad")));

    bindTemplateCrud();
    state.ruleBundleWizard.initialized = true;
  }
}
