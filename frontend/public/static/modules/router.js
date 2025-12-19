import { $,$$ } from "./dom.js";
import { state } from "./state.js";
import { toast } from "./toast.js";
import { loadCalendar } from "./views/calendar.js";
import { loadRules, loadRuleConflicts } from "./views/rules.js";
import { loadMaster } from "./views/master.js";
import { loadOptimization } from "./views/optimization.js";
import { initDslTester } from "./views/dsl.js";

export function setView(view) {
  state.currentView = view;
  $$(".nav__item").forEach((b) => b.classList.toggle("is-active", b.dataset.view === view));
  $$(".view").forEach((v) => v.classList.toggle("is-hidden", v.id !== `view-${view}`));

  const titleMap = {
    calendar: ["排班總覽", "自訂日期範圍（週 / 28 天 / 月）"],
    rules: ["規則維護", "自然語言 ↔ DSL + 對話與衝突"],
    master: ["資料維護", "主檔 CRUD（v1）"],
    opt: ["最佳化", "OR-Tools（v1，簡化）"],
    dsl: ["DSL 測試台", "雙向測試（NL ↔ DSL）"],
  };
  const [t, s] = titleMap[view] || ["", ""];
  $("#viewTitle").textContent = t;
  $("#viewSub").textContent = s;

  if (view === "calendar") loadCalendar().catch((e) => toast(`載入失敗：${e.message}`, "bad"));
  if (view === "rules") {
    loadRules().catch((e) => toast(`載入失敗：${e.message}`, "bad"));
    loadRuleConflicts().catch((e) => toast(`衝突載入失敗：${e.message}`, "bad"));
  }
  if (view === "master") loadMaster(state.masterKind).catch((e) => toast(`載入失敗：${e.message}`, "bad"));
  if (view === "opt") loadOptimization().catch((e) => toast(`載入失敗：${e.message}`, "bad"));
  if (view === "dsl") initDslTester();
}
