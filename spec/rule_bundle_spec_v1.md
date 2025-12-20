# Rule Bundle 規格備份（排班期規則集）

此文件為「每期排班規則集」技術規格備份，包含資料模型、流程、API、UI、版本與邊界條件，作為可重現、可審計、可回滾的排班規則基礎。

## 1. 核心設計：Rule Bundle Snapshot（本期規則集）

Rule Bundle 由四層組成，並在建立排班期時固定為快照：

1. **法規硬規則（LAW / GLOBAL HARD）**
2. **醫院方硬規則（HOSPITAL HARD）**
3. **公版規則（TEMPLATE：HARD/SOFT/PREFERENCE，排除個人偏好）**
4. **上一期個人偏好（NURSE_PREF）**

本期排班永遠使用該 Bundle（而非即時規則庫），確保結果可重現。

## 2. 資料模型（SQLite）

### 2.1 新增/調整

- `schedule_periods`：新增 `active_rule_bundle_id`
- `rule_bundles`：綁定 period，儲存 bundle hash、來源設定、驗證報告
- `rule_bundle_items`：每條規則快照（含 rule_version、dsl_hash、priority/enable 固化）
- `templates` / `template_rule_links`：公版規則集管理與覆寫

## 3. 規則載入流程（Wizard）

Wizard 固定 6 步驟：

1. 選排班期與科別
2. 載入 LAW 硬規則
3. 載入 HOSPITAL 硬規則
4. 選擇/編輯 TEMPLATE
5. 載入上一期 NURSE_PREF
6. 預覽與驗證 → 生成 Bundle

## 4. 載入策略重點

- **LAW**：GLOBAL + HARD + enabled
- **HOSPITAL**：HOSPITAL + HARD + enabled
- **TEMPLATE**：非 NURSE scope，允許 HARD/SOFT/PREFERENCE
- **NURSE_PREF**：支援 `CLONE_AS_IS` / `CLONE_LATEST_VERSION`

## 4.1 醫院層級硬規則集（HOSPITAL HARD）

本節整理「醫院層級硬規則集（HOSPITAL HARD）」的可直接匯入版本，確保能在目前的後端規則驗證與求解器路徑中生效。

前提對齊：

1. Rule Bundle 的層級定義中，第二層就是 **醫院方硬規則（HOSPITAL HARD）**；生成 bundle 時，系統也會依 `scope_type=HOSPITAL`、`type=HARD`、且符合 `hospital_id` 的規則清單納入。
2. DSL 規格的 root 結構（scope/type/priority/enabled/constraints）需符合既有規格。
3. 目前後端 validator 支援的 constraint name 集合已列在 `rules.py`（含新名與 legacy 名）；但「實際會影響 CP-SAT 求解」的，需以 `optimization.py` 目前解析到的項目為準（例如：`weekend_all_or_nothing`、`min_consecutive_off_days`、`max_work_days_in_rolling_window`、`min_full_weekends_off_in_window`、`if_novice_present_then_senior_present`、以及 legacy 的 `rest_after_night`、`max_consecutive`、`daily_coverage` 等）。

重要提醒（避免你匯入後「看起來驗證通過但求解沒吃到」）：

- 目前 `optimization.py` **沒有**直接處理新 DSL 名稱 `forbid_transition / rest_after_shift / coverage_required / max_consecutive_shift / max_assignments_in_window`；因此若你用這些「新名字」寫 HOSPITAL HARD，validator 會過，但求解器可能不會套用。相對地，`rest_after_night`（legacy）與 `weekend_all_or_nothing` 等是確定會生效的。

基於以上，以下提供一套可直接用於現行求解器的 HOSPITAL HARD 規則集（採用求解器已解析的 constraint name），並附可直接匯入的 DSL YAML。

---

### 一、醫院層級硬規則集清單（建議最小可用版）

以下規則皆設定：

- `scope.type: HOSPITAL`
- `scope.id: "<HOSPITAL_ID>"`（建議用數字字串，例如 `"1"`，因為後端 scope_id 會轉字串處理）
- `type: HARD`
- `enabled: true`
- `priority`: 給一個一致的高值（例如 8000~8999），以便未來覆寫/追蹤

#### A. 排班疲勞與連續性（Hard）

1. 夜班後隔日必 OFF（legacy：`rest_after_night`，hard 會觸發求解器的 `rest_after_night_hard`）
2. 最大連續夜班天數（legacy：`max_consecutive`，shift=N）
3. 最小連休天數（`min_consecutive_off_days`）
4. 7 日窗口內最多工作天數（`max_work_days_in_rolling_window`，window_days=7）
5. 14 日窗口內最多工作天數（同上，window_days=14）

#### B. 週末政策（Hard）

6. 週末「要休就兩天都休、要上就兩天都上」：`weekend_all_or_nothing`
7. 28 日窗口內最少完整週末休假次數：`min_full_weekends_off_in_window`（若你們院內確實把它當硬規）

#### C. 資深/新手搭配（Hard，若院內政策）

8. 新手在場需至少 1 名資深同班：`if_novice_present_then_senior_present`

---

### 二、可直接匯入的 DSL（HOSPITAL HARD 規則集）

下面每一段都是「一條規則版本」的 DSL（符合 DSL root 結構規格）。
請把 `<HOSPITAL_ID>` 替換成你的院區 id（例如 `1`）。

#### HOSPITAL HARD 001：夜班後隔日必 OFF（硬）

```yaml
dsl_version: "1.0"
id: "R_HOSPITAL_001"
name: "夜班後隔日必休（硬性）"
scope:
  type: HOSPITAL
  id: "<HOSPITAL_ID>"
type: HARD
priority: 8901
enabled: true
tags: ["hospital_hard", "fatigue", "night"]
notes: "院內硬規：夜班後隔天必須安排 OFF。"
constraints:
  - id: "C1"
    name: rest_after_night
    params: {}
    message: "夜班後隔日必須為 OFF"
```

#### HOSPITAL HARD 010：最大連續夜班 ≤ 2（硬）

（使用 legacy `max_consecutive`，確定會進入求解器的 max_consecutive dict）

```yaml
dsl_version: "1.0"
id: "R_HOSPITAL_010"
name: "最大連續夜班天數（硬性）"
scope:
  type: HOSPITAL
  id: "<HOSPITAL_ID>"
type: HARD
priority: 8890
enabled: true
tags: ["hospital_hard", "night", "consecutive"]
notes: "院內硬規：夜班不可連續超過 2 天。"
constraints:
  - id: "C1"
    name: max_consecutive
    params:
      shift: "N"
      max_days: 2
    message: "夜班連續不得超過 2 天"
```

#### HOSPITAL HARD 020：最小連休 ≥ 2 天（硬）

（此規則在求解器會直接加約束，確定生效）

```yaml
dsl_version: "1.0"
id: "R_HOSPITAL_020"
name: "最低連休天數（硬性）"
scope:
  type: HOSPITAL
  id: "<HOSPITAL_ID>"
type: HARD
priority: 8880
enabled: true
tags: ["hospital_hard", "off", "consecutive"]
notes: "院內硬規：休假一旦開始，至少連休 2 天（可允許期初期末例外）。"
constraints:
  - id: "C1"
    name: min_consecutive_off_days
    params:
      min_days: 2
      allow_at_period_edges: true
      off_code: "OFF"
    message: "連休至少 2 天"
```

#### HOSPITAL HARD 030：7 日窗口最多工作 6 天（硬）

（以 `max_work_days_in_rolling_window` 實作，求解器確定會套用）

```yaml
dsl_version: "1.0"
id: "R_HOSPITAL_030"
name: "7 日窗口最多工作天數（硬性）"
scope:
  type: HOSPITAL
  id: "<HOSPITAL_ID>"
type: HARD
priority: 8870
enabled: true
tags: ["hospital_hard", "window", "workdays"]
notes: "院內硬規：任意連續 7 天最多工作 6 天（至少 1 天 OFF）。"
constraints:
  - id: "C1"
    name: max_work_days_in_rolling_window
    params:
      window_days: 7
      max_work_days: 6
      include_shifts: []   # 空=自動視為 OFF 以外皆算工作
      sliding: true
    message: "任意 7 天內最多工作 6 天"
```

#### HOSPITAL HARD 031：14 日窗口最多工作 11 天（硬）

```yaml
dsl_version: "1.0"
id: "R_HOSPITAL_031"
name: "14 日窗口最多工作天數（硬性）"
scope:
  type: HOSPITAL
  id: "<HOSPITAL_ID>"
type: HARD
priority: 8865
enabled: true
tags: ["hospital_hard", "window", "workdays"]
notes: "院內硬規：任意連續 14 天最多工作 11 天（避免長期超載）。"
constraints:
  - id: "C1"
    name: max_work_days_in_rolling_window
    params:
      window_days: 14
      max_work_days: 11
      include_shifts: []
      sliding: true
    message: "任意 14 天內最多工作 11 天"
```

#### HOSPITAL HARD 040：週末全休或全上（硬）

（求解器會對每個 Sat/Sun pair 套上 `OFF` 相等約束）

```yaml
dsl_version: "1.0"
id: "R_HOSPITAL_040"
name: "週末全休或全上（硬性）"
scope:
  type: HOSPITAL
  id: "<HOSPITAL_ID>"
type: HARD
priority: 8850
enabled: true
tags: ["hospital_hard", "weekend"]
notes: "院內硬規：週末休假必須兩天連休；若上班則兩天都可排班。"
constraints:
  - id: "C1"
    name: weekend_all_or_nothing
    params:
      weekend_def: "SAT_SUN"
      off_code: "OFF"
    message: "週末必須全休或全上（OFF 需成對）"
```

#### HOSPITAL HARD 041：28 日窗口至少 2 個完整週末 OFF（硬）

（若你們院內確實把它當硬規；否則建議放 TEMPLATE/SOFT）

```yaml
dsl_version: "1.0"
id: "R_HOSPITAL_041"
name: "28 日窗口最少完整週末休假次數（硬性）"
scope:
  type: HOSPITAL
  id: "<HOSPITAL_ID>"
type: HARD
priority: 8840
enabled: true
tags: ["hospital_hard", "weekend", "window"]
notes: "院內硬規：每 28 天至少 2 次『完整週末（六日）』OFF。"
constraints:
  - id: "C1"
    name: min_full_weekends_off_in_window
    params:
      window_days: 28
      min_full_weekends_off: 2
      weekend_def: "SAT_SUN"
      off_code: "OFF"
      sliding: true
    message: "每 28 天至少 2 次完整週末休"
```

#### HOSPITAL HARD 050：新手在場需資深在場（硬）

（求解器確定支援，會針對每一天每班別加上觸發式約束）

```yaml
dsl_version: "1.0"
id: "R_HOSPITAL_050"
name: "新手在場需資深在場（硬性）"
scope:
  type: HOSPITAL
  id: "<HOSPITAL_ID>"
type: HARD
priority: 8830
enabled: true
tags: ["hospital_hard", "staffing", "seniority"]
notes: "院內硬規：當同班別出現新手（例如 N1/N2）時，至少要有 1 名資深（例如 N3/N4）同班。"
constraints:
  - id: "C1"
    name: if_novice_present_then_senior_present
    params:
      shifts: ["D", "E", "N"]
      department_id: ""  # 空字串=不限定科別；若要限定可填 ICU / ER 等 dept code
      novice_group:
        by_job_levels: ["N1", "N2"]
      senior_group:
        by_job_levels: ["N3", "N4"]
      trigger_if_novice_count_ge: 1
      min_senior: 1
    message: "新手在場需至少 1 名資深同班"
```

---

### 三、匯入時的操作要點（避免踩雷）

1. 請以 `scope_type=HOSPITAL`、`scope_id=<HOSPITAL_ID>`、`rule_type=HARD` 建立 `rules`，並把上述 YAML 存成該 rule 的最新 `rule_versions.dsl_text`。因為 Bundle 生成時是依這個條件過濾納入。
2. 這一組在 Rule Bundle Wizard（Step 3）會被預設全選載入（前端文案已寫明「HOSPITAL + HARD + 啟用規則，預設全選」）。
3. 若你之後想把「週末至少休幾次」改成軟性，不要改這個規則；請改放在 TEMPLATE/SOFT，因為 `min_full_weekends_off_in_window` 做 hard 在人力緊張時很容易導致 infeasible（這是實務上常見）。

## 5. API（v1）

### Rule Bundle

- `POST /api/rule-bundles:generate`
- `POST /api/rule-bundles/{id}/activate`
- `GET /api/rule-bundles/{id}`
- `GET /api/rule-bundles/{id}/items`

### Schedule Period

- `POST /api/schedule-periods`
- `GET /api/schedule-periods/{id}`
- `GET /api/schedule-periods/{id}/previous-periods`

### Templates

- `GET /api/templates`
- `POST /api/templates`
- `PUT /api/templates/{id}`
- `DELETE /api/templates/{id}`
- `PUT /api/templates/{id}/rules`

## 6. 與最佳化 Job 的關係

建立最佳化 Job 時綁定 `rule_bundle_id`（未指定時取 period.active_rule_bundle_id）。

## 7. 驗收重點

- Bundle 可生成、預覽與驗證
- Activate 後該期固定使用
- 公版編輯不影響既有 bundle
- NURSE_PREF 支援上一期拷貝
- 重跑可重現（固定 bundle + seed）
