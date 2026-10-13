# 真實 Supabase／Google 的本機串接

2026-10-13：使用者已決定暫緩正式部署，目前只串接真實 Supabase 與本機前後端。Docker、正式網域及 HTTPS 全面驗收仍為日後工作。

## 連線與資料庫

1. 在既有 Supabase 專案的 Connect 面板選 Session pooler、5432；Windows／IPv4 網路不使用僅提供 IPv6 的 direct endpoint。主機與使用者名稱必須取自專案，不猜測 region。asyncpg 的 prepared statements 不使用 transaction pooler 6543。
2. DATABASE_MIGRATION_URL 供初次 schema／hook 建立；DATABASE_URL 用受限的 application LOGIN，具 ntou_backend membership。帳密只存忽略的私有設定，不進 Git。
3. 新資料庫可執行 scripts/bootstrap_db.py，不加 --demo-seed。已有 profiles 時工具拒絕重設；升級需另外審核增量 SQL。
4. 啟用 RLS、確認 owner policies、private room-maps bucket 與 notifications Realtime publication。校方教室資料尚待確認，禁止把測試 seed 冒充正式課表。

## Google provider

- Google Cloud 建立／使用 Web OAuth client；Google 授權 redirect URI 取 Supabase provider 頁顯示的完整 callback。Google client ID／secret 只保存在 Supabase provider 設定，不進前端、Git 或報告。
- 目前專案的 Google redirect URI 為 `https://akubvdmdincihwqgqqpb.supabase.co/auth/v1/callback`；JavaScript origins 為 `http://127.0.0.1:5173` 與 `http://localhost:5173`，origins 不含 `/auth/callback` 路徑。
- 個人 Google Cloud 專案使用 External audience，維持 Testing；僅要求 `openid`、`userinfo.email`、`userinfo.profile`。依 [Google 官方說明](https://developers.google.com/identity/protocols/oauth2/production-readiness/overview)，僅基本身分 scopes 有 Testing allowlist 例外；校方 Workspace 管理員仍可阻擋外部應用。`Internal` 只適用於同一 Workspace 組織，不能以此替代應用程式的學校信箱限制。
- Client ID 是 Google 產生的 `.apps.googleusercontent.com` 識別碼，Client Secret 是 OAuth 密鑰，兩者都不是 Google 帳號／密碼。不要啟用付費試用、不要加入 Gmail／Drive scopes；不需要先部署網站即可測試本機 OAuth。
- Supabase 啟用 Google，停用 email/password、phone、anonymous 及其他登入 provider；啟用 public.ntou_google_signup_gate 的 Before User Created hook。
- Site URL 使用 http://127.0.0.1:5173；Redirect URLs 明列 http://127.0.0.1:5173/auth/callback，以及需要時的 localhost callback。日後正式部署改為核准 HTTPS URL。
- 用真實 @email.ntou.edu.tw 帳號驗證 Google 授權、PKCE、首次基本資料、session refresh、停權與 borrower/admin 邊界。帳號名稱、密碼、token 不記錄在公開測試報告。

資料庫憑證可由 Dashboard → Database → Settings → Download certificate 取得，存入私有檔案，並設定 DATABASE_SSL_CA_FILE。遠端資料庫在開發模式也驗證 TLS 與 hostname，不透過停用 SSL 驗證解決憑證錯誤。連接 pooler 時 pg_stat_ssl 描述的是 pooler 到內部 PostgreSQL 的連線；本機到 pooler 的 TLS 需檢查 client transport。

## 金鑰相容性與推播

SUPABASE_SECRET_KEY 優先於 legacy SUPABASE_SERVICE_ROLE_KEY；公開 key 不能填 sb_secret_ 或 service_role JWT。新版 opaque API keys 放 apikey，只有使用者 JWT／legacy JWT key 作 Bearer。

Edge Function 的 DISPATCH_API_KEY 必須等於後端 worker 使用的 server key。切換新舊 key 時一併更新；新版 Edge runtime 使用 SUPABASE_SECRET_KEYS.default，legacy worker 需顯式設定相符 DISPATCH_API_KEY。VAPID／DISPATCH_SECRET 只存私有設定。

推播仍需 Edge Function 部署與實機驗收；本機 unit／fixture 成功不代表已投遞真實裝置。

## 驗證範圍

本機透過真實上游的連線與 Google 登入驗證，必須與 tests-only fixture 分開記錄。正式 scripts/verify_supabase.py 要求 HTTPS，不能以 localhost HTTP 結果假冒正式驗收。尚未完成的外部步驟保留為待驗，不改寫為已成功。

## 2026-10-13 已確認狀態

- 真實 Supabase 已建立 9 張應用資料表、RLS、註冊限制函式、private room-maps bucket 與 notifications publication。
- 應用使用獨立 ntou_api LOGIN／ntou_backend membership；沒有 superuser、bypass RLS、建立 DB 或角色的權限。owner 連線另存私有 migration 設定。
- 本機到 Session pooler 為 TLS 1.3，憑證及 hostname 驗證通過；FastAPI health、教室查詢與公開設定皆回 200，DEMO_DATA=false。
- 未匯入 Demo seed；目前正式教室清單為空，須提供校方確認資料。
- Google 串接階段後端 218 項 pytest／前端 45 項測試通過；本輪加入教室匯入與憑證更新回歸後，完整後端 273 項及前端 46 項全通過，包含 100 筆申請／核准的唯一核准回歸。Google provider 設定與本人學校帳號的完整登入均已實際驗證。
- Dashboard 已確認 Before User Created hook 為 ENABLED，函式 `public.ntou_google_signup_gate`；Site URL 與兩個精確本機 callback 已儲存。
- Google Cloud 專案 `ntou-classroom-reservation` 已建立品牌「海大教室借用平台」、三個基本身分 scopes 及 Web client；使用者已將憑證儲存於 Supabase。Dashboard 與真實 Auth settings API 已確認 Google 啟用，Email、anonymous 與其他 provider 停用；nonce checks 與 email 要求維持啟用。
- 本人已完成學校 Google 授權、PKCE 回送及首次基本資料；首次驗收的身分 API 為 `onboarding_required:false`、borrower、`verified:true`。重新導航後 session 仍有效，自己的資料與借用歷史 API 回 200，當時借用人呼叫管理員 API 回 403。
- 資格查詢重複的資料庫往返已減少，角色初始化及完整連線 reset 維持隔離；每次請求仍向 Supabase 驗證，並讀取最新停權資料。`Server-Timing` 只揭露後端總耗時，mock timers 驗證正常與錯誤回應。
- 本機 FastAPI → Sydney Supabase 實測後端資格處理為約 768–1105ms，仍未達 NFR-006 的 500ms；本次五筆樣本不能視為正式壓測或 SLA。原要求保留，正式部署需評估服務區域並重新量測。詳見 `reports/real-google-acceptance.json`。
- 自然 token refresh、真實裝置推播、正式教室資料、正式 HTTPS 與完整雲端壓測仍待驗收；不以 session persistence 或本機 fixture 結果替代。
- 依使用者指示先停止本機 NFR-006 的反覆優化，500ms 目標及未達標紀錄保留；其他交付繼續進行。
- 正式教室清單的離線 CSV 驗證／owner 交易匯入工具已建立，操作見 [IMPORT_ROOMS.md](IMPORT_ROOMS.md)。校方資料尚未提供，真實 Supabase 未寫入任何示範教室或課程。
- 前端補上 `TOKEN_REFRESHED` 的事件回歸，驗證新的 Bearer、後端身分重驗及同一使用者通知保留。這仍不等於真實 session 自然到期更新驗收。
- 使用者已指定目前登入的學校帳號為首位管理員。受信任 owner 交易先確認本人 UUID、Auth／profile 一致、Google 身分、已驗證且未停權及無既有管理員，再將該帳號的 role 改為 admin，同交易記錄 `first_admin_granted`。提交後確認管理員 1 名、對應操作紀錄 1 筆，profile 其他欄位及應用 DB 角色權限保留；沒有以 metadata 或公開 API 升權。
- 刷新後實際 `/api/me` 回 admin，管理員使用者 API 回 200，`/admin` 顯示管理台。學校資料仍待蒐集，教室維持 0 間，完整真實借用／鑰匙／停權流程仍未驗收。匿名驗收結果見 `reports/first-admin-acceptance.json`；目標 UUID 與操作用 owner 設定只留在私有本機檔案。

## 真實本機登入驗收

1. Google provider 啟用且 Email／其他 provider 關閉後，在 `http://127.0.0.1:5173/login` 用本人學校 Google 帳號登入；Google 授權與 callback 必須在同一瀏覽器、同一 origin 完成，才保留 PKCE verifier。
2. 新使用者應進入 `/account` 完成姓名、證號、聯絡電話與系所；註冊前 identity 為 `onboarding_required:true`，`/api/me` 拒絕未完成資料的帳號。
3. 註冊成功應為 borrower、`verified:true`；重新載入、登出後再登入，個人資料仍存在；borrower 呼叫管理員 API 應回 403。
4. session persistence 與 token refresh 分開驗收。重新載入僅驗證 persistence，須觀察真實 refresh grant 與後續成功的 identity 請求，才能記錄 refresh 通過。公開報告不得包含帳號個資或 token。
5. 取消 Google 授權應能重試，callback code／錯誤參數不留在網址。正式教室資料仍為空，因此此階段不宣稱正式預約生命週期或 HTTPS 部署驗收通過。
