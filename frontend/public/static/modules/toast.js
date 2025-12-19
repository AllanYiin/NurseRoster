import { $ } from "./dom.js";

export function toast(msg, kind = "info") {
  const el = $("#toast");
  if (!el) {
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
