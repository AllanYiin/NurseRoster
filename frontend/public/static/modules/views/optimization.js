import { $ } from "../dom.js";
import { api } from "../api.js";
import { esc } from "../escape.js";
import { toast } from "../toast.js";
import { state } from "../state.js";
import { loadCalendar } from "./calendar.js";

export async function loadOptimization() {
  await loadJobs();
}

export async function loadJobs() {
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

export async function createAndRunJob() {
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
