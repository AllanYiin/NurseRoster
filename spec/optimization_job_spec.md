# Optimization Job Specification

本文件整理最佳化任務（Optimization Job）目前實作所對應的細部技術規格，供後續維護與驗證使用。內容來源為需求提供的規格，並整理成便於查閱的格式。

## 1. 任務概述
- 在指定的 `SchedulePlan`（期間 + 科別）與合併後的規則集合下進行排班求解。
- 預設必須滿足所有 hard constraints，並在此基礎上最小化 soft penalty、最大化偏好（以負值最小化表示）。
- 完成後產生新的草稿 `ScheduleVersion` 與完整 `Assignment` 集合，並提供可重現、可比較、可發布的結果。

## 2. API 介面
- `POST /optimization/jobs`：建立求解任務，包含計畫、版本、模式、時間限制、隨機種子、範圍與輸出設定。
- `GET /optimization/jobs/{id}`：查詢任務狀態與結果摘要。
- `GET /optimization/jobs/{id}/stream`：以 SSE 方式回傳進度/日誌/結果，事件類型包含 `phase`、`log`、`metric`、`result`、`error`。
- `POST /optimization/jobs/{id}/cancel`：請求取消任務。
- `POST /optimization/jobs/{id}/apply`：將成功結果套用/建版。

### SSE 事件建議
- `phase`：`compile_start|compile_done|solve_start|solve_progress|solve_done|persist_start|persist_done`。
- `log`：文字訊息，可附 stage/category。
- `metric`：最佳值、gap、objective breakdown、進度百分比。
- `result`：最終結果（version_id、摘要指標）。
- `error`：結構化錯誤 payload。

## 3. Job 狀態機
- `queued` → `compiling` → `solving` → `persisting` → `succeeded | failed | cancelled`。
- 狀態需持久化，便於追蹤與重跑。

## 4. 資料與前置檢查
- 資料來源優先序：Plan、Base Version（含 locked assignments）、Master Data（nurse/shift/rank）、Demand/Coverage、合併後的 Rules。
- 執行前必須檢查：日期區間有效、shift 至少包含 1 個 work + 1 個 off、範圍內至少 1 名護理師、鎖定資訊一致且無衝突、規則可編譯。
- 驗證失敗時，以 SSE `error` 回報並將狀態標記為 `failed`，不產生新版本。

## 5. CP-SAT 建模重點
- 變數：`x[n,d,s] ∈ {0,1}`，並衍生 `work[n,d]`、`night[n,d]`、`weekend[n,d]` 等輔助變數。
- 硬約束：每日唯一班、鎖定固定、班別集合、覆蓋需求（硬或 soft shortage 變數）、技能 mix、最大連續上班天數、禁止相鄰班別序列、最小休息時間（以 forbidden pairs 近似）。
- 目標：最小化 `soft_penalty*soft_multiplier + fairness*fairness_multiplier - preference*preference_multiplier`。夜班/週末公平性以 range 最小化示意。
- Warm start：可用 base version 產生 hint；可選最小改動成本變數。

## 6. 輸出與版本管理
- 成功時建立草稿 `schedule_version`，寫入全量 `assignment`，回傳 SSE `result` 包含 run_id、version_id、metrics 與 breakdown。
- 失敗時不建立版本（除非另有設定），回傳 SSE `error`。

## 7. 可觀測性
- 預設階段：compile_start/done、solve_start/progress/done、persist_start/done。
- Log 格式：`ts`、`level`、`stage`、`message`、`context`。
- `compile_report_json` 建議紀錄變數/約束/目標項數量；`solve_report_json` 建議紀錄 solver 狀態、目標值、gap、時間、breakdown。

## 8. 錯誤處理
- 統一 payload：`{ "ok": false, "error": { "code", "message", "details" } }`。
- 常見錯誤碼：`RULE_DSL_INVALID`、`OPT_INFEASIBLE`、`OPT_TIMEOUT`、`DB_CONSTRAINT`，其餘可依情境新增（如 VALIDATION、INTERNAL）。

## 9. SQLite 寫入
- `persisting` 階段需使用 transaction，建議分批寫入；若重跑同版本需先刪除舊資料。
- 建議 unique constraint `(version_id, nurse_id, date)` 以避免撞 key。

## 10. 驗收與測試提醒
- 確認 strict_hard 下 `hard_violations=0`。
- respect_locked 時輸出不得改動 locked 指派。
- SSE 需能顯示進度。
- 結果可落版並在 UI 檢視。
- 相同 seed/參數應能重現（允許多解但 objective 不惡化）。

## 11. 精選測試案例
- 覆蓋量不可行 → 回報 INFEASIBLE 並提示。
- Locked 衝突 → VALIDATION failed，指出衝突 nurse/date。
- 避免 D→N soft → 迭代後 D→N 次數下降，breakdown 有 avoid_sequence。
- 夜班公平性 → 提高 fairness_multiplier 後 range 下降。
- Change cost → base version 有調整時，change_weight>0 可減少改動格數。
