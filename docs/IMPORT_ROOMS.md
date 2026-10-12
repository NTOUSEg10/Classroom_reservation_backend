# 正式教室清單匯入

使用者尚未取得校方確認資料，真實 Supabase 仍為空清單。本工具只匯入教室基礎資料；週課表由平台借用紀錄產生，校方定期課程同步仍為 SPEC 的 Non-goal。

## 準備資料

複製 `data/rooms-template.csv` 為 `.local/rooms.csv`，依校方清單填入資料。模板只有標頭，沒有示範教室；實際資料檔請放 Git 忽略的 `.local/`，不要用它儲存借用人資料或憑證。

以 UTF-8 CSV 儲存，可有 BOM；模板的 13 欄皆須存在，可調整順序，不能新增或重複欄位。每檔最多 2 MiB、2000 筆。文字中若有逗號／雙引號，使用標準 CSV 引號；Excel 匯出請選 UTF-8，教室代碼欄設為文字，避免前導零消失。

| 欄位                   | 格式與用途                                                                            |
| ---------------------- | ------------------------------------------------------------------------------------- |
| `code`                 | 1–40 位英數及 `.`、`_`、`-`，首字為英數；同一代碼更新既有教室，改代碼會新增另一間教室 |
| `name`                 | 教室名稱，必填，最多 100 字元                                                         |
| `building`             | 建築名稱，必填，最多 100 字元                                                         |
| `floor`                | -20–100 的整數樓層；地下樓層為負數                                                    |
| `capacity`             | 1–1000 人的整數容量                                                                   |
| `equipment`            | 設備以 `\|` 分隔；沒有設備可留空，最多 20 項、不重複、每項最多 80 字元                |
| `latitude`,`longitude` | 可同時留空；填寫時需成對且在經緯度範圍內                                              |
| `map_x`,`map_y`        | 可同時留空；圖上座標 0–100，需成對                                                    |
| `location_text`        | 必填的位置文字描述，最多 1000 字元，地圖失敗時仍可閱讀                                |
| `location_verified`    | `true`／`false`；只有校方確認資料才能填 `true`                                        |
| `active`               | `true`／`false`；設為 `false` 暫停新借用，不刪除既有紀錄                              |

工具檢查格式及範圍，無法判斷教室位置是否真實、是否獲校方確認。不要自行編造經緯度，也不要把測試 seed 當成正式資料。

## 先驗證，再寫入

在後端 repository 及已安裝 `requirements.lock` 的 Python 環境執行：

```powershell
python -m scripts.import_rooms .local/rooms.csv
```

預設完全不連 DB、不讀取 Supabase token；只檢查整份檔案並輸出通過筆數。空白模板不是有效資料集，請先填至少一筆校方確認資料。若有錯，修正指出的列／欄位後再驗證。

寫入需要受信任維運人員的 `DATABASE_MIGRATION_URL`；不能使用應用程式的 `DATABASE_URL`，也不能把 DB 密碼放命令列或聊天。可在 Git 忽略的 `.local/room-import.env` 填入這兩個設定：

```dotenv
DATABASE_MIGRATION_URL=<校方專案的 migration／owner 連線>
DATABASE_SSL_CA_FILE=<Supabase 憑證的本機絕對路徑>
```

確認檔案及目標專案後，在 PowerShell 透過既有的 dotenv 套件載入私有檔案，再執行：

```powershell
python -c 'from dotenv import load_dotenv; load_dotenv(".local/room-import.env", override=True); import runpy; runpy.run_module("scripts.import_rooms", run_name="__main__")' .local/rooms.csv --apply
```

也可由受信任的部署工具事先提供相同環境變數，直接執行 `python -m scripts.import_rooms .local/rooms.csv --apply`。遠端連線必須驗證 TLS 與 hostname；不要透過關閉 SSL 解決憑證錯誤。正式操作前應依既有備份流程保存資料庫。

## 寫入語意與驗收

- 所有 CSV 列先完成驗證才連線；整批寫入包在同一 DB 交易。格式錯誤、權限錯誤、鎖定逾時或中途 SQL 錯誤都不產生部分成功。
- 以 `code` 新增／更新 metadata，既有 UUID 與 `map_path` 不變；預約、審核、鑰匙、通知及帳號紀錄不受此工具修改。
- 同一代碼的所有 CSV metadata 會覆寫，空白座標清為空值、空白設備清為空清單；教室代碼區分大小寫。請完整填妥每筆資料，確認後再執行。
- 檔案外的教室保留。要暫停借用，明確將該代碼的 `active` 改為 `false`；不要刪除歷史教室。
- 同一份檔案重跑不增加重複教室。修改容量／設備／位置等會更新 metadata；既有借用保留，重大變動須由管理員另行檢查。
- 成功後，在平台重新查詢確認名稱、容量與文字位置，再選時段及教室週課表。匯入清單不會自動建立預約、課程或地圖檔案。

單元測試驗證錯誤輸入、離線模式及憑證不出現在錯誤輸出；隔離 PostgreSQL 測試驗證重複匯入、保留 UUID／圖資／預約、整批 rollback 與受限角色拒絕。正式清單尚未提供，因此本輪不對真實 Supabase 執行 `--apply`，也不把隔離測試記為正式資料已匯入。
