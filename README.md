# NurseRoster

## Zeabur 部署策略
- **前後端分離**：前端為單頁式 SPA，可由 `src/app/static` 作為靜態資源雛形，後續可替換為 Vite/React build 產物並部署在 Zeabur 靜態站；後端為 FastAPI 容器，提供 `/api/**` 與 SSE/WS 端點。
- **持久化 SQLite**：後端容器請在 Zeabur 綁定持久化磁碟並掛載到 `/data`（或其他目錄），同時設定環境變數：
  - `DATA_DIR=/data`（會自動建 `logs`、`exports`）
  - `LOG_DIR=/data/logs`
  - `DB_PATH=/data/app.db`
- **容器啟動參數**：後端以 `python -m app` 啟動，請在 Zeabur 服務環境中設定 `BACKEND_HOST=0.0.0.0`、`BACKEND_PORT=8000`（也會向下相容 `APP_HOST`/`APP_PORT`），並開啟健康檢查 `/api/health`。
- **網路路由**：前端呼叫後端時，請在環境變數或前端設定中指向後端公開 URL（HTTPS）。SSE 與 WebSocket 均需允許跨站（Zeabur 反向代理會自動處理 `Connection: keep-alive`/`upgrade`）。

## 目錄結構與環境變數
```
project-root/
├─ src/
│  ├─ app/          # 後端程式與模板
│  └─ tests/        # 後端測試
├─ .env.example     # 請依需求複製為 .env
├─ requirements.txt
└─ run_app.bat
```

- 服務埠統一以 `.env` 管理：`BACKEND_HOST`、`BACKEND_PORT`（預設 127.0.0.1:8000）。
- `run_app.bat` 與程式本體都優先讀取 `BACKEND_HOST`/`BACKEND_PORT`，並對舊版 `APP_HOST`/`APP_PORT` 保持相容。
- `src/app/core/config.py` 會在啟動時解析根目錄 `.env`（內建解析器），請依 `.env.example` 建立。

## LLM Streaming 方案
- 主要通道採用 **SSE**（`GET /api/rules/nl_to_dsl_stream?text=...`）。
- 降級通道提供 **WebSocket**（`/api/rules/nl_to_dsl_ws?text=...`），前端可在 SSE 失敗時切換。
- **無金鑰時啟用 mock**：若未設定 `OPENAI_API_KEY`，後端自動使用 mock 產生 token/DSL，並在串流訊息中明確標示。

## Logging 與例外處理
- 全域啟動時會初始化 `logs/app.log`（INFO 級別，同步輸出到 console）。
- 主程式入口、SSE/WS 轉譯流程、最佳化任務皆加上 try-except，將技術細節記錄於 log 檔，不回傳敏感資訊給前端。
- 可透過 `LOG_DIR` 自訂 log 位置，確保與 SQLite 同樣置於 Zeabur 的持久化磁碟中。

## Windows 一鍵啟動
- 在專案根目錄直接執行 `run_app.bat`。
- 腳本會自動建立 `.venv`、安裝 `requirements.txt`，並以 `python -m app` 啟動服務。
- 如需自訂位址或埠號，可在執行前設定 `BACKEND_HOST`、`BACKEND_PORT`（亦支援相容的 `APP_HOST`、`APP_PORT`）環境變數。
