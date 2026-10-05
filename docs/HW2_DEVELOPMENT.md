# HW2 開發與交付說明

本專案使用 Codex 協助閱讀課程文件、理解 HW1、實作、取得語料、執行測試與撰寫分析。保留 `ir_hw1` 搜尋引擎，新增 `ir_hw2` 分離固定實驗與搜尋特徵；原 HW1 專案唯讀，HW2 原有 untracked 基礎皆保留。

各項調整的原因、現行設定、受影響檔案與驗證證據，集中記錄於 [HW2_CHANGELOG](HW2_CHANGELOG.md)。後續修改同步更新該紀錄及相關操作文件；只補文件時不將既有測試結果描述成重新執行。

2026-09-30 Word2Vec 故障修復：實際網站使用缺少 gensim 的舊 `.venv`，與測試的 `.venv-hw2` 不同；已重啟到正確環境，UI 增加套件載入失敗說明，啟動腳本增加套件檢查。5 項新增 UI 測試涵蓋缺套件、查詢與訓練，最新完整回歸 492 passed in 56.72s（原348＋HW2 144），見 `reports/hw2/word2vec-fix/`。本輪有 Word2Vec 真實瀏覽器補驗；下方 487 項與未重做瀏覽器的說明均為此修復之前的四組交付紀錄。

初版由環境／測試／拼字、語料、分析等工作者分工，主工作者整合 CLI、模型、搜尋副本與UI。2026-09-30原切詞版中，分析工作者負責原tokenizer契約、統計測試及本次文件；模型／拼字工作者更新對應契約與測試；語料工作者負責獨立統計驗證；主工作者負責UI、正式模型／完整回歸、讀圖指南、PDF及交付核對。每次明確分配檔案，不還原他人變更。

## 目前方法與重要界線

分析版本 `hw2-hw1-four-conditions-v5-log10`：A為基本空白切詞與正規化，B用HW1 `tokenize`處理標點，C去固定停用詞，D用HW1 `stem_term`。各組共用NFC／casefold；B保留GLP-1、小數及支援的內部撇號。完整比較A→B→C→D；UI預設顯示A、可依序切換。分析IDF及回歸使用log10，既有搜尋IDF／特徵展開獨立保留。

`baseline_tokenizer_spec()` 記錄實作、版本、regex、normalization、source hash及依賴，不含分析整體版本或log底數。本版沿用保存的B條件模型並重新驗證離線重載，沒有再次訓練。模型schema2儲存完整契約，重載拒絕缺少或不一致契約；拼字詞彙快取同樣包含版本與契約，避免UI rerun沿用舊詞彙。HW1 preprocessing未修改。

所有正式數字取自同一1000篇PubMed快照。合成資料只供手算測試；沒有人工語意／相關性gold standard，不將近鄰當正確率，也不將ΣDF代理量當實測壓縮bytes。Porter明示NLTK MARTIN_EXTENSIONS，不冒稱手刻；Levenshtein DP由本專案實作。

## 模組與重現入口

| 模組／指令 | 責任 |
| --- | --- |
| `ir_hw2/corpus.py` | 原XML、查詢、去重、英文非空摘要、固定快照、快取與續傳 |
| `ir_hw2/analysis.py` | 原HW1 tokenizer契約、A–D、CF／DF／log10 IDF、16回歸與圖表 |
| `ir_hw2/embeddings.py` | 有序句子的Skip-gram、模型契約、重載、近鄰／OOV |
| `ir_hw2/spelling.py` | Levenshtein DP、距離／CF候選排序、術語保護與opt-in |
| `ir_hw2/integration.py` | 固定快照的獨立搜尋副本 |
| `ir_hw2/cli.py`、`ui.py`、`app.py` | 明確觸發昂貴操作、繁中比較／搜尋／高亮介面 |
| `scripts/setup_hw2.ps1` | HW2新環境與路徑驗證 |
| `scripts/verify_hw2_tokenizer.py` | 獨立原token序列／統計／NumPy OLS檢查，另存分析比對21輸出 |
| `scripts/verify_hw2.py` | 正式快照、模型重載、搜尋／高亮及拼字的離線核對 |
| `scripts/build_hw2_reports.py` | 主報告與另頁摘要PDF匯出 |
| `scripts/verify_hw2_delivery.py` | 報告／模型句序／全套測試／最新PDF指紋整合核對 |

先執行完整pytest、兩個一般verify；變更報告後重建PDF，再跑delivery核對。後者不替代渲染視覺檢查。操作及命令見README／HW2_DEMO，需求追蹤與歷史演進見HW2_PLAN。

## 驗證證據的範圍

修改前342 passed加6個缺歷史Git fixture的setup errors，與程式assertion failure分開；修復真實fixture可攜性後原348項通過。各階段XML及來源hash保留，未刪測試或弱化斷言。本次作業四條件v5最終487 passed（原348＋HW2 139，50.69秒），三組試行已撤回。驗證以 `pytest-hw1-tokenizer.xml`、`tokenizer_verification.json`、`formal-verification.json` 為準；舊444／450紀錄不代表新版測試數。

原切詞版4張PNG已視覺查看，Streamlit AppTest包含在最終回歸；互動讀圖指南有明暗／手機尺寸QA。2026-09-29真實瀏覽器與截圖屬初版歷史，本版未聲稱重新用瀏覽器操作整個demo。

主工作者MCP曾回報Transport closed，使用直接原始碼／測試補證；獨立工作者另確認HW2 project與2026-09-30T07:02:58Z generation，13個指定路徑coverage metadata_match／no_recorded_issue。詳 `tokenizer_graph_coverage.json`；這不是全repo完整性證明，也不代表所有工具連線恢復。

自然對數初版與全符號拆詞log10版已分別封存於 `reports/hw2/history/`。原 `DEVELOPMENT_PLAN.md`、SYSTEM、SEARCH_REDESIGN、RESULTS保留歷史含義，目前進度不從舊待辦清單推定。
