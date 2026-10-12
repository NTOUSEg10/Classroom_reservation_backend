# 海大教室借用平台 — 教室匯入與 token refresh 增量審計

模式：`incremental,security,data-integrity,documentation,testing-authenticity`

日期：2026-10-13（Asia/Taipei）

審查範圍：明確指定的兩個 repository 工作樹，包含 staged／unstaged／untracked 檔案；沒有 fetch、切換分支或修改資料庫。

<!-- section:executive-summary -->

## 執行摘要

在本次限定範圍未發現尚未修正的 Critical／High／Medium／Low 缺陷。CSV 工具預設離線，只有明確 `--apply` 才使用維運 owner 連線；更新保留既有教室 UUID、圖資路徑與借用紀錄。新增前端測試驗證同帳號 token refresh 後使用新 token 並更新身分，不清空通知。

初查發現文件宣稱欄位錯誤提示、實作只有列號的小矛盾，已由實作修正成列號與欄位名稱，且不輸出原始資料；本報告統計的是最終快照的未修正問題。實際教室清單未提供，本輪沒有對真實 Supabase 執行匯入。測試帳號刷新事件不是自然的真實 OAuth refresh 驗收，這份增量審計也不是正式上線或完整 NFR 認證。

<!-- section:score-dashboard -->

## 評分

| 面向            | 分數         | 等級 | 覆蓋信心     | 依據與限制                                                                                            |
| --------------- | ------------ | ---- | ------------ | ----------------------------------------------------------------------------------------------------- |
| Security        | 9.0          | S    | Medium       | 追蹤 owner、SQL 參數、TLS 與秘密錯誤處理；未執行新 owner 真實雲端匯入                                 |
| Stability       | 9.0          | S    | Medium       | 追蹤單一交易、重跑與資料保留，讀取隔離 DB 測試結果；審查者未重跑共享 DB 測試                          |
| Testing         | 9.0          | S    | Medium       | 獨立執行 50 項 unit；讀取 55 項工具測試報告與 273 項完整回歸結果；refresh 的真實 SDK 流程仍未自然驗收 |
| Maintainability | 9.0          | S    | Medium       | 沿用既有套件及 TLS helper，CLI／文件契約相符；不評其他功能                                            |
| Release         | 9.0          | S    | Medium       | 明確區分空白模板、私有 owner 設定與正式資料，沒有 schema／權限變更；不評部署完成度                    |
| Performance     | Not assessed | —    | Not assessed | 此輪不追蹤 500ms 指標或執行效能量測                                                                   |
| Design          | Not assessed | —    | Not assessed | 沒有介面或整體架構變更，未重新評分                                                                    |
| Overall         | 9.0          | S    | —            | 已評五項的算術平均；不是完整 repository 的評分                                                        |

<!-- section:project-map -->

## 專案與變更地圖

後端比較基準：`3f77fb12fd8bef2714ac473ff3cb7251202e7914`；前端比較基準：`b1e10d67dcd5b6f3121c39cd70dbf836c436e04b`。審查開始時 HEAD 分別等於這兩個基準。比較是基準到指定工作樹檔案，不採 merge-base 三點比較。

指定的 8 個功能／文件檔案：後端新增 `scripts/import_rooms.py`、`tests/unit/test_room_import.py`、`tests/test_room_import.py`、`data/rooms-template.csv`、`docs/IMPORT_ROOMS.md`，修改 `README.md`、`docs/SPEC.md`；前端修改 `src/lib/api.test.ts`。2026-10-13 審查快照合計新增 832 行、刪除 2 行；來源為 tracked `git diff --numstat` 加五個新檔的實際行數。本審計產物、測試 XML、其他後續文件修訂不列入這個變更統計。

資料流：CSV → 有界讀取與完整解析 → Pydantic 欄位驗證 → 預設輸出筆數；明確 apply → owner DSN 與 TLS → owner 檢查 → 單一 DB transaction → 以 code upsert metadata。沿用未變更的 `app/config.py`、`supabase/schema.sql`、`app/main.py` 公開查詢與 `tests/harness.py` 隔離 DB 邊界。

前端範圍只有測試；追蹤未變更的 `src/lib/api.ts` 中 Auth event → session → 延後身分驗證 → API Bearer 與同帳號通知訂閱。

執行與證據：

- 審查者執行 `python -m pytest tests/unit/test_room_import.py -q`：50 passed，1.05 秒；不連 DB。
- 讀取實作代理產出的 `reports/room-import-tests.xml`：55 tests、0 failures、0 errors，3.351 秒，包含 50 unit 與 5 隔離 PostgreSQL 測試。這是代理執行結果，審查者沒有並行重跑共享測試 DB。
- 用合成 capacity 錯誤呼叫解析器：結果為 `CSV line 2: invalid field: capacity.`，沒有回顯輸入值。
- `git diff --check` 通過。主代理另執行 Ruff check 與 format，30 個檔案通過；本報告不冒充審查者重新執行的 Ruff。
- 讀取主代理產出的 `reports/room-import-full-pytest.xml`：273 tests、0 failures、0 errors，XML 計時 52.82 秒；主代理執行完整後端 suite。前端實作代理回報 46 tests、Svelte check 0 errors／warnings、Prettier 通過；不將此結果記為審查者重跑。

排除：環境密鑰、使用者個資、雲端 owner 實際寫入、自然 OAuth refresh、裝置推播、正式課程同步、正式部署、完整 NFR／全 repository 掃描；未讀依賴目錄做全面供應鏈審計。

<!-- section:coverage -->

## 覆蓋矩陣

| Dimension            | Coverage | 已查證證據                                                 | 排除與限制                                              |
| -------------------- | -------- | ---------------------------------------------------------- | ------------------------------------------------------- |
| security             | Medium   | CLI、TLS helper、schema grants、秘密錯誤及前端 token 呼叫  | 沒有新增雲端 TLS handshake／owner apply，也不評其他 API |
| data-integrity       | Medium   | UPSERT、transaction、schema 唯一鍵／FK、五項 DB 測試與 XML | DB 測試由實作代理執行；不做真實資料寫入或恢復演練       |
| documentation        | Medium   | README、SPEC、IMPORT_ROOMS、空白模板與實際 CLI 契約        | 不重寫部署文件，也不宣稱取得正式教室資料                |
| testing-authenticity | Medium   | 新 unit／DB／refresh 測試、真實 SQL 失敗場景與安全 harness | SDK refresh 事件是 mock，完整回歸由主代理另行執行       |

<!-- section:statistics -->

## 問題統計

| Severity | Count | Confirmed | Suspected |
| -------- | ----- | --------- | --------- |
| Critical | 0     | 0         | 0         |
| High     | 0     | 0         | 0         |
| Medium   | 0     | 0         | 0         |
| Low      | 0     | 0         | 0         |
| Info     | 0     | 0         | 0         |
| Total    | 0     | 0         | 0         |

<!-- section:top-risks -->

## 主要風險

限定的最終變更沒有未修正問題。owner 匯入是高權限維運操作，文件要求核對私有檔案／目標專案及先備份；這是操作邊界，不是本次查出的越權漏洞。正式資料、自然刷新、推播與部署仍待獨立驗收。

<!-- section:findings -->

## 詳細發現

無未修正的證據支持缺陷，因此沒有新增 issue card。初查的文件／欄位提示矛盾已在最終實作修正並重新追蹤，不列入未修正問題數。

<!-- section:security -->

## 安全性

覆蓋：Medium。查閱 `scripts/import_rooms.py:83`、`:197`、`app/config.py`、`supabase/schema.sql:152` 與對應 unit／DB 測試。

- 完整欄位標頭、大小／筆數、必要文字、代碼、整數、布林、有限座標及設備限制在連線前驗證；SQL 值使用 positional parameters。
- DSN 必須有 host／user／database，拒絕 fragment 與非 sslmode query keys；弱 sslmode 不能覆寫遠端的驗證 SSL context。CA 路徑沿用既有 helper。
- 僅使用 `DATABASE_MIGRATION_URL`，不回退成 app URL；owner 檢查在 transaction 內。app role 既有 room INSERT／capacity UPDATE 禁令保持。
- DB／檔案／Pydantic 錯誤使用受控訊息，僅回筆數、列號及已知欄位，不印 DSN、密碼或資料值。沒有新增公開管理 endpoint、角色升權或登入捷徑。

未確認新增的真實 owner 連線；unit 的 SSLContext assertion 是配置驗證，不等於真實 TLS handshake。

<!-- section:data-integrity -->

## 資料一致性

覆蓋：Medium。查閱 `scripts/import_rooms.py:161`、`:176`、`tests/test_room_import.py:29`、`:102`、`:120`、`:136`。

- 唯一 code 配合 ON CONFLICT 更新同一筆 metadata；更新清單不含 id／map_path，不包含其他業務表。缺席教室不刪除。
- 整批於單一 transaction，以一致 code 排序取得 row locks，設定 lock／statement timeout；沒有 transaction 中的外部 HTTP 呼叫。
- 隔離測試以後段資料觸發真實 SQL CHECK 失敗，確認前段既有教室更新 rollback，而非 mock transaction。
- 重跑測試核對筆數、UUID、圖資、完整既有 booking、profiles 筆數及檔案外教室。公開 API 測試確認 imported metadata 可查、inactive 排除與空週課表契約。

不聲稱 import 自動處理既有借用因容量變動的管理決策；文件要求另行檢查。沒有重新測試全套 reservation 競爭，既有防重複核准約束本次未修改。

<!-- section:documentation -->

## 文件契約

覆蓋：Medium。查閱指定 README、SPEC、IMPORT_ROOMS 與模板。

- README 初始化已移除 demo-seed 預設；模板只有標頭，空模板被拒絕，沒有正式資料或虛構地點。
- 文件與 CLI 的離線預設、explicit apply、owner 私有 env、TLS、設備 delimiter、座標成對、布林及 metadata 更新語意相符。
- 週課表是平台借用紀錄，不宣稱校方課程同步；定期課程匯入維持 Non-goal。
- 欄位提示修正後與文件相符。文件不能取代確認資料真實性的人工責任。
- SPEC 保留 500ms 目標與未通過實測，並記錄依使用者指示暫停本機反覆優化；本輪沒有降規或再做效能追逐。

未驗收每個維運環境中的完整 PowerShell owner apply 指令；沒有實際資料時不執行高權限寫入。

<!-- section:testing-authenticity -->

## 測試可信度

覆蓋：Medium。查閱兩個新 Python 測試檔、`tests/harness.py`、`reports/room-import-tests.xml` 及 `frontend/src/lib/api.test.ts:180`。

- Unit 處理正常與壞 CSV、BOM、數值／NaN、重複、上限、秘密錯誤、DSN 限制及預設完全不連 DB；另用 subprocess 執行實際 module CLI。
- DB 測試使用原有 loopback／專用 DB guard；觸發實際 rollback、重跑及受限角色拒絕，不以 canned DB response 替代。
- 前端 fake timers 驗證 callback 返回後才開始身分請求；檢查下一筆一般 API 與 identity 都使用刷新 token，profile 更新且同使用者通知未清空／訂閱未重建。
- 前端 SDK 本身是 mock，不能據此宣稱 Supabase 自然 refresh grant／server-issued token 已驗收；公開報告需持續維持這個區分。

審查者沒有並行清空或重跑共享 DB fixture；完整回歸由主代理執行、前端 runtime 由實作代理執行，結果如上。GitHub CI 結果仍由主代理後續確認，不預先宣稱通過。

<!-- section:fix-order -->

## 修復順序

沒有本次增量的未修正阻擋事項。已完成完整回歸，主代理繼續 Git 保存即可。取得校方清單及指定正式管理員後，才接續相關真實操作與驗收。

<!-- section:quick-wins -->

## 小幅改善

已完成欄位提示的低成本修正。不建議為本次純資料匯入增加第三方套件、公開權限或課程同步系統。

報告驗證：使用 skill 的 `report_lint.py` 對本 Markdown 及上述五個模式檢查，已通過。人工確認沒有帳號個資、密碼、token、實際 DSN 或雲端寫入結果被記入報告。
