# TODO

## 0. 基礎準備（技術可行性與環境）
- [x] 確認 Zeabur 佈署策略：前後端分離、Backend 容器綁定 SQLite 持久化磁碟。
- [x] 制定 LLM streaming 方案：SSE 為主，fallback WebSocket；無金鑰時啟用可選 mock。
- [x] Logging 與例外處理：主程式入口全域 try-except，關鍵 I/O/網路/推論加入防崩潰保護，logs/ 下分級日誌（避免敏感資訊）。

## 1. 資料模型與種子
- [ ] 以 SQLAlchemy/SQLModel 建立核心表：users、nurses、departments、shift_codes、skill_codes、schedule_periods、assignments、rules、rule_versions、optimization_jobs、projects、project_snapshots。
- [ ] 欄位邏輯檢查：scope、type、priority、validation_status、job 狀態列舉。
- [ ] 匯入預設種子：30 位護理師、預設班別代碼、職級代碼、科別、技能。

## 2. 後端 API（FastAPI `/api`）
- [ ] 專案與快照：POST /projects、GET /projects/{id}、POST /projects/{id}/snapshots、GET /projects/{id}/snapshots、POST /projects/{id}/restore/{snapshot_id}。
- [ ] 排班 CRUD：GET /schedule/assignments、PUT /schedule/assignments；GET /schedule/conflicts（含規則來源）。
- [ ] 規則與版本：GET /rules、POST /rules、DELETE /rules/{id}、POST /rules/{id}/versions:from_nl（SSE）、POST /rules/{id}/versions:from_dsl、POST /rules/{id}/activate/{version_id}、GET /rules/{id}/versions、GET /dsl/reverse_translate。
- [ ] 最佳化任務：POST /optimization/jobs、GET /optimization/jobs/{id}、GET /optimization/jobs/{id}/stream（SSE progress/log/result）、POST /optimization/jobs/{id}/cancel、POST /optimization/jobs/{id}/apply。
- [ ] 錯誤碼回傳格式統一：`{ok:false,error:{code,message,details}}`；常見碼 RULE_DSL_INVALID、OPT_INFEASIBLE、OPT_TIMEOUT、DB_CONSTRAINT。

## 3. LLM／DSL 流程
- [ ] NL→DSL pipeline：建立 rule_version 草稿、SSE streaming token、DSL validator、反向翻譯、保存 NL/DSL/validator/反譯結果。
- [ ] DSL Validator：Schema/型別檢查、邏輯檢查（max_days>0、權重範圍）、參照完整性（scope/shift），dsl_version 相容性。
- [ ] 覆寫處理：依 GLOBAL→HOSPITAL→DEPARTMENT→NURSE 層級組合；硬規則衝突回報，軟規則轉權重成本。

## 4. 最佳化服務（OR-Tools CP-SAT）
- [ ] 建模決策變數 x[nurse, day, shift]，硬限制：每日單班、coverage、連班上限、夜班休息、不可排日。
- [ ] 軟限制：假日 OFF、夜班平均、班別銜接、個人偏好；權重函式可調 multiplier。
- [ ] 任務執行：queue/worker 記錄 progress 0~100、log、best cost；不可行/timeout 回報主要衝突規則。
- [ ] 結果套用：產生 assignment_set 版本，可預覽/套用到 calendar，允許回滾。

## 5. 前端（SPA，React+TypeScript，淺色模式）
- [ ] 全域樣式：主色 #2563EB、輔色 #10B981、警示 #F59E0B、錯誤 #EF4444、背景 #F9FAFB；字體系統 sans；Toast 支援複製與足夠停駐時間。
- [ ] 行事曆視圖：依 SVG 規格呈現；月/週/日切換；點 cell 開 Drawer 顯示班別/覆蓋/規則/衝突，支援改班別、請假、備註；快篩科別/職級/技能/班別；版本切換（草稿/發布/最佳化）。
- [ ] 規則維護（對話式）：左側 scope/type 篩選；聊天輸入 NL→DSL streaming；顯示 DSL 預覽、validator PASS/WARN/FAIL、反向翻譯；規則 CRUD、覆寫提示；採用版本才生效。
- [ ] 資料維護頁：分頁（護理師/班別代碼/職級代碼/技能），表格 + Modal CRUD；可選 CSV 匯入/匯出；變更寫入 project_snapshots。
- [ ] 最佳化頁：參數設定（期間、時間上限、軟性倍率、目標 checkbox）、開始/取消；SSE streaming 進度條 + best cost log；預覽結果、套用行事曆、下載報表。
- [ ] DSL 測試頁：左 NL 輸入（可選 scope/type）、中間 DSL streaming、右側反向翻譯 + validator；支援樣本保存與 diff 比較。

## 6. QA 與驗收
- [ ] 規則驗收：NL→DSL streaming、validator 回傳、反向翻譯必產出、版本可設為 active 並在衝突檢查生效。
- [ ] 最佳化驗收：任務可建立/串流/取消，成功後可預覽並套用，失敗需列出衝突規則。
- [ ] State 持久化驗收：任何排班/規則/參數修改可由 snapshot 回復；關閉重開後可繼續。

## 7. 文件與交付
- [ ] 更新 README 與開發指南（含 Vite+FastAPI 運行、SSE 注意事項、Zeabur 部署與持久化磁碟設定）。
- [ ] 單元測試覆蓋：API health、Master Data CRUD、DSL validator 最小覆蓋。
- [ ] 執行 project_launcher.py 產出最新 run_app.bat 並檢查 requirements。
- [ ] 打包 ZIP 交付（含 spec/、種子資料、測試指令）。
