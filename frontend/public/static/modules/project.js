import { endOfMonth } from "./date.js";
import { state } from "./state.js";

export function projectMonthRange() {
  if (!state.project?.month) return null;
  const [y, m] = state.project.month.split("-").map((x) => Number(x));
  if (!y || !m) return null;
  const first = new Date(y, m - 1, 1);
  const last = endOfMonth(first);
  return [first, last];
}
