# 規格整理 v 1.1.3

以下是一份針對「**護理師排班系統**」專用的 **DSL 詳盡技術規格文件**（v1.0）。內容涵蓋：

* DSL 檔案結構（Rule / Constraint / Objective）
* **完整運算子**、優先序、型別規則
* **完整函數清單**（含可編譯/不可編譯、用途、回傳型別）
* 可做的操作（硬限制、軟目標、偏好、分層覆寫、鎖定/提示）
* 語法規範（YAML 規格、Expression Grammar、保留字、命名）
* 驗證規範（schema、語意、可編譯性、整包檢查）
* 編譯到 CP-SAT 的限制與最佳實務

> 本文件以「**可落地（可編譯）**」為設計中心：
> 任何 DSL 表達都要能被 deterministic 地轉成 IR，再轉 CP-SAT（OR-Tools）限制式或成本項。

---

## 1. DSL 概觀與使用情境

### 1.1 DSL 在系統中的角色

* 規則輸入：自然語言 →（LLM）→ DSL（存檔）
* 規則驗證：DSL → schema/語意/可編譯檢查
* 求解：Rule Bundle（本期規則集快照）內所有 DSL 編譯成 CP-SAT 模型
* 反向翻譯：DSL →（Translator）→ 自然語言（供使用者確認）

### 1.2 DSL 設計的核心限制（務必遵守）

* **可編譯性優先**：避免需要先知道解的函數（如 `shift_of`）用在求解階段
* **確定性**：相同 DSL + 相同 input + 相同 seed ⇒ 可重現結果（在 solver 設定固定時）
* **分層管理**：LAW / HOSPITAL / TEMPLATE / NURSE_PREF 由 Bundle 決定，DSL 本體不含 layer（layer 是 bundle item metadata）

---

## 2. DSL 檔案格式（YAML）結構規範

### 2.1 Rule Root

每份 DSL 文件描述「一條規則版本」：

```yaml
dsl_version: "1.0"
id: "R_..."
name: "..."
scope:
  type: GLOBAL | HOSPITAL | DEPARTMENT | NURSE
  id: null | "H001" | "ICU" | "N021"
type: HARD | SOFT | PREFERENCE
priority: 0..100000
enabled: true | false
tags: ["..."]
notes: "..."

constraints: []   # type=HARD 時使用
objectives: []    # type=SOFT/PREFERENCE 時至少一條
```

### 2.2 Constraint 與 Objective 結構

**Constraint**

```yaml
- id: "C1"
  name: <constraint_name_enum>
  for_each: <iterator>   # v1 可省略（多數用 targets 展開即可）
  where: <expr>          # v1 建議僅用於「展開時過濾」，不進 solver
  params: { ... }        # 依 name 決定 schema
  message: "..."
```

**Objective**

```yaml
- id: "O1"
  name: <objective_name_enum>
  weight: 0..100000
  for_each: <iterator>
  where: <expr>
  params: { ... }
  message: "..."
```

---

## 3. 命名規範與保留字

### 3.1 ID 規範

* `id`（rule）：建議 `R_<SCOPE>_<NNN>`
* `constraints[].id`：`C1`, `C2`…
* `objectives[].id`：`O1`, `O2`…

### 3.2 允許字元

* `id`：`[A-Za-z0-9_\-]+`
* scope id：依資料表（department_id、nurse_id）

### 3.3 保留字（Expression 中不可用作變數名）

`and, or, not, in, true, false, null`

---

## 4. 型別系統（Expression）

### 4.1 原生型別

* `bool`
* `int`
* `float`
* `string`
* `date`
* `time`
* `duration`（v1 以 minutes 的 int 表示）
* `nurse`（物件）
* `shift`（物件）
* `set<T>`
* `list<T>`

### 4.2 物件欄位（dot access）

* `nurse.id: string`
* `nurse.name: string`
* `nurse.department_id: string`
* `nurse.job_level: string`
* `nurse.skills: list<string>`
* `shift.code: string`
* `shift.is_off: bool`
* `shift.start_time/end_time: time`（若有）

### 4.3 Literal 表示

* string：`"ICU"`
* int：`123`
* float：`1.25`
* bool：`true` / `false`
* null：`null`
* set：`{"D","E","N"}`
* list：`["ICU","ER"]`
* date：`date("2026-01-01")`

---

## 5. Expression 語法規範（完整）

### 5.1 運算子（完整清單）

#### 5.1.1 布林運算子

* `not <bool>`
* `<bool> and <bool>`
* `<bool> or <bool>`

#### 5.1.2 比較運算子

* `==`, `!=`, `<`, `<=`, `>`, `>=`

#### 5.1.3 數值運算子

* `+`, `-`, `*`, `/`, `%`
* 一元負號：`-x`

#### 5.1.4 集合/成員運算子

* `x in {"A","B"}`
* `x not in {"A","B"}`

> v1 建議：`in` 用於 `string/int` 對 `set/list`，不要混用複雜型別。

### 5.2 優先序（由高到低）

1. `(...)`
2. `not`, unary `-`
3. `* / %`
4. `+ -`
5. `== != < <= > >= in not in`
6. `and`
7. `or`

### 5.3 EBNF（完整）

```ebnf
expr        := orExpr ;
orExpr      := andExpr ( "or" andExpr )* ;
andExpr     := cmpExpr ( "and" cmpExpr )* ;
cmpExpr     := addExpr ( ( "==" | "!=" | "<" | "<=" | ">" | ">=" | "in" | "not in" ) addExpr )* ;
addExpr     := mulExpr ( ( "+" | "-" ) mulExpr )* ;
mulExpr     := unaryExpr ( ( "*" | "/" | "%" ) unaryExpr )* ;
unaryExpr   := ( "not" | "-" ) unaryExpr | primary ;
primary     := literal | ident | funcCall | "(" expr ")" ;
funcCall    := ident "(" ( expr ( "," expr )* )? ")" ;
ident       := /[A-Za-z_][A-Za-z0-9_.]*/ ;
literal     := number | string | "true" | "false" | "null" | setLit | listLit ;
setLit      := "{" ( expr ( "," expr )* )? "}" ;
listLit     := "[" ( expr ( "," expr )* )? "]" ;
```

---

## 6. Expression 的「可編譯性」規範（重要）

Expression 可能出現在：

* `where:`（過濾展開 targets）
* 部分 params（例如 shifts list、dates list —— v1 多數用 literal，不建議在 params 寫運算）

### 6.1 分級

* **Filter-only 表達式**：只能用於展開/過濾（不進 solver）

  * 例：`dept(nurse) == "ICU"`
* **Solver-compilable 表達式**：可被編譯成線性限制（v1 先不開放自由式，改用內建 constraint/objective name + params）

> v1 強烈建議：
> **不要允許任意 expression 直接形成 solver 限制**。
> 求解約束統一走 `constraints[].name + params` 的可控枚舉，避免 LLM 生成出不可線性化的式子。

---

## 7. 內建函數（Functions）完整清單

下面函數分三類：
A) **資料查詢/分類（可用於 where 過濾）**
B) **排班指派查詢（求解階段可編譯）**
C) **日期/集合工具（where 或編譯輔助）

### 7.1 A 類：資料查詢（Filter-only / 可安全 eval）

| 函數                            | 參數            | 回傳     | 用途                   |
| ----------------------------- | ------------- | ------ | -------------------- |
| `dept(nurse)`                 | nurse         | string | 取得部門                 |
| `job_level(nurse)`            | nurse         | string | 取得職級                 |
| `has_skill(nurse, "VENT")`    | nurse, string | bool   | 技能判斷                 |
| `in_group(nurse, "FULLTIME")` | nurse, string | bool   | 合約/群組（需 ctx mapping） |

> `in_group` 若你尚未有 group 資料，可先不開放；但文件先定義。

### 7.2 B 類：排班指派查詢（Solver-compilable）

這些函數會被編譯成 `x[n,d,s]` 的線性形式（或輔助變數）。

| 函數                                    | 回傳   | 可用位置   | 說明                           |
| ------------------------------------- | ---- | ------ | ---------------------------- |
| `assigned(nurse, day, "D")`           | bool | solver | 是否排該班（對應 x）                  |
| `assigned_any(nurse, day)`            | bool | solver | 是否有排工作班（v1 建議不用，改用 work_var） |
| `count_assigned(nurse, days, shifts)` | int  | solver | 計數（展開成 Σx）                   |
| `count_work_days(nurse, days)`        | int  | solver | 工作日數（排除 OFF）                 |

> 注意：v1 中你實際建模是「exactly one shift per day（含 OFF）」
> 因此 `assigned_any` 可以用 `1 - x[OFF]` 表示。

### 7.3 C 類：日期/集合工具（Filter / IR 展開）

| 函數                           | 回傳               | 用途                          |
| ---------------------------- | ---------------- | --------------------------- |
| `date("YYYY-MM-DD")`         | date             | literal 化                   |
| `days_between(from,to)`      | list<date>       | 生成日期列表（v1 可不開放給 DSL，交由 ctx） |
| `is_weekend(day)`            | bool             | 週末判斷（需 calendar）            |
| `dow(day)`                   | int              | 星期幾（1..7）                   |
| `rolling_days(size, step=1)` | list<list<date>> | 產生滑動窗口（通常在 IR 生成時用）         |

---

## 8. DSL 可以做的「操作」能力（能力矩陣）

### 8.1 硬性限制（HARD constraints）

* 一人一天一班（含 OFF）
* 每日 coverage（班別需求）
* 最大連上天數
* 最大連續特定班（夜班等）
* 班別銜接禁止（transition）
* 夜班後休息（rest_after_shift）
* 任意窗口內最大班數/工作天
* 不可排日期（請假/禁排）
* 技能/資深 coverage
* 週末完整休假頻率、完整週末原則、最低連休（若已擴充）

> HARD 必須可編譯為線性限制，且違反即 infeasible。

### 8.2 軟性目標（SOFT objectives）

* 週末/夜班公平（range）
* 偏好週末休
* 避免 E→N
* 避免單日 OFF（penalize single off）
* 輪班多樣化（penalize consecutive same shift）

> SOFT 以成本最小化方式加入 objective。

### 8.3 偏好（PREFERENCE）

* 等同 SOFT，但 scope 通常是 NURSE，且 layer=NURSE_PREF
* 透過 bundle 可調整偏好影響力（weight_multiplier）

---

## 9. Constraint / Objective Name 枚舉（v1.0 建議完整集）

> 這是「DSL 能表達的功能邊界」。新增規則型態 = 新增 name + params schema + compiler 分支。

### 9.1 HARD constraints（name）

* `one_shift_per_day`
* `coverage_required`
* `max_consecutive_work_days`
* `max_consecutive_shift`
* `forbid_transition`
* `rest_after_shift`
* `max_assignments_in_window`
* `max_work_days_in_rolling_window`
* `unavailable_dates`
* `skill_coverage`
* `if_novice_present_then_senior_present`
* `max_consecutive_same_shift`
* `min_consecutive_off_days`
* `weekend_all_or_nothing`
* `min_full_weekends_off_in_window`

### 9.2 SOFT/PREFERENCE objectives（name）

* `balance_shift_count`（range）
* `balance_weekend_shift_count`（range）
* `penalize_transition`
* `prefer_off_on_weekends`
* `prefer_shift`
* `penalize_single_off_day`
* `penalize_consecutive_same_shift`

---

## 10. Params 規範（通用約束）

### 10.1 params 基本規則

* 必須是 object
* 不允許未知欄位（schema `additionalProperties=false`）
* 字串 enum 欄位必須符合定義
* shifts/dates list 需存在於 master data

### 10.2 常見 params 型別

* `shift_codes: list<string>`
* `dates: list<YYYY-MM-DD>`
* `window_days: int`
* `max_days / min_days: int`
* `required: int`
* `department_id: string`
* `by_job_levels: list<string>`

---

## 11. `where:` 的規範（v1 推薦做法）

### 11.1 使用定位

* `where` **只用於「展開 targets 過濾」**，不進 solver
* 支援的 pattern（v1 最穩）：

  * `dept(nurse) == "ICU"`
  * `job_level(nurse) in {"N3","N4"}`
  * `has_skill(nurse,"VENT")`

### 11.2 不建議（v1 禁止）

* 在 where 中呼叫會依賴解的函數：`assigned(...)`、`count_assigned(...)`
* 在 where 中做複雜數學（會讓可預測性下降）

---

## 12. `for_each:` 的規範（v1 可選）

### 12.1 v1 立場

* 大多數規則不需要 `for_each`，由 compiler 直接對 nurses/days 展開即可
* 若保留 `for_each`，建議只支援：

  * `nurses` / `days` / `shifts`
  * `rolling_days(size, step)`

### 12.2 目的

* 給未來 v1.2 做「更通用 rule」鋪路，但 v1 不強依賴。

---

## 13. 可編譯（Compiler）規範：DSL → IR → CP-SAT

### 13.1 編譯管線

1. YAML parse
2. JSON Schema validate（結構 + params）
3. Semantic validate（shift code / nurse id / dept id 存在）
4. Bundle-level validate（precheck + heuristics）
5. DSL → IR（targets 展開、where 過濾、freeze）
6. IR → CP-SAT（constraints / objectives）
7. Solve + Extract

### 13.2 決策變數標準

* `x[n,d,s] ∈ {0,1}`
* exactly-one：`Σ_s x[n,d,s] == 1`（含 OFF）

### 13.3 Objective 整數化規範

* `effective_cost = round(weight * penalty * COST_SCALE)`
* `COST_SCALE` 建議 100

---

## 14. 反向翻譯（DSL → NL）輸出規範（你系統必備）

### 14.1 每條 constraint/objective 必須翻譯成一段

包含：

* scope（GLOBAL/HOSPITAL/DEPARTMENT/NURSE）
* 類型（硬性/軟性/偏好）
* name 對應的自然語意
* params 展開（數字/班別/窗口）

### 14.2 where 的翻譯

* `where` 必須翻成「僅對…的人生效」

---

## 15. 版本與相容性規範

### 15.1 DSL 版本欄位

* `dsl_version: "1.0"` 必填

### 15.2 向下相容

* 同 major（1.x）必須向下相容
* 不可移除既有 `name`，只能標記 deprecated
* 新增 `name` 需同時新增：

  * schema params
  * compiler 分支
  * reverse translator 支援

---

## 16. 最佳實務（LLM 產 DSL 的約束）

### 16.1 生成規則

* LLM 只能從枚舉的 `name` 中選擇
* params 必須完全符合 schema
* where 僅使用允許 pattern
* 一條規則只做一件事（避免混雜）

### 16.2 建議的 DSL 風格

* HARD 規則拆細（每條只描述一種硬限制）
* SOFT/PREFERENCE 用 objectives 拆出多條，便於權重調整

---

## 17. 附錄：Expression 範例（合規 vs 不合規）

### 17.1 合規 where 範例

```yaml
where: dept(nurse) == "ICU"
where: job_level(nurse) in {"N3","N4"}
where: has_skill(nurse,"VENT")
```

### 17.2 不合規 where 範例（v1 禁止）

```yaml
where: assigned(nurse, day, "N")            # 依賴解
where: count_assigned(nurse, window, {"N"}) > 2  # 依賴解
where: shift_of(nurse, day) == "N"          # 依賴解且不可編譯
```
