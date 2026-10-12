> 歷史報告：以下是 2026-10-11 的密碼／名冊版本與拆分前路徑。2026-10-12 已改為 Google-only 並拆成兩個 repository；本文件保留當時證據，不能當成新版登入／部署驗收。新版結果見 UPGRADE_TEST_REPORT.md 與 UPGRADE_AUDIT_REPORT.md。

disposition: ship

Missing inputs: 本次為 code-led Operate，沒有 approved comp、diff report、QUALITY BAR card 或 critique-reference image；以已讀方向契約與產品真實性作判定，不臆造圖像承諾。此 disposition 只覆蓋下列七張有效E2Ecapture及一張actualCaddyproductionbuild首頁；新增違規分頁和CSP修復已完成修後verdict。

## persistence

Pass：`PRODUCT.md`、`.impeccable/contracts/frontend.md`、`.impeccable/surfaces/frontend-src-routes-page-svelte.md` 均存在且定義校園導引標誌的任務。FORM 的 seed key `5de9e9fc` 與 `.impeccable/questions/roll.json` key 一致；code-led 沒有 comp round，無須杜撰 approved comp 或 comp-led state。現在 `DESIGN.md`、`.impeccable/design.json` 已產出；已讀 DESIGN 的 token/色彩/布局與畫面一致，新世界文件是在本輪 finish 過程中萃取。

已重新開啟七張最新完整capture（2026-10-11T15:28:07Z packet）：[home desktop](C:/Project/ntouse-g10/reports/e2e-home-desktop.png)、[home mobile](C:/Project/ntouse-g10/reports/e2e-home-mobile.png)、[room mobile](C:/Project/ntouse-g10/reports/e2e-room-mobile.png)、[map fallback mobile](C:/Project/ntouse-g10/reports/e2e-map-fallback-mobile.png)、[admin desktop](C:/Project/ntouse-g10/reports/e2e-admin-desktop.png)、[violations desktop](C:/Project/ntouse-g10/reports/e2e-violations-desktop.png)、[violations mobile](C:/Project/ntouse-g10/reports/e2e-violations-mobile.png)；另外已重讀[actualCaddy home desktop](C:/Project/ntouse-g10/reports/caddy-home-desktop.png)。各自包含正常頁首、主要工作區與頁尾，無錯路由、空白、加载佔位或無內容的大面積異常；舊 failure screenshot 不納入本輪。

工程 full audit 另存 [AUDIT_REPORT.md](C:/Project/ntouse-g10/docs/AUDIT_REPORT.md)，26 dimensions、全部 FR/FRA/NFR trace、必要 markers/fields/stats，full report_lint通過。F1已從當前source移除全部Auth DELETE、修後89tests含新建／既有未確認identity保留+retry+零DELETE；F2已補API有界分頁與20筆UI獨立分頁、selectedUUID保持，API101筆與14前端測試通過，20-check browser report已驗101borrowers/violations與mobile結案，7captures已重讀。剩餘F3 Medium是已確認identity缺profile仍需核實來源／名冊後人工恢復。F4已由framework hash CSP、reviewer獨立bootstrap SHA256核對及actualCaddy五routehydration解除；caddy-browser.json的bootstrap_hash_allowed/untrusted_inline_blocked皆true、page_errors=[]，Caddy首頁畫面正常。先前5rawHTTP200單獨只證明HTMLfallback可取。此ship覆蓋修後7capture與Caddy畫面，正式Supabase/TLS/裝置驗收仍待完成。已核對先前200.html深連結与離線logout清project持久token/private subscriptions。

## fidelity

| Element / contract promise | Classification                | Capture / source evidence                                                                                                                                  |
| -------------------------- | ----------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------- |
| TYPE / OWN-WORLD           | match                         | 繁體中文系統無襯線字體、任務標題/欄位/代碼/次文層級一致；app.css本機字型堆疊與畫面相符。契約沒有特殊display lettering承諾。                                |
| MATERIAL                   | match                         | 地圖是明確本地幾何SVG、統一線條icons、平面工作控件；無仿紙、金屬、粉筆或需要raster卻用CSS冒充的物質。code-led契約未要求照片或rasterplate。                 |
| GROUND / OWN-WORLD         | match                         | 白工作面、灰綠地面、深海藍導覽、青綠操作與狀態，與契約/現有CSS/DESIGN值一致；無無根據的暖紙/暗色底替換。無approvedcomp供雙側取樣，未宣稱pixelmatch。       |
| THESIS                     | match                         | desktop列表同時保留位置、設備、容量、可借用狀態及查看；mobile仍逐項完整保留，沒有行銷hero或虛構統計取代查詢。                                              |
| STORY                      | match                         | 查詢→房間資訊/位置/提醒→申請；admin状态tabs与empty state接續管理流程。其審核/交付/歸還行為證據來自browser report，而非靜態圖臆測。                         |
| FIRST VIEWPORT             | match / acceptable adaptation | desktop252pxsidebar+上方查詢/邻近按钮+資訊列；mobile導覽移頂、時間兩欄、資訊列重排，是surface brief FIRST VIEWPORT/RWD与产品手机操作要求的明文adaptation。 |
| FORM / signature           | match                         | roommobile位置點標記ENG-201、房間代碼與常駐樓層/位置文字同時可見；fallbackcapture保留位置文字與座標而非空白map。seed record存在。                          |
| Truth / demonstration      | match                         | 每張頁首顯示示範教室/位置名冊未校方確認；room及fallback再次標示示範位置。測試者標為測試使用者，無真實名冊/精確校園測量/雲端推播成功宣稱。                  |
| F2 / pagination extension  | match                         | 新desktop/mobile capture顯示兩個獨立pager、被選借用人及最舊未結案紀錄，browser20checks含>100資料與結案；沿用原型式/色彩，mobile换行是既有RWDadaptation。   |
| Floor / control clarity    | match                         | 線條SVG圖示、無gradienttext/hardoffsetshadow/側條/仿材質，狀態帶文字；列表/表單對齊且沒有可見遮擋、裁切或overflow。未重跑detector。                        |

Keyboard / RWD證據來源是 [e2e-browser.json](C:/Project/ntouse-g10/reports/e2e-browser.json) 2026-10-11T15:28:07Z 的20 checks與 `tests/e2e.cjs`：375/768/1440首頁與admin整頁無橫向溢出，週課表focus+Enter与mobile按日、login Tab/Enter、borrower admin denied及既有token停權皆passed。SVGprotocolrequest11.335ms、navigation-to-marker1006.577ms。沒有親自screenreader、200%zoom、全route全focus序列或100真瀏覽器測試，不把静态capture当键盘证明。

## ceiling

Contract ceiling reached：原生校園導引器材是明確代碼、樓層、位置點、固定資訊欄與逐狀態文字，畫面均已使用。此工作介面沒有契約要求的材質深度、裝飾、特殊字體或動態未用。QUALITY BAR card未提供，無法評定其額外承諾；沒有據此杜撰新增資產或重設計要求。

## material_fixes

無：此七張E2Ecapture與actualCaddy首頁的方向／真實性／craft檢查沒有missing或contradicted項。verdict：F2 resolved — desktop與mobile均可見使用者101–102/102、違規101–101/101、保留所選借用人、最舊未結案的名字/ID及結案button；手機pagers正常換行、無遮擋或整頁overflow，20-check browser報告實際完成選人保持與結案。remaining：clear（這個ship覆蓋F2/F4修復、七張E2Epacket與actualCaddy首頁）；F4 resolved — actualCaddy首頁正常hydrated、與baseline布局一致，5route無pageerror並阻擋任意inline。

## keep

保留可比較資訊列、中文狀態文字、位置點與代碼＋常駐位置fallback的簽名，以及深海藍／白工作面／青綠操作的現有方向。
