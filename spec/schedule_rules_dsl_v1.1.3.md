# Schedule Rules DSL v1.1.3 完整規格

以下提供「本排班系統專用 DSL（Schedule Rules DSL）」的完整 v1 詳盡規格：包含語法/結構、型別系統、完整運算子、完整函數（內建函數庫）、可做的操作、規範與驗證規則、分層覆寫語意。設計目標：可機器驗證、可編譯到 OR-Tools CP-SAT、可反向翻譯、不可含隱式歧義。

---

## 1. DSL 的定位與設計原則

### 1.1 設計目標

* **可驗證**：100% JSON 結構 + Schema（Pydantic/JSON Schema）驗證。
* **可編譯**：每條規則都能映射為 Hard/Soft/Preference（constraint 或 penalty）。
* **可解釋**：每個 operator/function 都有 deterministic `explain()` 模板，支援 DSL→NL。
* **非圖靈完備**：不支援任意迴圈/遞迴，只支援**有界**量化/聚合。

### 1.2 資料面向

* `Nurse`, `Date`, `Shift`, `Dept`, `Assignment`, `LockedAssignment`, `Codes`。

---

## 2. Rule Document（JSON 物件）

建議完整欄位：

```json
{
  "dsl_version": "sr-dsl/1.0",
  "rule_id": "uuid-or-string",
  "name": "最大連續上班天數",
  "description": "全域硬性限制",
  "enabled": true,
  "scope": { "scope_type": "global|hospital|dept|nurse", "dept_id": null, "nurse_id": null },
  "category": "hard|soft|preference",
  "priority": 100,
  "parameters": {},
  "body": {
    "type": "constraint|objective",
    "when": {},
    "assert": {},
    "penalty": {},
    "reward": {},
    "weight": 5,
    "severity": "warn|error",
    "tags": ["fatigue","law"]
  }
}
```

* `constraint`：必須有 `assert`；`objective`：必須有 `penalty` 或 `reward`。
* Hard：`category=hard` 且 `body.type=constraint`。
* Soft/Preference：`category in (soft, preference)` 且 `body.type=objective`。

---

## 3. 型別系統

* 基本：`bool/int/number/string/date/time/duration`
* Domain：`nurse_ref/dept_ref/shift_ref/rank_ref/set<T>/list<T>`
* 推導：邏輯→bool、比較→bool、聚合→int/number、日期函數→date/int/bool。

---

## 4. 表達式語法（JSON AST）

* Operator：`{ "op": "OP_NAME", "args": [ ... ] }`
* Function：`{ "fn": "function_name", "args": { "param": "..." } }`
* v1 規範：operator 用 `op`+陣列，function 用 `fn`+物件，不可混用。

---

## 5. 運算子清單

邏輯、比較、算術、集合、條件、量化、字串共 45 個：

* 邏輯：AND/OR/NOT/XOR/IMPLIES/IFF
* 比較：EQ/NE/GT/GTE/LT/LTE/IN/BETWEEN
* 算術：ADD/SUB/MUL/DIV/MOD/ABS/MIN/MAX/CLAMP/ROUND
* 集合：SET/UNION/INTERSECT/DIFF/SIZE/CONTAINS/DISTINCT/SORT
* 條件：IF/COALESCE/IS_NULL
* 量化：FORALL/EXISTS/COUNT_IF/SUM/MIN_OF/MAX_OF
* 字串：CONCAT/LOWER/UPPER/MATCH

---

## 6. Domain Iterator

格式：`{"iter":"NURSES|DATES|SHIFTS|ASSIGNMENTS","where":bool_expr}`。`where` 只允許邏輯/比較/純查詢函數。

---

## 7. Lambda

格式：`{"lambda":["n","d"],"body":expr}`。參數依 iterator：NURSES→["n"], DATES→["d"], ASSIGNMENTS→["n","d"], SHIFTS→["s"].

---

## 8. 函數清單

* Assignment：shift_assigned, assigned_shift, is_work_shift, is_off_shift
* 資格：in_dept, has_rank_at_least, employment_type_is, nurse_is_active
* 日期：day_of_week, is_weekend, is_holiday, week_of_period, date_add, date_diff_days
* 序列：count_consecutive_work_days, has_sequence, rest_minutes_between
* Coverage：coverage_count, required_coverage, coverage_shortage
* 公平：count_shifts_in_period, count_weekend_shifts, deviation_from_mean
* 目標輔助：penalty_if, penalty_per_occurrence, reward_if
* Explain/UI（不可進 solver）：format_date, format_shift, lookup_nurse_name, explain_expr

---

## 9. 可做的操作

* Hard：一日一班、連續上班天數上限、休息時間、夜班上限、coverage 達成、技能 mix、不可上班日、鎖定格。
* Soft/Preference：偏好班別/休假、避免序列、夜班/假日公平、允許缺口但有 penalty。
* 分層覆寫：soft 可覆寫 weight/params；hard 只能加嚴。

---

## 10. 規範與驗證

* JSON Schema 驗證：必含 dsl_version/scope/category/body；hard 不得帶 weight；soft/preference 必帶 weight。
* Domain 驗證：引用的 dept/nurse/shift/rank 必須存在，日期落在期間，序列 shift 存在。
* Compile 驗證：不得包含不可編譯函數（regex/lookup/explain 等），量化 domain 有界，assigned_shift 不可直接進 solver。
* 決定性：相同輸入 + seed 必可重現。

---

## 11. Guard 與 Assert/Penalty

* `when=false`：constraint 不施加；objective penalty/reward=0。
* `assert` 必為 bool；`penalty/reward` 必為 number。

---

## 12. 範例

* 最大連續上班天數（Hard）：使用 FORALL ASSIGNMENTS + count_consecutive_work_days。
* 夜班至少 1 位 N2+（Hard Coverage）：FORALL DATES + coverage_count + has_rank_at_least。
* 避免 D→N（Soft）：SUM NURSES/DATES + penalty_if。

---

## 13. 分層合併

* semantic_key 決定同義規則，可覆寫/加嚴。
* 順序：global→hospital→dept→nurse，priority desc。
* Hard 加嚴判定：MAX 越小越嚴、MIN 越大越嚴、coverage 越大越嚴、禁止集合越多越嚴；放寬需阻擋。

---

## 14. 反向翻譯規範

* 每個 op/fn 需有 explain_template_zh、param_labels、example。
* 流程：normalize → extract_intent → render。不得用 lookup 類修改語意。

---

## 15. 實作建議

* 用 Pydantic 定義 RuleDoc/Expr/Iterator/Lambda。
* 兩階段編譯：DSL→IR（ConstraintIR/ObjectiveIR）→ CP-SAT。
* solver_support 白名單，禁止 regex/sort/lookup/explain 等進 constraint/objective。
* 不可編譯者僅供 UI/Debug/Explain。

---

## 16. JSON Schema（sr-dsl/1.0）

建議檔名：`schemas/sr-dsl-1.0.schema.json`，可直接用於後端驗證。包含 Scope/Body/Expr/OpExpr/FnExpr/DomainIterator/Lambda/Literal 定義；依 category/type 互斥約束；禁止 objective 缺 weight 等。完整內容請依上方規格展開。

---

## 17. Explain 模板（zh）

建議檔名：`dsl_explain/zh_TW_templates.json`。

* Operators：AND/OR/NOT… 至 MATCH，皆含 summary/render（中文）。
* Functions：shift_assigned、assigned_shift、coverage_count… explain label/params/render。
* Explain 輸出：summary + details + assumptions。

---

## 18. DSL → IR 規格

* RuleIR：包含 scope/category/priority/guard + constraint/objective。
* BoolIR：and/or/not、比較、量化（展開）、atom（布林變數）。
* Int/NumIR：線性運算、count/sum 展開；objective 必須可線性化。
* ConstraintIR：線性不等式或高階型（one_shift_per_day/coverage_min/max_consecutive…）。
* ObjectiveIR：weighted_sum + reified_penalty 等，常見型避免序列/公平/coverage_shortage。

---

## 19. 編譯規範

* 白名單：AND/OR/NOT、比較、ADD/SUB/MUL(常數)、IF(可線性化)、FORALL/COUNT_IF/SUM、shift_assigned/in_dept/has_rank_at_least/is_weekend/date_add/coverage_count/penalty_if/penalty_per_occurrence/reward_if。
* 禁止：MATCH、SORT、format_*、lookup_nurse_name、explain_expr、assigned_shift（未展開）。
* 展開：FORALL → 多條 constraint；coverage_count → Σx；penalty_if → reified 變數進 objective。

---

## 20. 配套檔案建議

* `dsl_runtime/solver_support.json`：op/fn solver_support 標註。
* `dsl_samples/*.json`：常見規則範例，供 NL→DSL/回歸測試。

---

# 規格整理 v 1.1.3

下面把「實務常見但目前 DSL 缺少/有限支援」補進 DSL v1.x 的擴充設計：**新增規則型態（HARD/SOFT）、語法、params、語意、以及 CP-SAT 編譯方式**。我會盡量用「可直接落地」的模板，讓你只要在 `ConstraintParamsDispatch / ObjectiveParamsDispatch` 與 `compile_constraints.py / compile_objectives.py` 增補對應分支就能上線。

---

## A. 週末休假頻率要求（每兩週至少一個完整週末休假）

### A1. 新增 HARD Constraint：`min_full_weekends_off_in_window`

**用途**：在任意（或以固定週期切分的）窗口內，要求「完整週末 OFF」的次數達到最低值。

**DSL**

```yaml
constraints:
  - id: "C_WEEKEND_OFF_FREQ"
    name: min_full_weekends_off_in_window
    params:
      window_days: 14                # 14天窗口（兩週）
      min_full_weekends_off: 1       # 至少1個完整週末OFF
      weekend_def: "SAT_SUN"         # v1：固定SAT+SUN
      off_code: "OFF"                # 可省略，用ctx判斷is_off
      sliding: true                  # true=任意連續14天都要滿足；false=按period切塊
```

**語意**

* 「完整週末 OFF」定義：週六與週日都 OFF。
* `sliding=true`：任意連續 `window_days` 天內，完整週末 OFF 次數 ≥ min。
* `sliding=false`：以 period 起點切成不重疊窗口（較寬鬆、較符合排班週期）。

**CP-SAT 編譯（核心）**

* 先對每位護理師 n、每個週末 w（週六日對）定義：

  * `fullWeekendOff[n,w]` Bool
  * 線性化：`fullWeekendOff <= offSat`, `fullWeekendOff <= offSun`, `fullWeekendOff >= offSat + offSun - 1`
  * 其中 `offSat = x[n,sat,OFF]`，`offSun = x[n,sun,OFF]`
* 再對窗口（sliding 或 block）加：

  * `Σ fullWeekendOff[n,w in window] >= min_full_weekends_off`

> 實作提示：需要 `calendar_index` 能找出每個週六對應的週日（跨月仍可）。

---

## B. 完整週末原則（要嘛整個週末上班，要嘛整個週末都休）

### B1. 新增 HARD Constraint：`weekend_all_or_nothing`

**用途**：避免只休週六但週日上班（或相反），要求週末兩天「同為 OFF 或同為 WORK」。

**DSL**

```yaml
constraints:
  - id: "C_WEEKEND_ALL_OR_NOTHING"
    name: weekend_all_or_nothing
    params:
      weekend_def: "SAT_SUN"
      mode: "OFF_OR_WORK"     # v1固定：兩天同態（都OFF或都工作）
```

**語意**

* 對每位 n、每個週末（sat,sun）：

  * `is_off(n,sat) == is_off(n,sun)`
    等價：不允許 OFF/WORK 不一致。

**CP-SAT**

* `offSat = x[n,sat,OFF]`, `offSun = x[n,sun,OFF]`
* 加 constraint：`offSat == offSun`

> 變體（可擴充）：如果你想允許「兩天都同一班別類型」也可加 mode，但 v1 先做同 OFF/WORK 最常用。

---

## C. 最低連休天數（避免單日休假）

### C1. 新增 HARD Constraint：`min_consecutive_off_days`

**用途**：只要開始休假，就至少連休 K 天；避免 Work–OFF–Work 的單日休。

**DSL**

```yaml
constraints:
  - id: "C_MIN_CONSEC_OFF"
    name: min_consecutive_off_days
    params:
      min_days: 2                 # 至少連休2天
      apply_to: "ALL"             # v1 可保留
      allow_at_period_edges: true # period頭尾若不足K天，是否放寬
```

**語意（常見實務）**

* 若某天為 OFF 且前一天不是 OFF（休假區段開始），則後面 `min_days-1` 天必為 OFF。

**CP-SAT（線性化）**

* 定義 `off[n,d] = x[n,d,OFF]`
* 定義 `startOff[n,d]`：當天是 OFF 且前一天非 OFF

  * `startOff <= off[d]`
  * `startOff <= 1 - off[d-1]`（d>0）
  * `startOff >= off[d] - off[d-1]`
* 對每個 startOff：

  * `off[n,d+r] >= startOff[n,d]` for r=1..min_days-1
* `allow_at_period_edges=true`：若 `d+r` 超出 period，則跳過該條（或改成 block 模式只檢查完整可檢窗口）。

### C2. 新增 SOFT Objective：`penalize_single_off_day`

**用途**：不強制，但盡量避免單日 OFF（更彈性）。

**DSL**

```yaml
objectives:
  - id: "O_AVOID_SINGLE_OFF"
    name: penalize_single_off_day
    weight: 10
    params:
      penalty: 1
```

**CP-SAT**

* 對每 n,d（d-1,d,d+1 都存在）定義 `singleOff`：

  * `singleOff = off[d] AND (1-off[d-1]) AND (1-off[d+1])`
* cost += weight * penalty * singleOff

---

## D. 每週工時或班數上限（任意7天內最多工作5天等）

> 你其實已經有 `max_assignments_in_window`，但要補齊兩個缺口：

1. **週期滑動窗口**（任意 7 天）要成為一級規則（更常用、更清楚）
2. **不同合約（全職/兼職）** 需 per-nurse params（或 job_level/contract_group）

### D1. 新增 HARD Constraint：`max_work_days_in_rolling_window`

**DSL**

```yaml
constraints:
  - id: "C_MAX_5_IN_7"
    name: max_work_days_in_rolling_window
    params:
      window_days: 7
      max_work_days: 5
      include_shifts: ["D","E","N"]   # 工作班別
      sliding: true                   # 任意連續7天
```

**CP-SAT**

* `work[n,d] = Σ_{s in include_shifts} x[n,d,s]`
* 對每 n、每個 start：`Σ_{k=0..W-1} work[n,start+k] <= max_work_days`

### D2. per-nurse / per-contract 變體（推薦做法）

新增一種 params 形式（擇一）：

**方式 1：rule 用 where + 多條規則**

```yaml
where: job_level(nurse) in {"PT"}     # 兼職群組（示例）
params: { window_days: 7, max_work_days: 3, include_shifts: ["D","E","N"], sliding: true }
```

**方式 2：params 直接帶 mapping（更省 rule 數）**

```yaml
params:
  window_days: 7
  include_shifts: ["D","E","N"]
  max_work_days_by_group:
    FULLTIME: 5
    PARTTIME: 3
  nurse_group_field: "contract_type"
```

> v1 建議先用方式 1（簡單、少 parser 功能），方式 2 放 v1.2。

---

## E. 週末班分配公平（不是「盡量週末OFF」，而是公平）

你已經有 `balance_weekend_work`（我前面 demo 補過），但你指出「目前 DSL 沒有明確內建」，所以這裡把它正式納入 **Objective 枚舉**，並補上兩種公平形式：**range** 與 **target-based**。

### E1. 新增 SOFT Objective：`balance_weekend_shift_count`

**DSL**

```yaml
objectives:
  - id: "O_BAL_WEEKEND"
    name: balance_weekend_shift_count
    weight: 25
    params:
      weekend_days: "SAT_SUN"      # or "HOLIDAY"（擴充）
      shifts: ["D","E","N"]        # 哪些算「週末班」
      metric: "range"              # v1 建議 range (max-min)
```

**CP-SAT**

* 計算每人週末工作次數 `cnt[n]`
* 定義 `maxC/minC`，cost += (maxC - minC) * weight

### E2. 目標值（target）變體（v1.2）

```yaml
metric: "target"
target_per_nurse: 2
penalty_per_diff: 1
```

* cost += |cnt[n] - target|（需要 abs 線性化）

---

## F. 新人與資深搭配（條件式規則）

你已有 `skill_coverage`（每班至少一位具技能），但「新人在場 → 必有資深」是 **條件式**。補一條硬規則：

### F1. 新增 HARD Constraint：`if_novice_present_then_senior_present`

**DSL**

```yaml
constraints:
  - id: "C_NOVICE_SENIOR_PAIR"
    name: if_novice_present_then_senior_present
    params:
      department_id: "ICU"
      shifts: ["D","E","N"]          # 哪些班適用
      novice_group:                  # 新人定義（擇一）
        by_job_levels: ["N1"]
      senior_group:
        by_job_levels: ["N3","N4"]
      min_senior: 1
      trigger_if_novice_count_ge: 1  # 只要有 >=1 新人就觸發
```

**語意**

* 對每一天 d、每個 shift s：

  * 若該班別有新人（>= trigger），則該班別資深數量 >= min_senior

**CP-SAT（線性化）**

* 定義：

  * `novCnt[d,s] = Σ_{n in novice} x[n,d,s]`
  * `senCnt[d,s] = Σ_{n in senior} x[n,d,s]`
* 定義 trigger bool `t[d,s]`：`novCnt >= trigger`

  * CP-SAT 可用 reified：`model.Add(novCnt >= trigger).OnlyEnforceIf(t)`
  * 以及 `model.Add(novCnt < trigger).OnlyEnforceIf(t.Not())`
* 再加：`model.Add(senCnt >= min_senior).OnlyEnforceIf(t)`

> v1 若你要更簡單：直接要求每個班次 `senCnt >= 1`（不管新人在不在），但會太硬。建議用上述條件式。

---

## G. 避免同一護理師連續太多天排同一班別（輪班變化）

### G1. 新增 HARD Constraint：`max_consecutive_same_shift`

**DSL**

```yaml
constraints:
  - id: "C_MAX_SAME_SHIFT"
    name: max_consecutive_same_shift
    params:
      shift_codes: ["D","E","N"]     # OFF 通常不算
      max_days: 3
```

**CP-SAT**

* 對每 shift t ∈ shift_codes：

  * `twork[n,d] = x[n,d,t]`
  * 對每 n、每個 start：`Σ_{k=0..max_days} twork[n,start+k] <= max_days`
    （禁止連續 max_days+1 天都是同一班）

### G2. SOFT 版本（偏好輪替）

`penalize_consecutive_same_shift`：每次連續超過 M 就加罰（v1 可先不做，硬規則較直觀）

---

## H. 跨科支援 / 輪調頻率限制（同人不同病房輪調太頻繁）

這一類需要你排班變數不只決定 shift，還要決定 **department assignment**。目前你的核心變數是 `x[n,day,shift]`，如果你允許跨科支援，建議擴成：

* `x[n,day,dept,shift] ∈ {0,1}`
  且每日 sum(dept,shift)=1（或 dept + OFF 特判）

> 如果 v1 暫不做跨科支援，就把這條列為 v1.2；但你要求先補 DSL 型態，我這裡給「可擴充語法」與編譯前置條件。

### H1. 新增 HARD Constraint（v1.2 起）：`max_department_switches_in_window`

**DSL**

```yaml
constraints:
  - id: "C_DEPT_SWITCH_LIMIT"
    name: max_department_switches_in_window
    params:
      window_days: 14
      max_switches: 2
      departments: ["ICU","ER"]         # 支援的輪調集合
      count_off_as_no_dept: true
```

**語意**

* 在任意 14 天內，某護理師「部門切換次數」不超過 2。

**CP-SAT（需要 dept 變數）**

* 定義 `deptOf[n,d]`（或 one-hot `y[n,d,dept]`）
* 定義 `sw[n,d]` 表示 d-1 到 d 是否切換：

  * `sw[n,d] >= y[n,d,dept] - y[n,d-1,dept]` 需要更完整線性化（one-hot switch 常用：`sw >= 1 - Σ_{dept} (y[d,dept] AND y[d-1,dept])`）
* 窗口限制：`Σ sw <= max_switches`

> v1 若你想暫不擴變數，可以把「跨科」視為技能/資格而不是 dept 維度，就不會有切換概念。

---

## I. DSL 擴充清單總表（新增 name）

把你 DSL 的枚舉擴充如下：

### I1. 新增 HARD constraints（name）

* `min_full_weekends_off_in_window`
* `weekend_all_or_nothing`
* `min_consecutive_off_days`
* `max_work_days_in_rolling_window`
* `if_novice_present_then_senior_present`
* `max_consecutive_same_shift`
* （v1.2）`max_department_switches_in_window`（需要 dept 維度變數）

### I2. 新增 SOFT objectives（name）

* `penalize_single_off_day`
* `balance_weekend_shift_count`（或 `balance_weekend_shift_count`/`balance_weekend_work` 統一命名其一）
* `penalize_consecutive_same_shift`（可選）
* （v1.2）`minimize_department_switches`（偏好少輪調）

---

## J. JSON Schema 與 Compiler 要改哪裡（最少改動）

### J1. schema_v1.json

* 在 `Constraint.name enum` 加上新 constraints
* 在 `Objective.name enum` 加上新 objectives
* 在 `ConstraintParamsDispatch` / `ObjectiveParamsDispatch` 追加對應 if/then params schema

### J2. compile_constraints.py / compile_objectives.py

* `compile_hard()` 加 switch case
* `compile_soft()` 加 switch case
* 增加 `weekend_pairs` 的工具函式（依 days 生成週末 sat->sun 的 index）

---

## K. 立即可用的 DSL 範例（把新規則用起來）

### K1. 「兩週至少一個完整週末休」+「週末要嘛全休要嘛全上」+「至少連休2天」

```yaml
dsl_version: "1.0"
id: "R_DEPT_WEEKEND_POLICY"
name: "Weekend rest policy"
scope: { type: DEPARTMENT, id: "ICU" }
type: HARD
priority: 90
enabled: true
constraints:
  - id: "C1"
    name: min_full_weekends_off_in_window
    params: { window_days: 14, min_full_weekends_off: 1, weekend_def: "SAT_SUN", sliding: true }
    message: "每14天至少有1個完整週末休假"
  - id: "C2"
    name: weekend_all_or_nothing
    params: { weekend_def: "SAT_SUN", mode: "OFF_OR_WORK" }
    message: "週末要嘛兩天都休，要嘛兩天都上班"
  - id: "C3"
    name: min_consecutive_off_days
    params: { min_days: 2, allow_at_period_edges: true }
    message: "休假至少連休2天"
```
