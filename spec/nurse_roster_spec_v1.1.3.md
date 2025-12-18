# Vibe Coding 開發規範

請依照以下規格以及遵守開發準則以進行此應用程式的開發。

# 規格整理 v1.1.3

## 0. 技術可行性分析

* **前後端分離 + Zeabur 部署**：可行。建議前端（SPA，不使用Streamlit）+ 後端（FastAPI）分開服務；SQLite 以檔案形式持久化，需注意 Zeabur 的**持久化磁碟**設定（避免容器重啟資料消失）。
* **自然語言→DSL + DSL→自然語言**：可行。以 LLM 做「轉譯器」，並將轉譯結果（DSL）、版本、校驗結果、反向翻譯結果一併保存，支援人工確認。
* **最佳化排班**：可行。建議用 **Google OR-Tools（CP-SAT）**或 ILP 求解；硬限制必須 100% 滿足、軟限制以加權成本函數最小化。
* **Streaming**：所有 LLM 輸出與最佳化進度必須以 **SSE（Server-Sent Events）或 WebSocket** streaming 顯示，避免一次性卡住 UI。

---

## 1. 目標與範圍

### 1.1 目標

* 提供護理排班的「可視化行事曆檢視」
* 以「對話式」維護排班規則：自然語言輸入→LLM 轉 DSL→儲存、版本化、可反向翻譯
* 管理基礎資料：人員、身分/職級、班別代碼等（CRUD）
* 提供最佳化排班：參數可調→執行→產出近似理想解（硬限制優先、軟限制盡量滿足）
* 提供 DSL 測試頁：NL→DSL + DSL→NL（獨立反向翻譯）以利確認正確性

### 1.2 非目標（v1 不做）

* 複雜身份驗證/權限系統（可先以單機/單租戶模式）
* 多院區跨資料庫、多租戶隔離（可預留設計）
* 超大型排班（>300 人、跨多科別超長期間）效能極限優化（先以 30–80 人/科/28 天為主）

---

## 2. 使用者角色與權限（技術版）

> v1 可先用簡化角色（前端以角色切換、後端以 header 模擬），後續再接 OAuth/SSO。

* **Admin/護理長（Manager）**

  * 規則維護（全域/院區/科別）
  * 人員與代碼檔管理
  * 執行最佳化、套用結果、調整後保存
* **一般護理師（Nurse）**

  * 檢視個人班表
  * 維護個人偏好（個人規則層級）
  * 檢視規則解釋/衝突原因（只讀）

---

## 3. 系統架構與模組（前後端分離）

### 3.1 高層架構（SVG）

```svg
<svg width="980" height="420" viewBox="0 0 980 420" xmlns="http://www.w3.org/2000/svg">
  <defs>
    <style>
      .box{fill:#ffffff;stroke:#111827;stroke-width:1.2;rx:14;ry:14}
      .title{font:700 16px ui-sans-serif,system-ui;fill:#111827}
      .text{font:13px ui-sans-serif,system-ui;fill:#111827}
      .muted{font:12px ui-sans-serif,system-ui;fill:#374151}
      .pill{fill:#f3f4f6;stroke:#d1d5db;stroke-width:1;rx:10;ry:10}
      .arrow{stroke:#111827;stroke-width:1.4;marker-end:url(#m)}
    </style>
    <marker id="m" markerWidth="10" markerHeight="10" refX="9" refY="3" orient="auto">
      <path d="M0,0 L9,3 L0,6 Z" fill="#111827"/>
    </marker>
  </defs>

  <rect x="20" y="28" width="300" height="360" class="box"/>
  <text x="40" y="60" class="title">Frontend (SPA)</text>
  <rect x="40" y="80" width="260" height="40" class="pill"/>
  <text x="55" y="105" class="text">Calendar View</text>
  <rect x="40" y="130" width="260" height="40" class="pill"/>
  <text x="55" y="155" class="text">Rules (Chat → DSL)</text>
  <rect x="40" y="180" width="260" height="40" class="pill"/>
  <text x="55" y="205" class="text">Master Data CRUD</text>
  <rect x="40" y="230" width="260" height="40" class="pill"/>
  <text x="55" y="255" class="text">Optimization</text>
  <rect x="40" y="280" width="260" height="40" class="pill"/>
  <text x="55" y="305" class="text">DSL Tester (NL↔DSL)</text>
  <text x="40" y="348" class="muted">SSE/WebSocket for streaming</text>

  <rect x="360" y="28" width="300" height="360" class="box"/>
  <text x="380" y="60" class="title">Backend (Python / FastAPI)</text>
  <rect x="380" y="80" width="260" height="44" class="pill"/>
  <text x="395" y="106" class="text">REST API + SSE endpoints</text>
  <rect x="380" y="132" width="260" height="44" class="pill"/>
  <text x="395" y="158" class="text">Rule Engine + DSL Validator</text>
  <rect x="380" y="184" width="260" height="44" class="pill"/>
  <text x="395" y="210" class="text">LLM Gateway (NL→DSL / DSL→NL)</text>
  <rect x="380" y="236" width="260" height="44" class="pill"/>
  <text x="395" y="262" class="text">Optimization Service (OR-Tools)</text>
  <rect x="380" y="288" width="260" height="44" class="pill"/>
  <text x="395" y="314" class="text">Job Queue (DB-backed)</text>

  <rect x="700" y="28" width="260" height="360" class="box"/>
  <text x="720" y="60" class="title">Storage</text>
  <rect x="720" y="80" width="220" height="54" class="pill"/>
  <text x="735" y="106" class="text">SQLite DB (persistent disk)</text>
  <rect x="720" y="142" width="220" height="54" class="pill"/>
  <text x="735" y="168" class="text">Artifacts</text>
  <text x="735" y="186" class="muted">exports / logs</text>
  <rect x="720" y="206" width="220" height="54" class="pill"/>
  <text x="735" y="232" class="text">Rule Versions</text>
  <text x="735" y="250" class="muted">NL + DSL + validation</text>

  <line x1="320" y1="210" x2="360" y2="210" class="arrow"/>
  <text x="328" y="196" class="muted">HTTPS</text>
  <line x1="660" y1="210" x2="700" y2="210" class="arrow"/>
  <text x="666" y="196" class="muted">SQL / files</text>
</svg>
```

### 3.2 技術棧建議（可替換但需等價能力）

* Frontend：React + TypeScript（Vite）、FullCalendar/自製排班格、State（Zustand/Redux）、SSE client
* Backend：FastAPI + Pydantic + SQLAlchemy（或 SQLModel）+ SQLite
* Optimization：OR-Tools（CP-SAT），或 PuLP/HiGHS（ILP）
* Streaming：SSE（建議）或 WebSocket（進階）
* 部署：Zeabur（Frontend 靜態站 / Backend container）、SQLite 綁定 persistent volume

---

## 4. 資料模型（SQLite Schema 草案）

> 符合「變動一致性」：每個核心物件均需 Create/Update/Delete 與版本/審計欄位。

### 4.1 核心實體

* `users`：使用者（v1 可簡化）
* `nurses`：護理師主檔
* `departments`：科別/病房
* `shift_codes`：班別代碼（D/E/N/OFF…）
* `skill_codes`：技能/證照（ICU、ER…可擴充）
* `schedule_periods`：排班期間（例如 2026-01 月）
* `assignments`：排班結果（某 nurse 某 date 的 shift）
* `rules`：規則（含分層 scope、版本）
* `rule_versions`：規則版本（NL、DSL、反向翻譯、validation）
* `optimization_jobs`：最佳化任務（參數、狀態、log、結果版本）
* `projects`：專案/工作區（State 持久化：打開專案繼續編輯）
* `project_snapshots`：快照（草稿班表、規則集選擇、UI 狀態）

### 4.2 重要欄位設計（節選）

* `rules.scope_type`: `GLOBAL | HOSPITAL | DEPARTMENT | NURSE`
* `rules.scope_id`: 對應 id（GLOBAL 可為 NULL）
* `rules.rule_type`: `HARD | SOFT | PREFERENCE`
* `rules.priority`: 數字越大越優先（解決覆寫）
* `rule_versions.dsl_text`: DSL 原文
* `rule_versions.validation_status`: `PASS | WARN | FAIL`
* `rule_versions.validation_report`: JSON（錯誤位置、建議）
* `optimization_jobs.status`: `QUEUED | RUNNING | SUCCEEDED | FAILED | CANCELED`
* `optimization_jobs.result_assignment_set_id`: 指向某次結果版本（可回滾）

---

## 5. 規則系統（NL→DSL→Rule Engine）

### 5.1 分層式規則套用與覆寫

規則生效順序（由低到高覆寫）：

1. GLOBAL（法規/基本勞動限制）
2. HOSPITAL（院內規範）
3. DEPARTMENT（科別/病房規範）
4. NURSE（個人限制/偏好）

合併策略：

* **硬性規則**：全部必須滿足（若衝突 → 最終判定為「不可行」並回報衝突來源）
* **軟性/偏好**：轉為成本函數（加權），同一維度若多條規則，取最大權重或累加（需明確定義）

### 5.2 DSL 設計（可讀、可驗證、可編譯）

建議採 YAML-like 或 S-expression 皆可；v1 建議 YAML-like，易除錯。

#### DSL 範例（硬性）

```yaml
id: R_GLOBAL_001
type: HARD
scope: GLOBAL
constraint:
  name: max_consecutive_work_days
  params:
    max_days: 6
```

#### DSL 範例（軟性）

```yaml
id: R_DEPT_010
type: SOFT
scope: DEPARTMENT
weight: 30
preference:
  name: avoid_night_shift_after_evening
  params:
    penalty: 1
```

#### DSL 範例（個人偏好）

```yaml
id: R_NURSE_021
type: PREFERENCE
scope: NURSE
scope_id: N021
weight: 50
preference:
  name: prefer_off_on_weekends
  params:
    saturday: true
    sunday: true
```

### 5.3 DSL 驗證器（Validator）

每次 LLM 轉譯後必跑：

* Schema 驗證（必填欄位、型別）
* 邏輯檢查（max_days > 0、weight 範圍等）
* 參照完整性（scope_id 存在、shift_code 存在）
* 版本相容性（`dsl_version`，支援向下相容）

### 5.4 LLM 轉譯流程（Streaming）

* 前端以「對話」輸入自然語言規則
* 後端：

  1. 建立 `rule_versions` 草稿（status=PENDING）
  2. 呼叫 LLM（SSE streaming token）
  3. 收到 DSL 後進行 validator
  4. 產出反向翻譯（獨立 prompt / 可用同模型不同 system 指令）
  5. 保存：NL、DSL、反向翻譯、validation report
* 前端顯示：

  * streaming DSL
  * validation 結果（PASS/WARN/FAIL）
  * 反向翻譯自然語言（供人類確認）
  * 一鍵「採用此版本」→ 成為 rule 的 active_version

---

## 6. 最佳化排班（Optimization）

### 6.1 問題建模（概念）

* 決策變數：`x[nurse, day, shift] ∈ {0,1}`
* 硬限制（例）：

  * 每人每天最多一個班
  * 每天每班別需求人數滿足（coverage）
  * 連續上班天數上限
  * 夜班後休息間隔
  * 護理師不可排不可用日（請假/禁排）
* 軟限制/偏好（例）：

  * 假日盡量 OFF
  * 夜班分配平均
  * 避免 E→N、N→D 等不理想銜接
  * 個人偏好班別（喜歡 D、不喜 N）

目標函數：最小化 `Σ(weight_i * penalty_i)`
硬限制不可違反，若無可行解需回傳「不可行」與最小衝突集合（v1 可先回傳 validator/solver infeasible 訊息 + 主要違規規則列表）。

### 6.2 參數（UI 可調）

* 規劃期間：起訖日期（預設 28 天）
* 班別需求（coverage）：每班別需求數/技能需求
* 軟性權重倍率（全域 multiplier）
* 求解時間上限（seconds）
* 隨機種子（可重現）
* 目標：均衡夜班、均衡假日、偏好優先等（以 checkbox 對應不同 penalty 啟用）

### 6.3 任務執行模式（Job + Streaming）

* `POST /optimization/jobs` 建立任務
* 後端將任務寫入 `optimization_jobs`（QUEUED）
* worker（同服務背景執行即可，v1 不必上外部 queue）：

  * RUNNING → 定期寫入 progress（0~100）與 log
  * SSE：`GET /optimization/jobs/{id}/stream` 推送 progress + 目前最佳解成本
  * SUCCEEDED：保存結果為一個 assignment_set 版本
* 結果套用：

  * 使用者可「預覽」最佳化產生的班表
  * 支援手動微調後保存（形成新版本）
  * 必須支援回滾到任一版本（state 持久化）

---

## 7. 前端 UI 規格（含 SVG 介面示意、淺色模式）

### 7.1 全域 UI 樣式

* Mode：預設淺色
* 主色（Primary）：#2563EB（藍）
* 輔色（Secondary）：#10B981（綠）
* 強調/警示（Warning）：#F59E0B（黃橘）
* 錯誤（Danger）：#EF4444（紅）
* 背景：#F9FAFB、卡片：#FFFFFF、邊框：#E5E7EB
* 字體：系統 sans（Noto Sans TC / system-ui）

---

### 7.2 行事曆視圖（Calendar）

#### 介面示意（SVG）

```svg
<svg width="980" height="520" viewBox="0 0 980 520" xmlns="http://www.w3.org/2000/svg">
  <defs>
    <style>
      .bg{fill:#F9FAFB}
      .card{fill:#FFFFFF;stroke:#E5E7EB;stroke-width:1.2;rx:16;ry:16}
      .h1{font:700 18px ui-sans-serif,system-ui;fill:#111827}
      .t{font:12.5px ui-sans-serif,system-ui;fill:#111827}
      .m{font:12px ui-sans-serif,system-ui;fill:#6B7280}
      .btn{fill:#2563EB;rx:10;ry:10}
      .btn2{fill:#F3F4F6;stroke:#E5E7EB;stroke-width:1;rx:10;ry:10}
      .btnt{font:600 12.5px ui-sans-serif,system-ui;fill:#fff}
      .btnt2{font:600 12.5px ui-sans-serif,system-ui;fill:#111827}
      .grid{stroke:#E5E7EB;stroke-width:1}
      .tagD{fill:#DBEAFE;stroke:#93C5FD;stroke-width:1;rx:10;ry:10}
      .tagE{fill:#D1FAE5;stroke:#6EE7B7;stroke-width:1;rx:10;ry:10}
      .tagN{fill:#EDE9FE;stroke:#C4B5FD;stroke-width:1;rx:10;ry:10}
      .tagO{fill:#FEE2E2;stroke:#FCA5A5;stroke-width:1;rx:10;ry:10}
      .tagTxt{font:700 12px ui-sans-serif,system-ui;fill:#111827}
    </style>
  </defs>

  <rect x="0" y="0" width="980" height="520" class="bg"/>
  <rect x="18" y="18" width="944" height="484" class="card"/>

  <text x="40" y="52" class="h1">行事曆排班總覽</text>

  <!-- Controls -->
  <rect x="40" y="68" width="260" height="34" class="btn2"/>
  <text x="52" y="90" class="m">期間：2026/01/01 - 2026/01/28 ▾</text>

  <rect x="312" y="68" width="150" height="34" class="btn2"/>
  <text x="324" y="90" class="m">科別：ICU ▾</text>

  <rect x="470" y="68" width="160" height="34" class="btn2"/>
  <text x="482" y="90" class="m">檢視：月/週/日 ▾</text>

  <rect x="796" y="66" width="150" height="38" class="btn"/>
  <text x="820" y="90" class="btnt">新增/調整排班</text>

  <!-- Calendar grid header -->
  <line x1="40" y1="118" x2="946" y2="118" class="grid"/>
  <text x="45" y="140" class="m">人員</text>
  <text x="160" y="140" class="m">01</text>
  <text x="210" y="140" class="m">02</text>
  <text x="260" y="140" class="m">03</text>
  <text x="310" y="140" class="m">04</text>
  <text x="360" y="140" class="m">05</text>
  <text x="410" y="140" class="m">06</text>
  <text x="460" y="140" class="m">07</text>

  <!-- Rows -->
  <line x1="40" y1="150" x2="946" y2="150" class="grid"/>
  <line x1="40" y1="210" x2="946" y2="210" class="grid"/>
  <line x1="40" y1="270" x2="946" y2="270" class="grid"/>
  <line x1="40" y1="330" x2="946" y2="330" class="grid"/>
  <line x1="40" y1="390" x2="946" y2="390" class="grid"/>

  <text x="45" y="185" class="t">N001 王小梅</text>
  <text x="45" y="245" class="t">N002 陳怡安</text>
  <text x="45" y="305" class="t">N003 林雅婷</text>
  <text x="45" y="365" class="t">N004 張惠雯</text>

  <!-- Shift tags row 1 -->
  <rect x="145" y="165" width="40" height="28" class="tagD"/><text x="158" y="184" class="tagTxt">D</text>
  <rect x="195" y="165" width="40" height="28" class="tagE"/><text x="208" y="184" class="tagTxt">E</text>
  <rect x="245" y="165" width="40" height="28" class="tagN"/><text x="258" y="184" class="tagTxt">N</text>
  <rect x="295" y="165" width="40" height="28" class="tagO"/><text x="303" y="184" class="tagTxt">OFF</text>

  <!-- Row 2 -->
  <rect x="145" y="225" width="40" height="28" class="tagE"/><text x="158" y="244" class="tagTxt">E</text>
  <rect x="195" y="225" width="40" height="28" class="tagE"/><text x="208" y="244" class="tagTxt">E</text>
  <rect x="245" y="225" width="40" height="28" class="tagD"/><text x="258" y="244" class="tagTxt">D</text>
  <rect x="295" y="225" width="40" height="28" class="tagD"/><text x="308" y="244" class="tagTxt">D</text>

  <!-- Right legend -->
  <rect x="680" y="156" width="266" height="220" class="btn2"/>
  <text x="696" y="182" class="t">圖例 / 快篩</text>
  <rect x="696" y="196" width="50" height="26" class="tagD"/><text x="716" y="214" class="tagTxt">D</text><text x="754" y="214" class="m">日班</text>
  <rect x="696" y="228" width="50" height="26" class="tagE"/><text x="716" y="246" class="tagTxt">E</text><text x="754" y="246" class="m">小夜</text>
  <rect x="696" y="260" width="50" height="26" class="tagN"/><text x="716" y="278" class="tagTxt">N</text><text x="754" y="278" class="m">大夜</text>
  <rect x="696" y="292" width="50" height="26" class="tagO"/><text x="707" y="310" class="tagTxt">OFF</text><text x="754" y="310" class="m">休假</text>

  <text x="696" y="344" class="m">點擊格子可編輯 / 查看規則解釋</text>
</svg>
```

#### 互動規格

* 點擊 cell：開啟右側抽屜（Drawer）

  * 顯示：該人員該日班別、覆蓋需求、觸發規則、衝突原因（若有）
  * 動作：改班別、標記請假、加註備註
* 快篩：科別、職級、技能、班別、顯示「衝突」標記
* 版本：可切換「草稿 / 已發布 / 最佳化結果版本」
* 保存：任何修改都要寫入 `project_snapshots`（可關閉後回來繼續）

---

### 7.3 規則維護（對話式 + 分層）

#### 介面示意（SVG）

```svg
<svg width="980" height="520" viewBox="0 0 980 520" xmlns="http://www.w3.org/2000/svg">
  <defs>
    <style>
      .bg{fill:#F9FAFB}
      .card{fill:#FFFFFF;stroke:#E5E7EB;stroke-width:1.2;rx:16;ry:16}
      .h1{font:700 18px ui-sans-serif,system-ui;fill:#111827}
      .t{font:12.5px ui-sans-serif,system-ui;fill:#111827}
      .m{font:12px ui-sans-serif,system-ui;fill:#6B7280}
      .btn{fill:#2563EB;rx:10;ry:10}
      .btn2{fill:#F3F4F6;stroke:#E5E7EB;stroke-width:1;rx:10;ry:10}
      .btnt{font:600 12.5px ui-sans-serif,system-ui;fill:#fff}
      .bubbleA{fill:#EFF6FF;stroke:#BFDBFE;stroke-width:1;rx:14;ry:14}
      .bubbleU{fill:#ECFDF5;stroke:#A7F3D0;stroke-width:1;rx:14;ry:14}
      .code{fill:#111827;rx:12;ry:12}
      .codeT{font:12px ui-monospace,SFMono-Regular;fill:#E5E7EB}
      .warn{fill:#FEF3C7;stroke:#F59E0B;stroke-width:1;rx:12;ry:12}
      .ok{fill:#D1FAE5;stroke:#10B981;stroke-width:1;rx:12;ry:12}
    </style>
  </defs>

  <rect width="980" height="520" class="bg"/>
  <rect x="18" y="18" width="944" height="484" class="card"/>
  <text x="40" y="52" class="h1">規則維護（對話 → DSL）</text>

  <!-- left scope panel -->
  <rect x="40" y="72" width="240" height="410" class="btn2"/>
  <text x="56" y="98" class="t">規則層級</text>
  <rect x="56" y="112" width="208" height="34" class="btn2"/><text x="68" y="134" class="m">GLOBAL（法規）</text>
  <rect x="56" y="152" width="208" height="34" class="btn2"/><text x="68" y="174" class="m">HOSPITAL（院內）</text>
  <rect x="56" y="192" width="208" height="34" class="btn2"/><text x="68" y="214" class="m">DEPARTMENT（ICU）</text>
  <rect x="56" y="232" width="208" height="34" class="btn2"/><text x="68" y="254" class="m">NURSE（個人）</text>

  <text x="56" y="292" class="t">類型</text>
  <rect x="56" y="306" width="208" height="30" class="btn2"/><text x="68" y="326" class="m">HARD / SOFT / PREFERENCE</text>
  <text x="56" y="360" class="t">搜尋</text>
  <rect x="56" y="374" width="208" height="30" class="btn2"/><text x="68" y="394" class="m">輸入關鍵字…</text>

  <!-- chat area -->
  <rect x="300" y="72" width="410" height="300" class="btn2"/>
  <text x="316" y="98" class="t">對話輸入（自然語言）</text>

  <rect x="320" y="116" width="360" height="58" class="bubbleU"/>
  <text x="336" y="140" class="t">「夜班後至少休息 1 天，避免連續大夜超過 2 天」</text>

  <rect x="320" y="184" width="360" height="78" class="bubbleA"/>
  <text x="336" y="208" class="t">LLM：正在轉換為 DSL（streaming…）</text>
  <text x="336" y="232" class="m">同時會產生反向翻譯供確認</text>

  <rect x="300" y="382" width="410" height="48" class="btn2"/>
  <text x="316" y="412" class="m">輸入規則文字…  (Enter 送出 / Shift+Enter 換行)</text>
  <rect x="622" y="392" width="78" height="32" class="btn"/>
  <text x="644" y="413" class="btnt">送出</text>

  <!-- right panel DSL + validation -->
  <rect x="730" y="72" width="216" height="410" class="btn2"/>
  <text x="746" y="98" class="t">DSL 預覽</text>
  <rect x="746" y="112" width="184" height="170" class="code"/>
  <text x="754" y="136" class="codeT">type: HARD</text>
  <text x="754" y="156" class="codeT">constraint:</text>
  <text x="754" y="176" class="codeT">  name: rest_after_night</text>
  <text x="754" y="196" class="codeT">  params: { days: 1 }</text>
  <text x="754" y="216" class="codeT">constraint:</text>
  <text x="754" y="236" class="codeT">  name: max_consecutive_night</text>
  <text x="754" y="256" class="codeT">  params: { max: 2 }</text>

  <text x="746" y="304" class="t">驗證</text>
  <rect x="746" y="314" width="184" height="54" class="ok"/>
  <text x="758" y="346" class="t">PASS：可採用</text>

  <text x="746" y="392" class="t">反向翻譯</text>
  <rect x="746" y="402" width="184" height="64" class="warn"/>
  <text x="758" y="426" class="m">「大夜後必須休 1 天」</text>
  <text x="758" y="448" class="m">「連續大夜不超過 2 天」</text>
</svg>
```

#### 功能規格

* 規則 CRUD：

  * 建立：對話輸入 → 產生 rule + rule_version（草稿）
  * 更新：可用「自然語言描述修改」或「直接編輯 DSL」（需再次 validator）
  * 刪除：soft delete（保留歷史版本）
* 分類與篩選：

  * scope、type、啟用狀態、關鍵字
* 覆寫視覺提示：

  * 同一 constraint name 在更高層級存在時，提示「覆寫 GLOBAL/HOSPITAL…」
* 規則啟用策略：

  * rule 有 `active_version_id`
  * 一鍵「採用版本」才會生效（避免 LLM 產出錯誤直接影響求解）

---

### 7.4 資料維護（人員/代碼檔）

#### 介面示意（SVG）

```svg
<svg width="980" height="520" viewBox="0 0 980 520" xmlns="http://www.w3.org/2000/svg">
  <defs>
    <style>
      .bg{fill:#F9FAFB}
      .card{fill:#FFFFFF;stroke:#E5E7EB;stroke-width:1.2;rx:16;ry:16}
      .h1{font:700 18px ui-sans-serif,system-ui;fill:#111827}
      .t{font:12.5px ui-sans-serif,system-ui;fill:#111827}
      .m{font:12px ui-sans-serif,system-ui;fill:#6B7280}
      .btn{fill:#2563EB;rx:10;ry:10}
      .btn2{fill:#F3F4F6;stroke:#E5E7EB;stroke-width:1;rx:10;ry:10}
      .btnt{font:600 12.5px ui-sans-serif,system-ui;fill:#fff}
      .grid{stroke:#E5E7EB;stroke-width:1}
    </style>
  </defs>

  <rect width="980" height="520" class="bg"/>
  <rect x="18" y="18" width="944" height="484" class="card"/>
  <text x="40" y="52" class="h1">資料維護（人員 / 代碼檔）</text>

  <!-- tabs -->
  <rect x="40" y="70" width="140" height="34" class="btn2"/><text x="60" y="92" class="t">護理師</text>
  <rect x="186" y="70" width="140" height="34" class="btn2"/><text x="206" y="92" class="t">班別代碼</text>
  <rect x="332" y="70" width="140" height="34" class="btn2"/><text x="352" y="92" class="t">職級代碼</text>

  <!-- actions -->
  <rect x="780" y="66" width="166" height="40" class="btn"/><text x="820" y="92" class="btnt">新增資料</text>

  <!-- table -->
  <rect x="40" y="120" width="906" height="340" class="btn2"/>
  <line x1="40" y1="154" x2="946" y2="154" class="grid"/>
  <text x="56" y="144" class="m">員編</text>
  <text x="160" y="144" class="m">姓名</text>
  <text x="310" y="144" class="m">科別</text>
  <text x="430" y="144" class="m">職級</text>
  <text x="540" y="144" class="m">技能</text>
  <text x="700" y="144" class="m">狀態</text>
  <text x="820" y="144" class="m">操作</text>

  <!-- rows -->
  <text x="56" y="184" class="t">N001</text><text x="160" y="184" class="t">王小梅</text><text x="310" y="184" class="t">ICU</text><text x="430" y="184" class="t">N2</text><text x="540" y="184" class="t">ICU</text><text x="700" y="184" class="t">在職</text><text x="820" y="184" class="t">編輯 / 刪除</text>
  <text x="56" y="224" class="t">N002</text><text x="160" y="224" class="t">陳怡安</text><text x="310" y="224" class="t">ICU</text><text x="430" y="224" class="t">N1</text><text x="540" y="224" class="t">-</text><text x="700" y="224" class="t">在職</text><text x="820" y="224" class="t">編輯 / 刪除</text>

  <text x="40" y="486" class="m">支援 CSV 匯入/匯出（v1 可選配），所有變更寫入專案快照</text>
</svg>
```

#### 預設值（v1 建議）

* 班別代碼 `shift_codes`

  * `D` 日班（08:00–16:00）
  * `E` 小夜（16:00–00:00）
  * `N` 大夜（00:00–08:00）
  * `OFF` 休假
* 職級代碼 `job_levels`

  * `N1`、`N2`、`N3`、`N4`（可擴充）
* 科別 `departments`

  * `ICU`、`ER`、`WARD-A`（示例）
* 技能 `skill_codes`

  * `ICU`、`ER`、`VENT`（呼吸器）等（示例）

---

### 7.5 最佳化排班頁

#### 介面示意（SVG）

```svg
<svg width="980" height="520" viewBox="0 0 980 520" xmlns="http://www.w3.org/2000/svg">
  <defs>
    <style>
      .bg{fill:#F9FAFB}
      .card{fill:#FFFFFF;stroke:#E5E7EB;stroke-width:1.2;rx:16;ry:16}
      .h1{font:700 18px ui-sans-serif,system-ui;fill:#111827}
      .t{font:12.5px ui-sans-serif,system-ui;fill:#111827}
      .m{font:12px ui-sans-serif,system-ui;fill:#6B7280}
      .btn{fill:#2563EB;rx:10;ry:10}
      .btn2{fill:#F3F4F6;stroke:#E5E7EB;stroke-width:1;rx:10;ry:10}
      .danger{fill:#EF4444;rx:10;ry:10}
      .btnt{font:600 12.5px ui-sans-serif,system-ui;fill:#fff}
      .bar{fill:#E5E7EB;rx:10;ry:10}
      .barFill{fill:#10B981;rx:10;ry:10}
    </style>
  </defs>

  <rect width="980" height="520" class="bg"/>
  <rect x="18" y="18" width="944" height="484" class="card"/>
  <text x="40" y="52" class="h1">最佳化排班</text>

  <!-- left params -->
  <rect x="40" y="70" width="380" height="410" class="btn2"/>
  <text x="56" y="98" class="t">參數設定</text>

  <text x="56" y="130" class="m">期間</text>
  <rect x="120" y="112" width="284" height="34" class="btn2"/><text x="132" y="134" class="m">2026/01/01 - 2026/01/28</text>

  <text x="56" y="172" class="m">求解時間上限（秒）</text>
  <rect x="200" y="154" width="204" height="34" class="btn2"/><text x="212" y="176" class="m">30</text>

  <text x="56" y="214" class="m">軟性權重倍率</text>
  <rect x="200" y="196" width="204" height="34" class="btn2"/><text x="212" y="218" class="m">1.0</text>

  <text x="56" y="256" class="m">目標</text>
  <rect x="120" y="238" width="284" height="90" class="btn2"/>
  <text x="132" y="262" class="m">☑ 夜班平均</text>
  <text x="132" y="286" class="m">☑ 假日公平</text>
  <text x="132" y="310" class="m">☑ 個人偏好優先</text>

  <rect x="56" y="350" width="166" height="40" class="btn"/><text x="88" y="376" class="btnt">開始最佳化</text>
  <rect x="238" y="350" width="166" height="40" class="danger"/><text x="290" y="376" class="btnt">取消</text>

  <!-- right status -->
  <rect x="440" y="70" width="506" height="410" class="btn2"/>
  <text x="456" y="98" class="t">執行狀態（Streaming）</text>

  <text x="456" y="130" class="m">Job ID: OPT-202601-0007   Status: RUNNING</text>
  <rect x="456" y="148" width="474" height="18" class="bar"/>
  <rect x="456" y="148" width="280" height="18" class="barFill"/>
  <text x="456" y="190" class="m">目前最佳成本：1240（迭代 812）</text>

  <rect x="456" y="208" width="474" height="180" class="btn2"/>
  <text x="470" y="234" class="m">log:</text>
  <text x="470" y="258" class="m">- coverage constraints OK</text>
  <text x="470" y="282" class="m">- improving night balance…</text>
  <text x="470" y="306" class="m">- best solution updated (cost=1240)</text>

  <rect x="456" y="404" width="160" height="40" class="btn2"/>
  <text x="478" y="430" class="t">預覽結果</text>
  <rect x="626" y="404" width="160" height="40" class="btn"/>
  <text x="662" y="430" class="btnt">套用到行事曆</text>
  <rect x="796" y="404" width="134" height="40" class="btn2"/>
  <text x="826" y="430" class="t">下載報表</text>
</svg>
```

---

### 7.6 DSL 測試頁（NL→DSL + DSL→NL）

#### 功能規格

* 左側：自然語言輸入（可選 scope/type）
* 中間：LLM streaming 產出 DSL
* 右側：獨立反向翻譯（DSL→自然語言）+ validator 結果
* 支援測試樣本保存、對比多次輸出差異（diff）

---

## 8. API 設計（FastAPI）

> 以下以 `/api` 為前綴；回應格式統一：`{ "ok": true, "data": ... }`，錯誤：`{ "ok": false, "error": { "code": "...", "message": "...", "details": ... } }`

### 8.1 專案 / 狀態持久化

* `POST /projects`：建立專案
* `GET /projects/{id}`：取得專案與目前 active snapshot
* `POST /projects/{id}/snapshots`：建立快照（保存草稿班表/規則選擇/UI 狀態）
* `GET /projects/{id}/snapshots`：列出歷史快照
* `POST /projects/{id}/restore/{snapshot_id}`：回復快照

### 8.2 行事曆 / 排班

* `GET /schedule/assignments?project_id=&from=&to=&department_id=`
* `PUT /schedule/assignments`：批次更新（支援手動調整）

  * body: `{ project_id, changes: [{ nurse_id, date, shift_code, note? }] }`
* `GET /schedule/conflicts?project_id=&from=&to=`：回傳衝突列表（對應規則與原因）

### 8.3 規則（Rule + Versions）

* `GET /rules?scope_type=&scope_id=&type=&q=`
* `POST /rules`：建立 rule（metadata）
* `DELETE /rules/{id}`
* `POST /rules/{id}/versions:from_nl`：自然語言→DSL（SSE streaming 可選）
* `POST /rules/{id}/versions:from_dsl`：直接貼 DSL → validator
* `POST /rules/{id}/activate/{version_id}`：採用某版本
* `GET /rules/{id}/versions`
* `GET /dsl/reverse_translate`：DSL→自然語言（獨立測試用）

### 8.4 資料維護（Master Data）

* `GET/POST/PUT/DELETE /nurses`
* `GET/POST/PUT/DELETE /departments`
* `GET/POST/PUT/DELETE /shift_codes`
* `GET/POST/PUT/DELETE /job_levels`
* `GET/POST/PUT/DELETE /skill_codes`

### 8.5 最佳化

* `POST /optimization/jobs`

  * body: `{ project_id, period: {from,to}, solver: {time_limit_sec, seed}, weights: {...}, coverage: {...} }`
* `GET /optimization/jobs/{id}`
* `GET /optimization/jobs/{id}/stream`（SSE）
* `POST /optimization/jobs/{id}/cancel`
* `POST /optimization/jobs/{id}/apply`：將結果寫入 project 的新 snapshot/version

### 8.6 Streaming 格式（SSE）

* event: `token`（LLM）
* event: `progress`（0..100）
* event: `log`
* event: `result`（完成）
* event: `error`

---

## 9. 預設測試資料（約 30 位護理師）

> v1 先提供 JSON seed（可由後端 `/seed` 或 migration 初始化）。以下給一組「合理分布」：3 科別、職級混合、部分具 ICU/ER 技能。

### 9.1 Nurses（30）

* ICU：12 人（含資深 N3/N4）
* ER：10 人
* WARD-A：8 人

（示例資料，欄位：`id, name, department, job_level, skills[]`）

```json
[
  {"id":"N001","name":"王小梅","department":"ICU","job_level":"N3","skills":["ICU","VENT"]},
  {"id":"N002","name":"陳怡安","department":"ICU","job_level":"N2","skills":["ICU"]},
  {"id":"N003","name":"林雅婷","department":"ICU","job_level":"N1","skills":[]},
  {"id":"N004","name":"張惠雯","department":"ICU","job_level":"N2","skills":["VENT"]},
  {"id":"N005","name":"蔡佩珊","department":"ICU","job_level":"N4","skills":["ICU","VENT"]},
  {"id":"N006","name":"李佳蓉","department":"ICU","job_level":"N2","skills":["ICU"]},
  {"id":"N007","name":"黃詩涵","department":"ICU","job_level":"N1","skills":[]},
  {"id":"N008","name":"許雅雯","department":"ICU","job_level":"N3","skills":["ICU"]},
  {"id":"N009","name":"周欣怡","department":"ICU","job_level":"N2","skills":[]},
  {"id":"N010","name":"鄭安琪","department":"ICU","job_level":"N1","skills":[]},
  {"id":"N011","name":"何婉婷","department":"ICU","job_level":"N2","skills":["VENT"]},
  {"id":"N012","name":"郭品妤","department":"ICU","job_level":"N3","skills":["ICU"]},

  {"id":"N013","name":"楊子晴","department":"ER","job_level":"N2","skills":["ER"]},
  {"id":"N014","name":"吳思妤","department":"ER","job_level":"N1","skills":["ER"]},
  {"id":"N015","name":"謝佳穎","department":"ER","job_level":"N3","skills":["ER"]},
  {"id":"N016","name":"沈佩儀","department":"ER","job_level":"N2","skills":[]},
  {"id":"N017","name":"趙怡君","department":"ER","job_level":"N1","skills":[]},
  {"id":"N018","name":"鍾雨潔","department":"ER","job_level":"N2","skills":["ER"]},
  {"id":"N019","name":"施婉如","department":"ER","job_level":"N4","skills":["ER"]},
  {"id":"N020","name":"曾怡蓁","department":"ER","job_level":"N2","skills":[]},
  {"id":"N021","name":"彭心妤","department":"ER","job_level":"N1","skills":[]},
  {"id":"N022","name":"方宜庭","department":"ER","job_level":"N3","skills":["ER"]},

  {"id":"N023","name":"葉采薇","department":"WARD-A","job_level":"N2","skills":[]},
  {"id":"N024","name":"高郁婷","department":"WARD-A","job_level":"N1","skills":[]},
  {"id":"N025","name":"邱筱晴","department":"WARD-A","job_level":"N2","skills":[]},
  {"id":"N026","name":"宋依珊","department":"WARD-A","job_level":"N3","skills":[]},
  {"id":"N027","name":"盧語嫻","department":"WARD-A","job_level":"N1","skills":[]},
  {"id":"N028","name":"梁思瑤","department":"WARD-A","job_level":"N2","skills":[]},
  {"id":"N029","name":"姚欣蓉","department":"WARD-A","job_level":"N4","skills":[]},
  {"id":"N030","name":"簡語彤","department":"WARD-A","job_level":"N2","skills":[]}
]
```

---

## 10. 錯誤處理與可觀測性

### 10.1 錯誤碼（例）

* `RULE_DSL_INVALID`：DSL schema/validator 失敗
* `RULE_CONFLICT_HARD`：硬性規則互斥導致不可行
* `OPT_INFEASIBLE`：求解器不可行
* `OPT_TIMEOUT`：時間到未找到可行/更佳解（仍可回傳 best-so-far）
* `DB_CONSTRAINT`：資料完整性問題

### 10.2 Log / Audit

* 規則版本變更、啟用版本、排班手動修改、最佳化套用，都要寫入 `audit_log`（v1 可簡化成表格 + JSON）

---

## 11. QA 驗收條件（技術導向）

### 11.1 規則（NL→DSL→反向翻譯）

* 輸入一條規則，必須：

  * streaming 顯示 DSL
  * validator 回 PASS/WARN/FAIL
  * 反向翻譯自然語言必定產出
  * 可將某版本設為 active，並在「衝突檢查」中生效

### 11.2 最佳化

* 在有 coverage + 硬限制情境：

  * 任務可建立、可串流進度、可取消
  * 成功後可預覽並套用到行事曆形成新版本
  * 若不可行，必須回報主要衝突規則（至少列出涉及的 rule ids）

### 11.3 State 持久化（專案）

* 任何排班/規則/參數修改後，關閉再開可從專案繼續（snapshot 可回復）

---

## 12. 版本切分建議（避免一次做太大）

* **v1**：Calendar（檢視+手動改）、Master Data、Rule Chat（NL→DSL+validator+reverse）、Optimization（基本 coverage + 幾條硬限制 + 軟性權重）
* **v1.1**：衝突解釋更完整（why/which rule）、規則覆寫視覺化、版本 diff
* **v1.2**：技能需求、職級需求、請假流程、匯入匯出

