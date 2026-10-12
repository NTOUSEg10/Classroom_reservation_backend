# 真實 Supabase／Google 的本機串接

2026-10-13：使用者已決定暫緩正式部署，目前只串接真實 Supabase 與本機前後端。Docker、正式網域及 HTTPS 全面驗收仍為日後工作。

## 連線與資料庫

1. 在既有 Supabase 專案的 Connect 面板選 Session pooler、5432；Windows／IPv4 網路不使用僅提供 IPv6 的 direct endpoint。主機與使用者名稱必須取自專案，不猜測 region。asyncpg 的 prepared statements 不使用 transaction pooler 6543。
2. DATABASE_MIGRATION_URL 供初次 schema／hook 建立；DATABASE_URL 用受限的 application LOGIN，具 ntou_backend membership。帳密只存忽略的私有設定，不進 Git。
3. 新資料庫可執行 scripts/bootstrap_db.py，不加 --demo-seed。已有 profiles 時工具拒絕重設；升級需另外審核增量 SQL。
4. 啟用 RLS、確認 owner policies、private room-maps bucket 與 notifications Realtime publication。校方教室資料尚待確認，禁止把測試 seed 冒充正式課表。

## Google provider

- Google Cloud 建立／使用 Web OAuth client；Google 授權 redirect URI 取 Supabase provider 頁顯示的完整 callback。Google client ID／secret 只保存在 Supabase provider 設定，不進前端、Git 或報告。
- Supabase 啟用 Google，停用 email/password、phone、anonymous 及其他登入 provider；啟用 public.ntou_google_signup_gate 的 Before User Created hook。
- Site URL 使用 http://127.0.0.1:5173；Redirect URLs 明列 http://127.0.0.1:5173/auth/callback，以及需要時的 localhost callback。日後正式部署改為核准 HTTPS URL。
- 用真實 @email.ntou.edu.tw 帳號驗證 Google 授權、PKCE、首次基本資料、session refresh、停權與 borrower/admin 邊界。帳號名稱、密碼、token 不記錄在公開測試報告。

## 金鑰相容性與推播

SUPABASE_SECRET_KEY 優先於 legacy SUPABASE_SERVICE_ROLE_KEY；公開 key 不能填 sb_secret_ 或 service_role JWT。新版 opaque API keys 放 apikey，只有使用者 JWT／legacy JWT key 作 Bearer。

Edge Function 的 DISPATCH_API_KEY 必須等於後端 worker 使用的 server key。切換新舊 key 時一併更新；新版 Edge runtime 使用 SUPABASE_SECRET_KEYS.default，legacy worker 需顯式設定相符 DISPATCH_API_KEY。VAPID／DISPATCH_SECRET 只存私有設定。

推播仍需 Edge Function 部署與實機驗收；本機 unit／fixture 成功不代表已投遞真實裝置。

## 驗證範圍

本機透過真實上游的連線與 Google 登入驗證，必須與 tests-only fixture 分開記錄。正式 scripts/verify_supabase.py 要求 HTTPS，不能以 localhost HTTP 結果假冒正式驗收。尚未完成的外部步驟保留為待驗，不改寫為已成功。
