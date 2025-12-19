import { $ } from "./dom.js";
import { state } from "./state.js";
import { toast } from "./toast.js";

export function openModal({ title, bodyHtml, onOk }) {
  $("#modalTitle").textContent = title || "";
  $("#modalBody").innerHTML = bodyHtml || "";
  $("#modalOk").textContent = "確定";
  state.modal.onOk = onOk || null;
  $("#modal").classList.remove("is-hidden");
}

export function closeModal() {
  $("#modal").classList.add("is-hidden");
  state.modal.onOk = null;
}

export function wireModal() {
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
