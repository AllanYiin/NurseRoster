import { $ } from "../dom.js";
import { api } from "../api.js";
import { esc } from "../escape.js";
import { toast } from "../toast.js";
import { state } from "../state.js";
import { openModal } from "../modal.js";

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

export async function loadMaster(kind) {
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

export function openMasterEditor(kind, row) {
  const meta = MASTER[kind];
  const isNew = !row;
  const fields = meta.columns
    .map((c) => {
      const v = row ? row[c.key] : c.type === "bool" ? true : "";
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
