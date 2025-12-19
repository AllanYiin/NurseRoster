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
