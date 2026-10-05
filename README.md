# IR-HW2：生醫摘要的 Zipf、前處理與詞彙模型

延續 HW1 繁體中文 Streamlit 搜尋平台，完成 **1,000 篇 GLP-1 英文 PubMed 摘要**實驗。依最新確認採作業四條件 **A：基本切詞與正規化 → B：標點處理 → C：停用詞移除 → D：Porter**。所有新程式、環境、資料與輸出在 HW2，原 HW1 僅唯讀參考。

## 啟動

環境已建置時，最簡單的方式是雙擊專案根目錄的 **[start_hw2.cmd](start_hw2.cmd)**。它固定使用 `.venv-hw2`，不受目前終端機啟用的 Python 影響；視窗保持開啟，再於瀏覽器開啟 <http://127.0.0.1:8501>。結束時在該視窗按 Ctrl+C。若已經有網站占用 8501，先在原本的啟動視窗按 Ctrl+C，再開啟本檔案；啟動檔不會擅自停止其他程序。

以下 PowerShell 指令適用於第一次建置；日常使用可只執行 `start_demo.ps1` 或上述啟動檔，不需每次重新安裝套件。

```powershell
Set-Location -LiteralPath 'C:\成大專案\IR-HW2'
.\scripts\setup_hw2.ps1
.\scripts\start_demo.ps1
```

開啟 <http://127.0.0.1:8501>。新環境 `.venv-hw2` 使用 Python 3.13.14，不使用搬移的 `.venv`。安裝腳本可重跑；初次安裝需網路，保存的搜尋、分析及模型可離線使用。前景啟動以 Ctrl+C 結束。

若 Word2Vec 出現 `No module named 'gensim'`，請先停止舊網站，再用上述 `start_demo.ps1` 啟動；不要用複製的 `.venv` 直接執行 `python -m streamlit run app.py`。啟動腳本會檢查必要套件並顯示實際 Python 路徑；頁面也提供環境診斷。只修正啟動環境即可讀取保存模型，不需要重訓。

「HW2 實驗室」提供五個主題：語料與前處理、Zipf 分析、CF／DF 與 IDF、Word2Vec、方法與報告。各主題用分頁呈現比較圖，完整數表與操作設定收進展開區；可切換數量指標、回歸／殘差、區段 R²／RMSE 及 IDF 圖。條件選單預設 A，四組顏色固定；高頻詞可 A–D 並排比較。既有搜尋保留 TF-IDF、原文高亮及文章管理。輸入停頓 200 ms 後開始更新拼字候選，點選即可套用並搜尋，也能直接搜尋原詞；打字只更新建議區。即時輸入使用 Streamlit 1.64，既有環境請先重跑 `scripts/setup_hw2.ps1` 再啟動。下載、重算與訓練由按鈕觸發，UI rerun 不重做。

## 網址展示版（Streamlit Community Cloud）

本專案需要執行 Python 的 Streamlit 伺服器，不能直接用 GitHub Pages 啟動。
程式與資料存放在 GitHub，網站由 Streamlit Community Cloud 執行。

1. 前往 <https://share.streamlit.io/>，登入並連接自己的 GitHub 帳號。
2. 選擇 **Create app → Yup, I have an app**。
3. Repository 填 `p77151087-jpg/IR-HW2`，Branch 填 `main`。
4. **Main file path 填 `cloud_app.py`**，它強制啟用展示模式。
5. 在 **Advanced settings** 將 Python version 設為 **3.13**。本專案不需要填入 Secrets。
6. 按 **Deploy**；建置成功後，以平台顯示的 `https://…streamlit.app` 網址分享。

展示版保留搜尋、文章詳情、語料統計、Zipf 圖表、CF／DF／IDF 切換與詞表下載、Word2Vec 查詢及報告下載；不提供文章上傳／刪除、語料下載／匯入、重新分析或模型訓練。固定資料與模型隨 Git 儲存庫部署。雲端本機磁碟不作為永久資料庫。

根目錄 `requirements.txt` 包含完整執行套件，`requirements-hw2.txt` 保留為本機安裝腳本的相容入口。`app.py` 與 `start_hw2.cmd` 仍供本機完整功能使用。未來提交並 push 到 `main` 後，Community Cloud 會依 GitHub 更新重新部署。

官方操作說明：[部署流程](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/deploy) · [套件設定](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/app-dependencies)。

## 正式結果

固定快照 `data/hw2/glp1-1000-20260929/`：一 PMID 為一 document，只計摘要正文。查詢 30,622 筆，候選 1,200，取回 1,100，納入 1,000，排除 5，另 195 不需使用。原 XML、取得時間、完整查詢、逐篇納排及 SHA256 均保留；搜尋文章庫為獨立副本，增刪不改正式快照。

| 條件 | Tokens | Unique terms | 全範圍 exponent | R² | RMSE（log CF） |
| --- | ---: | ---: | ---: | ---: | ---: |
| A 基本空白切詞 | 244,477 | 29,203 | 1.0810 | 0.9550 | 0.1018 |
| B HW1 標點處理 | 246,256 | 17,910 | 1.2783 | 0.9716 | 0.0948 |
| C B＋停用詞移除 | 179,304 | 17,792 | 1.2359 | 0.9657 | 0.1010 |
| D C＋Porter | 179,304 | 14,305 | 1.3041 | 0.9666 | 0.1050 |

各條件共用 HW1 NFC／casefold、撇號／連字號正規化。B 直接使用原 `tokenize`，保留 `GLP-1`、`IL6`、`3.5`、`β-cells`；C 移除固定 132 詞表，本語料實際刪除 118 詞型、66,952 tokens（27.188%）；D 沿用原 `stem_term`，tokens 不變、詞彙再少 19.599%。沒有搜尋複合詞展開或額外孤立字過濾。

分析 IDF=`log(N/DF)`；Zipf OLS、殘差及 RMSE 皆用 log（以 10 為底），HW1 搜尋權重獨立保留。B 全域 b=1.2783，中頻 b=1.0479；高 R² 不能證明 Zipf，需同看圖形、分段及殘差。不熟圖表可先看[互動讀圖指南](output/visualizations/zipf-reading-guide.html)。

Skip-gram 沿用已保存且原切詞契約相符的 B 模型，本版重新驗證離線重載；模型使用 10,843 句、246,256 個有序 tokens、9,658 個模型詞彙；100 維、window=5、min_count=2、epochs=30、seed=42、workers=1。`GLP-1` 可查單詞近鄰；多詞輸入會提示限制，未知詞回傳 OOV。cosine 不等於語意正確率。模型保存原 tokenizer 契約；不相符舊模型會要求重訓。

2026-10-03 圖表與作業解答更新：完整回歸 **497 passed（原348＋HW2 149），58.18秒**；最新紀錄 `reports/hw2/comparisons-pytest.xml`。主報告含9張圖、A–D各50詞附錄、39詞CF／DF／IDF、389 words IR討論與RQ1–RQ5；一頁摘要另附。網站「方法與報告」可直接下載PDF。補充圖以 `python scripts/build_hw2_comparison_figures.py` 從保存資料產生，與原21份正式輸出分開。

本次四組v5完整回歸 **487 passed（原有348＋HW2 139），50.69秒**；21 個分析輸出重跑逐位元一致，16 個回歸經獨立 NumPy OLS 核對，39 個 CF／DF／IDF 選詞檢查通過。修改前基線為 342 passed、6 個缺 Git 歷史 fixture 的 setup errors；唯讀取出原 XML、保存來源 hash、修復可攜性後原測試全過，沒有刪除測試或改斷言。

後續 Word2Vec 執行環境修復的最新完整回歸為 **492 passed（原348＋HW2 144），56.72秒**，包含新增的實際查詢表單、訓練按鈕與缺套件提示測試；紀錄另存 `reports/hw2/word2vec-fix/pytest-full.xml`／`.log`，不覆寫上述四組分析驗收紀錄。原因與修復見[變更紀錄](docs/HW2_CHANGELOG.md)。

## 重現

```powershell
# 固定快照驗證；已完成的 fetch 重用快照，不重新下載
.\.venv-hw2\Scripts\python.exe -X utf8 -m ir_hw2.cli verify
.\.venv-hw2\Scripts\python.exe -X utf8 -m ir_hw2.cli fetch

# 可離線重算；覆寫同名輸出，另存分析請加 --output 路徑
.\.venv-hw2\Scripts\python.exe -X utf8 -m ir_hw2.cli analyze
.\.venv-hw2\Scripts\python.exe -X utf8 -m ir_hw2.cli train
.\.venv-hw2\Scripts\python.exe -X utf8 -m ir_hw2.cli neighbors semaglutide
.\.venv-hw2\Scripts\python.exe -X utf8 -m ir_hw2.cli neighbors GLP-1
.\.venv-hw2\Scripts\python.exe -X utf8 -m ir_hw2.cli spell insulinn

# 需要時把快照副本加入搜尋庫
.\.venv-hw2\Scripts\python.exe -X utf8 -m ir_hw2.cli publish-search

# 保存完整測試與獨立重現核對（後者自動另存一份分析作比對）
.\.venv-hw2\Scripts\python.exe -X utf8 -m pytest -q --basetemp tmp/pytest-hw1-tokenizer-final --junitxml=reports/hw2/pytest-hw1-tokenizer.xml
.\.venv-hw2\Scripts\python.exe -X utf8 scripts\verify_hw2_tokenizer.py
.\.venv-hw2\Scripts\python.exe -X utf8 scripts\verify_hw2.py
.\.venv-hw2\Scripts\python.exe -m pip check

# 可選：限制 Python 程序對外連線的 demo，先結束現有 8501 程序
.\.venv-hw2\Scripts\python.exe -X utf8 scripts\run_offline_demo.py
```

建立新快照請用 HW2 內新目錄，例如 `-m ir_hw2.cli --snapshot data/hw2/glp1-new fetch --count 1000`；其他時間查詢結果可能不同，需保留原快照才能重現繳交數字。NCBI 下載每秒一請求、每批 100 PMID、暫時錯誤最多三次嘗試，具快取與續傳。官方規範及完整查詢見[語料取得紀錄](reports/hw2/corpus_acquisition.md)。

## 成果與程式

- [變更紀錄：四組恢復、預設 A、log10 與驗證](docs/HW2_CHANGELOG.md)、[需求追蹤與計畫](docs/HW2_PLAN.md)、[操作 demo](docs/HW2_DEMO.md)、[開發與 AI 協助說明](docs/HW2_DEVELOPMENT.md)。
- [完整報告：RQ1–RQ5 與 389 words 討論](reports/hw2/HW2_REPORT.md)、[Executive Summary](reports/hw2/EXECUTIVE_SUMMARY.md)；PDF 在 `output/pdf/`。
- [語料取得紀錄](reports/hw2/corpus_acquisition.md)、[環境及基線](reports/hw2/environment.md)。
- `reports/hw2/experiment/`：A–D、CF／DF、Top 50、IDF、回歸 CSV 及四張圖。
- `reports/hw2/model/`：模型、有序句子、設定及近鄰。
- `reports/hw2/tokenizer_verification.json`、`pytest-hw1-tokenizer.xml`、`formal-verification.json`：新版分析重現、測試與正式資料離線驗證。
- `ir_hw2/`：語料、分析、詞向量、拼字、CLI、UI 及搜尋副本整合；`ir_hw1/` 保留原搜尋引擎。

## 限制與規格待確認

單一主題、依 PubMed 日期排序的非隨機樣本，不能推論全部 PubMed。兩筆刊期年份為 2027，但電子出版為 2026，符合 PubMed 日期查詢。原切詞保留支援的複合詞／小數，仍不是完整生醫實體辨識器。Porter 可能過度或不足合併，採 **NLTK 3.9.2 MARTIN_EXTENSIONS**，不是手刻；教師是否要求自行寫演算法待確認。

小型 Word2Vec 沒有人工語意 gold standard；未知詞不等於拼錯，不會默改查詢。9/29 詳細版未取消 9/22 的 Word2Vec／拼字要求，因此皆保留；兩領域比較 optional 未做。原題截止 **2026/10/6**，繳交媒介與 demo 時長待最新通知。

## 歷史與新版界線

[HW1 README 封存](docs/HW1_README_ARCHIVE.md)、SYSTEM、SEARCH_REDESIGN、RESULTS 及 `DEVELOPMENT_PLAN.md` 保留原意；舊 4／15 篇與測試數不代表現況。自然對數初版封存於 `reports/hw2/history/natural-log-20260929/`，全符號拆詞 log10 版封存於 `reports/hw2/history/unicode-split-log10-20260930/`。中途ABC三組試行已撤回；目前版本為 `hw2-hw1-four-conditions-v5-log10`，不用舊 `verify_hw2_log10.py` 驗證新版。

2026-09-29 真實瀏覽器操作與畫面是歷史紀錄；本次新版 AppTest、正式離線整合與圖表／讀圖指南視覺核對，未冒稱重做瀏覽器操作。

## 重新匯出報告 PDF

修改 Markdown／正式實驗後，重建 PDF，再做交付核對。匯出器使用 Windows 微軟正黑體與 Segoe UI，讀主報告、摘要及四張正式 PNG。不要只憑文字抽取判斷排版，仍需渲染確認換頁、表格與缺字。

```powershell
.\.venv-hw2\Scripts\python.exe -m pip install -r requirements-reports.txt
.\.venv-hw2\Scripts\python.exe -X utf8 scripts\build_hw2_reports.py
# 需先完成上方完整測試、兩個 verify，以及本次 PDF 重建
.\.venv-hw2\Scripts\python.exe -X utf8 scripts\verify_hw2_delivery.py
```

PDF 位於 `output/pdf/`，來源指紋見 `reports/hw2/pdf_export.json`；交付核對見 `reports/hw2/analysis_verification.json`。一般分析或模型驗證不依賴 PDF，只有最後這項交付核對需要最新報告與 PDF。
