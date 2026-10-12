# 真實 Google 串接與連線效能變更審查

日期：2026-10-13（Asia/Taipei）。本次依 fuck-my-shit-mountain 審查新增 auth／pool／timing 變更，銜接既有完整 repository 審計；未重複宣稱所有外部服務已驗收。

## 範圍與證據

- `app/auth.py`：canonical Supabase 驗證、學校信箱與 profile 比對、角色依賴及資格聚合查詢。沒有 token／profile cache，停權資料每次讀取。
- `app/database.py`、`app/main.py`：pool initialization／release、交易使用及安全 middleware。核對鎖定 asyncpg 0.32.0 的 pool 實作：custom reset 前仍執行 internal reset／rollback；SQL reset 保留 session settings、cursor、LISTEN、advisory lock 清理，最後還原 ntou_backend；reset 失敗會終止連線。
- `tests/harness.py`、`tests/test_api.py`、`tests/unit/test_auth.py`、`tests/unit/test_security.py`：立即停權、撤銷驗證、清理／角色隔離與 timing 正常／錯誤分支；所有 DB 測試受 loopback 與專用資料庫名稱限制，未清空真實 Supabase。

## 修正與回歸

資格 API 原本重複 acquire／查詢，暖請求約六次 DB 往返；合併 profile／points、初始化角色及 reset 後約兩次。`Server-Timing` 使用 monotonic clock，涵蓋驗證、查詢與 awaited cleanup 到回應標頭完成；只公開毫秒數。早期 400／503 也帶既有安全標頭。

Ruff check／format check、完整 218 項 pytest 通過。100 筆並行核准為 1 筆 200、99 筆 409，approved_rows=1；直接 SQL 競爭為 1 筆成功、99 筆 23P01，輸家交易 rollback。證據：`reports/real-google-pytest.xml`、`reports/upgrade-concurrency-api.json`、`reports/upgrade-concurrency-direct-sql.json`。

實際本人學校登入、onboarding、session persistence 與 borrower HTTP 403 已驗證，詳見 `reports/real-google-acceptance.json`；此報告沒有姓名、信箱、證號、電話或 token。

## 未完成與覆蓋限制

本次程式路徑審查未發現具體高優先級安全缺陷。**NFR-006 實際效能仍未達標**：本機連 Sydney 的後端測量約 768–1105ms，高於 500ms。不得以 fixture、瀏覽器橋接或重新命名時限宣稱通過；部署環境及負載驗收仍待處理。

未驗證自然 token refresh、真實裝置推播、正式教室與課程資料、正式 HTTPS 或完整雲端 100 人負載。正式部署已依使用者要求暫緩；這些限制保留在規格與驗收報告中。
