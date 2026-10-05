# HW2 變更紀錄

更新日期：2026-10-03。工作目錄：`C:\成大專案\IR-HW2`。

本文件集中記錄本輪方法、介面、實驗與交付調整。現行版本為 **`hw2-hw1-four-conditions-v5-log10`**；原 HW1 唯讀，HW2 原有基礎檔案保留。完整需求追蹤及各階段歷史見 [HW2_PLAN](HW2_PLAN.md)，啟動與重跑命令見 [README](../README.md)。

## 2026-10-03：補齊作業展示與分區比較圖

網站新增 CF／DF／IDF 專頁與五主題導覽。前處理數量、A–D 高頻詞、Zipf 回歸／殘差、高中低頻 R²／RMSE、DF–IDF 關係及代表詞比較分頁呈現；原始數表、設定與下載按需展開。窄視窗的高頻詞圖改為上下排列，避免四圖造成橫向溢出，標籤顯示全部詞彙。

補上 RQ1–RQ5 作業解答、389 words IR 討論與需求對照表、網站 PDF 下載。主報告增加五張資料比較圖，共九圖，附錄直接列出 A–D 各50詞；另交付一頁摘要。數值仍來自固定1,000篇的正式 summary；計算、模型、21份正式分析輸出保持不變。顯示記號使用 log，底數仍為10。

完整回歸 **497 passed in 58.18 seconds**，零失敗／錯誤／跳過，紀錄 `reports/hw2/comparisons-pytest.xml`；最後標籤／刻度調整另以17項UI及圖表測試核對。新增測試針對覆蓋率、CF／DF差別、區段最佳判準、未定義擬合與圖表資料，不重做正式訓練。PDF及瀏覽器檢查證據見 `reports/hw2/pdf_qa.json`、`reports/hw2/comparisons-qa/`。

## 2026-10-02：詞頻圖簡化與 log 顯示記號

依使用者要求，rank-frequency 改為單張 CF 對數刻度圖；移除並排的線性 CF 圖，保留線性排名軸。標題說明前處理比較，圖例直接列出 A 基本切詞與正規化、B 標點處理、C 停用詞移除、D Porter 的累積關係。

圖表、網站讀圖文字／回歸表、主報告、摘要與互動讀圖指南，將顯示記號統一為 `log`，方法文字註明以 10 為底。數值計算仍呼叫 `math.log10`／`Math.log10`；分析版本、CSV／JSON 的底數與模型契約保留，避免純顯示調整影響計算。

以固定 1,000 篇快照重新產生正式輸出，確認 A–D 全部統計、選詞資料及 16 份 CSV 與修改前一致。獨立驗證通過 21 個輸出逐位元重現與 16 組 OLS 核對；更新分析原始碼指紋與驗證紀錄。

驗證：完整回歸 **492 passed in 144.44 seconds**，零失敗／錯誤／跳過，另存 `reports/hw2/chart-labels-pytest.xml`。先前針對分析／UI 的 58 項亦通過；新增 log 顯示後以本次完整回歸為準。

## 2026-10-02：避免重新啟動時再次選到舊環境

使用者再次看到「Word2Vec 套件無法載入」。實際確認 8501 由 `.venv/Scripts/python.exe -m streamlit run app.py` 啟動，舊環境仍沒有 gensim；`.venv-hw2` 的 Word2Vec、Streamlit 與 matplotlib 匯入均正常。9/30 的重啟只修復當時的執行程序，沒有阻止日後再次使用舊指令；這次依實際程序路徑及父子關係確認後，再將 HW2 網站切換到正確環境。

新增根目錄 [start_hw2.cmd](../start_hw2.cmd)，供雙擊啟動。它以自身所在目錄定位專案，明確呼叫 `.venv-hw2/Scripts/python.exe`，啟動前檢查必要套件，再啟動 127.0.0.1:8501；不受目前 shell 的虛擬環境影響。環境不完整或連接埠占用時顯示錯誤並保留視窗，不會安裝套件、重訓模型或自動停止其他程序。README 與 demo 已同步日常啟動方式。

本次直接透過新增的啟動檔啟動網站，核對服務程序確實使用 `.venv-hw2`，再以瀏覽器核對 Word2Vec。過程記錄於 `reports/hw2/launcher-fix-20261002/`，啟動 stdout／stderr 位於 `tmp/launcher-20261002.*.log`。本次未修改分析／模型程式或重跑全套 pytest；492 項仍是 9/30 的既有結果，不能當成 10/2 重跑紀錄。

## 2026-09-30：修復 Word2Vec 網站執行環境

使用者回報 Word2Vec 完全無法使用。已在當時的 `http://127.0.0.1:8501` 實際按下「查詢近鄰」，重現 `ModuleNotFoundError: No module named 'gensim'`。原因是網站由複製的 `.venv/Scripts/python.exe` 啟動；該環境沒有 gensim，而先前 CLI／pytest 使用 `.venv-hw2`，因此先前測試通過不足以保證正在執行的網站可用。

修復內容：

- 確認舊程序路徑及父子關係後，只重啟這個 HW2 網站，改用 `.venv-hw2`，仍在 8501；保存正式模型與語料，沒有重新訓練正式模型。
- `ir_hw2/ui.py` 在 Word2Vec 頁面先載入所需套件；缺少或無法匯入時，顯示繁體中文錯誤、目前 Python 診斷與 `setup_hw2.ps1`／`start_demo.ps1` 修復指令，不再到使用者按查詢或訓練才拋出未處理例外。
- `scripts/start_demo.ps1` 啟動前檢查 Word2Vec／Streamlit／繪圖套件，顯示實際 Python 路徑；失敗就停止並提示先完成環境建置。
- `tests/test_hw2_ui.py` 新增 5 項回歸：缺少 gensim、保存模型的 GLP-1 查詢、OOV、多詞輸入，以及明確按下訓練後能查詢。訓練測試只使用臨時小型 fixture，不覆寫正式模型。

驗證：修復前新增的缺套件提示案例確實失敗；修復後 UI＋embeddings **29 passed in 16.12s**，完整回歸 **492 passed in 56.72s（原 348＋HW2 144）**，0 failure／error／skipped。此為最新程式回歸；下節 487 項仍是四組分析交付當時的歷史結果，未覆寫原紀錄。主報告／PDF 的實驗結果與原驗收紀錄保持原樣。

本輪另實際操作 Word2Vec 瀏覽器查詢：`semaglutide` 回傳 `liraglutide`（cosine 0.670418）、`GLP-1` 正常回傳近鄰、`zzzznotincorpus` 顯示 OOV、`GLP-1 receptor` 顯示單詞查詢限制。原本缺少 gensim 的舊環境也另用 AppTest 確認現在顯示修復指引，沒有未處理例外。錯誤、修復後頁面及程序證據位於 `reports/hw2/word2vec-fix/`；[修復畫面](../reports/hw2/word2vec-fix/browser-fixed.png)、[pytest-full.log](../reports/hw2/word2vec-fix/pytest-full.log)、[pytest-full.xml](../reports/hw2/word2vec-fix/pytest-full.xml)。彙整核對保存為 `reports/hw2/word2vec-fix/verification.json`。這次只補做 Word2Vec 的瀏覽器流程，不表示整個 demo 已重新操作。

## 2026-09-30：恢復作業四組，預設 A

### 1. 最後確認的前處理方式

依使用者最後指示，恢復作業要求的 **A → B → C → D** 累積比較。中途「原切詞、stopwords、Porter」三組試行已撤回，不能再作為介面、正式結果或報告的現行定義。

| 組別 | 現行定義 | 如何與上一組比較 |
| --- | --- | --- |
| A | 摘要正文以空白基本切詞，再套用 HW1 正規化／小寫；保留附著標點 | 作為未處理標點的起點 |
| B | 用原 HW1 `tokenize` 規則處理標點；保留支援的內部連字號、撇號與小數 | A→B 觀察標點處理的影響 |
| C | 從 B 移除固定 132 詞停用詞表；保留 no、not、without | B→C 觀察停用詞移除的影響 |
| D | 從 C 套用原 HW1 `stem_term`，純 ASCII 字母使用 NLTK Porter | C→D 觀察詞幹合併的影響 |

四組共用 NFC、casefold 及既有撇號／連字號正規化。B 直接由摘要原文切詞，不把 A 清單重新串接，也不加入搜尋專用的複合詞展開或額外孤立字過濾。`GLP-1`、`IL6`、`3.5` 與 `β-cells` 在 B 中保留；不宣稱這套規則是完整生醫實體辨識。

例句 `The patients GLP-1 improved 3.5 mg.`：A 保留 `mg.`；B 處理句點後得到 `mg`；C 移除 `the`；D 再將 `patients`→`patient`、`improved`→`improv`。

四組都屬正式比較，沒有額外參考組：metadata 的 `primary_comparison` 為 A／B／C／D，`reference_condition` 為 null。Porter 使用 **NLTK 3.9.2 MARTIN_EXTENSIONS**，不是自行手刻；教師是否要求自行實作仍待確認。

### 2. log、介面與圖表

- **統計分析統一採 log₁₀**：IDF=`log10(N/DF)`，不平滑、不加 1；Zipf 回歸以 `log10(rank)` 預測 `log10(CF)`，RMSE 在 `log10(CF)` 空間計算。既有搜尋的 TF-IDF 權重仍獨立保存。
- **介面預設 A**：Top 50、區段分析及條件選單從 A 開始。舊 session 的條件狀態遷移後回到 A，之後尊重使用者手動選擇；不在每次 rerun 強制重設。
- **四組輸出同步**：前處理比較、rank-frequency、log-log、殘差圖、條件選單與 CLI 說明均標示 A／B／C／D。分析版本、log 底數或 tokenizer 契約不相符時，介面提示更新結果。
- **補充讀圖說明**：說明排名與 CF、log 軸每增加 1 代表十倍、彩色實測點、黑色回歸實線，以及殘差區段虛線。高 R² 不能單獨證明 Zipf's Law。
- **互動讀圖指南使用 A 資料**：讀取正式 `terms_A.csv`，共 244,477 tokens、29,203 詞；預設例詞 `semaglutide` 是 rank 49、CF 488。這與 B 的 CF 649 不同，數字必須連同條件閱讀。指南以 `glp-1` 與 `glp-1,` 展示 A 保留附著標點的結果。

程式位置：`ir_hw2/analysis.py`、`ir_hw2/ui.py`、`ir_hw2/cli.py`；教材：[互動讀圖指南](../output/visualizations/zipf-reading-guide.html)。

### 3. 正式語料與重算結果

沿用同一份 **1,000 篇 GLP-1 英文非空 PubMed 摘要**，一 PMID 為一 document，只計摘要正文。本輪恢復四組沒有重新下載或增刪正式語料。

快照：`data/hw2/glp1-1000-20260929/`。原始摘要 SHA256：`9738b68d03a6e39bed010803aa878cfdc66e0bbcaf005e8ee83d3bcfeb7b2631`。

| 條件 | Documents | Tokens | Unique terms | 全範圍 exponent | R² | RMSE（log10 CF） |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| A | 1,000 | 244,477 | 29,203 | 1.081025 | 0.955040 | 0.101757 |
| B | 1,000 | 246,256 | 17,910 | 1.278303 | 0.971602 | 0.094762 |
| C | 1,000 | 179,304 | 17,792 | 1.235926 | 0.965673 | 0.101039 |
| D | 1,000 | 179,304 | 14,305 | 1.304093 | 0.966623 | 0.105044 |

B→C 刪除 66,952 次出現（27.188%）及 118 個實際出現的停用詞型；C→D token 數不變，詞彙再減少 3,487（19.599%）。這些是語料統計，不能直接當成搜尋品質提升或實測壓縮量。

來源：[summary.json](../reports/hw2/experiment/summary.json)。正式實驗包含 16 個 CSV、1 個 summary JSON、4 張 PNG，共 21 個檔案；另有 16 組全域／分段回歸及 39 詞 CF／DF／IDF 比較，選詞表使用 B 條件。

### 4. Word2Vec、拼字與搜尋

- **Word2Vec 沿用相符的 B 模型並重新驗證離線重載**，本版沒有再次訓練。模型保存 B 的有序句子，保留停用詞、未 stemming，且不跨越文件／摘要 block／句子邊界。
- 保存模型為 Skip-gram：10,843 句、246,256 ordered tokens、9,658 個模型詞彙；vector_size=100、window=5、min_count=2、epochs=30、seed=42、workers=1。17.7362 秒是保存模型原本的訓練耗時，不是本輪重訓結果。
- 模型 schema 2 記錄 tokenizer 契約；重載拒絕缺少或不一致的契約。模型向量 SHA256 保持 `7de476d45de19d97d0572bbc561266ba6efac538c462a4f817144e647cae62f0`。近鄰仍是探索性結果，不是語意正確率。
- **拼字以 B 語料 CF 排序**，使用 Levenshtein 動態規劃；`semaglutid`→`semaglutide`、`insulinn`→`insulin` 有正式驗證。原查詢與建議並列，使用者明確採用才修改。保護已知詞、數字及縮寫等術語；OOV 不等於錯字。
- 拼字快取鍵納入版本與原 tokenizer 契約，避免相同語料卻沿用舊切詞結果。既有搜尋規則、原文位置及高亮繼續保留；搜尋命中數不等於四組分析的 DF。

程式位置：`ir_hw2/embeddings.py`、`ir_hw2/spelling.py`、`app.py`；模型：[metadata.json](../reports/hw2/model/metadata.json)；實證：[formal-verification.json](../reports/hw2/formal-verification.json)。

### 5. 報告、教材與交付檢查

主報告、Executive Summary、README、計畫、開發說明及 demo 均同步四組 v5。報告保留 RQ1–RQ5、39 詞比較及 **389 words** 英文 IR 意義討論；主報告 PDF **12 頁**，Executive Summary **獨立 1 頁**。

PDF 匯出器補強章節標題與表格一起換頁、英文討論字數範圍與抽取文字核對。交付驗證器以數字欄位辨別 CF／DF／IDF 表，避免把同名的 Word2Vec 近鄰表列當作統計列。兩份 PDF 已逐頁渲染查看，612 項來源文字／表格核對通過。

| 驗證 | 已實際取得的結果 | 證據 |
| --- | --- | --- |
| 完整回歸 | 487 passed＝原有 348＋HW2 139；50.69 秒；0 failure／error／skipped | [pytest log](../reports/hw2/pytest-hw1-tokenizer.log)、[JUnit XML](../reports/hw2/pytest-hw1-tokenizer.xml) |
| 分析獨立核對 | 1,000 文件各組 token／CF／DF；39 詞 IDF；16 組 NumPy OLS；21 檔重跑逐位元一致 | [tokenizer_verification.json](../reports/hw2/tokenizer_verification.json) |
| 正式功能 | 阻擋網路後，模型重載、搜尋／高亮與拼字核對通過 | [formal-verification.json](../reports/hw2/formal-verification.json) |
| 報告與輸出一致性 | 4 組統計、16 回歸、39 選詞、389 words、模型句序、測試及 PDF 來源 hash 通過 | [analysis_verification.json](../reports/hw2/analysis_verification.json) |
| PDF | 12＋1 頁視覺檢查，576＋36 項文字／表格核對通過 | [pdf_qa.json](../reports/hw2/pdf_qa.json)、[pdf_export.json](../reports/hw2/pdf_export.json) |
| 互動讀圖指南 | A 組完整詞表核對；760px 明／暗主題及 360px 手機版通過 | [tokenizer_guide_qa.json](../reports/hw2/tokenizer_guide_qa.json) |

487 項是四組程式版本已保存的實跑結果；此次集中補文件沒有重新執行全套測試。原始 6 個缺 Git 歷史 fixture 的 setup errors 與程式缺陷分開記錄，未刪除原測試或弱化斷言。2026-09-29 真實瀏覽器操作屬初版歷史，本版 Streamlit 驗證為 AppTest 與離線整合，不冒稱已重新走完瀏覽器 demo。

### 6. Lecture 3、歷史與仍待確認事項

[Lecture 3 評估](LECTURE3_REVIEW.md) 保留 60 頁閱讀結論及六個查詢的搜尋公式診斷。分數拆解、講義公式比較介面、人工相關性評估、CF–DF 散點圖與相似文章仍是後續建議，不能寫成此次已完成的功能；新增講義也不自動改變作業要求。

目前恢復的是作業四階段定義，同時保留原 HW1 tokenizer 作 B 及使用 log10 的決定；因此不可將最早不同切詞方式的舊數值直接當成新版結果。封存位置如下：

| 歷史內容 | 位置／狀態 |
| --- | --- |
| 自然對數初版 | `reports/hw2/history/natural-log-20260929/` |
| 全符號拆詞的 log10 版 | `reports/hw2/history/unicode-split-log10-20260930/` |
| 本輪中途四組版本、模型與文件 | `reports/hw2/history/hw1-four-conditions-20260930/` |
| ABC 三組試行 | 已撤回；沒有宣稱存在完整交付封存 |

手刻 Porter 的要求、提交媒介、demo 時長及截止日是否更新仍待教師資訊；原題截止 2026-10-06。兩領域比較仍為 optional，未執行。小型單領域語料、非隨機取樣與缺乏人工相關性／語意標記等限制，見正式報告。

### 7. 文件維護紀錄

此次補記新增本文件，並在 README、HW2_PLAN、HW2_DEVELOPMENT、HW2_DEMO 與 LECTURE3_REVIEW 加入入口或最新版本說明。程式、語料、模型、正式結果與已驗證 PDF 內容沒有因本次補文件而重新產生。文件核對直接讀取現行紀錄；MCP `list_projects` 與 `check_index_coverage` 回報 `Transport closed`，未將舊 graph generation 當作這次的新鮮證據。

本次文件的本機連結、四組數值及現有 PDF／教材來源指紋核對，保存於 `reports/hw2/documentation_verification.json`；這份文件檢查紀錄不替代程式測試。

後續變更依日期追加決策、受影響檔案、實際執行結果與已知限制；若改變程式或方法，更新 README／計畫／demo，重跑受影響驗證；若改變正式報告內容，重新匯出並檢查 PDF。只更新文件時，明示引用既有測試紀錄，不能把舊結果寫成重新執行。

## 2026-10-04：輸入時顯示拼字候選

- 「搜尋文章」改為輸入停頓 350 ms 後檢查拼字，不需先按搜尋或移開游標。單一錯字最多列出三個候選按鈕；點選後填回查詢並搜尋。多詞查詢保留其他文字，仍可按搜尋使用原詞。
- 只重繪輸入與建議區，既有文章結果保持到使用者搜尋或採用建議。建議快取包含語料版本與前處理版本；延遲點選舊建議不會覆蓋較新的輸入。編輯距離、CF 等資訊收進「查看拼字比較」。
- 使用 Streamlit 1.64 原生即時輸入，更新 requirements 與啟動檢查；手刻 Levenshtein、候選排序、生醫術語保護及正式分析結果保持原方法。
- 全套回歸 **507 passed in 172.22s**，見 `reports/hw2/live-spelling-complete-pytest.xml`。原 HW1 的 18 個測試檔 SHA-256 全數一致；Windows 測試 fixture 僅允許 AppTest 初始化 asyncio 時建立本機 self-pipe，執行應用程式前恢復原本的離線連線封鎖，另有新增測試驗證封鎖仍有效。
- 實際瀏覽器補驗輸入時候選、採用後輸入框／文章結果同步、保留原詞、連續改字及生醫詞保護；新證據保存在 `reports/hw2/live-spelling-qa/`。正式 PDF 與分析數值未因此次操作介面更新而重新產生。

## 2026-10-04：降低即時拼字延遲

- 將輸入停頓等待從 350 ms 降為 200 ms。搜尋頁載入時建立詞典索引，依語料 SHA、tokenizer 契約及索引版本快取；打字不再重新正規化約 17,910 個詞。每份索引另有最多 2,048 個詞的候選快取，語料更新時使用新的索引。
- 拼字仍使用手刻 Levenshtein 動態規劃。增加共同前後綴裁切、對角帶計算及字母集合的必要條件篩選；排序仍是編輯距離、CF、字典序。獨立完整矩陣測試與窮舉候選比對確認結果一致，未換用 SymSpell。
- 輸入區不再逐次掃描 1,000 個 XML。保留每 3 秒資料夾監看、搜尋／採用時的完整同步，以及閱讀文章時的更新檢查。
- 本機 1,000 篇／17,910 詞、11 次中位數：`insulinn` 的首次候選計算 **28.20 → 1.00 ms**；`semaglutid insulinn diabetees` **71.49 → 2.59 ms**。210 個實際語料查詢與優化前結果完全相同。這是 Python 計算時間，未包含 200 ms 等待、瀏覽器渲染及傳輸；詞典建置約 273 ms 加索引準備約 16 ms，移到首次開啟搜尋頁執行。詳見 `reports/hw2/spelling-performance/benchmark.json`。
- 全套 **512 passed in 48.05s**，見 `reports/hw2/spelling-performance/full-pytest.xml`；包含新增的獨立 DP 比對、候選篩選、快取隔離與輸出不可污染快取測試。瀏覽器驗證停留輸入框時更新候選、快速改字、多詞採用及舊搜尋結果保留。輸入法組字尚未完成時會等待完成組字；測試中取消未完成組字後，連續輸入正常。
