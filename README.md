# 海大教室借用平台 — 後端

發展者團隊：林品希、陳佳昀、林良承、李曜年、侯屏嘉、洪于宸。

FastAPI / Python / Pydantic 負責業務、權限與 API；Supabase 負責 PostgreSQL、Google Auth、Realtime、Storage 與推播 Edge Function。前端為獨立的 [Classroom_reservation_frontend](https://github.com/NTOUSEg10/Classroom_reservation_frontend) repository。

完整需求及已討論的 coding style：[docs/SPEC.md](docs/SPEC.md)。新版 Google OAuth、GSAP 與 repository 拆分的結果見[測試報告](docs/UPGRADE_TEST_REPORT.md)及[工程審查](docs/UPGRADE_AUDIT_REPORT.md)。[2026-10-11 歷史報告](docs/TEST_REPORT.md)保留原密碼／名冊版本的證據。

2026-10-13 已移除錄影用 Demo，保留週課表修正與前後週導覽。真實服務的本機設定見 [docs/CONNECT_REAL_SUPABASE.md](docs/CONNECT_REAL_SUPABASE.md)。目前尚無正式伺服器／網域，使用者已決定暫緩正式部署；Docker／HTTPS 設定保留供日後使用。

## 開發

需要 Python 3.12+、PostgreSQL 17+、Supabase 專案及 Google OAuth provider。以下在此 repository 根目錄執行：

```powershell
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.lock
.venv/Scripts/python.exe -m pip install -r requirements-dev.txt
Copy-Item .env.example .env
```

若 `.env` 已存在，直接編輯，不覆蓋自己的設定。本次工作區原本的 `.env` 已保留並複製到後端，過程未顯示其內容。DATABASE_URL、Supabase server key、DISPATCH_SECRET 只放後端，不能提交 Git；前端僅從 `/api/config` 取得公開設定。

對新的空白資料庫，以環境提供 DATABASE_MIGRATION_URL 後執行：

```powershell
.venv/Scripts/python.exe scripts/bootstrap_db.py
```

bootstrap 拒絕覆寫既有 schema。已有部署只套用經審查的升級 SQL，不能重跑 bootstrap 刪除資料。應用程式使用非 superuser、非 BYPASSRLS、非表擁有者的 LOGIN，授予 ntou_backend membership；正式連線使用 TLS verify-full。首次管理員正常 Google onboarding 後，由受信任 DB 管理者依核實的 Auth UUID 設定 profiles.role='admin'；不能從表單或 metadata 升權。

正式教室資料使用 [CSV 匯入說明](docs/IMPORT_ROOMS.md)與 [空白模板](data/rooms-template.csv)。工具預設只做離線驗證；指定 `--apply` 才用私有 migration 連線整批寫入，不刪除舊教室或預約。測試 seed 只供隔離測試使用，不匯入真實 Supabase。

```powershell
.venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-access-log
```

開發 API 文件為 `http://127.0.0.1:8000/api/docs`，正式環境停用。前端 Vite 預設代理到 8000；其他埠以 API_PROXY_TARGET 設定。

## 校園 Google 登入

僅允許 Google OAuth 身分且 email 精確為 `@email.ntou.edu.tw`。不再提供平台密碼註冊／登入，不依賴校方名冊。首次登入補填姓名、聯絡電話、系所與學生／教職員證號；email 與 UUID 從 Supabase 驗證結果取得。

在 Supabase Dashboard 配置：

1. 啟用 Google provider，將 Google Cloud OAuth client ID／secret 設在 Supabase；Google authorized redirect URI 使用 Supabase provider 顯示的 callback。
2. Supabase Redirect URLs 加入前端完整 `/auth/callback` URL。預設開發為 `http://127.0.0.1:5173/auth/callback`；若使用 localhost 也須另列 `http://localhost:5173/auth/callback`，兩者不能互換。正式環境只放核准的 HTTPS URL，移除開發位址。
3. 停用 Email/password、phone、anonymous 與其他非 Google provider。前端 `hd=email.ntou.edu.tw` 只是選帳號提示，後端仍獨立驗證。
4. 套用本專案 before-user-created hook SQL，在 Auth Hooks 選擇該函式，限制新身分的 provider／網域；只授權 supabase_auth_admin 執行，匿名 client 不得呼叫。

每次保護請求先向 Supabase 驗證同一 Bearer，再檢查 Google identity、已確認校園 email 與 OAuth amr。DB 每次重新讀取角色及停權。onboarding 寫入失敗後，可用原 Google session 重試，不刪除 Auth identity。既有非 Google／舊網域帳戶保留歷史，由受信任維運核實本人再處理移轉；不自動合併帳號。

實際 Google 授權、provider／hook 設定及外部網路仍須正式驗收；本機 HTTP fixture 只存在 tests，不可部署到正式環境。

## Coding style 與測試

已與使用者確認：JS／TS／JSON／YAML／Markdown 採 Prettier 預設雙引號、2 格縮排、行寬 80、分號、LF；Python 採 Ruff formatter，4 格縮排、雙引號、行寬 80。版本固定，CI 執行 check。

```powershell
npm ci
npm run format:check
.venv/Scripts/python.exe -m ruff format --check app notification_worker scripts tests
.venv/Scripts/python.exe -m ruff check app notification_worker scripts tests
.venv/Scripts/python.exe -m pytest -q --tb=short --junitxml=reports/pytest.xml
```

測試需要 TEST_DATABASE_URL，必須是 loopback 專用 ntou_integration／ntou_load／ntou_e2e。整合測試會清空專用 schema，harness 硬限制 reset 目標；不得指向正式 DB。SQL100 測試須預留 100 條連線，避免背景 server pool 佔滿預算。跨 repository Playwright 使用 E2E_BASE_URL／E2E_API_URL；安裝 tests/package-lock.json 的依賴後執行。

```powershell
deno check supabase/functions/dispatch-push/index.ts scripts/generate-vapid.ts
deno test supabase/functions/dispatch-push/security_test.ts
```

SQL 排他約束、row locks、RLS／grants 與 API 用真實 PostgreSQL 驗證。Supabase 上游 Google Auth／Storage／push mock 不能作為正式 SLA，新報告明示各自範圍。

## 推播與圖資

```powershell
deno run --allow-write scripts/generate-vapid.ts .local/vapid-private.json
```

VAPID 私密 JSON 放 Supabase dispatch-push Secret VAPID_KEYS_JSON；另設 VAPID_SUBJECT、DISPATCH_API_KEY（與後端 Supabase server key 相同）、DISPATCH_SECRET。後端設定 VAPID_PUBLIC_KEY、相同 DISPATCH_SECRET、PUSH_DISPATCH_ENABLED=true。函式採 server-only apikey＋dispatch secret 雙重驗證，verify_jwt=false 不代表開放匿名派送。

DISPATCH_SECRET 是自行產生的隨機共享密鑰：

```powershell
.venv/Scripts/python.exe -c "import secrets; print(secrets.token_urlsafe(32))"
```

輸出同時填入後端 `.env` 與 Edge Function 同名 Secret。開發環境且 PUSH_DISPATCH_ENABLED=false 可留空；正式設定必須完整。worker outbox 保證持久、失敗重試及 lease 恢復；provider／裝置三秒延遲须真實驗收。

Storage room-maps 是 private bucket，僅接受 ≤2MB PNG/WebP；管理員 API 回短效 signed URL。無校方圖資時顯示同源 SVG 示意圖及持續可見的文字位置，2 秒失敗降級。示範位置需校方確認後更新 location_verified。

## 部署與維運

前端獨立 npm ci／npm run build，再交付 build 產物。compose 的 FRONTEND_BUILD_DIR 可指定路徑，預設同層 `../frontend/build`；後端映像不包含前端原始碼、tests 或 secrets。

後端 `.env` 設 ENVIRONMENT=production、DEMO_DATA=false、HTTPS FRONTEND_ORIGIN／SUPABASE_URL、受限 DB 連線、推播設定及 APP_DOMAIN；確認 DNS 與防火牆後執行：

```powershell
docker compose up --build -d
```

Caddy 管理 TLS、HTTP redirect HTTPS 及 HSTS。API 只在私有 network，Uvicorn 只信任指定 Caddy proxy。SvelteKit build 產生精確 hash CSP；Caddy header 僅加入相容 document／framing 規則，新增 script-src／default-src header 須允許相同 bootstrap hashes。Docker、真憑證與 Google OAuth 仍須外部驗收。

GET /api/health 檢查 DB readiness；監控 5xx／409、API max／p95、pending outbox 年齡、push_dispatch_failed 與 push_emission_budget_exceeded。升級前備份 DB；回復應用映像不能自動回滾 SQL。正式唯讀 smoke 使用 HTTPS TEST_API_URL 與專用校園 Google borrower token，執行 `python -m scripts.verify_supabase`；仍須另跑 staging 100 人負載及實機推播。
