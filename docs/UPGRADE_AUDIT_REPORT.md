# 海大教室借用平台 — Google／雙 repository 升級 Full audit

**Modes:** full（26 canonical dimensions）。

**Date:** 2026-10-12，Asia/Taipei。

**Reviewer:** independent_review；應用程式、設定及測試唯讀，不執行 DB reset／pytest。

**Scope / revision / worktree state:** `C:/Project/ntouse-g10/backend` 與 `C:/Project/ntouse-g10/frontend` 的 first-party source、SQL、設定、scripts、tests、產品與部署文件。兩者各為獨立 Git repository、branch main；`git rev-parse --verify HEAD` 均無 revision，commitHash=null（unborn HEAD），工作檔尚未 commit／push。origin 分別為 Classroom_reservation_backend.git 與 Classroom_reservation_frontend.git；父目錄不是第三個 repository。本文件是新版審查；2026-10-11 的 AUDIT_REPORT／INDEPENDENT_REVIEW 保留為歷史。

<!-- section:executive-summary -->

## 1. Executive Summary

本輪 source trace 確認校園 Google Bearer 先經 Supabase `/auth/v1/user` 驗證，再限制可信 provider／identity、已確認 email、精確網域與同 UUID OAuth AMR。首次登入無 profile 是正常 onboarding；交易 advisory lock、唯一證號、profile＋audit 同交易及原 profile 重送回傳，解除舊版人工 Auth/profile 孤兒補建根因。沒有 Auth signup／DELETE 或 password grant；舊密碼入口固定 403。before-user-created hook 使用 invoker，僅 Auth role 可執行，舊名冊不授 runtime。

目前在本次first-party／本機證據範圍 **0項未解除Confirmed／Suspected finding**。F1查詢snapshot、F2身分owner/role remount＋guest恢復、F3所有取消/無code的SDKmutationqueue收尾、F4 callbackrouter初始化均已由源碼與有意義回歸閉合，保留於fixed ledger。最後Auth-only改動後重新build，34Vitest／31ChromeE2E／nativeCaddy七routes均通過；14張有效原圖由同reviewer檢查，UPGRADE_UI_REVIEW.md為本機rendered scope disposition:ship。

已覆核新版 Python **192 項全通過**（102 unit＋90 API/DB/worker integration）、100 API 核准只有一筆成功、100 條獨立 SQL 連線確認 99 筆在 winner 未提交前等待 lock、以及 700 次真本地 TCP 請求全部符合各自門檻。最後 source api.ts 修改時間10:58:49，E2E生成11:01:20、Caddy11:02:37（Taipei），runtime對應修後build。Auth為tests-only Google upstream fixture；新版31-check E2E全部passed、nativeCaddy七route hydrated且page_errors=[]。不沿用歷史20-pass；F3交錯以模擬實際SDK先persist＋SIGNED_IN時序的34unit補強，沒有把單flowE2E當競爭證明。

正式 Google 授權與 refresh、Dashboard provider/hook、auth.uid RLS／Realtime／Storage、Docker／TLS、Web Push provider／裝置三秒及校方精確圖資仍屬外部驗收 gate。本 reviewer 未讀 `.env`，不推斷憑證是否存在。HTTP fixtures、mock timers 和本地 TCP clients 都不能證明正式雲端 SLA。

<!-- section:score-dashboard -->

### Score Dashboard

| Dimension       | Score | Grade | Coverage | Justification                                                                                            |
| --------------- | ----- | ----- | -------- | -------------------------------------------------------------------------------------------------------- |
| Security        | 8.7   | A     | Medium   | Google-only/least privilege/SDK ownership、OSV36/npm0有源碼與回歸；真Auth/RLS/provider/image未正式驗收。 |
| Stability       | 8.8   | A     | Medium   | 192Python、SQL99lockwait、34Vitest與最終31E2E閉合F1–F4；正式outage/recovery未演練。                      |
| Performance     | 8.5   | A     | Medium   | 700TCP門檻、100API/SQL overlap、realGSAP148changes/reduce0；無cloud/soak/device容量證據。                |
| Testing         | 8.8   | A     | Medium   | 192Python/34Vitest/31E2E、Caddy7routes與14原圖；fixtures邊界明確，真Google/TLS/device仍未測。            |
| Maintainability | 8.7   | A     | Medium   | splitCI/lock/style/secretignore、localownership/queue有局部回歸；無commit/history與長期維運證據。        |
| Design          | 8.8   | A     | Medium   | Auth/profile、DB不變量/outbox、scopedmotion及前端state所有權清楚；visualship限已看包。                   |
| Release         | 8.2   | A     | Medium   | 最後build+Caddy7route/guestCTA/hashCSP；未commit/push、remoteCI/Docker/TLS/Google/rollback未驗收。       |
| Overall         | 8.6   | A     | —        | 七维算術平均60.5/7，四捨五入一位；分數不構成正式發布或SLA認證。                                          |

<!-- section:project-map -->

## 2. Project Map

| Boundary        | Entry and trace                                                                                                                                                       |
| --------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Google session  | frontend login → supabase-js PKCE → `/auth/callback` → exchange → api session／identity stores → FastAPI campus_identity → Supabase get-user → DB profile。           |
| Onboarding      | account form → Register extra=forbid → validated Auth UUID/email → transaction advisory lock → original profile or borrower INSERT＋audit；不查名冊、不改角色／停權。 |
| Public query    | home → availability／schedule → indexed overlap SQL；WeekSchedule、RoomMap／map-loader → SVG／signed map／持續位置文字。                                              |
| Business writes | main → rules／database.transaction → reservation/profile/room locks → schema exclusion／request_id → audit＋notification 同交易。                                     |
| Suspension      | admin profile lock／violation points → new write 重新讀 eligibility；不以過期 session claim 授權。                                                                    |
| Notifications   | durable DB outbox → worker 100 batch／SKIP LOCKED lease → bounded Edge HTTP → owned subscriptions → provider；Realtime＋2s polling 補讀。                             |
| Split release   | frontend 獨立 npm／static build＋CSP hash → backend compose bind FRONTEND_BUILD_DIR → Caddy `200.html` fallback／private FastAPI。                                    |
| Test seams      | backend harness 僅 loopback named test DB reset，restricted-role pool＋HTTP Auth fixture；E2E／production_browser 連獨立 frontend URL/build，無生產 test-login。      |

**Commands and outcomes:** 本 reviewer 使用 `rg --files --hidden`、PowerShell source reads、Git roots/branch/HEAD/origin/check-ignore 讀取及官方 Auth hook／JWT／PKCE 文件；沒有執行 DB tests、啟動 server、改 app 或讀 secrets。本 reviewer 已在最終source/evidence閉合後先Prettier格式化兩份review文件，再執行full report_lint，exit0；另人工核對26mode/零統計/7score平均/UI五段契約。新版 artifacts 的 UTC 2026-10-11T21:42 等同 Taipei 2026-10-12；按實際版本與生成時間辨識，歷史未加 upgrade 的 reports 不作新版驗證。

**Inventory and exclusions:** first-party 範圍包括兩個 repo 的 runtime entry、routes/components/stores、SQL/bootstrap/hook/seed、worker/Edge、CI/deploy、manifests/locks與測試。排除 `.git`、`.local`、`.venv`、node_modules、`.svelte-kit`、build、cache、binary assets、實際 `.env` 與 reports 生成物；report artifacts 僅作驗證證據。只為釐清 callback 時序抽讀安裝版本 auth-js 的 `_exchangeCodeForSession`，不是第三方全集審計。其餘未逐行審第三方實作、容器 image／OS、真服務 Dashboard／政策及真裝置。

### Verified upgrade runtime evidence

| Artifact                                    | Independently read result                                                                                                                                            | Boundary                                                                                             |
| ------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------- |
| reports/upgrade-pytest.xml                  | 192 tests、0 failures/errors/skips，66.123s；API81、concurrency3、worker6、Auth59、smoke9、rules13、security21                                                       | PostgreSQL/role/constraints 真執行；Supabase get-user/Storage/Edge 是 fixture。                      |
| reports/upgrade-concurrency-api.json        | 100×201；核准1×200＋99×409、approved_rows=1；applications max853.742ms、approvals max391.292ms                                                                       | ASGI API、100不同 users；dispatch spreads121.353/33.316ms。                                          |
| reports/upgrade-concurrency-direct-sql.json | 100獨立 connections/PIDs；99 blocked before winner commit；1 approved＋99 SQLSTATE23P01、approved_rows=1                                                             | explicit_transaction_overlap=true；spread63.811ms。max452.910ms含刻意hold，不是API SLA。             |
| reports/upgrade-live-http-100-users.json    | 7×100=700真TCP；availability640.516ms、week149.070、applications589.686、eligibility202.505、history289.547、permission177.721、adminnav210.801（每組max）全部過門檻 | 100 clients/101profiles/4rooms/100pending；spread21.951–83.573ms，不稱同1ms發送、100真人或正式容量。 |
| reports/upgrade-frontend-validation.json    | format pass、check0/0、34 Vitest/5files pass、build/hash pass、npm audit0                                                                                            | 34Vitest最終檢查已記錄；Caddy/完整E2E亦為guest修後版本。                                             |
| reports/python-dependencies.json            | 36 locked Python packages、OSV findings[]                                                                                                                            | 查核時已知advisories；不是第三方全集安全認證。                                                       |
| reports/upgrade-e2e-browser.json            | 31checks全部passed；querysnapshot/cross-tab/guest/callback/keyboard/RWD/realGSAP/業務lifecycle/onboarding                                                            | Authupstreamfixture；F3交錯已34unit驗證；Auth5＋full8＋Caddy1均已看；UI判定獨立記錄。                |

reports/upgrade-tooling.json已記錄Deno2.9.6 strictcheck/2securitytests、backend格式/Ruff/36OSV/npm0及Caddy2.10.2validate；upgrade-caddy-browser.json為本版builtSPA真Chrome七route/hashCSP證據。真Google/TLS/Docker/Dashboard/devicepush仍未正式驗收。

<!-- section:coverage -->

### Coverage Matrix

| Dimension            | Coverage     | Evidence inspected                                                            | Exclusions / limits                                                     |
| -------------------- | ------------ | ----------------------------------------------------------------------------- | ----------------------------------------------------------------------- |
| accessibility        | Medium       | semantic forms／labels／alerts、app.css、WeekSchedule、callback/onboarding    | 31E2E鍵盤/RWD375/768/1440已讀；screen reader/zoom未測，14張UI包已覆核。 |
| ai-safety            | Not assessed | runtime routes、manifests、worker／Edge                                       | 無 AI/model/RAG/tool 執行 surface。                                     |
| architecture         | High         | two repo boundaries、auth/main/database/rules、api/motion、compose            | 正式網路與故障演練未測。                                                |
| backend-api          | High         | campus_identity/current_user、Register、onboarding／login routes、test_api    | 真上游 response contract待正式驗收。                                    |
| code-consistency     | Medium       | Prettier/Ruff/.editorconfig、Python/TS/CSS patterns、CI                       | 格式化／check正在完成，未以個人偏好評分。                               |
| comment-coverage     | High         | trust-before-claims、advisory lock、lease/reset comments、SPEC/README         | 不以 comment 數量計分。                                                 |
| concurrency          | High         | onboarding advisory、profile locks、GiST、worker lease、192tests與API/SQL100  | 99 lock waits證明交易重疊；無正式cloud/長期soak。                       |
| configuration        | Medium       | Settings、env examples、Supabase config/hook、CI/Caddy/compose                | 真env／Dashboard／憑證未讀。                                            |
| cost                 | Medium       | pools／timeouts／pagination／100 batch drain／SVG                             | 無雲端帳單、quota、長期 object lifecycle。                              |
| data-integrity       | High         | schema constraints、transaction、profile/audit retry、noAuthmutation tests    | 真 auth.users FK與 migration/restore演練未測。                          |
| dependency-weight    | Medium       | two manifests/locks、GSAP core-only、Docker copy                              | 新 build/network尺寸尚待；非第三方全集。                                |
| design               | High         | auth/profile 分離、rules／outbox／SQL不變量、motion action                    | F1/F2/F4新E2E閉合；F3queue已34unit/新runtime閉合，視覺另review。        |
| documentation        | Medium       | SPECv1.1／prompt／READMEs／PRODUCT／contracts、smoke                          | 舊報告明確歷史；新test／design文件正在同步。                            |
| fallback             | Medium       | HTTP errors、map timer／text、local logout、callback retry UI                 | 新callbackerror/mapfallback/guestCTA通過；真upstreamoutage未演練。      |
| frontend-state       | Medium       | api stores／SDK callback、home/reservations/account/routes/motion             | F3交錯已34unit補強；F1/F2已過回歸，全route matrix非穷舉。               |
| maintainability      | Medium       | module ownership／style／CI／scripts／tests／docs                             | 無commit/changehistory，新state fixes尚未验证。                         |
| observability        | Medium       | health、audit／outbox、worker log/error class、redacted smoke                 | production alerts/dashboards 未接入；不能讀真logs。                     |
| performance          | Medium       | 700TCP max門檻全pass、indexes/pools、100batch、160–280ms motion               | 新realGSAP/reduce/cleanup已過；雲端soak/provider未驗。                  |
| privacy              | Medium       | server identity、owner SQL/RLS、redacted errors、PKCE URL removal、ratehashes | F2已解除，F3暫存/持久state已閉合；retention/device policy未指定。       |
| release              | Medium       | independentGit/CI/manifests、compose/build path、CSP、bootstrap/hook          | unborn HEAD、remote CI、realGoogle／Docker／TLS未驗收。                 |
| security             | Medium       | Googleonly/sub/amr、invoker grants、SSRF/upload/TLS／CORS guards              | F3本地storage交錯已修；真Auth/RLS/provider/Storage未測。                |
| stability            | Medium       | atomic onboarding／timeouts／worker lease／fallback／state machine            | F1/F2/F4閉合；F3已34unit閉合；192Python/31E2E通過。                     |
| supply-chain         | Medium       | fixed packages/locks、SHA actions、Deno lock、OSV36零finding／npm0初版        | image/signing/SBOM未測；不是全集安全認證。                              |
| testing              | Medium       | 102unit＋90DB/API/worker全pass、34Vitest、E2E31pass/source                    | F3剩餘交錯已34unit驗；真Google/TLS/device另驗。                         |
| testing-authenticity | High         | resetguard、FakeSupabase、live/E2E/SQLbarrier、smoke scope                    | 明示mock，不當Google／SLA認證。                                         |
| type-safety          | High         | Pydantic forbiddenextras/bounds、UUID/enums、TS types／Deno strict            | frontend api<T>是type assertion，remote contract非runtime schema驗證。  |

### Requirement traceability

全 FR/FRA/NFR 為目標；source trace 與測試 source 是審計證據，新版 runtime pass 僅在最終 artifacts 覆核後列入。

| Requirement             | Trace                                                                                 | Current limit / risk                                                                |
| ----------------------- | ------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------- |
| FR-001                  | DB role CHECK/default、current_admin、frontend admin nav                              | 真Auth/RLS未正式驗收。                                                              |
| FR-002                  | Google identity→Register四欄→UUID/email server-owned→advisory transaction／retry      | F4已新E2E/Caddy閉合，F3已SDK交錯回歸；onboarding/identity192tests及31E2E通過。      |
| FR-003                  | availability overlap／filter、home query、WeekSchedule                                | F1snapshot新E2E已解除；正式房間資料未核實。                                         |
| FR-004                  | create_reservation、immediate/scheduled、request_id replay                            | 100applications201、max853.742ms；申請成功不等於核准。                              |
| FR-005                  | admin approve/reject理由／state／audit                                                | 192tests＋E2E審核/交付/歸還通知通過；正式現場另驗。                                 |
| FR-006                  | status machine、suspend/resume／points、boundedusers/violationspagination             | 正式管理流程未驗收。                                                                |
| FR-007                  | hand/return timestamp＋actor、legal transitions                                       | 真鑰匙工作現場未驗收。                                                              |
| FR-008                  | server-ownedhistory＋limit/offset                                                     | F2 cross-tab＋late-ownerresponse新E2E已解除；真DBowner/分頁通過。                   |
| FRA-001                 | SVG pin/code/constantlocation／demo label／coordinates                                | 校方精確圖資待核實。                                                                |
| FRA-002                 | schoolGoogle identity、6–16位證號、自填資料、verify本人證號                           | v1.1取消roster；格式不證明證號所有權。                                              |
| FRA-003                 | transaction通知→Realtime/poll／lease worker→Edge→push                                 | 真Realtime/provider/device未驗收。                                                  |
| FRA-004                 | public redacted7day schedule、mobile dayselector                                      | 31E2E鍵盤切週視圖、手機按日及375/768/1440 RWD通過。                                 |
| FRA-005                 | activepoints＋profilelock＋suspend/resume gate                                        | points/profilelock integration通過；eligibility100responses max202.505ms。          |
| NFR-001                 | availability/schedule SQL、loading UI                                                 | TCPavailabilitymax640.516ms、week149.070ms；F1 UI snapshot回歸pass。                |
| NFR-002                 | idempotentreservation／transaction                                                    | TCP100apps max589.686ms；ASGI100apps max853.742ms，皆<2s。                          |
| NFR-003                 | verifiedcampusGoogle＋DBverified/activechecks                                         | no-profile onboarding正常200；borrowrequiresprofile。                               |
| NFR-004                 | responsive CSS／semantic form/weekly mobile                                           | 14張新desktop/mobile/Auth/Caddy原圖已看；RWD31E2E375/768/1440pass。                 |
| NFR-005                 | 100batchdrain／1s poll／1.7s bounded request、durable retries                         | <3s真正端到端provider/device尚未驗收。                                              |
| NFR-006                 | partialactiveviolationsindex＋points_for                                              | TCP100eligibility max202.505ms <500ms；正式資料規模未測。                           |
| NFR-007                 | sameorigin SVG／numericmarker                                                         | 新SVG3.986ms/marker850.203ms <2s；officialmap未核實。                               |
| NFR-008                 | 1999/2000ms／error/late resultwatchMap＋visibletext                                   | fake timers證明邏輯，不是網路SLA。                                                  |
| NFR-009                 | v1.1 Google-only取消平台密碼案例；login403、callbackretryerrors、不echoPII            | Google端密碼/取消授權需真OAuth驗收。                                                |
| NFR-010                 | fixed100clients／boundedpool／liveTCP tool                                            | TCP100history/permission/admin max289.547/177.721/210.801ms；非100實體browser。     |
| NFR-011                 | nopasswordmodel／PKCE／no-secretclientconfig、TLSguard／Caddy/CSP                     | Google／realTLS/container/remoteCI未驗收；F3已關閉。                                |
| NFR-012                 | GiST `[)` exclusion＋roomlock、independentSQL100 waiters test                         | API1成功99×409、SQL1成功99×23P01；99waits證明overlap，不宣稱1ms同步。               |
| NFR-013                 | current_admin＋borrower cancellationownerexception                                    | 192tests的borrower/anon/偽role入口回歸通過；正式權限設定另驗。                      |
| NFR-014                 | writes重新查profilelock／suspended/points、無roleclaimcache                           | 已登入token停權後新申請403與<5s回歸通過；freshread不靠roleclaim。                   |
| Upgrade: Git／style     | twoGit roots/main/origins、Prettier/Ruff pin/checkCI、secretignores                   | HEADnull/noauthor/no push；格式/Ruff/Deno/npm/OSV及Gitignores已驗，remoteCI未執行。 |
| Upgrade: Google／motion | PKCEcallback/onboarding／policy tests、motionmatchMedia scope/revert／visibledefaults | F3storage交錯已閉合；realGSAP148styles/reduce0、三輪cleanup、Caddy7routes已過。     |

<!-- section:statistics -->

### Finding Statistics

| Severity | Count | Confirmed | Suspected |
| -------- | ----- | --------- | --------- |
| Critical | 0     | 0         | 0         |
| High     | 0     | 0         | 0         |
| Medium   | 0     | 0         | 0         |
| Low      | 0     | 0         | 0         |
| Info     | 0     | 0         | 0         |
| Total    | 0     | 0         | 0         |

只計尚未解除root causes；歷史finding、外部待驗收及同因跨维度不重複計數。

<!-- section:top-risks -->

## 3. Top Risks

無尚未解除的code finding；以下是正式發布前的coverage gates，不計入finding數：

1. 真Google/provider/hook/get-user/refresh、Supabase auth.uid RLS/Realtime/Storage尚未正式驗收；HTTPS唯讀smoke未對真服務執行。
2. Docker、TLS憑證鏈、remoteGitHubActions、migration/backup/restore/rollback及長期cloud/soak未驗收。
3. 真provider/裝置推播三秒與校方精確房間/樓層/座標資料待正式環境驗證。

<!-- section:findings -->

## 4. Detailed Findings

本次已審範圍沒有尚未解除的finding。下列是已修原因與回歸證據；正式服務未執行的驗收是coverage limit，沒有捏造成程式bug或count中的Info。

### Fixed and verified in this upgrade

本表不是尚未解除 finding，不含 machine finding/field markers；source修正與新31-check E2E逐項對照，沒有沿用歷史圖/數字。

| ID / original priority | Original trigger and impact                                                                                                                                 | Current fix evidence                                                                                                                                                                                                                                                     | Regression evidence                                                                                                                                                                                                                                                                  |
| ---------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| F1 / Medium            | availability await期間編輯但未送出，舊server結果被標為新時段/room link                                                                                      | frontend/src/routes/+page.svelte:40 immutable snapshot、:56params、:71queried/roomLink同源                                                                                                                                                                               | upgrade-e2e-browser.json Delayed availability preserves submitted time and room-link snapshot passed；tests/e2e.cjs使用延遲回應及未提交欄位編輯。                                                                                                                                    |
| F2 / Medium            | 跨分頁換帳號，page-local history/eligibility/created/admin/forms仍屬上一人；晚response可覆蓋新人                                                            | frontend/src/routes/+layout.svelte:116按AuthUUID/admin-role key remount、callback例外；reservations:33generation／:58active+owner commit；admin同guard。root補guest else loading=!ready，登入empty state可恢復                                                           | 同JSON cross-tab account change＋previous owner late response passed；/reservations及/admin guest login prompt、無private rows/actions兩項passed；UI account/room局部state由同key生命週期清。                                                                                        |
| F3 / Medium            | 修前SDK晚saveSession/SIGNED_IN越過logout/newflow；最後殘餘是sidebar離開pendingcallback再back無code，新intent未等舊storagewrite；reload可恢復supersededtoken | api.ts:38callbackSessionPending區分待完成flow與原有效session；:41mutationqueue；:309capturepending、:314queue、:315/324currentgen cleanup；:389finally及:435logout清flag。取消/no-code等pendingSDK收尾後清本projecttoken；更晚login不被舊cleanup、無pending原session保留 | reports/upgrade-frontend-validation.json 34Vitest/5files通過；api.test.ts:536cancel/no-code兩case defer SDK先save＋SIGNED_IN再resolve、:574更晚callback保留；既有logout/newcallback/newredirect/identityfailure仍過。最後31E2E＋Caddy7route針對此新build再過，不把單flow當race證明。 |
| F4 / High              | 修前onMount在DEVrouter未started時replaceState throw，callback停loading（installedKit:2558/744；歷史upgrade failure）                                        | callback:13afterNavigate、:17await complete、:19replaceState，activeunmountguard避免late goto/error                                                                                                                                                                      | 新E2E cancel/invalid-code/missing-verifier/no-code均pass；callbackfocused五項pass；upgrade-caddy-browser.json七routes hydrated、page_errors=[]、hashbootstrap允許、任意inline禁止。證明本地建置/CSP，不代表TLS/真Google。                                                            |

<!-- section:accessibility -->

## Accessibility

**Coverage:** Medium。**Evidence inspected:** labels／原生button、skiplink、alerts/status、WeekSchedule／app.css、callback/account。**Exclusions / limits:** 31E2E鍵盤及375/768/1440已驗，14張UI包已覆核；未screenreader/200%zoom。

Google單一動作、唯讀email、可重試callbackerror降低首次操作歧義；reduced-motion不隱藏控件。F1結果誤標已由submitted snapshot解除，避免可理解性與room link失配。

<!-- section:ai-safety -->

## AI safety

**Coverage:** Not assessed。**Evidence inspected:** manifests、runtimeAPI／routes、worker/Edge。**Exclusions / limits:** 沒有model、agent、RAG、embedding或tool execution；開發文件提到AI skills不等於產品AI surface，無AI測試宣稱。

<!-- section:architecture -->

## Architecture

**Coverage:** High。**Evidence inspected:** twoGit roots、app layers、api/motion、compose、SPEC。**Exclusions / limits:** 正式network未實測。

FastAPI為唯一業務寫入口，Authidentity由Supabase擁有、profile由DB擁有，前端session／identity與UIstate須明确失效（F2/F3）。splitCI不依賴父repo；前端build由顯式bind供Caddy。

源碼 trace：`compose.yaml:4`以backend根build，:36 bind显式FRONTEND_BUILD_DIR、:40 create_host_path=false；`deploy/Dockerfile:5`僅runtime app/worker；`app/main.py:117`依production設定在lifespan啟動outbox worker，不需要第二個漏配compose服務。bootstrap `scripts/bootstrap_db.py:29`拒絕既有profiles、套schema及Auth hook，沒有部署reset。

<!-- section:backend-api -->

## Backend API

**Coverage:** High。**Evidence inspected:** main/auth/models/rules、newtest_api、smoke。**Exclusions / limits:** 真上游Auth/Storage未驗收。

identity無profile200；register只收四欄、serveremail/UUID，重試回原profile；login403且不parsepassword。各owner/admin入口查DB角色，querylimit1–100，HTTP錯誤中文且不回傳上游body。

<!-- section:code-consistency -->

## Code consistency

**Coverage:** Medium。**Evidence inspected:** `.editorconfig`／Prettier／Ruff／package scripts／CI及Python/TSpatterns。**Exclusions / limits:** reports/upgrade-tooling.json backendPrettier/Ruff過，frontendformat/check0/0過；不以偏好猜問題。

使用者已選雙引號/80/LF，CI採check，不自動改PR；SQL/Caddy不交語意不支援的formatter。無因個人命名偏好產生finding。

<!-- section:comment-coverage -->

## Comment coverage

**Coverage:** High。**Evidence inspected:** validatedBearercLAIMS、onboarding advisory、lease/reset safety、README/SPEC。**Exclusions / limits:** 無history可判斷多年stalecomment。

comments說明先驗token再讀AMR、無row時序列化重試、I/O不持DBlock、testreset白名單；不是單純重述語法。舊版報告已標歷史，不以舊comment當新版驗收。

<!-- section:concurrency -->

## Concurrency

**Coverage:** High。**Evidence inspected:** advisoryonboarding、profile/reservation/roomlocks、GiST、request_id、workerlease、upgradeAPI/SQL100 artifacts。**Exclusions / limits:** 本地PG/fixture；正式network/soak未測。

同AuthUUID的profile建檔與audit原子；不同UUID同證號由UNIQUE防守。核准roomlock＋exclusion雙層，停權與申請共用profilelock。F1/F2/F3已修的frontendasyncstate競態不同於DBmutex失效，兩者各有回歸。

<!-- section:configuration -->

## Configuration

**Coverage:** Medium。**Evidence inspected:** Settings、envexample、Supabase config/hook、compose/Caddy/CI。**Exclusions / limits:** actualenv、DNS/cert/Dashboard未讀。

production驗HTTPS、DBTLS／restrictedlogin／demo=false／必要secrets；API信任固定Caddyproxy，localhealth例外限制loopback。Supabase config停用email/sms/anonymous/manual linking、Googlesecret取env；Dashboard啟hook仍為正式gate。

拆分回歸已實作source修正：`deno.json:3`明確nodeModulesDir=none，避免新backend/package.json令Deno隱含manual而依賴另一repo node_modules；CI:53仍從backend根strictcheck兩檔。`supabase/config.toml:4`site_url127.0.0.1、:5兩個exact127/localhost callback與`.env.example:6`origin127一致，README明示兩個origin不能互換；未讀改實際.env。Caddy APP_DOMAIN是compose必填環境，不把缺值解析失敗當production設定bug。

<!-- section:cost -->

## Cost

**Coverage:** Medium。**Evidence inspected:** pool20、timeouts、boundedpages/worker、signedmapcache、sameoriginSVG。**Exclusions / limits:** 無bill/quota/长時資料量。

沒有AI或maps tile付費呼叫；outbox失敗backoff上限60s、HTTP有界。圖資覆寫會留下舊Storageobject，正式資料保存/lifecycle尚需營運設定，不因示範規模猜測已發生成本事故。

<!-- section:data-integrity -->

## Data integrity

**Coverage:** High。**Evidence inspected:** schema／transaction/onboarding、failedprofile/auditretry、FK/UNIQUE/exclusion。**Exclusions / limits:** 真auth.users／DBrestore未測。

serverownedemail/UUID、borrowerdefault與原profile重試不覆寫admin/suspension。profile/audit同交易，暫時失敗留下可正常重試Googleidentity；沒有跨服務delete補償，舊F3根因解除。bootstrap拒絕既有profiles，不reset部署資料。

<!-- section:dependency-weight -->

## Dependency weight

**Coverage:** Medium。**Evidence inspected:** manifests/locks、GSAPcoreimport、buildCSPscript、DockerCOPY。**Exclusions / limits:** 新bundle/networkprofile待覆核。

新增GSAP是明示需求，統一action而非每頁獨立依賴；沒有ScrollTrigger/付費map/font服務。後端image只copyruntime，formatter/testdeps不進應用程式source。

<!-- section:design -->

## Engineering design

**Coverage:** High。**Evidence inspected:** auth/profileboundary、rules/database/outbox/motion、principles。**Exclusions / limits:** 本機視覺ship另見UPGRADE_UI_REVIEW.md；正式驗收不在capture證據內。

F1/F2已局部修；F3剩餘分支已沿現有queue修復，不需重寫。Googleidentity和profile分離符合正常onboarding；資料庫持有核准不變量；motionaction封裝scoped lifecycle。main較大但有可辨endpoint與統一helpers，行數不是finding。

<!-- section:documentation -->

## Documentation

**Coverage:** Medium。**Evidence inspected:** SPECv1.1、prompt、twoREADMEs、PRODUCT/contracts、verify_supabase。**Exclusions / limits:** 新test/designartifacts尚在同步。

SPEC先寫policy修訂，指出證號格式不是所有權、Google端密碼不由平台處理；clone/relativebuildpath與head狀態清楚。smoke真get-user比較profileUUID且要求HTTPS/borrower，尚未執行不稱驗收。

<!-- section:fallback -->

## Fallback

**Coverage:** Medium。**Evidence inspected:** map-loader、error/retry UI、localstoragelogout、callbackerrors、APItimeouts。**Exclusions / limits:** 真upstreamoutage／deviceoffline未演練。

位置文字一直可見、遲到map不覆蓋fallback；API503可重試而非假成功。callback移除URLcode/error，提供重新登入。catch保留原callback錯誤合理，但不能掩蓋F3取消意圖竞態。

<!-- section:frontend-state -->

## Frontend state

**Coverage:** Medium。**Evidence inspected:** api stores/allcriticalroutes、motionaction、SDKexchangesequence。**Exclusions / limits:** 31E2E含F1/F2/guest/callback；全route交錯非穷舉，F3no-code交錯由34Vitest補強。

F1snapshot與F2 keyedowner已驗解除；F3cancel/no-code已串行SDK持久化收尾。refreshIdentity有tokencommitguard／singleflight，不能自動使所有route的localdata失效。GSAPgeneration取消queuedmicrotask，update/destroyrevert，無跨nodeglobalselector。

<!-- section:maintainability -->

## Maintainability

**Coverage:** Medium。**Evidence inspected:** moduleboundaries、twoCI/style、tests/scripts/docs。**Exclusions / limits:** 無commit/changehistory；F1/F2/F4回歸已驗，F3剩餘交錯已34unit驗。

責任按服務拆分、錯誤及persistencehelpers集中，沒有預測未來需求新增framework。F1/F2適合本地snapshot/ownerguard，F3適合統一authlifecycle；避免多套競爭state管理。

<!-- section:observability -->

## Observability

**Coverage:** Medium。**Evidence inspected:** health、audit、outboxattempts/errors、workerwarnings、JSONtools／smoke。**Exclusions / limits:** productionmonitor/alerts/tracing未接入。

health確認DB；業務audit不含密碼，worker存errorclass並警告emissionbudget。smoke不輸出token或identifier。沒有正式alertdelivery證據，不把README列監控名稱當已啟用。

<!-- section:performance -->

## Performance

**Coverage:** Medium。**Evidence inspected:** SQLindexes/pool/statementtimeouts、worker100drain、SVG、motionbounds。**Exclusions / limits:** 700TCP/100API有實測；新版browsermotion及cloudsoak尚未完成。

borrow/approval必要lock短交易，worker先claim再HTTP。GSAP只transform/opacity，results最多12列，.22s+.06s=280ms，不延遲資訊可用；reducedmode跳過tween。mock時間只驗timeout邏輯，不證性能。

<!-- section:privacy -->

## Privacy

**Coverage:** Medium。**Evidence inspected:** ownerqueries/RLSgrants、redactederrors、PKCEURLcleanup、stores/localroutes、ratehash。**Exclusions / limits:** retention/deletion/exports/lockscreenguidance未正式指定。

F2已由key remount/lateguard解除，F3持久session剩餘交錯已修；serverownerSQL不因前端問題失效。getidentity只回本人profile、role由DB，publicschedule去除user/purpose；secret不進config/日誌。Googleprovidercredential只後端/Supabaseenv。

<!-- section:release -->

## Release

**Coverage:** Medium。**Evidence inspected:** Gitmetadata、twoCI/manifests、bootstrap/hook、composeCaddy/hashCSP/smoke。**Exclusions / limits:** 無commit／push/remoteCI、Docker/TLS/realGoogle/rollback未驗收。

兩個repo可各自安裝／check；後端跨服務工具顯式用URL/buildpath，compose不包含另repo。auth-hook可獨立套在既有schema，migration/bootstrap與runtimeprivileges分開。正式升級先backup、設定Googleallowlist與hook，再真OAuth驗收；本地nativeCaddy只可證SPA/CSP，不能證TLS。

<!-- section:security -->

## Security

**Coverage:** Medium。**Evidence inspected:** campus_identity/current_admin、hook/grants、validation/TLS/CORS/SSRF/upload、secretsignore。**Exclusions / limits:** realSupabase/Auth/RLS、imageadvisories/正式secretrotation未驗。

信任順序get-user同Bearer→provideronlyGoogle→confirmed/nonanonymous/exactemail→verifiedidentitysameemail→sub/AuthUUID/AMRoauth；不相信mutablemetadata。hook匹配官方user事件shape，invoker固定search_path只authadmin可呼叫，runtime無rostergrant。F2/F3修復守住browseridentityboundary，已驗證；正式服務仍另驗收。

官方來源：[Before User Created hook](https://supabase.com/docs/guides/auth/auth-hooks/before-user-created-hook)、[JWT claims](https://supabase.com/docs/guides/auth/jwt-fields)、[PKCE flow](https://supabase.com/docs/guides/auth/sessions/pkce-flow)。文件確認事件與方法的含義；實作的正式服務相容性仍需真驗收。

<!-- section:stability -->

## Stability

**Coverage:** Medium。**Evidence inspected:** transactiontimeouts/errorhandlers、state rules、workerlease/retry、mapcallbackrecoveries。**Exclusions / limits:** 192tests/31E2E通過；F3交錯已34unit閉合；正式outage/recovery未驗。

profile建檔暫時失敗可以同Googleidentity再submit，沒有不可逆Authcompensation；worker30slease恢復、失敗backoff。F1已解除；F3暫存UI與持久state失配已34unit/源碼解除，不能以successpromiseresolve假認為latestintent仍有效。

<!-- section:supply-chain -->

## Supply chain

**Coverage:** Medium。**Evidence inspected:** manifests/locks、pinnedSHAactions、Deno/config、dependency-auditscript。**Exclusions / limits:** OSV36零finding與frontend初版npm0已讀；SBOM/signing/containerimage未掃。

固定npm/Python/Deno與CIaction版本，formatter作devdependency；不下載／執行任意套件調查。advisory0只代表掃描時已知advisories，非所有依賴或邏輯安全保證。

兩repo `.gitignore:*.env`／`.env.*`僅例外example；backend node_modules/.venv/.local及frontend build/.svelte-kit/node_modules均由git check-ignore驗證，不將示例public設定當洩密，也不掃輸出actual secrets。CIactions固定SHA且permissions contents:read；後端CI只安裝自身Python/tooling lock，前端CI只npm自身根，remote執行尚未驗。

<!-- section:testing -->

## Testing

**Coverage:** Medium。**Evidence inspected:** test_auth/test_api/concurrency/worker、api/motiontests、E2E/production_browser。**Exclusions / limits:** 192Python/34Vitest/31E2E/Caddy7routes已讀；F3交錯已34unit驗；外部正式服務未驗。

新測試針對missing/extra四欄、wrongdomain/providers/sub/AMR、profile/audit失敗retry、sameUUID20重送與證號競爭、hookprivilege。motionunitmockengine驗dispatch/cleanup，不代替realGSAPbrowser；F1/F2已有可觀察browser回歸；F3剩餘交錯已新增3有意義cases。

<!-- section:testing-authenticity -->

## Testing authenticity

**Coverage:** High。**Evidence inspected:** harness resetguard/FakeSupabase、TCP/DB/load/barriers、browser、verify_supabase。**Exclusions / limits:** realGoogle／Auth／Push服務未執行。

reset僅loopback三個ntou_test用途DB，schema/auth-hook真SQL、應用ROLE真限制；Authfixture token是transport驗证，不是正式JWTcryptography。production無harnesslogin。100asyncclients不是100真人／browser；dispatchspread與DBlockoverlap分開記錄。smoke只有HTTPS真get-user後才可標real_auth。

<!-- section:type-safety -->

## Type safety

**Coverage:** High。**Evidence inspected:** PydanticInput/UUID/enums/bounds、trustedAuthpayloadchecks、TSinterfaces/motion、Denostrict。**Exclusions / limits:** APIgenericasT不做remotejsonschema驗證，realcontract未驗收。

forbidextras阻擋id/role/verified/email/password；AMR非list或sub不匹配failclosed。nullableprofile是正常onboarding，不用假Profile填補。沒有把fixtureassertion或TS編譯成功當成所有資料真實性保證。

### Principles analysis

資料庫持有一致性、Auth持有身份、API持有業務授權，界線簡單；fail-fast驗證守外部payload，dependency注入隔離測試HTTP而非生產開後門。F1/F2/F3原因是所有權與副作用時序，已局部修snapshot／keyedowner／identitygeneration/SDKqueue，未引入泛用框架。formatter是已確認規格，並非憑個人偏好全repo重構。

<!-- section:fix-order -->

## Recommended Fix Order

無尚未解除finding要排序。F1–F4均有source/回歸閉合，最後F3改動後34unit＋31E2E＋Caddy7route再驗。正式deployment gates依SPEC／README：配置真Google/provider/hook與受限DB→HTTPS唯讀smoke→正式100clients/Realtime/推播→backup/restore/rollback驗收；不能以本地pass跳過。兩個review文件先Prettier，再full report_lint及人工一致性檢查。

<!-- section:quick-wins -->

## Quick Wins

本輪局部snapshot、keyedowner、generation/SDKqueue、routerlifecycle與guestready恢復已完成；沒有依個人風格產生的新quickwin或框架重構要求。
