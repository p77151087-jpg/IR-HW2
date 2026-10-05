# Lecture 3 與目前 HW2：優化評估

本次閱讀：`lecture-3-tfidf-1-20260929-1.pdf`，共 60 頁。全文抽取及所有頁面圖像均已閱讀，另放大核對第 17、57–59 頁。來源位於 `C:\成大專案\課程內容\IR\HW2`；閱讀中間檔位於 `tmp/lecture3-review/`。本文件是優化建議，並非新增作業規格或宣稱建議功能已完成。

2026-09-30 補記：HW2 正式摘要分析使用 log10，並依使用者最後指示恢復作業四組：A 基本切詞與小寫、B 沿用 HW1 切詞規則處理標點、C 移除 stopwords、D Porter。下列六個查詢仍是 9/29 對既有搜尋權重的歷史比較，不是新版摘要實驗；本次更換分析基準不改變該搜尋索引與公式。

四組恢復、預設 A、教材及交付更新見 [HW2_CHANGELOG](HW2_CHANGELOG.md)。本文的「本次」及原測試引用指 2026-09-29 講義評估；最新四組測試紀錄為 `reports/hw2/pytest-hw1-tokenizer.xml`（487 passed），不能把下方歷史檢查當成新版全套回歸。本文的後續優化建議尚未因此變成已完成項目。

## 1. 判斷與建議順序

目前作業已具備講義的主要計算基礎：倒排索引、log TF、DF-based IDF、完整文件向量 L2 norm、cosine 與分數遞減排序。最有價值的下一步是把計算變成可檢查的展示，並建立能評估「排序是否更好」的證據。

建議先完成「搜尋分數拆解＋公式對照」，接著補人工相關性評估。CF／DF 視覺化與相似文章可作為後續加分項。Lecture 3 沒有明確新增 HW2 繳交項目、取消 Word2Vec／拼字校正，或變更截止日；原 HW2 必做範圍繼續有效。是否必須手刻 Porter，這份講義也未解答。

| 優先 | 講義依據 | 建議 | 現有可沿用位置 | 驗收方式 |
| --- | --- | --- | --- | --- |
| 1 | pp. 34–44、46–53、59 | 每筆搜尋結果增加「分數怎麼算」：查詢詞、文件 TF、DF、IDF、查詢與文件權重、兩個 norm、各詞 cosine 貢獻 | `ir_hw1/tfidf.py`、`ir_hw1/search.py`、`app.py` | 各詞貢獻和等於顯示分數；以手算小語料及正式資料核對；處理 OOV、零向量、stem／原查詢對照 |
| 1 | pp. 35–38、57–59 | 增加明確標示的講義公式比較頁，與現行公式並列 Top 10；記錄 query weighting | `ir_hw2/ui.py`；本次 `scripts/review_lecture3.py` 可作比較原型 | 比較使用同一索引、同一候選文件與前處理；測試 DF=N 時 IDF=0；比較設定可保存；正式 A–D 統計不混用搜尋特徵 |
| 2 | pp. 15–19、23–26 | 固定至少 10 個 GLP-1 查詢與資訊需求，人工標記結果，報告 P@5、P@10；有分級標記時再加入 nDCG | `tests/test_tfidf.py` 的計算測試可保留，另建獨立 retrieval evaluation | 保存 queries、qrels、系統輸出與評分程式；標記者不要看到系統名稱與分數；未標記文件不可冒充確定不相關 |
| 3 | pp. 3–11、20–22、40 | 在既有 CF／DF 表之外，增加 CF–DF 散點圖、DF/N 覆蓋率、CF/DF（出現文件內的平均次數） | `ir_hw2/analysis.py`、`ir_hw2/ui.py`、正式實驗 CSV | 各圖與原始 CSV 一致；標示停用詞、領域詞；避免自動刪除高 DF 領域詞或低頻基因詞 |
| 選配 | pp. 54–55 | 文章詳情提供 TF-IDF「相似文章」 | 現有 postings／TF-IDF norm、文章詳情頁 | 完整文件向量間 cosine、排除文章本身、正確處理零向量；註明文字特徵相似不等於臨床結論相同 |
| 低 | pp. 56、60 | 規模增加後再評估 Top K heap 等效率改善 | `ir_hw1/search.py` | 先量測資料規模與延遲；與既有排序完全一致且有效改善後才採用 |

本次已新增可重跑的診斷與此評估文件；上表介面及人工評估仍是後續建議，未改動既有搜尋預設或正式實驗。

## 2. 60 頁閱讀對照

| 頁碼 | 主題 | 對目前作業的意義 |
| --- | --- | --- |
| 1–2 | term weighting、DF、postings | 既有資料結構已能支援 |
| 3–11 | Zipf、頻率分布、resolving power | 補強 stopwords 與區辨力的討論；不要把近似規律當成必然定律 |
| 12–14 | 統計獨立性、索引廣度與專一性、詞與片語 | 說明詞袋限制；不自動新增 PMI 或受控詞彙系統為必做項 |
| 15–19 | precision、recall、F measure、trade-off | 明確區分計算正確性與檢索品質 |
| 20–22 | function/content words、頻率與辨識力 | 高頻不一定無用，低頻也不一定應刪除 |
| 23–29 | ranked retrieval、Jaccard 與其限制 | 說明目前排序的理由，避免將 score 說成相關機率 |
| 30–35 | binary/count、BOW、log TF | 保留搜尋原文位置；詞頻增加的效果不是線性 |
| 36–44 | DF、IDF、TF-IDF、向量 | 分開講義、HW1 搜尋、HW2 摘要分析公式 |
| 45–53 | 文件長度、L2 normalization、cosine | 使用全文件 norm，不只正規化命中的查詢詞 |
| 54–56 | 文件相似度、倒排累加、Top K | 可增加相似文章；效能改善應先量測 |
| 57–60 | weighting variants、SMART、範例與總結 | 適合做可重現公式比較，部分記號及算式需校核 |

## 3. 現有公式與講義的差異

以下 N 是索引中的文件數，DF 是包含詞的文件數，tf 是詞在單篇文件中的次數。講義 Zipf 段落的 token 總數不可直接與此 N 混用。

| 項目 | 現行搜尋 | Lecture 3 | HW2 正式摘要分析 |
| --- | --- | --- | --- |
| 文件 TF 權重 | `1 + ln(tf)`，tf>0 | p.35：`1 + log10(tf)`，tf>0；p.57 列其他方案 | CF／DF 為真實 token 計數，未套搜尋 TF 權重 |
| IDF | `ln((N+1)/(DF+1)) + 1` | p.38：`log10(N/DF)`；另有不同 SMART 組合 | `log10(N/DF)`；2026-09-30 依使用者要求統一以 10 為底 |
| 查詢 TF | 去重後的詞，各詞 TF=1 | 可依所選方案用原始或 log TF；範例查詢沒有重複詞 | 不適用 |
| norm | 查詢 L2、完整文件 L2 | cosine 需要兩者；固定查詢排序時可省略共同的 query norm | 不適用 |
| 特徵 | Porter 與搜尋專用複合詞展開 | 教學模型須另外指定前處理 | 摘要正文；A 基本切詞→B 標點→C stopwords→D Porter；不含搜尋專用展開 |

現有 `ir_hw1/tfidf.py` 與手算測試已確保完整文件 norm；`search.py` 以分數由高至低排序。`app.py` 也已有 cosine 百分比不是準確率的說明。這些都值得保留。

**對數底數的影響要分開說明。** 單純把未平滑 IDF 從 ln 換成 log10，是所有 IDF 乘同一常數，完整 cosine 中會抵消。但把 `1+ln(tf)` 換成 `1+log10(tf)` 並不是同一常數縮放；平滑 IDF 與未平滑 IDF 也不同，因此排序可能改變。不能籠統宣稱「換 log 底數一定不影響 TF-IDF 排序」。TF-IDF 與 query/document weighting 可參考 [Stanford IR book：weighting schemes](https://nlp.stanford.edu/IR-book/html/htmledition/document-and-query-weighting-schemes-1.html)。

## 4. 已實際執行的公式比較

程式：`scripts/review_lecture3.py`。完整結果：`reports/hw2/lecture3_diagnostics.json`。記錄時間：2026-09-29 15:10:40 UTC。使用目前 `data/index.json` 的 1,000 篇文件，沒有重新下載、建索引或執行正式 A–D 實驗。

四個方案都沿用同一組既有 Porter relevance postings、相同查詢詞、二元 query TF、候選文件與 L2 cosine，僅改變權重：

1. `legacy`：現行搜尋公式。
2. `unsmoothed_ln`：文件 TF 仍為 `1+ln(tf)`，IDF 改成 `ln(N/DF)`。
3. `idf_base_only`：在方案 2 上僅將 IDF 換為 `log10(N/DF)`。
4. `lecture_log10`：文件 TF 為 `1+log10(tf)`，IDF 為 `log10(N/DF)`。

方案 4 是講義基本 TF-IDF／cosine 的一個明確組合，不宣稱講義只允許這一種配置，也不是 p.59 document 不使用 IDF 的特定範例。這些搜尋特徵不是 HW2 A–D 的原始摘要計數。

| 固定查詢 | 既有匹配文件數 | 現行／講義方案前 10 名共同篇數 |
| --- | ---: | ---: |
| semaglutide | 234 | 5 / 10 |
| insulin | 203 | 7 / 10 |
| obesity treatment | 695 | 7 / 10 |
| GLP-1 | 580 | 7 / 10 |
| semaglutide kidney disease | 542 | 8 / 10 |
| tirzepatide cardiovascular risk | 565 | 7 / 10 |

這是六個查詢的排序敏感度檢查，不是具代表性的品質評估；前 10 名交集也不反映相同文章的名次移動。沒有人工相關性標記，不能據此宣稱任一方案更準確。

實際通過的程式斷言：重算現行公式與既有搜尋分數最大差異小於 `1e-12`，現行 Top 10 完全一致；僅換未平滑 IDF 的 log 底數，分數最大差異小於 `1e-12`；各詞貢獻和等於既有分數；執行前後索引 bytes 完全一致。記錄的索引 SHA-256 為 `295253a775870f508907a7643e8ee33371778d25fddf3cce33b5ed33c02c4884`。

例如查詢 `semaglutide kidney disease`，首篇 `PMID42567173` 的分數為 `0.1996818997`。這張表可直接作為「計分說明」功能的原型資料：

| 索引詞 | 文件 TF | DF | 現行 IDF | cosine 貢獻 |
| --- | ---: | ---: | ---: | ---: |
| semaglutid | 10 | 234 | 2.449169 | 0.061219237 |
| kidnei | 15 | 131 | 3.025953 | 0.104921916 |
| diseas | 5 | 353 | 2.039458 | 0.033540747 |

查詢 norm 為 `4.394793416`，完整文件 norm 為 `73.631770470`；表中三個貢獻相加得到 cosine。這些是 Porter 後的索引詞，介面應同時顯示原查詢，避免使用者誤以為字被拼錯。

重跑（PowerShell，工作目錄 IR-HW2）：

```powershell
.\.venv-hw2\Scripts\python.exe -X utf8 scripts/review_lecture3.py
```

會重寫診斷 JSON，且結果取決於當時 `data/index.json`；因此比較時需核對記錄的索引 hash。這是已實跑的診斷斷言，不等同重新執行完整 pytest。本次未重新執行全套測試；既有完整測試紀錄仍以 `reports/hw2/pytest-final.log` 為準。

## 5. 檢索評估應如何補

`scripts/verify_hw2.py` 現有搜尋／高亮驗證能查出資料流或實作不一致；`tests/test_tfidf.py` 能驗證公式。兩者都不是人工相關性評估。`scripts/evaluate_sentences.py` 中的 precision／recall 是斷句任務，也不能當成搜尋品質。

建議固定查詢及資訊需求，例如某查詢究竟想找藥物減重效果，還是腎臟結果；合併各方案的 Top 10／Top 20 去重後，隱藏方案及排名資訊進行人工判讀。先做 P@5、P@10，保存每一筆標記及理由。評量前就決定 tie-breaking、無結果及少於 K 筆時的處理規則。若調整參數，需留出未參與調整的查詢。

只標記檢索結果的一小部分，不能聲稱已知整個 1,000 篇集合的真正 recall。若需要 recall／F1，可完整標記一個明確限定的子集合，並將評估結論限制在該集合；或清楚報告以 pooled judgments 計算的近似 recall 及漏標限制。P@K 與 ranked evaluation 的使用可參考 [Stanford IR book：evaluation of ranked retrieval](https://nlp.stanford.edu/IR-book/html/htmledition/evaluation-of-ranked-retrieval-results-1.html)。

人工標記尚未建立；不可用 AI 自評或 cosine 閾值產生標準答案，再宣稱已驗證相關性準確率。

## 6. 講義公式／記號需要留意的地方

這些問題已對照頁面影像及定義，不應照抄到程式與報告。

| 頁碼 | 核對結果 | 作業採用方式 |
| --- | --- | --- |
| 17 | 列出的 Fβ 公式正確，但 β 的說明方向顛倒 | `Fβ=(1+β²)PR/(β²P+R)`；β>1 偏重 recall，β<1 偏重 precision |
| 29 | intersection / sqrt(union) 不是一般二元向量 cosine | 二元 cosine 為 `|A∩B|/sqrt(|A||B|)`；一般向量採 p.53 的 dot product／norm 定義 |
| 49、51 | decreasing angle／increasing cosine 的方向會先列不相似者 | 最相似先列：角度由小至大，cosine 由大至小；現有程式排序正確 |
| 58 | 講義採 qqq.ddd（query 在前），與常見 SMART 慣例相反；範例 ltn.ltc 與 document「no idf」文字不一致 | 報告直接列 query/document 各自的 TF、IDF、norm，避免只給縮寫；依講義順序及 no-idf 文字，應是 ltn.lnc，p.59 也如此標示 |
| 59 | insurance 的 document log TF 應為 1.30103；norm 展開式漏掉平方項的 1.30103，而所列約 1.92 接近正確值 | 精算 norm=1.921634473、未正規化查詢 score=3.071910953；若查詢也 L2 正規化，cosine=0.801416217 |
| 48、52 | 「整篇文字加倍，方向完全不變」需限定 TF 表示 | 對 raw TF 的等比例縮放成立；`1+log(tf)` 一般不是等比例縮放，不能用完全相同分數作為 log-TF 的普遍測試斷言 |

Fβ 的方向可由公式極限核對：β→∞ 時趨近 recall，β→0 時趨近 precision；亦見 [Stanford IR book：F measure](https://nlp.stanford.edu/IR-book/html/htmledition/evaluation-of-unranked-retrieval-sets-1.html)。SMART 慣例在 [Stanford weighting schemes](https://nlp.stanford.edu/IR-book/html/htmledition/document-and-query-weighting-schemes-1.html) 採 document.query。一般 cosine 定義見 [Stanford：dot products](https://nlp.stanford.edu/IR-book/html/htmledition/dot-products-1.html)。

p.59 的大於 1 分數本身不是 bug：該範例未除 query norm，固定查詢下不影響名次，但不得把它標成 0–1 cosine 或百分比相關機率。本次診斷另外以 N=1,000,000 及該頁 DF／TF 精算，結果已寫入 JSON；課堂表格若逐欄取兩位小數，會出現與精算不同的 3.08。

## 7. 查核範圍與保留事項

採 Tier 2 查核 HW2 自己的 graph project `C-e68890e5a4a7e5b088e6a188-IR-HW2`，root `C:/成大專案/IR-HW2`；本次起始 generation `2026-09-29T02:18:51Z`，新診斷加入後自動更新至 `2026-09-29T15:10:59Z`。相關符號以 search_graph、trace_path、get_code_snippet 檢視，並檢查依賴路徑 coverage；結論以具體程式內容為準，不以 graph 沒找到就推論功能不存在。

已核對 `ir_hw1/tfidf.py`、`ir_hw1/search.py`、`ir_hw1/index.py`、`ir_hw2/analysis.py`、`ir_hw2/ui.py`、`app.py`、`tests/test_tfidf.py`、`scripts/verify_hw2.py`、`scripts/evaluate_sentences.py` 及現有 HW2 報告。`data/index.json` 在 graph 中因 parse timeout 缺漏，診斷直接讀取 JSON 補證；新診斷腳本及結果也直接讀取確認。乾淨 coverage 僅表示未記錄缺漏，不是完整性的證明。

本次未改動原 HW1、正式語料快照、A–D 實驗結果、Word2Vec 模型、既有搜尋公式或主報告。後續實作應保留「搜尋特徵」與「摘要統計」的分界；不因新講義重新生成正式結果，亦不把所有延伸主題都升格為必做功能。
