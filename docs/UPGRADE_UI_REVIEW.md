disposition: ship

以 degraded finish-reviewer inline 執行；code-led 無 approved comp／comp-diff，本包未提供 decision comp／QUALITY BAR card，依已固定 OWN-WORLD 與 craft floor 評審；不重跑 detector。最後F3只改Auth收尾，DOM/tokens未變；同reviewer重看最後重擷取E2E8＋Caddy1，既有Auth5保留。此 ship 僅涵蓋下列本機渲染與已驗行為，工程／正式部署結論另見 UPGRADE_AUDIT_REPORT.md。

## persistence

Pass。2026-10-12 新版資料包按 root 最後指定的 **Auth5＋E2E8＋Caddy1＝14張**逐張查看原圖；全數有正確 document top、符合命名的內容、1440px desktop／375px mobile，無黑或未渲染區。本輪不使用 failure／debug 或 2026-10-11 密碼版畫面。

| Packet | Files inspected in backend/reports                                                                                                                                                                                                                                      | Evidence                                                                                                                                         |
| ------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------ |
| Auth5  | upgrade-auth-login-desktop.png；upgrade-auth-callback-cancel-desktop.png；upgrade-auth-callback-invalid-code-desktop.png；upgrade-auth-onboarding-desktop.png；upgrade-auth-onboarding-mobile.png                                                                       | upgrade-auth-ui-captures.json：5張passed，首次表單停在送出前；真app/HTTP/PG，Google/Supabase上游fixture。                                        |
| E2E8   | upgrade-e2e-home-desktop.png；upgrade-e2e-home-mobile.png；upgrade-e2e-room-mobile.png；upgrade-e2e-admin-desktop.png；upgrade-e2e-violations-desktop.png；upgrade-e2e-violations-mobile.png；upgrade-e2e-map-fallback-mobile.png；upgrade-e2e-onboarding-completed.png | upgrade-e2e-browser.json：31checks全部passed，包含guestCTA、querysnapshot、cross-tab/lateowner、業務lifecycle/onboarding。                       |
| Caddy1 | upgrade-caddy-home-desktop.png                                                                                                                                                                                                                                          | upgrade-caddy-browser.json：7routes hydrated、guest兩route登入提示、page_errors=[]、bootstrap hash可執行/任意inline被擋；loopbackHTTP非TLS驗收。 |

PRODUCT.md、.impeccable/contracts/frontend.md、surface contract、DESIGN.md及design.json均存在；source/CSS對應Google-only延伸與既有token。未要求comp-led建置，state／批准comp／hero/finaldiff不適用；原生SVG導引圖無shipping raster義務。

鍵盤/RWD與動畫證據來自真Chrome測試及其assertions：375/768/1440無整頁溢出、週課表keyboard切換與手機按日、Googlebutton可鍵盤啟動；real GSAP一般模式觀察148次style變更、reduce為0，三輪快速account/home導覽後style清理／卸載不再更新。截圖只證畫面，不以靜態圖推斷焦點時序、動畫或跨帳號隔離。未做screen reader/zoom、正式Google/provider/hook、真TLS/Docker、Realtime/裝置Push或校方位置驗收。

## fidelity

先從畫面盤點：深海藍固定導覽與line-icon品牌，白工作面上為查詢欄位/比較列；teal主要動作與文字狀態；手機將導覽置頂、表單順序保留、資訊列重排。新登入只有一個Google動作，callback錯誤有可見理由/重試，onboarding四欄與唯讀email清楚；管理台逐條操作與獨立分頁；map pin、ENG-201代碼與常駐位置文字構成簽名。

| Element / promise             | Classification        | Render/source evidence and authority                                                                                                                                       |
| ----------------------------- | --------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| TYPE                          | match                 | 系統中文無外部字體，H1/section/label/metadata有大小與字重階層，數字/時段可比較。OWN-WORLD明示此字體，屬固定Operate方向，不因通用display-font偏好重做。                     |
| MATERIAL                      | match                 | SVG做精確幾何示意圖／marker與統一線圖示，沒有仿紙、雕刻、玻璃或照片替身；文字明示未獲校方確認。契約未要求raster/photo。                                                    |
| GROUND                        | match                 | Caddy原圖取樣navy(10,10)=#123a4d、ground(280,90)=#f5f7f6、paper(350,270)=#ffffff、teal(1260,330)=#087c75，與app.css/既有DESIGN及OWN-WORLD一致，沒有擅改暖cream或藍黑地色。 |
| THESIS                        | match                 | 首頁直接查時段，容量/設備/位置/狀態與查看動作按列比較；未新增行銷hero或虛構統計。                                                                                          |
| OWN-WORLD                     | match                 | 白工作面、海藍導覽、青綠動作與克制線圖示跨查詢/Auth/admin一致。                                                                                                            |
| STORY                         | match                 | Google登入→唯讀校園email＋四欄資料→借用資格/提出申請；管理台審核/鑰匙生命週期由31E2E驗證，照片不替代API成功。                                                              |
| FIRST VIEWPORT                | acceptable adaptation | Desktop保留252px sidebar、查詢表單在比較結果前；375px導覽置頂、日期全寬/時間兩欄、資訊列分組，依既定mobile contract及NFR-004適配。                                         |
| FORM                          | match                 | FORM保留seed key5de9e9fc／candidate3。room原圖pin對应ENG-201、floor與常駐文字；fallback保留文字與示範提示，簽名未稀釋。                                                    |
| Google/callback extension     | acceptable adaptation | SPECv1.1要求Google-only；移除舊password表單，取消/失效有具體錯誤與重新登入/先查教室路徑，無新增未授權視覺方向。                                                            |
| Onboarding extension          | acceptable adaptation | SPECv1.1要求四欄基本資料，email只讀；desktop分欄、375px堆疊確認資訊，送出動作及輸入皆可见。                                                                                |
| Pagination/operational states | match                 | 102人/101違規分頁、保留選擇提示、狀態文字及結案動作desktop/mobile可見；query loading/error/fallback/guest恢復由測試驗證。                                                  |

CSS主要色對比計算：muted/ground4.89:1、muted/white5.26:1、white/teal5.06:1、ink/white12.80:1；placeholder使用muted、opacity1，focus-visible為teal輪廓（onboarding圖亦可見）。這是抽查既有色對及畫面，不是完整WCAG認證。

## ceiling

Reached within the committed Operate world；未提供獨立QUALITY BAR card，不能聲稱超過未知card上限。比較列、地點代碼/常駐位置、狀態文字、就地管理操作與主查詢動作已形成可辨識的校園導引紀律。GSAP以results前12列0.22s＋0.06s為主要更新節奏，page/location0.24s、status僅變更0.16s；transform/opacity與reduced-motion/lifecycle限制有明示需求，未因一般motion palette加入blur/clip動畫。Refuse檢查沒有kicker、行銷metrics、glyph icon、gradienttext、厚側stripe、仿物材質或nested裝飾card。示範room/fixture個資明示於banner/測試包，沒有當成校方正式圖資或雲端SLA。

## material_fixes

None within this rendered packet and visual contract. 初稿recapture缺的Google/callback/onboarding畫面已由root最後指定Auth5包補足，14張驗證完畢；本輪無style fix、rebuild或額外資產生成要求。工程F3已由新34Vitest及最後31E2E/Caddy7route的source/build證據閉合，工程報告保留原因；本視覺ship不代替正式部署判定。

## keep

保留同源幾何位置點＋教室代碼＋常駐文字、查詢與結果的可比較層級、Google-only四欄onboarding、文字狀態/恢復CTA及reduce/cleanup紀律；demo標示與本機/雲端驗收界線不能淡化。
