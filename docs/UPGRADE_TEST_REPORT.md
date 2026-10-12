# v1.1 Google OAuth／雙 repository 測試報告

驗證日期：2026-10-12（Asia/Taipei）。需求來源：[SPEC.md](SPEC.md)。[2026-10-11 報告](TEST_REPORT.md)保留原密碼／名冊版本的歷史證據，不能作為新版登入驗收。

## 結果與證據

新版 Python 完整套件 **192 項通過、0 failures／errors／skipped**，JUnit 耗時 **66.123 秒**。真實 TCP HTTP **7 組 × 100 個請求，共 700 次**，每組的最慢回應均符合本機門檻。100 個獨立 PostgreSQL 連線確認 **99 個交易同時等待鎖**後才提交 winner，結果 **1 筆核准、99 筆 SQLSTATE 23P01**。

最終穩定前端版本的 Chrome E2E **31 項全通過**，有8張新版成功畫面；原生 Caddy 2.10.2 的最後 production build **7條路由啟動成功、0 pageerror、bootstrap exact hash 允許、任意 inline script 阻擋**。兩個匿名 private route 均顯示登入提示，不顯示私密紀錄或管理操作。前端 **34 項 Vitest／5檔通過、Svelte check 0 error／0 warning、Prettier／build＋CSP 通過、npm audit 0**。[前端驗證紀錄](../reports/upgrade-frontend-validation.json)另記錄Auth callback／logout／新登入競爭的unit範圍。

新版 runtime artifacts 的 UTC 2026-10-11T21:42–21:43 等同臺北 **2026-10-12 05:42–05:43**；最後 E2E 為 **2026-10-12 11:01**，Caddy 為 **11:02**。日期依實際時區轉換辨識，所有歷史未加 upgrade 的 artifacts 不作新版通過證據。

| 分層                        | 通過數／範圍 | 證據                                                                                                            |
| --------------------------- | ------------ | --------------------------------------------------------------------------------------------------------------- |
| API／真實 PG 整合           | 81           | [upgrade-pytest.xml](../reports/upgrade-pytest.xml)                                                             |
| 並行／直接 SQL              | 3            | [API 指標](../reports/upgrade-concurrency-api.json)、[SQL 指標](../reports/upgrade-concurrency-direct-sql.json) |
| Worker／真實 outbox         | 6            | 同一份 JUnit；包含兩個 worker 處理 200 筆、provider hang timeout／retry                                         |
| Auth unit                   | 59           | 同一份 JUnit；校園 Google policy、同 Bearer get-user 前提、OAuth AMR                                            |
| HTTPS deployment smoke unit | 9            | 同一份 JUnit；script 邊界與輸出隔離，沒有連線正式服務                                                           |
| 規則／安全 unit             | 13＋21       | 同一份 JUnit                                                                                                    |
| 真實 localhost TCP          | 700          | [upgrade-live-http-100-users.json](../reports/upgrade-live-http-100-users.json)                                 |

這是案例與需求追蹤，**未量測行數／branch coverage 百分比**。前端／Edge／dependency／格式檢查由各負責代理執行，最終證據於本報告更新時收斂。[新版工具檢查紀錄](../reports/upgrade-tooling.json)記錄後端 Prettier／Ruff check、Caddy validate、Deno 2.9.6 兩檔 check／兩項安全測試、npm audit 0、Python lock 36 套件 OSV findings 0；不代表 Docker／TLS／GitHub CI／真 OAuth 已驗收。

## 環境、資料與隔離

| 環境         | 實際版本／規模                                                                                                |
| ------------ | ------------------------------------------------------------------------------------------------------------- |
| OS／硬體     | Windows 11 10.0.26200；Intel Core i5-10500H，6 核／12 threads；RAM 7.83 GiB                                   |
| Python／後端 | Python 3.12.10；pip 26.2.1；FastAPI 0.143.0；Starlette 1.7.0；asyncpg 0.32.0；pytest 9.1.1                    |
| 資料庫       | PostgreSQL 17.11，loopback 127.0.0.1:55432，max_connections=120                                               |
| Node／瀏覽器 | Node 24.20.0；npm 11.19.0；Playwright 1.64.0；Chrome 154.0.8037.98；Asia/Taipei                               |
| 前端         | Svelte 5.57.2；SvelteKit 2.70.3；Vite 7.3.7；supabase-js 2.117.3；GSAP 3.15.0                                 |
| 格式工具     | Prettier 3.9.10、prettier-plugin-svelte 4.1.1；Ruff 0.17.0                                                    |
| TCP fixture  | 100 個不同借用人＋1 admin、4 間教室、100 pending；100 個獨立 httpx clients                                    |
| E2E fixture  | 初始 102 profiles（101 borrower＋1 admin）＋Auth-only 身分103；101 violations；首次建檔完成後新增一個 profile |

只允許 loopback 的 `ntou_integration`、`ntou_load`、`ntou_e2e` reset，三者分別供 pytest、TCP、browser 使用。測試設定 `_env_file=None`，不讀取真實 `.env`。DSN 與 fake session 檔放在已忽略的 `.local`，不列印、不提交 Git。factory 的 session 檔標示 `test_only=true`，與 fake upstream 預先登錄的同一 token／user 相符；應用程式沒有 test login route。

PostgreSQL、交易、advisory／row lock、grant／restricted role、GiST 排他約束真實執行。一般整合 API 使用 ASGITransport；TCP 與 Chrome 使用真正的 loopback HTTP。Auth get-user／Google 授權／Storage／Edge 上游是 tests-only HTTP fixture，**未以真實 Google／Supabase 環境執行驗收**。

業務時鐘固定 2026-10-12 10:00 臺北時間；timeout 策略用可注入 clock／fake timers。性能用 `perf_counter()`、Node `performance.now()`、Chrome protocol timing，不以固定業務時鐘計時。下方小數三位是報告格式，不代表 OS 發送精度或同一 1 ms 的封包抵達證據。

## Google 身分、首次建檔與安全回歸

- `/auth/identity` 先驗證同一 Bearer 的 Supabase get-user，再限制 confirmed、非 anonymous、可信 app_metadata provider／providers 僅 Google、identities 僅 Google、identity email_verified 為 boolean true 且與 email 相同、精確 `@email.ntou.edu.tw`。已由 upstream 驗證的 token 還須 sub 相同、AMR 含 OAuth；password／token_refresh-only AMR 均拒絕。
- 新 Google 身分無 profile 回 `onboarding_required=true`；完成姓名／電話／系所／證號後建立 verified borrower。email／UUID 只取已驗證身分，額外 role／verified／suspended／id／email／password 均422，錯誤不回顯輸入。
- 注入真正 PostgreSQL trigger，分別讓 profile INSERT 與 audit INSERT 失敗，斷言整個交易 rollback、原 Auth identity 保留、同 session 重試只產生一個 profile／audit。只呼叫 upstream GET user，沒有 signup、password grant 或 Auth DELETE，也無舊版人工孤兒對帳流程。
- 同 UUID 的20個並行建檔全部返回同 profile、DB只有一筆 profile／register audit；不同 UUID 同時競爭同證號為201／409各一。既有 admin／suspended profile 重送原資料，不覆寫角色、停權或姓名。
- `/me/verify` 要求本人已填證號，無名冊查詢；runtime role 無權讀舊名冊。舊 `/auth/login` 對合法、空白或 malformed JSON 均403，不解析密碼、不呼叫上游、不回顯聯絡資訊。onboarding 的 account／IP 限速、429／Retry-After、hash key 與60秒窗口恢復仍有真實 DB 回歸。
- 每次 reset 套用 `supabase/auth-hook.sql`，integration 執行 `supabase/tests/auth-hook.sql` 的真實 SQL assertions：合法 Google／精確網域可建立、domain bypass／mutable metadata／anonymous拒絕，function invoker、PUBLIC／anon／authenticated／ntou_backend 不可執行。正式 Dashboard hook 啟用與真 Supabase role 行為另待驗收。

Browser fixture 檢查 Google provider、hd 校園 picker hint、PKCE S256；authorize 回302至正式 callback，token exchange 驗證 auth_code 與 verifier 的 SHA256 base64url 等於原 challenge，再交付 factory 內同一 fake session。這可驗證真實 supabase-js 的 PKCE 與應用流程，無法證明 Google 外部 consent、校方 OAuth 設定或正式 JWT 簽章。

## 真實 TCP 100 使用者負載

每組100個不同身分，依序執行，總700次。session 準備由 ignored fixture 檔完成，沒有呼叫舊密碼入口。計時從 request 發出至完整 response 收到；p95 採 nearest-rank，門檻對每個 request 的 max 判斷。

| 場景                     | count／status |  p50 ms |  p95 ms |  max ms | 門檻 ms | dispatch spread ms |
| ------------------------ | ------------- | ------: | ------: | ------: | ------: | -----------------: |
| 時段可用性               | 100／200      | 590.142 | 620.162 | 640.516 |    2000 |             83.573 |
| 七日課表                 | 100／200      | 131.778 | 148.106 | 149.070 |    2000 |             34.904 |
| 借用申請                 | 100／201      | 464.565 | 576.961 | 589.686 |    2000 |             29.849 |
| 違規資格                 | 100／200      | 168.974 | 198.885 | 202.505 |     500 |             24.592 |
| 本人歷史                 | 100／200      | 221.608 | 275.189 | 289.547 |    5000 |             23.987 |
| 身分／權限刷新           | 100／200      | 145.637 | 176.731 | 177.721 |    5000 |             21.951 |
| 99 borrower＋1 admin切頁 | 100／200      | 173.998 | 209.552 | 210.801 |    5000 |             26.615 |

上述全通過，只證明本機一次100-clients burst。不是100真人瀏覽器、長時間 soak、遠端 Auth／網路或大量歷史資料的容量保證。

## 100 個核准競爭者

ASGI API先釋放100個不同人的申請，全部201；再釋放100個核准請求，**1×200、99×409**，DB為1 approved／99 pending。同 request_id 的100次重送只產生一筆。部分 overlap拒絕、相鄰時段兩筆都可核准。

| API 場景 |  p50 ms |  p95 ms |  max ms | dispatch spread ms |
| -------- | ------: | ------: | ------: | -----------------: |
| 100申請  | 734.988 | 848.654 | 853.742 |            121.353 |
| 100核准  | 317.074 | 385.202 | 391.292 |             33.316 |

直接SQL取得100條不同 backend PID 的連線，winner UPDATE 保持未提交；observer查 pg_stat_activity，觀察其餘99個 wait_event_type=Lock，才提交winner。**1成功／99排他失敗**；失敗交易 rollback、finally關閉所有連線。dispatch spread **63.811 ms**，p50／p95／max **436.226／444.729／452.910 ms**，包含刻意hold，不是API SLA。這證明100個交易確實重疊，沒有以Python mutex或task數推論，也沒有宣稱同1ms抵達。

## Chrome／GSAP／Caddy 回歸

[upgrade-e2e-browser.json](../reports/upgrade-e2e-browser.json)的31項檢查全部通過。Chrome使用實際supabase-js，Google authorize／token HTTP由fixture攔截；FastAPI與PG為真正TCP／交易。除了PKCE成功／四類錯誤／首次建檔及reload外，完成借用人鍵盤登入、immediate申請、本人歷史、管理員核准／交付鑰匙／歸還、本人通知及停權後禁止申請。borrower管理導覽隱藏，直接admin頁拒絕；guest `/reservations`／`/admin` 不停留loading、有登入CTA、無private rows／admin tabs。

375／768／1440px首頁與管理台均無整頁橫向溢出；七日課表可由鍵盤切換，手機可選單日。初始102 profiles逐頁可讀，包含原100筆上限之外的borrower；違規使用者與紀錄獨立20筆分頁，已選UUID在next／back仍可見且不變。101 violations可讀到第六頁最舊未結案紀錄，顯示joined借用人姓名／證號，375px可結案且真實PATCH回resolved=true。Auth-only103最後完成onboarding，建立同UUID verified borrower；post body只有name／phone／department／institutional_id。

地圖資源Chrome protocol實測 **3.986 ms**；從navigation開始至marker可見的Node monotonic耗時 **850.203 ms**，都<2000ms。圖資request abort仍有具體樓層／位置文字。Vitest另外驗證1999／2000ms timeout、遲到忽略與unmount；固定business clock不作效能計時。

GSAP normal preference觀察到 **148次transform／opacity style變化**，reduced-motion **0次**；兩種模式各做3次快速來回SPA導覽，最後heading無殘留inline transform／opacity、沒有detached node動畫更新或pageerror。這驗證實際browser行為，不是FPS或正式裝置動畫效能測量。

兩項review回歸也使用真business API：availability response在route.fetch後暫停，改input再放行，caption與room-link仍指向原submit時段，下一次查詢才換新時段；同context真正第二tab從Google A切至B，B歷史先載入，再釋放held A response，畫面始終不顯示A的private purpose。路由未以fixture偽造業務資料，也未提供production test endpoint。

| 成功畫面            | artifact                                                                                                                                                                       |
| ------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| 首頁desktop／mobile | [desktop](../reports/upgrade-e2e-home-desktop.png)、[mobile](../reports/upgrade-e2e-home-mobile.png)                                                                           |
| 教室／地圖手機      | [room](../reports/upgrade-e2e-room-mobile.png)、[map fallback](../reports/upgrade-e2e-map-fallback-mobile.png)                                                                 |
| 管理／違規分頁      | [admin](../reports/upgrade-e2e-admin-desktop.png)、[violations desktop](../reports/upgrade-e2e-violations-desktop.png)、[mobile](../reports/upgrade-e2e-violations-mobile.png) |
| 新Google身分建檔    | [onboarding completed](../reports/upgrade-e2e-onboarding-completed.png)                                                                                                        |
| 正式build＋Caddy    | [production home](../reports/upgrade-caddy-home-desktop.png)                                                                                                                   |

另以獨立 focused capture 擷取新 Google UI，共5張；使用重新建立的專用 E2E fixture 與實際 app 渲染，沒有覆寫上面31項／8張的完整 E2E 報告。首次建檔表單停在送出之前，校園 email 唯讀、姓名／證號／電話／系所四欄可見，desktop1440px／mobile375px均無整頁溢出。[capture紀錄](../reports/upgrade-auth-ui-captures.json)：[Google login](../reports/upgrade-auth-login-desktop.png)、[取消callback](../reports/upgrade-auth-callback-cancel-desktop.png)、[失效code](../reports/upgrade-auth-callback-invalid-code-desktop.png)、[onboarding desktop](../reports/upgrade-auth-onboarding-desktop.png)、[mobile](../reports/upgrade-auth-onboarding-mobile.png)。這組同樣只mock外部Google／Supabase，後端TCP／PG真實；畫面個資都是測試fixture。

原生Caddy使用production Caddyfile的headers／fallback，只改loopback HTTP origin／bind、frontend sibling build root、API address並關閉admin endpoint。最後build的 `/`、`/login`、`/auth/callback`、`/account`、`/reservations`、`/admin`、room deep-link均200且真正SPA hydration；guest的兩個private routes另驗登入提示／無loading與private controls。meta hash允許框架bootstrap，response CSP禁止framing；任意新inline script實際被阻擋，正常導覽無pageerror。[Caddy browser](../reports/upgrade-caddy-browser.json)、[設定／scope](../reports/upgrade-caddy-validation.json)。這是loopback HTTP，未測正式TLS憑證鏈或Docker。

## 全需求追蹤

「本機通過」只指下列案例與環境；外部gate另列。所有27個FR／FRA／NFR均有本機案例，但正式Auth／推播／雲端效能不能以fixture取代。

| ID      | 結果／證據與限制                                                                                                                                                      |
| ------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| FR-001  | 本機通過：DB admin／borrower、extra role422、runtime不能升權、metadata不授管理權；E2E borrower入口隱藏／directadmin拒絕／guest登入CTA。                               |
| FR-002  | 本機通過：Google onboarding必填／extra拒絕、verified borrower、PG profile／audit rollback重試、同UUID原profile保留admin／停權；Chrome首次建檔＋reload。真Google待驗。 |
| FR-003  | 本機通過：交集equipment、capacity／building、availability overlap／adjacent；held response＋改input的caption／link snapshot browser回歸。                             |
| FR-004  | 本機通過：immediate／scheduled201、100次request_id重送一筆、atomicity；Chrome實際申請及本人歷史。                                                                     |
| FR-005  | 本機通過：approve／reject reason／狀態機／越權403；100approval唯一；Chrome管理員核准。                                                                                |
| FR-006  | 本機通過：admin狀態／停權／恢復、同交易audit、同token重查DB；Chrome管理操作及停權。                                                                                   |
| FR-007  | 本機通過：handed／returned timestamps與actor、非法轉移409；Chrome交付與歸還。                                                                                         |
| FR-008  | 本機通過：owner scope／foreign404、分頁2/1/0／filter／422；Chrome完整紀錄與真secondtab A→B晚到A資料隔離。                                                             |
| FRA-001 | 本機展示通過：SVG／marker／文字／座標／示範標示、Chrome map<2s；校方位置與正式Storage待驗。                                                                           |
| FRA-002 | 本機通過：confirmed／Google-only／boolean verified identity email／exact domain／OAuth AMR＋本人證號；無roster讀取權限或依賴。                                        |
| FRA-003 | 本機部分通過：notification同交易／owner read、outbox retry／lease、200筆雙worker、Chrome補讀；真Realtime／裝置Push待驗。                                              |
| FRA-004 | 本機通過：7日API不洩漏purpose／user，Chrome三寬度／鍵盤／mobile日切換。                                                                                               |
| FRA-005 | 本機通過：3points停權、結案可恢復；101violations API paging／filter與102人UI、selectedUUID維持、手機第六頁最舊紀錄結案。                                              |
| NFR-001 | 本機通過：TCP100availability max640.516ms<2s、Chrome loading結束／results；cloud待驗。                                                                                |
| NFR-002 | 本機通過：TCP100applications全201，max589.686ms<2s；DB冪等性／atomicity。                                                                                             |
| NFR-003 | 本機通過：缺／forged bearer401、無profile／非Google／未確認／metadata不可信／非OAuth AMR403。                                                                         |
| NFR-004 | 本機通過：375／768／1440px首頁／週課表／admin、手機申請／違規結案、鍵盤登入／週切換；未做正式全站無障礙稽核。                                                         |
| NFR-005 | 本機部分通過：真DB durable outbox／lease／retry；hang選1.7s deadline，timer加速10ms且真cancellation。未測正式event→實機<3s。                                          |
| NFR-006 | 本機通過：TCP100eligibility max202.505ms<0.5s；violations partial index；大資料量EXPLAIN待驗。                                                                        |
| NFR-007 | 本機通過：map resource3.986ms、navigation→marker850.203ms，皆<2s；正式Storage／校方圖資待驗。                                                                         |
| NFR-008 | 本機通過：Vitest1999／2000ms／late／unmount、Chrome圖資abort保留文字。                                                                                                |
| NFR-009 | 本機通過：舊password入口403不解析／回顯、四種callback可重試且清URL／憑證、onboarding422／429；真Google密碼／consent UI待驗。                                          |
| NFR-010 | 本機通過：TCP100history／permission／adminnav每筆<5s、真secondtab身分隔離；cloud100users／soak待驗。                                                                  |
| NFR-011 | 本機部分通過：unsafe URL／TLS config拒絕、HTTPS middleware／HSTS、schema無password、PKCE與Git ignore、最新build Caddy hash／inline阻擋；真TLS／Docker／OAuth待驗。    |
| NFR-012 | 本機通過：API100=1／99，SQL100PID＋99真lockwait=1／99，overlap／adjacent。                                                                                            |
| NFR-013 | 本機通過：borrower所有admin讀寫／圖資403、metadata role無效、foreignnotification404；UI入口隱藏及guest無controls。                                                    |
| NFR-014 | 本機通過：停權commit後同token immediate403、integration monotonic<5s、不核准停權者；Chrome已登入借用人表單隱藏。                                                      |

v1.1額外要求：兩個repo獨立roots／origin／ignore由root驗證，尚無commit／push；Prettier／Ruff與各repo CI設定、34Vitest／check0/0／正式build通過。Google PKCE／回呼／onboarding、GSAP normal／reduced-motion／quicknav清理及built CSP均有新版Chrome證據。Ruff lint範圍E4／E7／E9／F，與formatter需求相符；沒有宣稱全部可選lint規則通過。

## 可重現命令

以下從 **backend repository** 執行；本工作區的 Python runtime 在父目錄 `.venv`。獨立clone可以在backend內建立`.venv`並把命令prefix改成`.venv/Scripts/python.exe`。測試DSN由環境`TEST_DATABASE_URL`或ignored `backend/.local/database.env`提供，內容不能寫進命令列或報告。

```powershell
../.venv/Scripts/python.exe -m pip check
../.venv/Scripts/python.exe -m pytest -q --tb=short --junitxml=reports/upgrade-pytest.xml
```

SQL hook在上述pytest中由`test_auth_hook_sql_and_business_role_permissions`执行。SQL100前先停止本輪live API pool；禁止同時執行兩個schema-reset pytest。TCP factory／runner在不同終端，跑完停止factory再進入browser：

```powershell
../.venv/Scripts/python.exe -m uvicorn tests.harness:load_app --factory --host 127.0.0.1 --port 8003 --no-access-log
../.venv/Scripts/python.exe -m tests.live_load --base-url http://127.0.0.1:8003
```

Browser的API、Vite、runner分別開終端：

```powershell
../.venv/Scripts/python.exe -m uvicorn tests.harness:e2e_app --factory --host 127.0.0.1 --port 8004 --no-access-log
```

```powershell
Set-Location ../frontend
$env:API_PROXY_TARGET='http://127.0.0.1:8004'
npm run dev -- --port 5173 --strictPort
```

```powershell
$env:E2E_API_URL='http://127.0.0.1:8004'
node tests/e2e.cjs
```

前端命令從frontend，後端格式／Edge命令從backend：

```powershell
npm run format:check
npm run check
npm test
npm run build
npm audit --audit-level=low
```

```powershell
npm run format:check
../.venv/Scripts/ruff.exe format --check .
../.venv/Scripts/ruff.exe check .
deno check supabase/functions/dispatch-push/index.ts scripts/generate-vapid.ts
deno test supabase/functions/dispatch-push/security_test.ts
```

Caddy先`validate --config deploy/Caddyfile --adapter caddyfile`；loopback browser preview只替換domain／frontend build root／API address，保留production headers／fallback。preview啟動後：

```powershell
$env:PRODUCTION_BASE_URL='http://127.0.0.1:8081'
node tests/production_browser.cjs
```

## 尚未完成的正式驗收

1. **未以真實Google／Supabase環境執行驗收**。沒有執行`scripts/verify_supabase.py`的正式HTTPS唯讀smoke；9項unit僅驗證script輸入、拒絕錯身分／錯provider／nonHTTPS、輸出隔離。正式smoke需要專用borrower Google access token，會核對API identity、Supabase get-user同UUID／Google、舊login403／borrower admin403及三條讀取延遲；不查password hash，也不能替代100人負載。
2. 正式Dashboard Google provider／redirect allowlist／before-user-created hook、外部Google consent／PKCE／refresh、真JWT驗簽、auth.users FK／auth.uid RLS、Realtime與Storage private bucket尚未驗收。工作區真`.env`未讀，不推斷憑證是否存在。
3. 真TLS憑證鏈／HTTPS redirect／Docker與remoteCI、cloud100users／soak、大資料量、跨網路WebPush實機<3s仍待驗收。local Caddy CSP通過也不代表TLS上線。
4. 校方教室正式座標／圖資未核實；新版Google不需舊roster，但本人證號的權威校務核對不在本輪範圍。

## 本輪問題與修正回歸

首次新版Chrome捕獲直接callback在router初始化前呼叫replaceState，導致loading不結束；修正在afterNavigate完成後處理URL與登入。取消／缺code清理本project PKCE storage；四類callback在最後完整E2E通過。pending callback／logout／新callback的SDK副作用由generation／串行Auth寫入保護，前端專用unit34項包含這些競爭。

review發現舊availability結果與新input時段失配、跨tab身分改變保留page-local歷史，source改採submitted snapshot與keyed owner／role route、lifetime／owner／latest request guard；兩項真business API browser回歸通過。F2修正後匿名loading曾不結束，root補ready邊界，最後完整E2E的兩個guest檢查及latest-build Caddy同時通過。

測試工具跟著實際DOM調整GSAP account導覽locator；新增private fixture紀錄後，管理員操作用唯一purpose定位所要核准的紀錄，避免first-row順序影響。最後穩定source重建專用E2E DB、重新跑完整31項，再以同一最後build跑7-route Caddy；沒有重跑未變更且已通過的192 pytest／700TCP／SQL100。歷史failure圖片僅作問題紀錄，review使用本報告列出的新版成功captures。

最後Auth flow補強後，cancel／no-code會在既有Auth mutation queue等pending exchange的SDK session寫入結束，再由current generation清理；無pending的穩定session保留，較新登入不受舊cleanup影響。前端新增3項race unit後為34項全通過；同一最後build重新執行31項完整E2E與7-route原生Caddy均通過，backend API未變，因此192 pytest／700TCP／SQL100沒有白跑。額外5張Google UI圖保留10:48的獨立擷取，F3未更動DOM／文案／tokens，與新8張E2E及1張Caddy共14張成功UI證據。
