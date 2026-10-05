# HW2 接手理解、需求追蹤與實施計畫

更新：2026-09-30。工作根目錄 `C:\成大專案\IR-HW2`；HW1 唯讀。原題截止 2026-10-06，尚無其他更新。目前方法見第 3 節，四組v5結果見第 10 節；第 1 節與第 4–9 節保留接手／各版歷史，不可將其中舊數值當成現況。實測證據另存 `reports/hw2/`。

本輪決策、變更檔案、正式數值、模型沿用及驗證證據集中於 [HW2_CHANGELOG](HW2_CHANGELOG.md)。2026-09-30 補文件時只核對既有實跑紀錄，未重新執行全套測試或正式實驗。

其後的 Word2Vec 故障修復另有實跑：網站原以缺少 gensim 的舊 `.venv` 啟動，已切換 `.venv-hw2`，新增缺套件提示、啟動前檢查與 5 項 UI 測試。最新回歸為 492 passed in 56.72s，記錄在 `reports/hw2/word2vec-fix/`；第 10 節的 487 項保留為四組分析驗收歷史。正式語料、分析方法與模型維持不變。

## 1. 接手檢查與 HW1 理解（2026-09-29 歷史）

已依序閱讀 README、SYSTEM、SEARCH_REDESIGN、RESULTS、DEVELOPMENT、DEMO 與歷史 DEVELOPMENT_PLAN；舊文中的 4／15 篇與 348 項等數字不是目前結果。接手時 `data/processed/articles.jsonl` 為空、`data/raw` 無 XML，原程式全為 untracked，全部保留。沒有另找到檔案形式的 AGENTS.md；依本次對話提供的 AGENTS 規範。

HW2 graph project 為 `C-e68890e5a4a7e5b088e6a188-IR-HW2`、root `C:/成大專案/IR-HW2`、generation `2026-09-29T01:37:13Z`，Tier 2 驗證。相關 Python 路徑 coverage 均為 metadata_match／no_recorded_issue（不代表完整性證明）；`scripts/start_demo.ps1` 第 4 行 partial，已直接讀取補證。工具 git metadata 的 root_exists=false 與實際檔案不符，因此不依該欄判定 repo 存在性。

資料流：PubMed／PMC XML → `xml_parser` 產生 `Document/TextBlock` → `preprocessing` 保留原文位置 → `relevance` 搜尋特徵 → `index` 四組倒排索引 → `tfidf/search` 排名 → `snippets` 原文高亮 → Streamlit `app.py`。`library/corpus/storage/sync` 負責下載、快照、鎖、同步；`statistics/sentence_splitter` 負責原文統計與規則斷句；`cli/ui_management` 為操作入口。

搜尋複合詞會展開：IL6 產生 il-6、il、6；搜尋 IDF 是 ln((N+1)/(DF+1))+1；摘要顯示字數是空白切分；網頁固定 Porter。上述行為均不得直接充作 HW2 實驗。HW2 新增 `ir_hw2` 獨立分析模組，沿用 XML、資料型別及安全儲存，保留搜尋規則。

複製 `.venv` 的 pyvenv.cfg 有 HW1 建置路徑，原啟動測試失敗（亦涉及 sandbox 存取）；建立 `.venv-hw2` 並驗證解譯器及啟動器。先完整執行未修改程式的 pytest 基線，再修復 fixture 可攜性。真實 fixture 依賴 Git `ad8bf2b`，缺歷史造成的 setup error 必須分開記錄，不刪除測試或宣稱通過。

## 2. 規格來源與需求追蹤

三份 PDF 已完整抽取頁面文字；詳細版第 2、3、5 頁另查頁面圖像確認公式。H = Homework-2-26-20260922-1.pdf；D = project-2-details-20260929-1.pdf；L = lecture-2-dictionary-20260922-1.pdf。抽取與視覺核對中間檔位於 `tmp/hw2-specs/`。

| ID／來源頁碼 | 要求 | 既有可用功能 | 待開發／驗證方式 | 成果位置 |
| --- | --- | --- | --- | --- |
| R1 H1、D1–2 | 同主題約 1,000 篇英文非空摘要、唯一 PMID | EFetch、PubMed parser | 固定 GLP-1 查詢、批次快取續傳、逐篇納排原因、快照 hash；核對數量／語言／空摘要／去重 | `ir_hw2/corpus.py`、`data/hw2/` |
| R2 D3–4、L7/10/36–46 | A tokenizer+lowercase、B 標點、C stopwords、D stemming | NLTK Porter | 獨立累積 pipeline；手算測試；保存規則／停用詞 hash | `ir_hw2/analysis.py`、`resources/hw2_stopwords.json` |
| R3 D3 | documents/tokens/vocabulary/average、CF/DF、Top50 | 原文及資料模型 | 全條件統計及 CSV；CF>=DF、DF<=N、sum(CF)=tokens | `reports/hw2/experiment/` |
| R4 H1、D2–4、L56–58 | rank-frequency、log-log、回歸 slope/intercept/exponent/R²/RMSE | 無獨立分析 | 以 10 為底的對數 OLS、全排名及預先定義三區段；人工序列回歸測試、圖像核對 | `ir_hw2/analysis.py`、圖表與 regression.csv |
| R5 D4 | 比較 A–D／高、中、低頻，R² 是否充分 | 無 | 區段與殘差圖、singleton比例；避免把高 R² 當證明 | `reports/hw2/HW2_REPORT.md` |
| R6 D4–5 | >=20 詞 CF/DF，>=10 詞指定 IDF | 搜尋 IDF 不適用 | IDF=log10(N/DF)，不平滑；跨頻率選詞、手算 | `cf_df_comparison.csv`、`idf_terms.csv` |
| R7 H1、L23–35 | CBOW 或 Skip-gram、近鄰展示 | 原文與句界 | 有序句子訓練、文件邊界、固定 seed／單 worker、模型儲存重載及 OOV 測試 | `ir_hw2/embeddings.py`、`reports/hw2/model/` |
| R8 H1 | 必要拼字校正、DP edit distance | 搜尋及高亮 | Levenshtein DP，距離／CF 排序；正確詞、錯字、OOV、數字／基因術語保護；明確選用建議 | `ir_hw2/spelling.py`、UI、tests |
| R9 H1、D8 | 系統說明／results／demo、RQ1–RQ5 | Streamlit 平台 | 繁中新增分析功能、明確按鈕觸發下載／訓練；AppTest、離線重載 | `app.py`、`ir_hw2/ui.py`、`docs/HW2_DEMO.md` |
| R10 D5–6 | IR 意義 300–500 words，stopwords／index／compression／TF-IDF | HW1 系統說明 | 英文 300–500 words 專段並機器計數，繁中分析本文 | `reports/hw2/HW2_REPORT.md` |
| R11 D7–8 | technical argument、另外一頁 Executive Summary | 無 | 引用本次數值，輸出一頁 PDF 並視覺核對 | `reports/hw2/EXECUTIVE_SUMMARY.md`、`output/pdf/` |
| R12 使用者要求 | 重現入口、回歸、輸出來源完整 | pytest/CLI | 基線、新測試、重跑 hash、環境鎖定、README 啟動流程 | `ir_hw2/cli.py`、`reports/hw2/`、README |

規格差異：H1 篇數 10–1000，D2 收斂為約1000，本次目標1000；D 未重述 Word2Vec／拼字校正，未明確取消，仍必做。D 允許 stemming 或 lemmatization，H 指定 Porter，本次採 NLTK Porter `MARTIN_EXTENSIONS`，記錄版本，不宣稱手刻。是否教師要求自行重寫 Porter、提交媒介與 demo 時長待確認，不阻礙開發。D7 兩領域比較 optional；L59–78 skip lists／biword／proximity、L79–93 clustering 等延伸不自動列必做。

## 3. 目前固定實驗方法（作業四條件 v5）

- 固定快照一篇 PMID 為一 document，只取 abstract block.text 正文，排除標題、小標題及全文。搜尋文章庫可增刪，正式快照獨立保存。
- 查詢 GLP-1／glucagon-like peptide-1、英文、有摘要、publication date 至 2026-09-29；查詢、排序、時間、實際納排及 hash 保存。屬日期排序的單主題非隨機樣本。
- **A 為基本切詞與正規化**：空白切分，每個 token 呼叫 HW1 `normalize`。**B為標點處理**：直接用 HW1 `tokenize(text)` 的 `Token.term`；C 去固定132停用詞；D 直接用 HW1 `stem_term`，純 ASCII 字母套用 NLTK Porter MARTIN_EXTENSIONS。
- 共同正規化為 NFC＋casefold，`’`→`'`、`‐`／`‑`→`-`。B 保留 `glp-1`、`il6`、`3.5`、`β-cells` 及支援的內部撇號。沒有 relevance 特徵展開、孤立字／數字過濾或第二輪停用詞刪除。C 保留 no／not／without。
- 例句 `The patients GLP-1 improved 3.5 mg.`：B 保留 the、glp-1、3.5，C 去 the，D patients→patient、improved→improv。A 保留最後的 mg.；各條件以原摘要建立，B 不將 A 清單重組。
- 分析版本 `hw2-hw1-four-conditions-v5-log10`。`baseline_tokenizer_spec()` 保存原實作／版本／regex／normalization／source SHA256／依賴；不包含分析版本或 log 底數，避免統計改動無端使模型失效。原 tokenizer 版本 unicode-word-v1，preprocessing source hash 為 `f7108e87d1c19c43e012836adcb6d8b429e4d06c5cdc2bead4a06f71f04919c2`，本次未修改。
- metadata primary_comparison為A／B／C／D，reference_condition為null；本版依最新確認回歸課堂四組，沒有把A降為額外參考或只交付三組。
- CF=總出現次數，DF=包含詞的不同 PMID 數；IDF=log10(N/DF)，不平滑。相同 CF 以 Unicode 詞序給 ordinal rank 1..V。
- x=log10(rank)、y=log10(CF)，OLS y=a+slope*x，b=-slope。RMSE=sqrt(mean((y-yhat)^2))，計於 log10(CF) 空間；R² 在 y無變異時為null。全域1..V，高頻前floor(1%V)，中頻其後至floor(10%V)，其餘低頻；極小資料才做最少點防呆。比較圖形、殘差、R²、RMSE、singleton，沒有 power-law 統計證明。
- Word2Vec 採 Skip-gram；原順序 B tokens 保留停用詞，無 stemming；各文件／abstract block／句界不跨越。vector_size=100、window=5、min_count=2、epochs=30、seed=42、workers=1、negative=5、sample=0.001。模型 schema2 保存完整原 tokenizer 契約，不接受缺少／不相符的舊模型。
- 拼字以 Levenshtein DP＋B語料 CF 排序，明示原查詢及建議、使用者選擇採用；保護已知詞、數字、非ASCII、大小寫術語、縮寫及短詞。未知不等於錯字，無候選不改寫。
- UI 預設從 A 顯示，可依序切換 B／C／D；全部A／B／C／D均為正式比較條件。版本、底數、tokenizer契約不相符時提示更新結果。耗時工作由明確按鈕或CLI觸發。
- 官方規範查核2026-09-29：NCBI無key最多3 requests/s，本專案單線1 request/s、批次100、暫時錯誤最多3次嘗試、快取續傳。[一般規範](https://www.ncbi.nlm.nih.gov/books/NBK25497/)、[參數文件](https://www.ncbi.nlm.nih.gov/books/NBK25499/)。不傳信註冊、不虛構email；摘要可能有版權，本地課程分析不代表開放授權。

## 4. 原始分階段實作及分工（歷史計畫）

1. 接手、三份 PDF、圖譜、環境與原始 pytest 基線。環境工作者負責 `.venv-hw2`、安裝腳本、依賴與基線；原始失敗與後續修復分開。
2. 獨立 analysis 與手算測試（專責工作者：analysis、stopwords、analysis tests），主工作者整合介面契約。
3. 正式 corpus 快照（專責工作者：corpus、corpus tests、下載 manifest）。先測 mock／小樣本，才實際取得1000篇。
4. 主工作者負責 embeddings、spelling、CLI、UI；環境工作者完成後可承接其中獨立模組，明確分配避免同檔編輯。
5. 完整回歸、正式 Zipf／模型訓練與離線重載、圖表QA、報告與一頁摘要、README/demo。

每個工作者不得改別人的責任檔案；所有變更互相可見，勿清理 untracked 基礎。每階段更新本計畫與實測紀錄。外部下載受阻時保留快取／錯誤，不以合成資料代替正式結果。

## 5. 初版驗收進度（歷史，最新見第 10 節）

- [x] 確認 HW2 與 graph；閱讀交接文件、題目與講義；寫出規格差異與方法。
- [x] 新環境與未修改測試基線。
- [x] 小型資料手算驗證與獨立分析模組。
- [x] 固定1000篇正式 PubMed 語料及來源查核。
- [x] A–D、Zipf、CF/DF、IDF正式實驗輸出。
- [x] Word2Vec、拼字校正、UI整合及重載測試。
- [x] 全套回歸、報告、300–500 words、一頁摘要、demo及重現指南。


## 6. 初版完成紀錄（2026-09-29 歷史）

- 新環境 `.venv-hw2`，Python 3.13.14；套件與 launcher 均指向 HW2，建置與 freeze 見 `reports/hw2/environment.md`。
- 修改前 342 passed、6 fixture setup errors（缺 Git 歷史），沒有 assertion failure。唯讀取出 HW1 原始 15 篇 fixture 並保存 hash 後，舊 348 項通過；完整新增後 444 passed（舊348＋新96）。18份原測試斷言檔未修改，原始錯誤紀錄仍保留。
- 正式快照 `data/hw2/glp1-1000-20260929`：唯一英文非空摘要1000篇，原XML與來源完整；候選1200、下載1100、排除5、未需使用195。原始摘要 SHA256=`9738b68d03a6e39bed010803aa878cfdc66e0bbcaf005e8ee83d3bcfeb7b2631`。
- A-D 正式 tokens：244477／266039／198384／198384；詞彙：29255／13338／13220／9613。21個統計與圖表輸出重跑逐位元一致，四張圖已視覺核對，見 `reports/hw2/analysis_verification.json`。
- Skip-gram 正式訓練：1000篇、10843句、8473模型詞彙；單worker、固定seed；模型及有序句子保存在 `reports/hw2/model`。離線重載與OOV已驗證，不宣稱跨平台重訓完全相同。
- 拼字使用自行實作DP，依距離／CF排序、原查詢與建議並列、使用者主動採用；39項校正測試及AppTest通過。
- `app.py` 保留搜尋／詳情／概覽／管理，新增「HW2 實驗室」；獨立快照的搜尋副本已加入資料庫。正式離線核對搜尋與掃描集合、高亮位置、模型、拼字成功，見 `reports/hw2/formal-verification.json`。
- `reports/hw2/HW2_REPORT.md` 回答RQ1-RQ5，包含32詞CF/DF/IDF及384 words IR討論；README、`docs/HW2_DEMO.md` 提供環境、網站、實驗與離線步驟。原README全文保存為 `docs/HW1_README_ARCHIVE.md`。
- 最終graph coverage generation `2026-09-29T02:06:29Z`：app及所有ir_hw2核心檔案metadata_match/no_recorded_issue；`scripts/start_demo.ps1` 第10行partial，已直接完整讀取補證。圖譜Windows root_exists錯誤欄位仍不採作真實FS判定。

最終 PDF 排版與真實瀏覽器操作核對均已完成，驗收紀錄如下。規格待確認仍為是否要求手刻Porter、繳交媒介、demo時長及是否另有更新截止日；兩領域比較為optional，未執行。



## 7. 初版最終驗收（2026-09-29 歷史）

- 真實瀏覽器確認 A-D表、Zipf三張圖與B區段、CF/DF/IDF匯出控制項、Word2Vec近鄰與未知詞、拼字明確採用，見 `reports/hw2/browser-validation.json`。`insulinn` 原查詢0篇，採用後 `insulin` 203篇；畫面證據保存於 `reports/hw2/screenshots`。沒有觸發重抓或重訓。
- `output/pdf/HW2_REPORT.pdf` 共12頁，`HW2_EXECUTIVE_SUMMARY.pdf` 單獨1頁。最新13頁逐頁Poppler渲染及視覺核對通過，表格不拆頁、無缺字／裁切／重疊。完整輸出與來源hash見 `reports/hw2/pdf_export.json`，QA見 `pdf_qa.json`；PDF抽取英文討論仍為384 words。
- 補充graph coverage generation `2026-09-29T02:16:21Z`：新增PDF匯出器、setup／stop腳本、fixture、六個HW2測試檔均metadata_match／no_recorded_issue。此訊號依然不是完整性證明，實際測試與原始碼核對另外保留。
- R1-R12 必做範圍均已完成並有對應檔案／實測證據；套件Porter是否符合教師實作規定仍待確認，未宣稱手刻。兩領域optional未執行。HW1原始專案未修改，HW2未追蹤的原始基礎檔完整保留，未建立提交。
- 最新操作入口為根目錄README，步驟見HW2_DEMO，分工與AI協助說明見HW2_DEVELOPMENT。


## 8. log10 v2 更新（2026-09-30 歷史）

依使用者要求，HW2 分析統一使用以 10 為底的 log：IDF、Zipf 回歸、殘差、RMSE、圖表、UI 與報告同步更新；分析版本 `hw2-abstract-cumulative-v2-log10`。固定語料及 A–D token 規則保留，Word2Vec 不需重新訓練。HW1 搜尋權重仍是獨立設定。

舊 ln 實驗、報告及驗證已保存於 `reports/hw2/history/natural-log-20260929/`。同一語料實際重跑兩次，最新驗證見 `reports/hw2/log10_verification.json`；完整測試 450 passed（原有348＋HW2 102）。UI 拒絕將舊底數結果標成 log10，會提示重新執行。先前段落的444項與PDF hash均是初版歷史紀錄。


## 9. HW1 原切詞 v3 工作結果（2026-09-30 歷史）

依使用者要求，正式實驗改以原 HW1 切詞作 B 基準，再移除停用詞與 Porter；A 保留課堂標點前參考。log10 保留，不修改 HW1 搜尋規則。舊全符號拆詞 log10 輸出、模型、報告、兩PDF及驗證已完整封存於 `reports/hw2/history/unicode-split-log10-20260930/`。

| 條件 | Tokens | Unique terms | 全域 exponent | ΣDF |
| --- | ---: | ---: | ---: | ---: |
| A 參考 | 244,477 | 29,203 | 1.081025 | 162,028 |
| B 原切詞 | 246,256 | 17,910 | 1.278303 | 152,375 |
| C 停用詞 | 179,304 | 17,792 | 1.235926 | 128,458 |
| D Porter | 179,304 | 14,305 | 1.304093 | 121,831 |

- 固定1000篇摘要及原XML未變，abstracts SHA256 仍為 `9738b68d03a6e39bed010803aa878cfdc66e0bbcaf005e8ee83d3bcfeb7b2631`。B→C 去66,952 tokens（27.188%）；C→D 詞彙少19.599%，tokens不變。全16回歸、39詞CF／DF／IDF、每組Top50與4圖已更新。
- `scripts/verify_hw2_tokenizer.py` 已獨立依HW1有序tokens及NumPy OLS核對，21份輸出重跑逐位元一致，16擬合最大差約1.954×10⁻¹⁴，所有快照30檔未變；紀錄 `reports/hw2/tokenizer_verification.json`。舊 `verify_hw2_log10.py` 僅供歷史版，已有版本防護。
- 正式 Skip-gram 重訓：10843句、246256 ordered tokens、9658詞彙，17.7362秒；schema2 metadata保存原tokenizer契約。GLP-1可查單詞近鄰，多詞與OOV均明示；模型離線重載、5查詢搜尋／高亮及拼字校正通過，見 `formal-verification.json`。vectors SHA256=`7de476d45de19d97d0572bbc561266ba6efac538c462a4f817144e647cae62f0`。
- 完整回歸當前483 passed（原348＋HW2 135），43.16秒，`pytest-hw1-tokenizer.xml`／`.log`；analysis46項、UI6項包含其中。新增UI預設A調整的最終回歸由主工作者完成後同步此紀錄。
- 主報告已更新RQ1–RQ5、39詞分兩表、16回歸表、4正式圖與389 words IR討論，摘要及README／demo同步。PDF與整合交付核對由主工作者重建；`scripts/verify_hw2_delivery.py` 需先有新版PDF與完整測試，輸出 `analysis_verification.json`，不要將歷史PDF hash當成本版。
- 4張正式PNG已視覺核對。新版互動讀圖指南位於 `output/visualizations/zipf-reading-guide.html`，已於760px明暗與360px手機核對，見 `tokenizer_guide_qa.json`。2026-09-29的真實瀏覽器操作是歷史證據，本版沒有冒稱重新完成該流程。

圖譜證據：本次主工作者 MCP 的 list_projects／search_graph／check_index_coverage 呼叫回報 `Transport closed`，故直接完整讀取相關原始碼與測試補證，沒有拿 HW1 graph 代替HW2。獨立工作者後續成功取得HW2 project `C-e68890e5a4a7e5b088e6a188-IR-HW2`、root `C:/成大專案/IR-HW2`；最後 generation `2026-09-30T07:02:58Z`，13個明確指定的source／test／verification路徑均metadata_match／no_recorded_issue，詳 `reports/hw2/tokenizer_graph_coverage.json`。這只代表該次有限範圍的best-effort coverage，不證明全儲存庫完整，也不代表主工作者的MCP連線已恢復。

仍待教師確認：Porter是否必須手刻、繳交媒介、demo長度及是否更新2026-10-06截止日。兩領域比較仍為optional未做。所有正式數字來自真實快照，合成資料只作測試。


## 10. 作業四條件 v5（2026-09-30，現況）

使用者最後確認依作業要求恢復四組，現況為A基本切詞與NFC／casefold正規化、B沿用HW1 tokenizer的標點處理、C停用詞、D Porter，介面預設A。四組都列入正式比較，primary_comparison為ABCD、reference_condition為null，版本 `hw2-hw1-four-conditions-v5-log10`。中途ABC三組試行已撤回，不作為交付現況；第9節四組舊版已封存於 `reports/hw2/history/hw1-four-conditions-20260930/`。

新版正式分析已執行：A–D tokens=244477／246256／179304／179304，詞彙=29203／17910／17792／14305，完整16回歸、39詞CF／DF／IDF、21份CSV／JSON／PNG。語料與原HW1 tokenizer指紋未變。

模型沿用已保存的相同B條件、原tokenizer契約之模型，並重新離線驗證重載成功；沒有再次訓練。metadata記錄10843句、246256tokens、9658詞彙，原訓練17.7362秒、vectors SHA256仍7de476d45de19d97d0572bbc561266ba6efac538c462a4f817144e647cae62f0。分析46項手算／輸出測試通過；最終全套487 passed in50.69s（原348＋HW2 139），無失敗／錯誤／跳過。四組獨立核對passed，耗時7.112s，21檔重跑逐位元一致、16擬合及39選詞皆通過，見最新版 `tokenizer_verification.json` 與 `pytest-hw1-tokenizer.xml`。

報告、摘要、README、demo與開發說明均以四組v5為準；來源PDF原A–D要求恢復，不需額外規格豁免。PDF已重建，delivery verifier已核對最新來源hash及英文討論389words；主報告12頁、摘要1頁均完成逐頁視覺檢查，612項來源文字／表格核對通過，紀錄見 `reports/hw2/pdf_qa.json`。看圖導讀也使用正式A組資料（244,477 tokens、29,203詞），桌面明暗模式與手機版驗證見 `reports/hw2/tokenizer_guide_qa.json`。舊483／484及三組版487項47.72秒均為中途歷史；本版487項50.69秒須依最新XML與原始碼版本辨識，不能只看測試總數。
