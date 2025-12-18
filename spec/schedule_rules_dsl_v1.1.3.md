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

