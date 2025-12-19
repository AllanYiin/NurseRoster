import { $, $$ } from "./dom.js";
import { api } from "./api.js";
import { toast } from "./toast.js";
import { state } from "./state.js";
import { wireModal } from "./modal.js";
import { openProjectCreator, setCurrentProject } from "./project.js";
import { setView } from "./router.js";
import { loadCalendar } from "./views/calendar.js";
import {
  runNlToDslStream,
  runValidateDsl,
  runDslToNl,
  saveRuleFromPanel,
  loadRules,
  syncRuleFiltersFromUI,
  resetRuleFilters,
  sendRuleChat,
  applyScratchToDsl,
  loadRuleConflicts,
  renderRuleChatLog,
  setRuleChatScratch,
} from "./views/rules.js";
import { loadMaster, openMasterEditor } from "./views/master.js";
import { createAndRunJob, loadJobs } from "./views/optimization.js";
import { nlToDslLab, runDslValidateOnly, runDslLabReverse, runDslLabValidate } from "./views/dsl.js";

export async function boot() {
  wireModal();

  $$(".nav__item").forEach((b) => b.addEventListener("click", () => setView(b.dataset.view)));
  $("#btnRefresh").addEventListener("click", () => setView(state.currentView));

  $("#btnLoadCalendar").addEventListener("click", () => loadCalendar().catch((e) => toast(`載入失敗：${e.message}`, "bad")));
  $("#calRange")?.addEventListener("change", () => loadCalendar().catch((e) => toast(`載入失敗：${e.message}`, "bad")));
  $("#calStart")?.addEventListener("change", () => {
    $("#calStart").dataset.manual = "1";
  });

  $("#btnNlToDsl")?.addEventListener("click", runNlToDslStream);
  $("#btnValidate")?.addEventListener("click", () => runValidateDsl().catch((e) => toast(`驗證失敗：${e.message}`, "bad")));
  $("#btnDslToNl")?.addEventListener("click", () => runDslToNl().catch((e) => toast(`反向翻譯失敗：${e.message}`, "bad")));
  $("#btnSaveRule")?.addEventListener("click", () => saveRuleFromPanel().catch((e) => toast(`儲存失敗：${e.message}`, "bad")));
  $("#btnReloadRules")?.addEventListener("click", () => loadRules().catch((e) => toast(`載入失敗：${e.message}`, "bad")));
  $("#btnApplyRuleFilter")?.addEventListener("click", () => {
    syncRuleFiltersFromUI();
    loadRules().catch((e) => toast(`載入失敗：${e.message}`, "bad"));
  });
  $("#btnClearRuleFilter")?.addEventListener("click", () => {
    resetRuleFilters();
    loadRules().catch((e) => toast(`載入失敗：${e.message}`, "bad"));
  });
  $("#ruleFilterQ")?.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      syncRuleFiltersFromUI();
      loadRules().catch((err) => toast(`載入失敗：${err.message}`, "bad"));
    }
  });
  $("#btnChatSend")?.addEventListener("click", sendRuleChat);
  $("#btnChatApplyToDsl")?.addEventListener("click", () => {
    setView("dsl");
    applyScratchToDsl("tester");
  });
  $("#btnScratchToTester")?.addEventListener("click", () => {
    setView("dsl");
    applyScratchToDsl("tester");
  });
  $("#btnReloadConflicts")?.addEventListener("click", () => loadRuleConflicts().catch((e) => toast(`衝突載入失敗：${e.message}`, "bad")));
  $("#ruleChatScratch")?.addEventListener("input", (e) => {
    state.ruleChatScratch = e.target.value;
  });
  renderRuleChatLog();
  setRuleChatScratch(state.ruleChatScratch);

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

  $("#btnCreateJob").addEventListener("click", () => createAndRunJob().catch((e) => toast(`建立失敗：${e.message}`, "bad")));
  $("#btnReloadJobs").addEventListener("click", () => loadJobs().catch((e) => toast(`載入失敗：${e.message}`, "bad")));

  $("#btnDslValidateOnly").addEventListener("click", () => runDslValidateOnly().catch((e) => toast(`驗證失敗：${e.message}`, "bad")));
  $("#btnDslLabNlToDsl").addEventListener("click", nlToDslLab);
  $("#btnDslLabDslToNl").addEventListener("click", () => runDslLabReverse().catch((e) => toast(`反向翻譯失敗：${e.message}`, "bad")));
  $("#btnDslLabValidate").addEventListener("click", () => runDslLabValidate().catch((e) => toast(`驗證失敗：${e.message}`, "bad")));
  $("#btnCreateProject").addEventListener("click", () =>
    openProjectCreator({
      onCreated: async () => {
        toggleProjectNav(true);
        setView("calendar");
      },
    })
  );

  const toggleProjectNav = (enabled) => {
    $$(".nav__item[data-requires-project]").forEach((btn) => {
      btn.disabled = !enabled;
    });
  };

  try {

    state.project = await api("/api/projects/current");
    setCurrentProject(state.project);
    toggleProjectNav(true);

  } catch (e) {
    setCurrentProject(null);
    toast("目前沒有專案資料，請先建立專案。", "warn");
    toggleProjectNav(false);
  }

  setView(state.project?.id ? "calendar" : "no-project");
}
