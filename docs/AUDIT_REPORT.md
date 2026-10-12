> 歷史報告：以下是 2026-10-11 的密碼／名冊版本與拆分前路徑。2026-10-12 已改為 Google-only 並拆成兩個 repository；本文件保留當時證據，不能當成新版登入／部署驗收。新版結果見 UPGRADE_TEST_REPORT.md 與 UPGRADE_AUDIT_REPORT.md。

# 海大教室借用平台 — Full engineering audit

**Modes:** full（26 個 canonical dimensions）  
**Date:** 2026-10-11，Asia/Taipei  
**Reviewer:** independent_review；應用程式唯讀，僅撰寫審查文件  
**Scope / revision / worktree state:** `C:/Project/ntouse-g10` 全部 first-party 程式、SQL、設定、測試與產品文件。此目錄不是 Git repository；commitHash / revision = null，無可證明的基準分支、diff 或歷史覆蓋。

<!-- section:executive-summary -->

## 1. Executive Summary

本地實作已有可驗證的權限、狀態機、停權、交易 outbox 與資料庫排他约束。修後最新 [pytest.xml](C:/Project/ntouse-g10/reports/pytest.xml) 為 89 tests、0 failures、0 errors、0 skipped；[瀏覽器報告](C:/Project/ntouse-g10/reports/e2e-browser.json) 20 checks 全通過。100 個獨立 DB 連線在第一個 transaction 尚未 commit 時產生 99 個 lock waiters，最後僅 1 核准、99 個 SQLSTATE 23P01，證明约束對重疊核准有效。這些測試不能替代正式 Supabase、TLS 或裝置推播驗收。

目前 **1 Medium confirmed operational risk（F3）**：已確認的Auth identity缺profile時仍需受信任維運核對來源／名冊後補建。README有人工runbook，可降低風險；尚無持久、可定位的profile recovery工作。High F1誤刪身份已移除全部Auth DELETE，89-test suite包含新建／既有未確認Auth的失敗保留、零DELETE與同UUID重試；Medium F2已補有界API和20筆UI分頁、selectedUUID保持，101筆API／14前端／20browser檢查及修後capture均通過。High F4 production CSP已改framework hash policy，reviewer獨立核對bootstrap SHA256；actualCaddy browser五route hydration、禁止任意inline script、page_errors=[]通過。三項已修root causes只列ledger，不計入未解除統計。

獨立視覺判定為 **ship，僅限七張E2E capture＋一張actualCaddy productionbuild畫面與方向契約**；工程與正式上線判定仍受F3和下列正式驗收界限約束。尚未對真實Supabase / TLS / 裝置執行正式驗收；本 reviewer 未讀實際 `.env`，不推斷當前憑證是否存在。Supabase Auth 實際 email / bcrypt / 新 API key 行為、auth.uid RLS、Realtime、private Storage、真正 Web Push provider／裝置接收、Docker／HTTPS 及校方名冊／精確圖資均未實測，coverage 為 Medium 或 Not assessed，不宣稱完整 SLA certification。

<!-- section:score-dashboard -->

### Score Dashboard

| Dimension       | Score | Grade | Coverage | Justification                                                                                     |
| --------------- | ----- | ----- | -------- | ------------------------------------------------------------------------------------------------- |
| Security        | 8.2   | A     | Medium   | API role/SQL/RLS邊界與依賴掃描有證據；F1已移除未知所有權Auth DELETE並有回歸，真Auth/RLS仍待驗收。 |
| Stability       | 7.8   | A     | Medium   | 排他約束、交易outbox、lease/retry與恢復流程有測試；F3已確認identity缺profile仍需人工對帳。        |
| Performance     | 8.5   | A     | Medium   | 本地100TCP clients各route max低於预算；未做正式雲端或持續soak／真瀏覽器群。                       |
| Testing         | 8.4   | A     | Medium   | 修後89真DB/單元測試、14前端測試；F1及101筆F2回歸通過，正式Supabase與全accessibility未測。         |
| Maintainability | 8.3   | A     | High     | 小型分層、統一業務寫入口、清單分頁與產品/維運文件；F3需人工介入。                                 |
| Design          | 8.3   | A     | Medium   | schema/rules/API/worker責任清楚、ownership安全修正；跨Auth/DB恢復仍需F3。                         |
| Release         | 7.8   | A     | Medium   | lock、固定CI actions、Caddy原生/深連結驗證；Docker/TLS/正式Auth/push驗收仍待完成。                |
| Overall         | 8.2   | A     | —        | 七維算術平均57.3/7，四捨五入到一位小數；不代表正式部署與外部SLA認證。                             |

<!-- section:project-map -->

## 2. Project Map

| Boundary / entry | Trace and responsibility                                                                                                                                                                      |
| ---------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 產品與契約       | `docs/prompt.md` → `docs/SPEC.md` → `PRODUCT.md`；`.impeccable/contracts/frontend.md`、surface brief 與 `DESIGN.md` 描述 code-led 校園作業介面。                                              |
| 公開瀏覽         | `frontend/src/routes/+page.svelte` → `$lib/api.ts` → `GET rooms/availability`、room schedule → PostgreSQL reservations；RoomMap → map-loader → 同源 SVG / private signed URL / 常駐位置文字。 |
| Auth             | register/login → `backend/app/main.py` → `supabase_request` → Auth；受保護 endpoint → `auth.current_user` 真正查 Auth user → DB profile；admin role 來自 DB，無信任 user_metadata 升權。      |
| 業務寫入         | Pydantic models → `rules.py` → DB transaction/profile 與 reservation locks → status change、audit、notification 同交易；schema GiST 排除核准重疊。                                            |
| 停權與違規       | admin endpoint → profile lock / violations → 點數與 suspended → 新申請重新檢查 eligibility；未依舊 session 內角色或停權快取授權。                                                             |
| 通知             | transaction notification → worker SKIP LOCKED + lease → bounded HTTP Edge dispatch → service-only subscription lookup → Web Push；Realtime 及輪詢補讀是獨立接收路徑。                         |
| 部署             | Svelte static build `200.html` → Caddy SPA fallback；FastAPI/worker container → restricted DB role；Caddy 為唯一可信 reverse proxy。                                                          |
| 測試             | unit + `tests/conftest.py` 真 PostgreSQL fixture + Auth/Storage/Push MockTransport；`tests/e2e.cjs` 與 `tests/live_load.py` 走 TCP API、真 DB，Auth fixture 僅存在 test harness。             |

**Inventory:** 最終 `reports/first-party-inventory.txt` 為94個first-party檔案；早期84-file snapshot亦以 `rg --files --hidden` 排除runtime/deps/generated reports/actual `.env`刷新。後增的Auth logout/borrower selection測試、`frontend/scripts/check-csp.mjs`、`tests/production_browser.cjs`、DESIGN、TEST_REPORT及本次文件已納入。所有first-party runtime entry、測試、schema/seed、deployment/CI/script和產品文件均已閱讀；lockfiles檢查manifest、固定版本與實際工具輸出，未逐行審核第三方實作。

**Commands and outcomes:** 本 reviewer 執行 `rg --files` / `rg` / PowerShell source reads、XML/JSON evidence reads、七張E2E及一張Caddy `view_image` 檢查與報告 linter；`git status --short` 回傳不是 Git repository。沒有執行 pytest 或重置 DB，以免與測試 agent 衝突。下列執行結果由測試/實作 agent 的現存 artifacts 與相應測試原始碼交叉核對，並非聲稱本 reviewer 親自執行。

| Evidence artifact                                      | Result and interpretation                                                                                                                                                                                                                               |
| ------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `reports/pytest.xml`                                   | 89 / 0 failures / 0 errors / 0 skipped；涵蓋 rules、API/Auth/權限/停權、DB 約束、worker lease/retry/hung provider。                                                                                                                                     |
| `reports/concurrency-api.json`                         | 100 distinct users；applications 100×201，max 705.244 ms；approvals 1×200、99×409，max 390.115 ms，approved_rows=1；asyncio Event dispatch spread 56.227 / 26.949 ms，沒有 1 ms 絕對同時的聲稱。                                                        |
| `reports/concurrency-direct-sql.json`                  | PostgreSQL 17.11、100 independent connections；winner commit 前 99 blocked connections，explicit_transaction_overlap=true；1 success + 99×23P01，max 213.592 ms 含刻意保留 transaction 的時間，非 API SLA。                                             |
| `reports/live-http-100-users.json`                     | 真 TCP + DB、100 distinct identities；各 route max 低於 2s / 0.5s / 5s 預算，Auth mock。精確值見 performance section。                                                                                                                                  |
| `reports/e2e-browser.json`                             | Chrome 154.0.8037.98、Asia/Taipei、20 checks 全 pass；375/768/1440 overflow、keyboard login/weekly navigation、borrower admin denied、審核/鑰匙交還、既有 token 停權、位置 fallback；五張完整截圖。                                                     |
| `reports/frontend-validation.json`                     | Node 24.20.0；check 0 errors/warnings，Vitest 4 files / 14 tests，其中 5 logout regressions；build 成功且 `200.html` 存在、`index.html` 不存在；npm audit 0 vulnerabilities。                                                                           |
| `reports/python-dependencies.json`                     | OSV 對 lock 中 36 PyPI packages querybatch，findings=[]；是掃描當時的 advisory 結果，非供應鏈或所有邏輯安全保證。                                                                                                                                       |
| `reports/caddy-validation.json`                        | 官方 Caddy 2.10.2 checksum verified、production config validate passed；loopback HTTP 用實際 Caddy 測 5 deep links 都 200 且符合 built fallback；Docker/正式 TLS 未執行。                                                                               |
| `reports/caddy-browser.json`、`caddy-home-desktop.png` | production設定副本只替換loopback listener/builtroot/APIaddress；5routes hydrated、精確hash允許、任意inline阻擋、page_errors=[]、passed=true。reviewer已重新開啟實際Caddy首頁，內容/布局與baseline一致。仍無TLScertificate／Docker／remoteSupabase驗收。 |
| `deno.json`、`deno.lock`、Edge security tests          | strict 設定與固定依賴已讀；TEST_REPORT記錄Deno2.9.7 check＋2securitytests成功；CI固定2.9.6；未有真部署／裝置 receipt artifact。                                                                                                                         |

**Coverage limits:** 排除 `.local/`、`.venv/`、各 `node_modules/`、`.svelte-kit/`、`frontend/build/`、cache、reports 生成物及實際 secrets；reports 僅作證據讀取。無 repo history／Git revision；沒有 Docker/TLS、真實 Supabase、校方名冊/座標、外部監控、長期流量或真實裝置的完成驗收證據。未審第三方程式全集、OS/browser push reliability、全 route 輔助科技或逐像素對比不存在的 approved comp。

<!-- section:coverage -->

### Coverage Matrix

| Dimension            | Coverage     | Evidence inspected                                                                        | Exclusions / limits                                                                 |
| -------------------- | ------------ | ----------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------- |
| accessibility        | Medium       | app.css、semantic controls、WeekSchedule/RoomMap、keyboard/RWD browser checks、7 captures | 未做 screen reader、200% zoom、所有 route 完整 focus traversal。                    |
| ai-safety            | Not assessed | manifests、全部 runtime routes/scripts/Edge/worker                                        | 無 AI/model/tool execution surface，不適用。                                        |
| architecture         | High         | backend layers、API client、schema、worker、compose                                       | 正式網路拓撲與故障演練未實測。                                                      |
| backend-api          | High         | main/auth/models/rules、test_api、OpenAPI definitions                                     | Supabase 真上游 contract 待驗收；F1/F2已修，延伸browser20checks與recapture已通過。  |
| code-consistency     | High         | Python/TS/CSS source、routes、types、manifests                                            | 未把排版或個人命名偏好當 finding。                                                  |
| comment-coverage     | High         | auth補償、lock/lease、安全/fixture comments、README                                       | 不以 comment 數量計分。                                                             |
| concurrency          | High         | GiST/locks/request_id、100 API + directSQL overlap、worker concurrency tests              | 不代表部署端 100 人的真網路或長期 soak。                                            |
| configuration        | Medium       | Settings、env examples、Caddy/compose/Docker、production tests                            | 正式 env、certificate、Supabase Auth/Storage 設定未讀取。                           |
| cost                 | Medium       | bounded pools/timeouts、private maps、pagination、worker retry、dependencies              | 無雲端用量帳單、quota 或長期 object lifecycle 測量。                                |
| data-integrity       | High         | schema constraints、transaction helpers、registration、idempotency/transition tests       | local auth schema 不等於完整雲端 auth.users；F1已修、F3仍需恢復流程。               |
| dependency-weight    | Medium       | manifests/locks、frontend build、Docker includes                                          | 未做正式 bundle/network profile或逐個第三方 internal audit。                        |
| design               | High         | module responsibility、types、rules、outbox/DB boundary                                   | cross-service recovery仍有F3，F1已修；不是視覺偏好評分。                            |
| documentation        | High         | prompt/SPEC/PRODUCT/README/DESIGN、harness、scripts                                       | 外部校方政策未提供，無 Git history。                                                |
| fallback             | Medium       | map-loader timer tests、browser map failure、logout tests、API error handlers             | 真上游 outage、Realtime restore、網路斷線裝置未演練。                               |
| frontend-state       | Medium       | all routes、api stores/auth callbacks、request generation、5logout tests                  | 全 route race、cross-tab lifecycle 未做exhaustive runtime testing；F2已修。         |
| maintainability      | High         | all first-party layers/scripts/tests/docs                                                 | 單一新專案無長期 change history；F2已修、F3。                                       |
| observability        | Medium       | health、audit/outbox、worker logs、JSON metrics、README runbook                           | 正式 logs/alerts/dashboards未接入；F3 warning沒有safe correlation。                 |
| performance          | Medium       | indices/pools/limits、realHTTP100、API100、SVG timing                                     | 雲端延遲、長期 soak、100真瀏覽器未測。                                              |
| privacy              | Medium       | RLS/grants、owner paths、redacted errors、rate hashes、push payloads                      | 正式資料保存規則／裝置鎖屏政策未提供；真雲端 RLS未測。                              |
| release              | Medium       | CI/Docker/compose/Caddy/locks/bootstrap+README、production_browser                        | 無Git revision與真Docker/HTTPS/remote deploy/rollback evidence；F1/F4已修並有回歸。 |
| security             | Medium       | Auth/roles/RLS/SSRF guards、SQL/upload/errors、advisory tools                             | F1已修；實際 Auth/RLS/Storage/modern key handling未實測。                           |
| stability            | Medium       | transactions/timeouts/state machine、worker/backoff、fallback、tests                      | F2已修、F3；正式外部服務failure/recovery未測。                                      |
| supply-chain         | Medium       | locks、SHA CI actions、OSV/npm、verified Caddy release、Deno lock                         | 無 artifact signing/SBOM 檢查，Deno依賴未有全面 advisory scan。                     |
| testing              | Medium       | pytest89、Vitest14、browser20、concurrency/load/harness                                   | F1/F2回歸已補；真Supabase與全accessibility未測。                                    |
| testing-authenticity | High         | conftest/harness/live_load/e2e/directSQL源碼與 JSON/XML                                   | Auth/Storage/provider 明確 mock；不外推 formal SLA。                                |
| type-safety          | High         | Pydantic bounds/enums/UUID、TS interfaces/generics、strict Deno/check                     | HTTP/DB runtime資料仍需 runtime validation，remote contract未測。                   |

### Requirement traceability

每一項需求均納入目標；「local verified」只表示列出的實作路徑與本地證據，非正式雲端驗收。

| Requirement | Trace / current evidence                                                                                        | Limit or remaining risk                                                                                 |
| ----------- | --------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------- |
| FR-001      | `auth.current_admin` DB role、schema role CHECK；API borrower forbidden + browser admin nav/direct denial       | 真 Auth/RLS未驗收。                                                                                     |
| FR-002      | Register model、roster-before-signup、transaction profile；缺欄位/格式/duplicate測試                            | F1已移除Auth DELETE並通過失敗保留/重試回歸；F3已確認孤兒仍需人工恢復。                                  |
| FR-003      | availability overlap `[start,end)`、equipment/capacity/building filters；API bounds + browser query             | 正式房間資料未提供。                                                                                    |
| FR-004      | create_reservation + rules immediate/scheduled、request_id unique/replay；API100及 idempotency tests            | 100 local identities不是100真使用者。                                                                   |
| FR-005      | admin approve/reject reason/status + audit/notification；API與browser lifecycle                                 | 雲端通知未驗收。                                                                                        |
| FR-006      | state transitions、suspend/resume、active points checks、audit                                                  | F2已補有界分頁；101筆API舊未結案可達與結案回歸通過，延伸browser101borrowers/records回歸通過。           |
| FR-007      | handed/returned timestamps與actor、transition validation；browser鑰匙交還                                       | 未做現場人員/鑰匙驗收。                                                                                 |
| FR-008      | own/admin history scopes與limit/offset/total、handover/return fields；API + browser history                     | 全瀏覽器歷史長清單未測。                                                                                |
| FRA-001     | RoomMap同源SVG點、代碼、樓層、座標、常駐location_text與demo banner                                              | 示意圖/座標屬標示示範，非校方精確測量。                                                                 |
| FRA-002     | roster + institutional_id + confirmed email verification；forgery/unverified API tests                          | 真校方名冊與email service未驗收。                                                                       |
| FRA-003     | same-transaction notify、RLS owner read、Realtime + polling、workerlease/retry                                  | provider/Realtime/device receipt <3s待部署驗收。                                                        |
| FRA-004     | WeekSchedule七日與mobile day selector；375/768/1440 keyboard checks                                             | 全部輔助科技/語音閱讀未测。                                                                             |
| FRA-005     | points_for + suspended/profile locks、resolve + resume gate；API/browser停權                                    | F2已補20筆使用者與違規独立分頁；14前端單元與101筆API回歸通過，延伸browser101borrowers/records回歸通過。 |
| NFR-001     | realHTTP availability max418.887ms、weekly129.942ms；UI loading/results                                         | 2s本地预算通過；正式網路與雲端Auth未測。                                                                |
| NFR-002     | API100 applications max705.244ms、100201、idempotent constraints                                                | dispatch spread56.227ms，未聲稱绝對1ms同時。                                                            |
| NFR-003     | Auth dependency401、unverified/roster403、API permission tests                                                  | 正式Auth configuration待驗收。                                                                          |
| NFR-004     | browser home/admin375/768/1440 overflow + 5 desktop/mobile captures                                             | sampled routes；非全裝置/全狀態認證。                                                                   |
| NFR-005     | worker100batch/full-drain、1s poll/1.7srequest、mock clock/retry/hung-provider                                  | 無正式event→Realtime/provider/device <3s evidence。                                                     |
| NFR-006     | realHTTP eligibility max186.209ms <500、violations_active_owner partial index                                   | 正式大表資料量/雲端延遲未測。                                                                           |
| NFR-007     | e2e SVG request11.335ms、navigation-to-marker1006.577ms <2000                                                   | 同源localhost測量；未測正式位置圖資。                                                                   |
| NFR-008     | map-loader 1999/2000ms+late results/error tests、browser text fallback                                          | mock timer證明邏輯，非網路SLA。                                                                         |
| NFR-009     | 不存在/密碼錯誤不同訊息、422不echo密碼、rate-limit tests                                                        | 存在性提示是明文需求取捨；不增加未授權披露。                                                            |
| NFR-010     | realHTTP100 route maxima <5s、admin-under-load173.001ms、permission refresh140.059ms                            | 固定100 async clients/identities、1admin混合負載，非100實體瀏覽器。                                     |
| NFR-011     | production HTTPS/TLS/role guards、Caddy HSTS/hashCSP/native validate＋browserhydration、無business password欄位 | realTLS/hash `$2...`、Docker/net trust待部署；`verify_supabase.py`尚無遠端結果。                        |
| NFR-012     | API1winner99conflicts；SQL100connections99waiters1winner99×23P01；adjacent tests                                | 本地真PostgreSQL，非正式雲端cluster實測。                                                               |
| NFR-013     | current_admin統一入口、role forgery與owner/admin endpoint tests                                                 | 真 auth.uid RLS需正式token測試。                                                                        |
| NFR-014     | current request重讀profile，API/browser已有token仍被拒絕、under-loadrefresh140.059ms                            | 正式跨instance通知/token scenarios未實測。                                                              |

<!-- section:statistics -->

### Finding Statistics

| Severity | Count | Confirmed | Suspected |
| -------- | ----- | --------- | --------- |
| Critical | 0     | 0         | 0         |
| High     | 0     | 0         | 0         |
| Medium   | 1     | 1         | 0         |
| Low      | 0     | 0         | 0         |
| Info     | 0     | 0         | 0         |
| Total    | 1     | 1         | 0         |

僅計算目前未解除的 root causes；已修復 ledger、部署待驗收和不適用維度不重複計數。

<!-- section:top-risks -->

## 3. Top Risks

1. **F3 / Medium:** 已確認Auth缺profile可能阻擋正常登入／重新註冊，依README由受信任維運核對來源及名冊後補建；尚無可定位、持久待修狀態。F1/F2/F4修後證據列於ledger，不再當目前風險。
2. 正式外部驗收界限：SupabaseAuth/RLS/Storage/Realtime、TLS/container與provider/device未執行，coverage Medium；屬明示gate而非捏造confirmed bug。

<!-- section:findings -->

## 4. Detailed Findings

<!-- finding:F3 -->

### F3 — 已確認 Auth 身份缺 profile 時，恢復仍需人工維運

- Severity: <!-- field:severity --> Medium
- Confidence: <!-- field:confidence --> High
- Category: <!-- field:category --> data-integrity
- Status: <!-- field:status --> Confirmed
- Affected area: <!-- field:affectedArea --> Auth identity / profile provision跨服務恢復；FR-002及維運。
- Evidence: <!-- field:evidence --> [main.py:149](C:/Project/ntouse-g10/backend/app/main.py:149) profile/audit交易；:153–156失敗只記`signup_profile_pending_reconciliation`並保留身份；:142–143已確認重複signup的空identities會409；:165–167登入先要求profile存在。README維運末段明列未確認者可重試、已確認缺profile需維運核實來源／名冊後補建。`tests/test_api.py:43`新建與既有未確認身份保留/retry回歸通過，不涵蓋confirmed孤兒自助恢復。
- Problem: <!-- field:problem --> 不刪未知所有權Auth是正確安全修正；但保留identity與已確認後缺profile的恢復是另一個責任。當DB交易失敗後本人先確認email，現有登入與重註冊路徑皆不會補建profile。通用warning沒有safe correlation/待修狀態；目前只能靠人工對帳。這是已記錄的恢復界限，並非要求重新加入不安全DELETE。
- Why it matters: <!-- field:userVisibleImpact --> 本人可能因沒有profile而登入回「帳號不存在」、重註冊回「帳號已註冊」，需要管理員另取資料、核對名冊後修復；runbook降低風險但沒有自助或持久修復保證。
- Realistic failure scenario: <!-- field:failureScenario --> Auth signup回身份→profile INSERT/audit timeout→API失敗且身份保留→本人確認校園email→DB恢復後login仍無profile、signup走已確認duplicate；受信任維運介入才能完成。
- Minimal fix: <!-- field:minimalFix --> 保持不刪未知Auth的安全邊界。提供受控repair command或已驗證本人identity/roster的profile recovery入口，加入不含email/password/token的safe correlation及告警／持久對帳記錄；完全DB outage時採安全外部事件並在恢復後重試。核實來源，不把auth.users LEFT JOIN候選當自動刪除名單。
- Regression verification: <!-- field:regressionTestSuggestion --> 模擬profile交易失敗、之後email確認，再試login/register；驗證能安全定位並由受控修復完成本人profile/正常驗證，其他產品identity与競賽成功profile保持完整。另確認已有未確認帳號retry仍通過。
- Estimated effort: <!-- field:estimatedEffort --> 2–4小時可加入受控repair與明確告警；durable跨服務queue需部署決策，現有runbook可作短期緩解。

### 已修復並有目前證據的 ledger（不計入 finding statistics）

| Previously observed risk                            | Current source / regression evidence                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| --------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| F4：Caddy原script-src self阻擋built inlinebootstrap | `frontend/svelte.config.js:8`kit.csp.mode=hash、Caddyheader僅frame-ancestors/base-uri/form-action；`check-csp.mjs`與build自動斷言允許exacthash/self、拒絕unsafe-inline/eval/任意script。reviewer獨立以SHA256核對built唯一bootstrap hash相符。`reports/caddy-browser.json`2026-10-11T15:33:18Z五route hydrated、bootstrap_hash_allowed=true、untrusted_inline_blocked=true、page_errors=[]、passed=true；實際Caddy首頁capture已獨立重讀。此為loopback HTTP builtSPA/proxy/CSP驗證，不外推TLS/remoteAuth。 |
| F1：公開signup回傳身份被當新建，失敗補償可能誤刪    | `main.py:153–156`現在只記reconciliation事件、完全不呼叫Auth DELETE；`test_failed_profile_creation_retains_auth_identity_for_reconciliation`的new-auth/existing-unconfirmed-auth兩例在89-test suite通過，均保留身份、零DELETE並同UUID重試成功。原控制路徑依[官方Auth source](https://github.com/supabase/auth/blob/master/internal/api/signup.go)確認；未宣稱雲端故障重現。                                                                                                                               |
| F2：違規及選人清單100筆截斷                         | `main.py:387–394`boundedlimit/offset/count/穩定created_at,id排序、joinname/ID；admin20筆兩種分頁、`borrower-options.ts`保留selected UUID；101筆API舊未結案後頁/結案回歸、3selection單元及check/build通過；browser20checks含101borrowers/violations及mobile結案通過；新desktop/mobile capture已獨立核對。                                                                                                                                                                                                 |
| SPA fallback index.html / 200.html不一致            | `frontend/svelte.config.js` fallback200.html、Caddy try_files；frontend build artifact與實際Caddy5deep links全200相符。                                                                                                                                                                                                                                                                                                                                                                                  |
| 推播清理503阻止離線登出                             | `api.ts:120` nested finally呼叫signOut、清除project localStorage/session/profile/notices/privatepoll/channel、阻止stale callbacks；`api.test.ts`5 regressions。不是雲端撤銷成功保證。                                                                                                                                                                                                                                                                                                                    |
| 未驗名冊先建Auth占位                                | `main.py:129–136` roster/duplicate guard在signup前；registrationnegative tests；password model/Login不strip原密碼。                                                                                                                                                                                                                                                                                                                                                                                      |
| production privilege/TLS/health proxy與secret輸出   | `main.py:38–49` SET ROLE + session_user guard、TLS context；Settings URL/DB TLS guards、loopback health exception、Docker信任指定proxy、secret repr/validation redaction tests。                                                                                                                                                                                                                                                                                                                         |
| worker滿批仍sleep / 小batch                         | `worker.py` LIMIT100，滿batch即drain；1.7s timeout、lease/retry、hung-provider test。TimeoutError已被處理，不是未捕捉崩潰finding。                                                                                                                                                                                                                                                                                                                                                                       |
| upload body與依賴advisory                           | Caddy max_size3MB、app檔案2MB+type/magic；Starlette1.7.0 lock、OSV36packages findings[]；pip26.2.1是工具版本，不是app依賴安全證書。                                                                                                                                                                                                                                                                                                                                                                      |

<!-- section:accessibility -->

## 5. accessibility

**Coverage: Medium.** 已讀app.css焦點/reduced-motion、native forms、Status文字、RoomMap替代文字、WeekSchedule按日/aria controls及全部route。**Verified:** `tests/e2e.cjs`使用Tab定位login email/password再Enter，週課表toggle與mobile day用focus+Enter；最新JSON對375/768/1440皆通過；home/admin無document overflow，七張完整capture無重疊裁切。**Limits:** 未親自執行screen reader、200%zoom、全部鍵盤順序/錯誤朗讀，不能以svelte-check0warnings代表WCAG全面合規。未發現capture可證明的material accessibility defect。

<!-- section:ai-safety -->

## 6. ai-safety

**Coverage: Not assessed.** manifests、backend/frontend/worker/Edge/script未包含模型呼叫、prompt、agent tool execution、retrieval或不可信模型输出。模型風險維度不適用；不以不存在AI功能作0分或捏造finding。

<!-- section:architecture -->

## 7. architecture

**Coverage: High.** 已讀main/auth/models/rules/database、Svelte routes/lib、SQL、worker與compose。**Verified:** 業務寫入只有API；frontend Supabase client只處理Auth與Realtime；validation、authorization、transaction與dispatch分層，外部HTTP在worker DB claim後執行，無在持鎖期間推播。沒有循環依賴或不必要框架的具體證據。**Limits:** 單一新專案沒有歷史演化或遠端拓撲演練；Auth/DB恢復邊界的F3仍須處理，不以整體分層合理掩蓋它們。

<!-- section:backend-api -->

## 8. backend-api

**Coverage: High.** 逐一讀取main endpoints、models/Depends/auth及test_api。**Verified:** UUID/bounds、状态enum、duplicate409、auth401/admin403、拒絕原因、owner scopes、request_id同內容replay/不同內容409、SQL errorsredaction、history/userslimit/offset/total；沒有未授權業務寫入捷徑。F1未證明ownership的DELETE已移除，F2違規清單後頁已补並有API101筆回歸。**Limits:** 未以正式Supabase驗證上游response、email lifecycle、新keygate或Storage contract；本地mock不能證明它們。

<!-- section:code-consistency -->

## 9. code-consistency

**Coverage: High.** 已讀Python/TS/Svelte/CSS和manifests。**Verified:** 狀態集中於enum/labels、UTC存DB/Taipei表現由time helpers承擔、API錯誤與授權由共用client/Depends處理，通知與audit由共用helper寫入；types/check成功。未以縮排、短句或檔案大小提出finding。**Limits:** 未做每個工具跨平台styleformatter對照，這不構成已證明的功能風險。

<!-- section:comment-coverage -->

## 10. comment-coverage

**Coverage: High.** 已讀補償、profile/room locking、workerlease/timebudget、privacyredaction、RLS與testfixture的註解。**Verified:** worker說明短claim後外部I/O、30秒lease/1.7秒期限；test comments明示Authprovider與timers的mock界線。F1原「newly-created」假設已改為明述既有未確認identity不可刪；來源與安全修正一致。**Limits:** 不要求逐行註解，無comment密度目標；README無法代替F3持久修復狀態。

<!-- section:concurrency -->

## 11. concurrency

**Coverage: High.** 已讀transactionhelper、create/status/violations/resolve鎖順序、schema及concurrency/worker tests。**Verified:** 核准由GiST `EXCLUDE` `[)` 限制approved/checked_out，邻接合法；request_id ownerunique；新申請鎖profile後驗eligibility、狀態轉換重新讀取locked資料；同transactionaudit/notify。API100只1winner，直接SQL100PID/99blocked-before-commit只1winner99×23P01。worker SKIP LOCKED/lease及two-worker tests防同次claim重复。**Limits:** 未聲稱全部並行交錯無deadlock；有限lock_timeout與409/503降低失敗影響。未測正式cloudpool長期負載或精確1msdispatch。

<!-- section:configuration -->

## 12. configuration

**Coverage: Medium.** 已讀Settings、env examples、productiontests、compose/Docker/Caddy和Supabase config。**Verified:** production拒絕非HTTPS外部URL、不驗certificate的DB TLS、superuser/bypassrls login；指定proxy信任、API不公開hostport、localhealth exception範圍明確；service/dispatchsecrets不回config或repr。原生Caddyvalidates、max3MB、SPA200fallback；F4修正的built CSP hash已獨立核對，actualCaddy browser5routehydration與阻擋任意inline已通過。**Limits:** 正式Authemailconfirmation設定、secret值、privatebucket實際權限、DNS/TLS/容器network未取得。配置例子不是部署成功證明。

<!-- section:cost -->

## 13. cost

**Coverage: Medium.** 已讀poollimits、APIboundedqueries、worker100batch/backoff、upload2MB、signedURLcache和dependencies。**Verified:** HTTP/DB期限、最多100pushbatch、expiredsubscriptioncleanup、authratecountercleanup與分页抑制常见無界成本；沒有token/model費用。F2已補可到達分页並保留上限。**Limits:** 未取得正式Storage object數、帳單/egress/quota，未測地圖替換多年留存與全部用戶100通知輪詢成本；無證據把這些變成已量化的高成本finding。

<!-- section:data-integrity -->

## 14. data-integrity

**Coverage: High.** 已讀schema/seed、profile provision、business transactions、constraints、rules及DBnegative tests。**Verified:** status/role/points/time/capacity constraints、foreignkeys、UUID/idempotency、activepointindexes、GiSToverlap；審核/違規/audit/notification原子性，不信任前端計算。F1已以保留identity解除誤刪；F3仍是已確認identity缺profile的跨服務恢復界限。**Limits:** 本地schema有條件建立auth.users FK，沒有假稱已驗真雲端Authtable；backup/restore/remote migration仍待staging。

<!-- section:dependency-weight -->

## 15. dependency-weight

**Coverage: Medium.** 已讀frontend/package、backendrequirements/lock、deno與test manifests、Docker copy範圍、build結果。**Verified:** runtime為FastAPI/httpx/asyncpg/Pydantic、Svelte/Supabaseclient與小型Edgewebpush；未發現需另一框架維持的重複功能。frontendfonts/SVG同源；testharness依賴不進appimage，node_modules泛用ignore。**Limits:** 尚無bundletreemap/正式下載大小profile，不以manifest套件個數或單一大lockfile判定bloat。

<!-- section:design -->

## 16. design

**Coverage: High.** 已讀layers/types/rules/schema/outbox並追蹤borrower/admin lifecycle。**Verified:** role與状態sourceoftruth在DB，傳輸model與業務rules分責，當前簡潔API架構足以承載小型平台；localclock/transport注入支援真DB邏輯測試。F1所有權邊界及F2有界collection契約已修；F3顯示profileprovision恢復仍依人工維運。**Limits:** 此維度重點是工程責任/抽象，不將個人視覺風格作finding；獨立視覺矩陣在INDEPENDENT_REVIEW。

<!-- section:documentation -->

## 17. documentation

**Coverage: High.** 已讀原始prompt、SPEC全部需求/驗收、PRODUCT、README、DESIGN、directioncontract與bootstrap/verify scripts。**Verified:** 示範帳號僅testfixture、名冊/圖資來源限制、Realtime/provider/device不同语義、DBrole/TLS/privateStorage/部署步驟、bootstrap非migrationhistory、備份及回退DB界線、orphanmanualrunbook均明示。**Limits:** 真校方政策/正式值未提供，沒有Gitrevision不能產虛構commitmetadata；README與SPEC已改為signup可能回傳既有身份、保留身份與核實来源的安全對帳。

<!-- section:fallback -->

## 18. fallback

**Coverage: Medium.** 已讀map-loader/RoomMap+timertests、allroute loading/error/empty states、Auth/logout、API handlers和workerretry。**Verified:** 2s地圖fallback、晚到結果不覆蓋、常駐文字及browsererrorcapture；API錯誤不虛構成功；logout push/auth失敗仍清project credentials/privatepoll/channel，5單元回歸；Caddydeep links200，builtSPA5routes實際hydrated且CSP仍拒絕任意inline。**Limits:** 真斷網/跨tab/Authrevocation/Realtime重連/裝置權限變動未完整實測。F3的人工修復不是自動fallback。

<!-- section:frontend-state -->

## 19. frontend-state

**Coverage: Medium.** 已讀allroutes、stores/initialize/session/authcallbacks、requestgeneration與busy/error/selection。**Verified:** profile/notificationresponse比對owner，logout清理timer/channel并guardqueuedauthcallback，apierror與timeout可讀、成功以API結果更新；querygeneration降低舊request覆盖新结果。F2後頁可達性及選人保持已修，新desktop/mobile capture已覆蓋新增部分、同reviewer verdict ship。**Limits:** 未做每一個rapidtab/queryedit/crosstab/authrefresh交錯的runtime探索，不把讀碼無疑點等同不存在stalerace；沒有codeledapp「假登入」UI。

<!-- section:maintainability -->

## 20. maintainability

**Coverage: High.** 已讀全部firstparty，module關係與腳本/測試/文件交叉核對。**Verified:** 小型分層、共用api/time/status/Icon/RoomMap/WeekSchedule、集中rules/transactionhelpers；無必要拆成更多service的具體證據；testDBloopback/allowlist guard降低誤重置風險。F2分页已修；F3人工對帳是目前維護成本。**Limits:** 沒有長期變更/Git歷史；不以行數、個人口味或可刪單次helper製造重構工作。

<!-- section:observability -->

## 21. observability

**Coverage: Medium.** 已讀health/readiness、auditlogs、notificationattempt/claimed/delivered/error字段、workerlogs、metrics與READMErunbook。**Verified:** readiness查真DB；status/verify/suspend/violation的audit與變動同transaction，pushlast_error僅class避免洩token；push_dispatch_failed/budgetexceeded及max/p95 JSON有可用調查入口。F3通用warning無ownedUUID/correlation，不足以可靠追踪個別修復。**Limits:** 無正式logpipeline、alertdelivery或pendingoutboxdashboard實測，不把列在README當已接通監控。

<!-- section:performance -->

## 22. performance

**Coverage: Medium.** 已讀queryplans相關indexes、pool/HTTP/statement/locktimeouts、分页、signedURLcache、前端字體/SVG、負載工具和JSON。**Verified:** `live-http-100-users.json`各100requests的max(ms)：availability418.887、weekly129.942、applications440.607、eligibility186.209、history242.695、permissionrefresh140.059、adminnavigation173.001，全部低於各预算。另APIbarrier applications705.244/approvals390.115；SVGrequest11.335/marker1006.577。**Limits:** 真TCP+DB、上游AuthMockTransport；一次固定100asyncclients、1admin混合，不是100真瀏覽器/持續soak。workerpoll+request<3s的設定只是headroom，DBpool/Edge/device延遲仍待實測。

<!-- section:privacy -->

## 23. privacy

**Coverage: Medium.** 已讀allreturnedfields/ownerscopes、RLS/grants、signedmap、validationerrors、ratehashes、worker/Edgepayloads與testnegativepaths。**Verified:** 公開schedule不暴露borrowerpurpose/phone；history/notifications本人或admin、role从DB；九張firstpartytableRLS與anon/authenticatedrevoke，authenticated只ownerprofiles/notificationsread；privatepushendpointservice-only、secretsredacted。NFR009明要求帳號不存在/密碼錯誤，是記錄的存在性揭露取捨並有rate limit。**Limits:** 未有校方retention/鎖屏通知政策、正式RLS/token/Storageverify；未宣稱合規認證。

<!-- section:release -->

## 24. release

**Coverage: Medium.** 已讀CI、Docker/Caddy/compose、bootstrap與READMEdeploy/backup，以及locks/原生Caddyartifact。**Verified:** CIpostgres17.11+pytestJUnit、frontendcheck/Vitest/build/audits、strictDeno securitytests、alwaysuploadreports、SHA固定actions；實際Caddyproductionconfig可validate、5builtSPAdeep links在loopback200，caddy-browser五routehydrated且任意inline被阻擋；appimageexclude test/secrets/fixtures。**Limits:** 此workspace非Gitrepo，CI未遠端跑；Docker/realTLS/正式Auth&Realtime&push/stagingmigration&rollback未完成。F1/F4已解除；F3與正式待驗收項目需列在releasegate，不能直接宣稱正式上線。

<!-- section:security -->

## 25. security

**Coverage: Medium.** 已追蹤Auth登入→真user lookup→profile→admin/owner endpoint；registration、SQL參數、RLS/grants、pushSSRFguard、upload、CSP/proxy/TLS與dependencyadvisories。**Verified:** 非user_metadata決定role；所有adminendpointDepends current_admin、borrowerforbidden/forgerytested；SQL參數化、uploadtype/magic/2MB+Caddy3MB、不收SVG；Edge雙secret/apikeyconstant-time驗證與pushserviceknownhost/HTTPSguard、denosecuritytests；OSV36/npm0。F1的High破壞性ownership缺陷已移除並有新建/既有identity回歸；F4hash CSP與實際browserblock/boot回歸已通過。**Limits:** 真cloudAuth版本/modernkeys/verifyjwt=falsegate、RLSauth.uid、Storagepolicy、實際TLS未驗收；無runtimepenetrationtest或全第三方sourceaudit。

<!-- section:stability -->

## 26. stability

**Coverage: Medium.** 已讀startup/close、errorhandlers、rules/transitions、transactions、workerlease/boundedretry與frontenderrorstates。**Verified:** DBtimeouts受控、wrongtransition拒絕、rejectionreason、handover/returnactor、auditnotify原子；hung-providerTimeoutError被捕捉並持久重試，其他notification不被阻塞；滿batchdrain避免固定sleep累積。F2後頁不可達已修；F3跨服務profile缺失需介入。**Limits:** 不保證所有externalmalformedresponse或productionoutage場景；無processkill/正式failover/裝置實測。

<!-- section:supply-chain -->

## 27. supply-chain

**Coverage: Medium.** 已讀fullPython/npm/Deno locks、manifests、SHAactions、dependencyaudit脚本與工具結果。**Verified:** Python36pinnedpackages OSVfindings[]；frontendnpmaudit0；Starlette1.7.0已固定；TEST_REPORT的Deno2.9.7check/tests＋denolock，CI固定2.9.6；Caddy2.10.2官方releasechecksumverified。**Limits:** advisory時間點2026-10-11，不證明未公開漏洞；未全面稽核所有transitiveDeno advisories、Dockerimageprovenance/signing、registryaccount或SBOM。無Gitrepo不能證明releasecommit。

<!-- section:testing -->

## 28. testing

**Coverage: Medium.** 已讀全部unit/integration/browser/load tests及fixtures，核對最新XML/JSON。**Verified:** 89pytest無skip/failure、14Vitest包括5logout、20browserchecks；業務negativecases、pointssuspension、roleforge、clockboundaries、maptimeout/late、realSQLconstraint/workerretry被測。F1new/existing-unconfirmed保留、零DELETE、同UUIDretry及F2>100violation後頁/結案已加入89-test suite；borrower-selection3例新增於14Vitest。**Limits:** 審查者沒有重跑DBtests；環境先前TooManyConnections資源問題已由fresh最後XML0failure解除，沒有以舊failurepng冒充正式capture或只對test文字計數。

<!-- section:testing-authenticity -->

## 29. testing-authenticity

**Coverage: High.** 已讀conftest/harness/live_load/e2e/production_browser/concurrency/metrics與fixtures執行路徑，核對artifacts。**Verified:** integration真的asyncpg+Postgres，concurrencydirectSQL100獨立connections且winnerheld到99waiters；liveTCPFastAPI，borrower100distinctUUID，HTTPlatencies量測真response而非硬編通過；browser真的DOM/keyboard/overflow/screenshot。production_browser另走實際Caddy builtfallback、等待5route DOM標題、檢查CSPmeta/header並注入不受信任script以確認被阻擋；非只檢查HTTP200。upstreamAuth/Storage/Push明確mock、mockclock只測邏輯。**Limits:** 因mock不得宣稱bcrypt已確認、真Realtime/provider/device3s、real100campususers/正式precisecoordinates；`scripts/verify_supabase.py`提供驗收入口但尚無完成artifact。所有報告以這個範圍解讀。

<!-- section:type-safety -->

## 30. type-safety

**Coverage: High.** 已讀models/rules、SQLtypes/constraints、TSinterfaces/api/generics/time/map-loader及Edge/denoconfig。**Verified:** inputUUID、email、enum、length/range與timezone驗證；Svelte/TScheck0errors/warnings、strictDenocheck；APIstatus/Collection/Profile/Room/Notice共同types，DB仍以constraints守狀態/time/foreignkeys。**Limits:** generics不驗遠端JSON，response_json及signedURLguards有runtime範圍檢查但沒有證明真cloud所有responsevariants；F1原為語意ownership缺陷，已改安全保留；型別正確本身不能防止此類風險。

### Principles analysis

KISS/YAGNI：当前小型分層不需新增微服務或全面重構；F2修正沿用有界分页即可。DRY/SRP：rules、time、status、transactionhelper已集中；F1已移除「查無profile就delete」；F3須為Auth provision提供可追踪恢復責任。Fail-fast與最小權限：productionTLS/roleguards、APIadminDepends及排他constraint有證據；不要以fail-fast誤刪未知身份。其餘未有具體根因的原則不另列finding。

<!-- section:fix-order -->

## 31. Recommended Fix Order

1. **F3:** 在不刪未知Auth的安全邊界內加入可定位的provision/reconciliation、告警或受控repair command；保留核實來源的runbook。
2. 正式部署驗收（非新增finding）：真SupabaseAuth/email/hash/RLS/Storage/Realtime、provider/deviceeventtiming、Docker/proxy/HTTPS及校方名冊圖資；使用verify_supabase.py與SPEC，不以localmock或HTTPCaddy代填。
3. 已修F1/F2/F4的回歸納入現有CI／build檢查；89pytest、14前端、20browser與actualCaddyhash/hydration均已有本輪artifact，不需為無變更的已通過案例重跑。

<!-- section:quick-wins -->

## 32. Quick Wins

- **F3:** 先讓pendingreconciliation事件有不含email/password/token的safe correlation與受控維運告警；這改善定位，未等同durablerecovery。
- 以README新runbook人工核實來源／名冊補建profile；不復原F1破壞性DELETE，不批量刪除候選Auth身份。

**Report validation:** 最終已用 skill `scripts/report_lint.py --modes full docs/AUDIT_REPORT.md` 驗證 sections / 26 dimensions / fields / enums / statistics，結果 `docs/AUDIT_REPORT.md: OK`、exit0；本輪最後回填後再次lint通過。人工檢查已區分目前findings、已修ledger、mock與正式未驗收，不含實際secret。
