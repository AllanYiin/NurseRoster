import { $, $$ } from "../dom.js";
import { api } from "../api.js";
import { esc } from "../escape.js";
import { toast } from "../toast.js";
import { isoDate, addDays, endOfMonth, startOfWeek } from "../date.js";
import { state } from "../state.js";
import { openModal } from "../modal.js";
import { openProjectCreator, projectMonthRange } from "../project.js";

export async function loadCalendar() {
  const grid = $("#calendarGrid");
  if (!state.project) {
    if (grid) {
      grid.innerHTML = `
        <div class="empty">
          <div class="muted">目前沒有可用的專案資料，請先建立專案。</div>
          <button class="btn btn--primary" data-action="create-project">建立專案</button>
        </div>
      `;
      grid.querySelector("[data-action='create-project']")?.addEventListener("click", () =>
        openProjectCreator({
          onCreated: async () => {
            await loadCalendar();
          },
        })
      );
    }
    return;
  }
  const startEl = $("#calStart");
  const rangeEl = $("#calRange");
  const rangeMode = rangeEl?.value || "28";
  if (!startEl.value) {
    const pm = projectMonthRange();
    const ws = pm ? pm[0] : startOfWeek(new Date());
    startEl.value = isoDate(ws);
  }
  let start = new Date(startEl.value + "T00:00:00");
  let days = [];
  if (rangeMode === "month") {
    const pm = projectMonthRange();
    if (pm && !startEl.dataset.manual) {
      start = pm[0];
      startEl.value = isoDate(start);
    }
    const monthEnd = pm ? pm[1] : endOfMonth(start);
    let cur = new Date(start);
    while (cur <= monthEnd) {
      days.push(isoDate(cur));
      cur = addDays(cur, 1);
    }
  } else {
    const span = Number(rangeMode) || 7;
    days = Array.from({ length: span }, (_, i) => isoDate(addDays(start, i)));
  }

  const [nurses, shifts, assignments] = await Promise.all([
    api("/api/master/nurses"),
    api("/api/master/shift_codes"),
    api(`/api/calendar/assignments?project_id=${state.project.id}&start=${days[0]}&end=${days[days.length - 1]}`),
  ]);

  const shiftMap = new Map(shifts.map((s) => [s.code, s]));
  const key = (staffNo, day) => `${staffNo}__${day}`;
  const asgMap = new Map(assignments.map((a) => [key(a.nurse_staff_no, a.day), a]));

  if (!grid) return;
  if (!nurses.length) {
    grid.innerHTML = `<div class="muted">目前沒有護理師資料，請先到「資料維護」新增。</div>`;
    return;
  }
  let html = "";
  html += `<div class="calwrap">`;
  html += `<div class="cal" style="--day-count:${days.length}">`;
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
