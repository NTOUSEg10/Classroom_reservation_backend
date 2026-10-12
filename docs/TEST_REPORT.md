> 歷史報告：以下是 2026-10-11 的密碼／名冊版本與拆分前路徑。2026-10-12 已改為 Google-only 並拆成兩個 repository；本文件保留當時證據，不能當成新版登入／部署驗收。新版結果見 UPGRADE_TEST_REPORT.md 與 UPGRADE_AUDIT_REPORT.md。

# 測試報告

更新時間：2026-10-11T23:30:28+08:00（臺北時區）。需求來源：[SPEC.md](SPEC.md)。本報告記錄本機實測與尚未驗收的外部服務，不把 mock 結果視為正式環境 SLA。

## 結果與環境

最終 Python 完整套件 **89 項通過、0 失敗、0 error、0 skipped**，耗時 **41.504 秒**。前端 **14 項 Vitest／4 個檔案通過**，Svelte check **0 error／0 warning**，正式 build 成功；Deno strict typecheck 通過、**2 項安全測試通過**。Chrome E2E **20 項檢查全通過**。真實 TCP HTTP 的 **7 組 × 100 個請求共 700 次**全部符合各自本機門檻。

| 環境               | 實際版本／規模                                                                                |
| ------------------ | --------------------------------------------------------------------------------------------- |
| 作業系統／硬體     | Windows 11 10.0.26200；Intel Core i5-10500H，6 核心／12 執行緒；RAM 7.83 GiB                  |
| Python／後端       | Python 3.12.10；pip 26.2.1；FastAPI 0.143.0；Starlette 1.7.0；asyncpg 0.32.0；pytest 9.1.1    |
| 真實資料庫         | 本機 PostgreSQL 17.11，127.0.0.1:55432；max_connections=120                                   |
| 前端／瀏覽器       | Node 24.20.0；npm 11.19.0；Playwright 1.64.0；Chrome 154.0.8037.98；Asia/Taipei               |
| Edge Function 檢查 | Deno 2.9.7；只執行型別檢查與安全 unit test，未部署到 Supabase                                 |
| HTTP 負載資料      | 100 個不同借用人、1 個管理員、4 間教室、100 筆 pending 申請；100 個獨立 httpx clients         |
| DB 應用權限        | 測試 pool 使用 SET ROLE ntou_backend；100 個 SQL 競爭者使用 100 個不同 PostgreSQL backend PID |

Python 組成：API／整合 41 項、並行 3 項、worker 6 項、Auth unit 5 項、規則 unit 13 項、安全 unit 21 項，共 89 項。Vitest 包含 3 項時段／時區、3 項地圖 timer、5 項登出失敗回歸及 3 項跨頁借用人選擇回歸。這是需求／案例覆蓋，不是行數或 branch coverage 百分比；本次未量測程式碼 coverage 百分比。

`backend/requirements.lock` 已與本機 `pip freeze` 的 36 個套件逐項一致，`pip check` 通過。lock 記錄這個 Windows 環境；其他平台須另驗證解析結果。OSV 查核這 36 個套件未回報已知漏洞，npm audit 回報 0 漏洞；這些結果不等同沒有安全風險。[Python 查核紀錄](../reports/python-dependencies.json)、[前端驗證紀錄](../reports/frontend-validation.json)。

## 隔離與測試邊界

- reset 硬限制 loopback 且資料庫名稱只能為 `ntou_integration`、`ntou_load`、`ntou_e2e`；分別供 pytest、TCP 負載、瀏覽器使用。每項整合測試重建專用 schema。測試設定以 `_env_file=None` 排除工作目錄 `.env`，不得使用正式 DB。
- PostgreSQL、交易、row lock、RLS／grant、GiST 排他約束都是真實執行。一般整合 API 使用 ASGITransport；負載與瀏覽器使用真正 localhost TCP FastAPI HTTP。
- Supabase Auth／Storage／Edge Function 上游 HTTP 是 **tests/ 專用 fixture**。Fake token 與測試使用者僅驗證應用合約，不證明正式 JWT 簽章、email 寄送、Supabase 網路延遲或 Auth 密碼儲存。
- 業務日期固定於 2026-10-11 10:00 臺北時間；timeout 邊界用 fake clock／fake timers。性能使用 `time.perf_counter()`、Node `performance.now()` 或 Chrome protocol timing，不使用固定日期的時計量效能。
- 負載是單次本機 100 使用者 burst，並非 100 個真實瀏覽器、長時間 soak、正式雲端網路或大量歷史資料下的容量保證。

## 真實 TCP 的 100 使用者負載

API server 使用 `tests.harness:load_app` 與獨立 `ntou_load`。每位使用者先獨立登入；100 次登入是準備步驟、沒有納入並行 SLA。下列每一列都對 **每個 response 的 max** 驗證門檻，不以平均值代替。

單位：毫秒。p95 為排序後 nearest-rank 95 百分位，計時自每項 request 發出至完整 response 收到。

| 場景                                 | 請求數 |     p50 |     p95 |     max | 門檻 | dispatch spread | 結果 |
| ------------------------------------ | -----: | ------: | ------: | ------: | ---: | --------------: | ---- |
| 時段可用性查詢                       |    100 | 392.587 | 415.843 | 418.887 | 2000 |          34.076 | 通過 |
| 七日課表查詢                         |    100 | 112.826 | 128.820 | 129.942 | 2000 |          28.590 | 通過 |
| 借用申請                             |    100 | 354.579 | 427.719 | 440.607 | 2000 |          25.062 | 通過 |
| 違規／資格查詢                       |    100 | 149.045 | 179.679 | 186.209 |  500 |          28.213 | 通過 |
| 本人歷史資料載入                     |    100 | 188.716 | 232.764 | 242.695 | 5000 |          20.321 | 通過 |
| 身分／權限重新查詢                   |    100 | 123.021 | 139.585 | 140.059 | 5000 |          18.907 | 通過 |
| 99 位借用人與 1 位管理員切頁資料查詢 |    100 | 153.737 | 172.370 | 173.001 | 5000 |          18.770 | 通過 |

所有場景均 100 次預期回應：申請為 201，其餘為 200。原始數據與 UTC 時間：[live-http-100-users.json](../reports/live-http-100-users.json)。Realtime／Auth 真實外網成本未包含，雲端部署仍須重測。

## 100 筆核准競爭與冪等性

API 整合競爭先同時送出 100 位借用人的同房同時段申請，全部 201，再釋放 100 個管理員核准請求：**1 次 200、99 次 409**，DB 為 **1 筆 approved、99 筆 pending**。同 request_id 的 100 次重送只有一筆 DB 紀錄。部分重疊時段拒絕，相鄰時段兩筆均可核准。

| ASGI API 場景 |  p50 ms |  p95 ms |  max ms | dispatch spread ms |
| ------------- | ------: | ------: | ------: | -----------------: |
| 100 次申請    | 594.112 | 695.766 | 705.244 |             56.227 |
| 100 次核准    | 323.513 | 374.790 | 390.115 |             26.949 |

直接 SQL 測試取得 **100 條獨立連線／100 個不同 PID**。第一筆 UPDATE 保持在**未提交交易**；觀察連線查 `pg_stat_activity`，確認其餘 **99 條連線的 wait_event_type 都為 Lock**，才提交第一筆。最終 **1 筆成功、99 筆 SQLSTATE 23P01 排他約束失敗**；輸掉的交易全部 rollback，所有連線在 finally 關閉。這項測試證明 100 個競爭交易實際重疊，不依賴 Python mutex，也不只靠 task 數量推論。

直接 SQL 的 dispatch spread **33.486 ms**，p50／p95／max 分別為 **205.941／209.522／213.592 ms**。這些耗時包含刻意等待 99 條連線阻塞的交易 hold，不能當 API latency SLA。

所有 barrier 都是在同一 event-loop tick 釋放等待者；OS／scheduler 實際發出仍有上表 spread。**沒有宣稱 100 個封包在同一個 1 ms 抵達**，精度到小數三位只代表報告格式。原始證據：[concurrency-api.json](../reports/concurrency-api.json)、[concurrency-direct-sql.json](../reports/concurrency-direct-sql.json)。

## Browser、通知與部署設定

Chrome 實際完成借用人鍵盤登入、立即申請、本人歷史、管理員核准、交付鑰匙、歸還鑰匙、本人通知及停權後禁止再次申請。一般借用人的管理台導覽不存在，直接開 `/admin` 顯示拒絕；管理員可見入口。375／768／1440 px 的首頁和管理台無整頁水平溢出；七日課表可由鍵盤切換，375 px 可按日期切換顯示日。

同源 SVG 資源實測 **11.335 ms**；從房間頁導覽開始至 marker 可見的實際 monotonic 耗時 **1006.577 ms**，均 <2000 ms。地圖 request abort 時保留完整文字位置；Vitest 驗證 1999 ms 尚未降級、2000 ms 降級、遲到圖資不覆蓋備案及卸載後不更新。E2E 無 pageerror。原始證據：[e2e-browser.json](../reports/e2e-browser.json)，本輪有 7 張畫面擷取：原有五張基準畫面，以及違規分頁 desktop／mobile 各一張。

審計回歸使用 **102 個 profile（101 borrower＋1 admin）與 101 筆違規**。實際 UI 逐頁可讀取所有 102 人；第 100 筆之外的借用人可加入違規選擇。切換使用者下一頁／上一頁後已選擇 UUID 與可見選項維持一致；使用者與違規各自獨立分頁，每頁 20 筆。101 筆違規依 created_at DESC,id 穩定分頁，最舊未結案資料位於第六頁，顯示 joined 借用人姓名／證號，在 375px 手機可結案並收到 resolved=true。API 整合另驗證 101 筆歷史的 total／limit／offset／user_id filter、無遺漏或重複、結案後可恢復停權；Vitest 有 3 項選擇保留回歸。

註冊 profile／audit 交易寫入失敗時，**不再 DELETE Auth identity**，保留新建或既有未確認帳號，且不覆寫其原密碼。記錄不含 email、UUID、密碼的 signup_profile_pending_reconciliation 警示；未確認帳號重試可使用相同 UUID 建立 profile。兩種情況均有真實 PostgreSQL trigger failure／rollback／retry 回歸；Auth HTTP 仍為測試 fixture，正式身分服務對帳另需驗收。

Worker 的 6 項測試檢查狀態與 notification 同交易 durable 儲存、私密 provider headers、失敗退避、不正確 ack 不標示送達、30 秒 lease 過期恢復，以及兩個 worker 對 **200 筆通知、每個 batch 100 筆**各自 claim，總共 200 次、無重複。卡住 provider 的回歸使用真實 task cancellation，但把 timeout **加速成 10 ms**並斷言選定 budget 為 **1.7 秒**；失敗記錄 TimeoutError／重試時間，另一筆正常通知仍成功。這不證明外部裝置 3 秒內收到推播。

Native Caddy 2.10.2 已驗證 production Caddyfile 可解析。新 build 由 kit.csp hash mode 產生 script-src self＋精確 bootstrap hash；build 自動斷言檢查 meta、hash相符及禁止 script unsafe-inline／unsafe-eval。Caddy header 僅保留 frame-ancestors／base-uri／form-action，與 HTML 的 fetch directives 相容。以 production 設定副本只替換 loopback 網址／build root／API address，並限制 listener 為 127.0.0.1，實際 `/`、`/login`、`/account`、`/admin`、教室詳情五個路徑皆 200，內容為已 build 的 `200.html` fallback。Chrome 另確認五個路徑均成功執行 Svelte 啟動程式、顯示主標題且無 pageerror；精確 bootstrap hash 可執行，透過 DOM 插入的任意 inline script 被 CSP 阻擋。首頁截圖已檢查。[caddy-browser.json](../reports/caddy-browser.json)、[caddy-home-desktop.png](../reports/caddy-home-desktop.png)。**沒有執行 Docker 或取得真實 HTTPS 憑證**。[caddy-validation.json](../reports/caddy-validation.json)。

## 全需求追蹤矩陣

「本機通過」只代表本報告環境；外部待驗收項目不算完成正式服務驗收。

| ID      | 狀態                           | 目前證據／未完成範圍                                                                                                                                                                                                                                                   |
| ------- | ------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| FR-001  | 本機通過                       | borrower/admin 約束、禁止 privilege payload、偽造 metadata 不升權、受限 DB role 無法改 role；E2E 借用人隱藏入口且直接頁面拒絕、admin 可見                                                                                                                              |
| FR-002  | 本機通過                       | 欄位／聯絡資料／校園 email／證號驗證、無名冊提前 403、成功只建立 unverified borrower、重送409、profile 寫入失敗保留新建／既有未確認 Auth identity，不刪除、不改原密碼；記錄 signup_profile_pending_reconciliation，未確認帳號重試建立相同 UUID profile；上游為 fixture |
| FR-003  | 本機通過                       | 時段可用性、設備交集、部分重疊及相鄰查詢；真實 TCP 100 查詢均 <2s                                                                                                                                                                                                      |
| FR-004  | 本機通過                       | immediate/scheduled 均 pending，順序重送及 100 次同 request_id 僅一筆                                                                                                                                                                                                  |
| FR-005  | 本機通過                       | approve/reject、拒絕理由必填、非法狀態轉換及越權拒絕；E2E 核准                                                                                                                                                                                                         |
| FR-006  | 本機通過                       | 狀態機、停權／恢復、狀態 audit 內容及 audit 不可刪；E2E 停權                                                                                                                                                                                                           |
| FR-007  | 本機通過                       | handed_at／returned_at 與 actor 真實 DB 斷言，禁止跳狀態／先歸還；E2E 交付及歸還                                                                                                                                                                                       |
| FR-008  | 本機通過                       | 本人歷史與外人隔離、3 筆資料分頁2/1/0、status filter、無重複及邊界422；E2E 完整歷史                                                                                                                                                                                    |
| FRA-001 | 本機展示通過；校方資料待確認   | 同源 SVG、marker、樓層／座標／文字及示範標示；目前 seed 位置未經校方確認，真實 Storage 私有 bucket 待驗收                                                                                                                                                              |
| FRA-002 | 本機通過；真實 Auth 待驗收     | 未確認 email、錯證號／名冊拒絕；匹配後 verified；確認狀態是 Auth fixture                                                                                                                                                                                               |
| FRA-003 | 部分，外部待驗收               | durable outbox、本人通知／read ownership、worker retry／lease、E2E 補讀可見；真實 Realtime 及 Web Push 裝置接收尚未驗收                                                                                                                                                |
| FRA-004 | 本機通過                       | 七日 API 只回 approved/checked_out 且不洩露 user/purpose；Vitest 週界限、E2E 三寬度週視圖／手機日切換                                                                                                                                                                  |
| FRA-005 | 本機通過                       | 有效違規3points停權，未結案不能恢復，結案後可恢復／再次申請；101筆API分頁及102人／101違規UI跨頁、保留借用人選擇、手機結案最舊未結案紀錄                                                                                                                                |
| NFR-001 | 本機通過；雲端待驗收           | 真實 TCP 100 availability 每個 <2s；E2E loading 結束與結果；正式網路／資料量待重測                                                                                                                                                                                     |
| NFR-002 | 本機通過；雲端待驗收           | 真實 TCP 100 application 全201、每個 <2s；冪等性資料庫斷言                                                                                                                                                                                                             |
| NFR-003 | 本機通過                       | 未登入／偽造 bearer 401，未 verified／未確認 email 403                                                                                                                                                                                                                 |
| NFR-004 | 本機通過                       | E2E 375/768/1440 px 首頁／週課表／管理台與手機申請，鍵盤登入與週切換；未做全站無障礙正式稽核                                                                                                                                                                           |
| NFR-005 | 部分，裝置待驗收               | durable notification／worker 時限策略與 retry／hang cancellation；沒有真實 Supabase event 到實機收到 <3s 證據                                                                                                                                                          |
| NFR-006 | 本機通過；雲端待驗收           | 真實 TCP 100 eligibility 每個 <0.5s；schema 有未結案 violations partial index；未跑大資料量 EXPLAIN                                                                                                                                                                    |
| NFR-007 | 本機通過                       | 同源地圖資源及 navigation→visible marker 真實計時均 <2s；無外部字型阻塞                                                                                                                                                                                                |
| NFR-008 | 本機通過                       | Browser 圖資 request failure＋Vitest 1999/2000ms timeout、遲到忽略、文字備案                                                                                                                                                                                           |
| NFR-009 | 本機通過；真實 Auth 待驗收     | 精確帳號不存在／密碼錯誤、無姓名／電話洩露、account/IP 429、Retry-After60、60s 後恢復、DB key 僅 hash                                                                                                                                                                  |
| NFR-010 | 本機 API 通過；雲端100人待驗收 | 真實 TCP 100 不同身分，歷史／權限刷新及 99 borrower+1admin 切頁資料均 <5s；未跑100真實瀏覽器／遠端 soak                                                                                                                                                                |
| NFR-011 | 部分，外部待驗收               | 設定拒絕不安全 URL／DB TLS／privileged login name，HTTPS middleware／HSTS、Caddy validate＋實際SPA深連結、public schema 無 password 欄位；真實 Auth bcrypt hash、TLS憑證鏈／redirect及Docker部署未驗證                                                                 |
| NFR-012 | 本機通過                       | API100核准1/99；SQL100 PID、99實際lock waits才commit、1成功99排他失敗；partial overlap拒絕／adjacent兩筆成功                                                                                                                                                           |
| NFR-013 | 本機通過                       | borrower 對管理讀取／停權／違規／核准拒絕／交鑰匙／圖資入口均403，偽造 metadata無效；本人取消及他人通知404                                                                                                                                                             |
| NFR-014 | 本機通過                       | 真實DB停權提交後同一既有 token申請403，unit/integration assert elapsed <5s；禁止核准被停權借用人；E2E 隱藏申請表                                                                                                                                                       |

## 可重現命令

以下命令從專案根目錄執行；DSN 由安全環境或已忽略的 `.local/database.env` 提供，不能寫進命令列。TCP／E2E 用各自專用 DB；**跑 SQL100 前先以 Ctrl+C 停止本輪測試伺服器**，以 max_connections=120 環境避免 pool 佔滿。不得同時執行兩個重建 ntou_integration 的 pytest。

```powershell
$env:PYTHONUTF8='1'
.venv/Scripts/python.exe -m pip check
.venv/Scripts/python.exe -m pytest tests backend/tests -q --tb=short --junitxml=reports/pytest.xml
```

TCP 負載：另開一個終端啟動 factory，再在原終端執行 runner。

```powershell
.venv/Scripts/python.exe -m uvicorn tests.harness:load_app --factory --host 127.0.0.1 --port 8003 --no-access-log
.venv/Scripts/python.exe -m tests.live_load --base-url http://127.0.0.1:8003
```

Browser：API、Vite、runner 分別在三個終端。

```powershell
.venv/Scripts/python.exe -m uvicorn tests.harness:e2e_app --factory --host 127.0.0.1 --port 8004 --no-access-log
```

```powershell
Set-Location frontend
$env:API_PROXY_TARGET='http://127.0.0.1:8004'
npm run dev -- --port 5173 --strictPort
```

```powershell
$env:E2E_API_URL='http://127.0.0.1:8004'
node tests/e2e.cjs
```

前端與 Edge Function：

```powershell
Set-Location frontend
npm run check
npm test
npm run build
npm audit --audit-level=low
Set-Location ..
deno check supabase/functions/dispatch-push/index.ts scripts/generate-vapid.ts
deno test supabase/functions/dispatch-push/security_test.ts
```

Caddy 原設定驗證使用已驗證官方 checksum 的本機 `caddy.exe validate --config deploy/Caddyfile --adapter caddyfile`；深連結使用 loopback preview 設定，詳見 JSON scope。啟動該 preview 後執行 `node tests/production_browser.cjs`，可重測 build 的深連結、bootstrap hash 與 CSP 阻擋；其他網址可用環境變數 PRODUCTION_BASE_URL 指定。安裝 lock 可用 `.venv/Scripts/python.exe -m pip install -r backend/requirements.lock`。

## 未完成驗收與本輪問題紀錄

1. 本輪未以真實 Supabase 環境執行驗收，也未執行 `scripts.verify_supabase`；工作目錄 `.env` 存在不代表已完成連線或驗收，本輪沒有讀取或確認其私密設定。真實 Auth email confirmation／token、bcrypt hash 儲存、Storage private bucket、Realtime 權限與實機 Web Push 尚未驗收。此 smoke 需要專用 borrower token 及唯讀 Auth row 驗證連線，不可用 fixture 報告取代。
2. 尚未取得部署網域／真實 TLS 憑證鏈，也未執行 Docker container 或正式 HTTPS redirect。Caddy config 與本機 HTTP fallback 通過不代表 TLS 上線通過。
3. 校方教室位置／正式名冊尚待匯入、核實。100 人 staging 持續負載、較大資料量及跨網路裝置推播 <3s 尚未建立證據。
4. 一輪完整測試曾因背景 TCP 負載 pool 佔用本機 120 條連線預算，出現 TooManyConnectionsError。停止本輪 idle server 後修正測試的部分連線失敗 cleanup，再完整重跑，全89項通過；沒有提高門檻或減少100條連線。
5. 該次第三方 traceback 曾包含本機測試登入資料；已更換僅限本機的測試密碼，最終報告覆寫為無失敗 XML，後續命令使用 `--tb=short`。DSN／token／hash 未寫入本報告。既有 factory 若仍持有舊 DSN，重跑時應先停止並重建。
6. 自動核准審查拒絕停止／重啟既有測試伺服器的組合指令，只回覆 blocked by policy；本輪改用新埠8003／8004，不需額外權限。Caddy browser probe 已完成，原生 Caddy 已正常停止；本輪 8004 API／5173 Vite session 已由測試 runner 結束，專案 `.local/pgdata` 的 PostgreSQL 亦以 pg_ctl 正常停止。[清理紀錄](../reports/test-validation-status.json)。
