import { endOfMonth, isoDate } from "./date.js";
import { state } from "./state.js";
import { $ } from "./dom.js";
import { api } from "./api.js";
import { openModal } from "./modal.js";
import { toast } from "./toast.js";

export function projectMonthRange() {
  if (!state.project?.month) return null;
  const [y, m] = state.project.month.split("-").map((x) => Number(x));
  if (!y || !m) return null;
  const first = new Date(y, m - 1, 1);
  const last = endOfMonth(first);
  return [first, last];
}

export function setCurrentProject(project) {
  state.project = project;
  const pill = $("#projectPill");
  if (!project) {
    if (pill) pill.textContent = "尚無專案資料";
    return;
  }
  if (pill) pill.textContent = `專案：${project.name}（${project.month}）`;
  const pm = projectMonthRange();
  if (pm) {
    $("#conflictStart").value = isoDate(pm[0]);
    $("#conflictEnd").value = isoDate(pm[1]);
  }
}

export function openProjectCreator({ onCreated } = {}) {
  const today = new Date();
  const monthValue = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}`;
  openModal({
    title: "建立專案",
    bodyHtml: `
      <div class="form">
        <label class="field full">
          <span>專案名稱</span>
          <input type="text" id="projectName" placeholder="例如：護理排班 2024/08" value="新專案" />
        </label>
        <label class="field">
          <span>月份</span>
          <input type="month" id="projectMonth" value="${monthValue}" />
        </label>
      </div>
    `,
    onOk: async () => {
      const name = $("#projectName").value.trim();
      const month = $("#projectMonth").value.trim();
      if (!name) throw new Error("請輸入專案名稱");
      if (!month) throw new Error("請選擇月份");
      const project = await api("/api/projects", {
        method: "POST",
        body: JSON.stringify({ name, month }),
      });
      setCurrentProject(project);
      toast("已建立專案", "good");
      if (onCreated) await onCreated(project);
    },
  });
}
