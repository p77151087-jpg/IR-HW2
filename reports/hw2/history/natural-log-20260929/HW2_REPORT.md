# Biomedical IR Homework 2：1,000 篇 GLP-1 摘要的詞頻、Zipf 與檢索分析

實驗日期：2026-09-29。語料：固定 1,000 篇 PubMed 英文非空摘要。所有數值取自本次正式執行；手算合成資料僅用於測試。本報告對應 9/29 詳細版 RQ1–RQ5，並保留 9/22 原題的 Word2Vec 與拼字校正範圍。

**主要發現：本語料呈現少數高頻詞與大量稀有詞，但不能用全範圍的一條直線宣稱「證明 Zipf’s Law」。四種前處理的中頻區段都比高頻、低頻區段有更高 R² 與更低 log-space RMSE。B 組中頻 exponent 為 0.997343，接近 1；同組全範圍 exponent 卻為 1.399350。**

## 1. 語料、範圍與來源

正式快照位於 [glp1-1000-20260929](C:/成大專案/IR-HW2/data/hw2/glp1-1000-20260929/snapshot.json)。查詢式完整保存如下，依 PubMed `pub date` 排序選取前 1,000 篇符合納入規則的紀錄：

```text
("GLP-1"[Title/Abstract] OR "glucagon-like peptide-1"[Title/Abstract])
AND english[Language] AND hasabstract
AND ("1900/01/01"[Date - Publication] : "2026/09/29"[Date - Publication])
```

下載開始時間為 `2026-09-29T01:50:15.695115+00:00`，完成時間為 `2026-09-29T01:50:43.670501+00:00`。這是依主題與日期排序取得的目的性樣本，不是全部 PubMed 或一般英文的隨機代表樣本。查詢可在標題命中，但統計內容只取 `Article/Abstract/AbstractText` 正文；文章標題、結構化摘要小標題及全文均不計入。

| 取得與篩選項目 | 實際數量 |
| --- | ---: |
| 查詢符合總數 | 30,622 |
| 保存候選 PMID | 1,200 |
| 已下載紀錄 | 1,100 |
| 正式納入唯一 PMID、英文非空摘要 | 1,000 |
| 排除 | 5 |
| 排除原因：不支援的 PubmedBookArticle | 2 |
| 排除原因：空摘要 | 3 |
| 已下載且合格，但名額已滿 | 95 |
| 名額已滿而不需下載 | 100 |
| 重複候選 PMID／重複回傳紀錄 | 0／0 |

`not_needed=195` 是 95 篇合格未選加 100 篇未下載，不應和 5 篇排除混為一談。逐篇納排結果在 [selection.json](C:/成大專案/IR-HW2/data/hw2/glp1-1000-20260929/selection.json)，原始 API 回覆在快照下 `raw-batches`。兩篇 BookArticle 的排除理由曾由「EFetch 未回傳」更正為「格式不支援」；更正前 metadata 與稽核紀錄仍保留，正文及納入 PMID 不變。另有兩篇文章的期刊卷期年份為 2027，但電子發表日期為 2026、符合 PubMed 日期查詢；不可只以 `Document.year` 誤判違反截止日期。

摘要 JSONL SHA256：`9738b68d03a6e39bed010803aa878cfdc66e0bbcaf005e8ee83d3bcfeb7b2631`。分析用 PMID／摘要文字序列 SHA256：`f990854805c5951c6b386ab5071c0ae9eb3630dedc5f4dd0cc9b9b7ea11b9e4a`。前者驗證檔案，後者驗證真正送入分析的內容。可增刪的搜尋文章庫與此固定實驗快照分開。

本次未使用 API key；程式單線每秒最多 1 request、每批 100 PMID、暫時錯誤最多 3 次嘗試，保存快取供失敗續傳。官方無 key 限制為每秒 3 requests，參見 [NCBI E-utilities 使用規範](https://www.ncbi.nlm.nih.gov/books/NBK25497/) 與 [NCBI API key 說明](https://www.ncbi.nlm.nih.gov/books/NBK53593/pdf/Bookshelf_NBK53593.pdf)。`tool=ir_hw2`；未提供聯絡 email，沒有虛構註冊資料。原始 PubMed 摘要可能受著作權保護，本地課程分析保存不代表所有摘要皆為開放授權。

## 2. 獨立、累積的 A → B → C → D

| 條件 | 本次實作與可重現定義 |
| --- | --- |
| A | 以非空白序列作 token，執行 Python `str.lower()`；保留附著與獨立標點。 |
| B | A 再把所有非 Unicode Letter／Mark／Number 字元視為分隔，取連續 `[\p{L}\p{M}\p{N}]+`。標點、連字號與數學符號都會拆詞。 |
| C | B 再移除固定 132 詞的專案停用詞表 `hw2-function-words-v1`；保留 `no`、`not`、`without`。本次語料實際出現其中 118 種。 |
| D | C 再對純 ASCII 字母 token 使用 NLTK Porter `MARTIN_EXTENSIONS`；含數字或非 ASCII 的 token 不 stemming。 |

例如 `IL6 GLP-1 1.5 cats,`：A 得 `il6, glp-1, 1.5, cats,` 四個 token（最後一個包含逗號）；B 得 `il6, glp, 1, 1, 5, cats` 六個 token。這是預先定義的比較規則，**不等於理想的生醫檢索 tokenizer**。尤其 `1`、`0` 的高頻部分反映複合詞、小數與統計數字被拆開，不能直接解釋成語意主題。

本流程不做 HW1 搜尋索引的 IL6 → il-6／il／6 額外特徵展開，不做 Unicode 正規化或 casefold，也不做隱藏的孤立字母、數字過濾。每個 PMID 算一篇 document；同篇同詞無論出現多少次，DF 只增加一次。即使某篇文章的詞在 C／D 全部被移除，N 仍保留該篇，以維持同一比較母體。重複 PMID、無效 PMID 或空摘要輸入會明確報錯。

停用詞表 [hw2_stopwords.json](C:/成大專案/IR-HW2/resources/hw2_stopwords.json) 的 SHA256 為 `d907482b2aabc0443ae05c95e0c9685ef6f8ff8789370a34c004a498d1abc406`。分析版本 `hw2-abstract-cumulative-v1`；Python 3.13.14、NLTK 3.9.2、regex 2026.9.10、Matplotlib 3.11.2。完整規則、套件版本、詞表與程式碼 SHA256 都在 [summary.json](C:/成大專案/IR-HW2/reports/hw2/experiment/summary.json)。NLTK 提供不同 Porter 模式，本作業明確選用 Martin 擴充版本，**不是自行撰寫 Porter 演算法**；模式定義參見 [NLTK 官方文件](https://www.nltk.org/api/nltk.stem.porter.html)。

## 3. 詞彙與高頻詞：RQ3

| 條件 | Documents | Tokens | Unique terms | 平均 tokens／篇 | CF=1 詞數 | CF=1／詞彙 | Top 10／tokens | ΣDF |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| A | 1,000 | 244,477 | 29,255 | 244.477 | 17,412 | 59.518% | 18.012% | 162,036 |
| B | 1,000 | 266,039 | 13,338 | 266.039 | 4,865 | 36.475% | 18.285% | 157,621 |
| C | 1,000 | 198,384 | 13,220 | 198.384 | 4,861 | 36.770% | 9.118% | 133,436 |
| D | 1,000 | 198,384 | 9,613 | 198.384 | 3,429 | 35.670% | 9.718% | 126,120 |

此處單字數是各條件的 tokens，不能套用 HW1 介面以空白切分顯示的摘要字數。ΣDF 是不含位置的「詞—文件」postings entry 數量，可用作索引大小的其中一個代理量，並不是實際壓縮位元組數。

| 條件 | 依排名列出的 Top 10（括號為 CF） |
| --- | --- |
| A | and (10,586), the (6,144), of (5,807), in (4,864), with (4,126), to (3,567), a (3,105), for (2,255), were (1,867), was (1,713) |
| B | and (10,666), the (6,154), of (5,837), in (4,901), 1 (4,285), with (4,135), to (3,669), a (3,167), glp (3,052), 0 (2,779) |
| C | 1 (4,285), glp (3,052), 0 (2,779), 2 (1,434), receptor (1,210), weight (1,155), patients (1,096), obesity (1,086), risk (1,054), associated (938) |
| D | 1 (4,285), glp (3,052), 0 (2,779), us (1,461), 2 (1,434), patient (1,305), studi (1,286), receptor (1,263), associ (1,215), weight (1,199) |

完整 Top 50 分別見 [A](C:/成大專案/IR-HW2/reports/hw2/experiment/top50_A.csv)、[B](C:/成大專案/IR-HW2/reports/hw2/experiment/top50_B.csv)、[C](C:/成大專案/IR-HW2/reports/hw2/experiment/top50_C.csv)、[D](C:/成大專案/IR-HW2/reports/hw2/experiment/top50_D.csv)；完整詞表另有 `terms_A.csv` 至 `terms_D.csv`，包含每個詞的 rank、CF、DF 與 IDF。

![A–D 計數及索引大小代理量](C:/成大專案/IR-HW2/reports/hw2/experiment/preprocessing_comparison.png)

**A → B：標點正規化既合併字形，也拆出更多 token。** Tokens 增加 21,562（8.820%），詞彙卻減少 15,917（54.408%）；A 的 `data,` 和 `data.` 這類表面形式可在 B 合併。同時 GLP-1、小數及各種連字號被切開，不能把增加的 tokens 當成新增內容。單次詞比例由 59.518% 降到 36.475%，顯示 A 的長尾有相當部分與附著標點等表面差異相關；這不是對每個稀有詞做來源歸因的因果估計。

**B → C：少量詞型承擔大量出現次數。** 刪除 118 種實際出現的停用詞，只減少 0.885% 詞彙，卻刪除 67,655 tokens（25.431%）；ΣDF 減少 24,185（15.344%）。Top 10 的 token 份額由 18.285% 降至 9.118%，高頻端轉向領域詞與數字。全範圍 exponent 由 1.399350 降至 1.353468，高頻段由 0.800667 降至 0.606083，不能假設移除停用詞必然讓整體「更 Zipf」。

**C → D：stemming 合併詞型，而不是刪除 token。** Tokens 保持 198,384，詞彙由 13,220 降至 9,613（減少 27.284%），ΣDF 再降 5.483%。如 studies／study 可合併，分開詞型的 DF 可能有重疊，合併後不能直接把 DF 相加。D 的 `us` 是 `use` (647)、`using` (534)、`used` (262)、`useful` (10)、`uses` (8) stemming 後的 1,461 次總和；原始代名詞 `us` 已在 C 移除。這說明「先停用詞、後 stemming」的順序會產生表面上像停用詞的 stem；本次沒有臨時追加第二輪過濾。詞型合併也可能損失語意區別，不能僅因詞彙變小就宣稱搜尋品質提升。

## 4. Zipf 方法、全範圍與分段結果：RQ1、RQ2

每個條件依 CF 由大至小排列，同頻詞以 Unicode 詞彙順序穩定排序，給予 ordinal rank 1…V，不使用共享排名或平均排名。所有詞都保留，包含 CF=1。令 x=ln(rank)、y=ln(CF)，OLS 擬合 y=a+slope×x，Zipf exponent b=−slope，即 CF≈exp(a)×rank^(−b)。log 底數均為自然常數 e。

R²=1−Σ(y−ŷ)²／Σ(y−ȳ)²；RMSE=√[Σ(y−ŷ)²／n]。RMSE 在 **ln(CF) 空間**，分母為 n，不是 n−2，也不是原始 CF 空間。頻率完全相同時 y 沒有變異，R² 記為 null；少於兩點或 rank 不變時不回報不存在的擬合參數。本次表格的每列都有足夠資料。

預先分段規則：高頻為前 floor(1%×V) 名，中頻為其後至 floor(10%×V)，低頻為剩下 90%。程式為極小測試資料另有至少兩點的邊界防呆；正式語料沒有觸發調整。下表明列各自實際 rank 區間；不同條件的相同百分位不是同一群詞，也不保證 CF 門檻相同。

| 條件／區段 | Rank 範圍 | n | slope | intercept a | exponent b | R² | RMSE ln(CF) |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| A 全部 | 1–29,255 | 29,255 | -1.080311 | 10.717248 | 1.080311 | 0.954883 | 0.234578 |
| A 高頻 | 1–292 | 292 | -0.844591 | 9.438389 | 0.844591 | 0.995895 | 0.052227 |
| A 中頻 | 293–2,925 | 2,633 | -1.065685 | 10.824890 | 1.065685 | 0.996448 | 0.037399 |
| A 低頻 | 2,926–29,255 | 26,330 | -0.973492 | 9.678811 | 0.973492 | 0.864802 | 0.226231 |
| B 全部 | 1–13,338 | 13,338 | -1.399350 | 13.166838 | 1.399350 | 0.967425 | 0.256266 |
| B 高頻 | 1–133 | 133 | -0.800667 | 9.532118 | 0.800667 | 0.990390 | 0.073878 |
| B 中頻 | 134–1,333 | 1,200 | -0.997343 | 10.599013 | 0.997343 | 0.995616 | 0.038884 |
| B 低頻 | 1,334–13,338 | 12,005 | -1.639395 | 15.279961 | 1.639395 | 0.973650 | 0.158526 |
| C 全部 | 1–13,220 | 13,220 | -1.353468 | 12.735397 | 1.353468 | 0.960945 | 0.272308 |
| C 高頻 | 1–132 | 132 | -0.606083 | 8.382862 | 0.606083 | 0.982708 | 0.075280 |
| C 中頻 | 133–1,322 | 1,190 | -0.939893 | 10.114003 | 0.939893 | 0.994813 | 0.039864 |
| C 低頻 | 1,323–13,220 | 11,898 | -1.609315 | 14.984423 | 1.609315 | 0.972632 | 0.158646 |
| D 全部 | 1–9,613 | 9,613 | -1.467445 | 13.345200 | 1.467445 | 0.959162 | 0.302006 |
| D 高頻 | 1–96 | 96 | -0.559951 | 8.399781 | 0.559951 | 0.979700 | 0.074259 |
| D 中頻 | 97–961 | 865 | -0.986720 | 10.473323 | 0.986720 | 0.993090 | 0.048317 |
| D 低頻 | 962–9,613 | 8,652 | -1.752498 | 15.758680 | 1.752498 | 0.976736 | 0.158956 |

完整精度見 [regression.csv](C:/成大專案/IR-HW2/reports/hw2/experiment/regression.csv)。表內四捨五入只用於閱讀，後续運算採 JSON／CSV 完整數值。

![Rank-frequency 全範圍與 CF 對數軸](C:/成大專案/IR-HW2/reports/hw2/experiment/rank_frequency.png)

圖 1 左側線性軸凸顯頭部集中；右側僅 CF 軸取對數，讓完整 rank 範圍與低頻階梯可見。不能從左側被壓平的長尾判斷詞頻均勻。

![自然對數 Zipf 散點與全範圍 OLS](C:/成大專案/IR-HW2/reports/hw2/experiment/log_log.png)

圖 2 顯示觀察值與全範圍 OLS。A 的 exponent 雖最接近 1，並不代表 A 是最佳文字處理方式；A 同時有最高的單次詞比例與明顯離散平台。B–D 的中段接近直線，頭部與尾部的斜率則不同。

![全範圍 OLS 殘差](C:/成大專案/IR-HW2/reports/hw2/experiment/residuals.png)

圖 3 是「觀察 ln(CF) − 全範圍預測 ln(CF)」，不是各段重新擬合後的殘差。虛線標記高／中／低頻邊界。四組均有系統性的彎曲，B–D 頭部尤其被全範圍直線高估，低頻端有 CF 為小整數造成的斜帶。這與純隨機、無結構的微小殘差不同。

**RQ1：是否符合 Zipf？** 可說具有 Zipf 式的非均勻詞頻結構，以及中頻區段的良好局部近似；不能說所有 rank 服從同一個精確的 power law。這一結論同時使用圖形、分段 slope、R²、RMSE 與殘差，不只選一個最漂亮的數字。

**RQ2：exponent 是多少？** 必須連同前處理和擬合區間回答。A–D 全範圍分別為 1.080311、1.399350、1.353468、1.467445；若選 B 為保留停用詞且處理標點的參考條件，其全範圍 b=1.399350，中頻 b=0.997343。不能把後者當成全語料的唯一 exponent。

**哪個區段擬合最好？** 在這套預先指定的三段中，四組皆以中頻段同時達到最高 R² 與最低 RMSE；其 b 介於 0.939893–1.065685，也最接近課堂 b≈1 的直觀模型。但各段 x／y 範圍不同，R² 不能完全等價跨段比較，這是本次描述性結論，不是無條件最佳區間搜尋。

**R² 是否充分？** 不充分。排序後的 rank／CF 不是獨立隨機觀測；OLS 對每個詞型給相同權重，長尾的詞型數占大部分；同頻詞被分配不同 ordinal ranks，又形成平台。高 R² 只表示在所選 log 空間的線性解釋程度，沒有比較其他分布、做 power-law 適合度檢定、估計 cutoff 不確定性或外部語料驗證。若只挑 CF=1 的平台，水平線 RMSE=0，但 R² 無定義、b=0，更不能稱為理想 Zipf。若要提出統計上的分布主張，還需要事先選定模型、替代分布與適當的抽樣／適合度程序；本作業沒有冒稱完成這些延伸分析。

## 5. CF、DF 與指定 IDF：RQ4

CF(t)=所有摘要中 t 的出現次數；DF(t)=包含 t 的不同 PMID 數。指定公式為 **IDF(t)=ln(1000／DF(t))**，不平滑、不加 1；HW1 搜尋的 `ln((N+1)/(DF+1))+1` 仍只用於既有搜尋，不混入本表。

以 B 條件選取 32 個實際觀察到的 terms：前 10 名、固定排名百分位，以及存在的領域／否定詞，涵蓋高、中、低頻。表中的數字 token 是 B 規則真正產生的結果，另保留基因樣式詞 `wnt5a`；不以合成示例取代實測。下表同時滿足至少 20 個詞的 CF／DF 比較與至少 10 個詞的 IDF 計算。

| B term | CF | DF | IDF=ln(1000／DF) |
| --- | ---: | ---: | ---: |
| and | 10666 | 997 | 0.003005 |
| the | 6154 | 977 | 0.023269 |
| of | 5837 | 973 | 0.027371 |
| in | 4901 | 961 | 0.039781 |
| 1 | 4285 | 955 | 0.046044 |
| with | 4135 | 915 | 0.088831 |
| to | 3669 | 944 | 0.057629 |
| a | 3167 | 922 | 0.081210 |
| glp | 3052 | 766 | 0.266573 |
| 0 | 2779 | 414 | 0.881889 |
| receptor | 1210 | 798 | 0.225647 |
| patients | 1096 | 405 | 0.903868 |
| obesity | 1086 | 484 | 0.725670 |
| diabetes | 867 | 531 | 0.632993 |
| treatment | 812 | 431 | 0.841647 |
| semaglutide | 682 | 234 | 1.452434 |
| glucose | 627 | 345 | 1.064211 |
| not | 573 | 367 | 1.002393 |
| insulin | 487 | 201 | 1.604450 |
| agonist | 331 | 256 | 1.362578 |
| no | 331 | 242 | 1.418818 |
| control | 268 | 202 | 1.599488 |
| without | 245 | 176 | 1.737271 |
| syndrome | 105 | 67 | 2.703063 |
| lean | 63 | 29 | 3.540459 |
| rapidly | 29 | 29 | 3.540459 |
| reflecting | 11 | 11 | 4.509860 |
| referral | 6 | 6 | 5.115996 |
| wnt5a | 4 | 1 | 6.907755 |
| 749 | 2 | 2 | 6.214608 |
| cytoplasm | 1 | 1 | 6.907755 |
| ⁸ | 1 | 1 | 6.907755 |

可重用表格：[CF／DF CSV](C:/成大專案/IR-HW2/reports/hw2/experiment/cf_df_comparison.csv)、[IDF CSV](C:/成大專案/IR-HW2/reports/hw2/experiment/idf_terms.csv)。例如 `semaglutide` 的 IDF=ln(1000／234)=1.452434，而 `and` 為 ln(1000／997)=0.003005。

**高 CF、相對低 DF 為何可能出現？** 同一篇藥物研究可以反覆使用藥名，所以 CF 增加，DF 卻只增加一次。實際 `semaglutide` 出現 682 次、分布於 234 篇，平均每篇命中文章約 2.91 次；它的覆蓋率只有 23.4%。這表示局部重複及主題聚集，並不意味著每篇都重要。更極端的 `wnt5a` 四次全在同一篇，而 `cytoplasm` 只有一次；兩者 DF 都是 1，IDF 因此完全相同。

**哪個量表示分布廣度？** DF，或正規化後 DF／N，直接回答有多少文件含該詞。CF 衡量全語料累積使用強度，兩者作用不同：`lean` 的 CF=63、`rapidly` 的 CF=29，但 DF 同為 29，所以兩者 IDF 同為 3.540459。反過來，`agonist` 與 `no` 的 CF 都是 331，DF 分別 256、242，IDF 便不同。這些是不能用 CF 直接替代 DF 的實際反例。

**為何 CF 與 DF 都重要？** CF 有助描述 token 儲存與高頻字負擔；DF 決定一般倒排 postings 的文件覆蓋與 IDF。TF 則保留個別文件的重複程度。常見詞若幾乎每篇都有，IDF 會低；但「CF 高」不必然推出「IDF 低」，仍需檢查 DF。極低 DF 雖得到高 IDF，也可能是錯字、數值片段或很窄的概念，不能把高 IDF 當成相關性標籤。要主張 retrieval effectiveness 改善仍需 query、relevance judgments 與評估指標，本次未測試檢索準確率提升。

## 6. IR 意義與 technical argument：RQ5

詞頻不均勻直接影響工程成本。B 中前 10 個詞僅占 13,338 個詞型中的一小部分，卻承擔 18.285% tokens；另一端 4,865 個單次詞占 36.475% 詞彙，但僅占 1.829% tokens。這提示字典的長尾與高頻 postings 的成本來源不同，不能只用一個 tokens 或 vocabulary 數字描述所有索引儲存。

停用詞移除使 B→C 的 ΣDF 從 157,621 降至 133,436，說明減少長 postings 的潛在效益；但本專案沒有測量索引檔案壓縮 bytes 或查詢延遲，因此只能稱為儲存／計算負擔代理量。高 DF 詞的 docID gaps 通常較短、可適合 gap encoding；大量稀有詞則有不同的字典與短清單開銷。變長整數編碼、字典前綴壓縮與分塊處理可利用這種不均勻性，實際收益仍取決於資料排列、編碼格式與位置資訊，不是 Zipf exponent 就能單獨預測。

即使 Zipf 只是一個近似經驗規律，它仍能指導容量估計、字典與 postings 的分工、快取熱門詞、停用詞政策及 TF-IDF 權重。這次更重要的學習是：**同一批摘要，僅修改可明確重現的 token 定義，就得到不同的 exponent、長尾規模與索引負擔；資料處理是研究結論的一部分。** 保留否定詞與生醫詞樣式、將實驗 tokenizer 與搜尋規則分開，能讓統計比較不以破壞檢索行為為代價。

### English discussion: Why does Zipf’s Law matter to IR?

<!-- IR_ENGLISH_START -->
Zipf's law matters to information retrieval because vocabulary and occurrences impose different costs. In this fixed collection of 1,000 GLP-1 abstracts, condition B contains 266,039 tokens but only 13,338 distinct terms. Its ten most frequent terms account for 18.285 percent of occurrences. Meanwhile, 4,865 terms occur once. A system designed around an average term would therefore overlook both a concentrated head and a substantial vocabulary tail.

Stopword removal illustrates the distinction. Moving from B to C removes 118 observed term types, only 0.885 percent of the vocabulary, but removes 67,655 occurrences, or 25.431 percent of tokens. This can reduce processing and storage associated with common words. It does not establish better retrieval effectiveness: frequent words can support phrases, and negation can change biomedical meaning. Our fixed stoplist consequently preserves no, not, and without. A separate relevance evaluation would be necessary before changing production search behavior.

An inverted index must represent both its dictionary and its postings. Rare terms enlarge the dictionary even when their individual lists are short. Common terms create long lists and can dominate query processing. In our experiment, removing stopwords reduces the total number of term-document postings from 157,621 to 133,436. These counts are storage proxies, not measured compressed bytes. Encoding sorted document identifier gaps, using variable-length integers, and compressing dictionary prefixes can exploit regularities, but actual savings depend on document ordering, representation, and whether positions are stored.

TF-IDF addresses a different question: discrimination across documents. With the assignment formula, `and` has DF 997 and IDF 0.003005, whereas semaglutide has DF 234 and IDF 1.452434. Repetition within a few documents can produce high CF without high DF. Indeed, lean and rapidly have different collection frequencies but identical DF and IDF. Thus frequency ranking alone cannot replace document-frequency weighting, and a rare term's high IDF is not a guarantee of relevance or correctness.

Finally, Zipf is useful as an engineering approximation rather than a universal proof. Condition B has a full-range exponent of 1.399350, while its middle segment has an exponent of 0.997343. Systematic residual curvature and discrete tail plateaus remain despite high R-squared values. These observations motivate explicit preprocessing, fixed snapshots, and segment-aware interpretation. The practical lesson is to anticipate uneven resource demands and evaluate design choices using reproducible measurements, while preserving domain-specific distinctions that a convenient statistical model may hide.
<!-- IR_ENGLISH_END -->

英文段落以兩個標記間正文按空白分割機器計數為 **384 words**，符合 300–500 words；不包含標題或本句。檢核結果與正文 hash 記於 [analysis_verification.json](C:/成大專案/IR-HW2/reports/hw2/analysis_verification.json)。

## 7. Word2Vec：正式模型與探索性近鄰

採 Gensim Skip-gram with negative sampling，從每篇摘要的原始順序取得句子與 B tokens；不從 CF 表、排序詞表或 postings 反推句子。文件、摘要 block 與偵測句子邊界都不跨越。選 Skip-gram 是為直接學習中心詞對周邊詞的關係；此選擇沒有透過本次實驗與 CBOW 比較，不能宣稱比 CBOW 更好。Gensim 的演算法、句子輸入與儲存介面參見 [官方 Word2Vec API](https://radimrehurek.com/gensim/models/word2vec.html)。

| 正式訓練項目 | 實際設定／結果 |
| --- | --- |
| Documents／sentences／ordered tokens | 1,000／10,843／266,039 |
| 算法 | sg=1；negative=5；hs=0（Skip-gram 負採樣） |
| vector_size／window／min_count | 100／5／2 |
| epochs／seed／workers | 30／42／1 |
| sample／ns_exponent | 0.001／0.75 |
| alpha → min_alpha | 0.025 → 0.0001 |
| shrink_windows／sorted_vocab | true／1 |
| 詞彙大小 | 8,473 |
| 訓練耗時 | 19.8944 秒（本次環境單次觀測） |
| Gensim／NumPy／SciPy | 4.4.0／2.5.3／1.18.1 |

模型詞彙 8,473 正好等於 B 的 13,338 詞減去 4,865 個單次詞；min_count=2 是模型詞彙閾值，保存的輸入句子仍保留全部 B tokens 及句子邊界。Gensim 訓練時的稀有詞過濾與高頻詞下採樣會影響有效上下文，不應把原始 token 次數直接當成所有 epochs 的實際更新次數。保存檔為 [word2vec.model](C:/成大專案/IR-HW2/reports/hw2/model/word2vec.model)，[metadata.json](C:/成大專案/IR-HW2/reports/hw2/model/metadata.json) 記錄句子順序、穩定 SHA256 初始雜湊、單 worker、平台與各項指紋。固定 seed 支援同環境的重現；跨套件、BLAS 或平台不宣稱向量逐位元相同。

本次實際近鄰的前三名如下（cosine 不是語意正確率）：

| 查詢詞 | 第 1 鄰近詞／cosine | 第 2 鄰近詞／cosine | 第 3 鄰近詞／cosine |
| --- | --- | --- | --- |
| semaglutide | liraglutide／0.693068 | dulaglutide／0.608107 | cagrisema／0.543347 |
| insulin | resistance／0.703936 | basal／0.579535 | glargine／0.573417 |
| obesity | overweight／0.595054 | gynecological／0.592382 | cvds／0.586365 |
| glp | 1／0.742724 | hepatotoxicity／0.714821 | receptor／0.687835 |
| liraglutide | semaglutide／0.693068 | dulaglutide／0.677448 | tirzepatide／0.639115 |

完整輸出見 [neighbors.json](C:/成大專案/IR-HW2/reports/hw2/model/neighbors.json)。`zzzznotincorpus` 回傳 OOV，不用隨機向量冒充；`GLP-1` 依 B 變成 `glp`、`1`，單詞近鄰介面提示輸入限制，而非悄悄取其中一詞。`glp` 的最近鄰為數字 `1`，正好提醒 token 規則會影響模型；`obesity` 的部分近鄰也不能直接視為同義詞或經驗證的醫學關係。小型單領域語料、縮寫斷句與稀有詞估計均限制解讀，沒有人工標註基準可計算「語意正確率」。

正式模型已在封鎖網路的整合驗證中從磁碟重載成功，向量 SHA256 為 `92aef64d0555dc0d979432128df87944d7fe78fdd7f20f903b7d8c66c27f3926`。結果記於 [formal-verification.json](C:/成大專案/IR-HW2/reports/hw2/formal-verification.json)。這項檢查驗證現有模型可離線重載；不把它擴張宣稱為跨平台重新訓練相同。

## 8. 拼字建議與介面整合

拼字校正採動態規劃 Levenshtein edit distance，在正式 B 語料詞彙中找候選，以距離由小至大、CF 由大至小及穩定詞序排序；最多回傳 3 個候選，最大距離 2，較短詞的允許距離更保守。原查詢與建議並列，使用者明確採用後才送入搜尋。合法但未收錄的生醫詞不應被推定為拼錯，因此保護包含數字、非 ASCII、混合大小寫、全大寫縮寫與短詞，也保留已知詞。

以下為正式語料上的實際輸出，原查詢均未被建議函式直接覆寫：

| 原查詢 | 回傳建議／保留結果 | 檢核重點 |
| --- | --- | --- |
| semaglutide | 保留 semaglutide | known_word；不修正正確詞 |
| semaglutid | semaglutide | 距離 1、CF=682 |
| insulinn | insulin | 距離 1、CF=487；次選 insulins 距離 1、CF=8，再次選 inulin 距離 2、CF=6 |
| zzzznotincorpus | 保留原詞，標記 unresolved | 允許距離內無候選，不捏造替代詞 |
| GLP-1 BRCA1 IL6 HbA1c | 整串原樣保留 | GLP-1 含數字受保護，其餘為語料已知詞 |
| Semaglutide treatment | 大小寫及原查詢保留 | 已知詞不額外改寫 |

正式離線搜尋亦保留既有原文位置高亮：`semaglutide` 命中 234 篇、`insulin` 命中 203 篇、`obesity treatment` 命中 695 篇、`GLP-1` 命中 580 篇、未知查詢 0 篇。這些命中數來自 HW1 的既有搜尋規則，**不等於 B 條件的 DF**；例如 B 的 insulin DF=201，不能因搜尋結果 203 而改寫分析表。

Streamlit 延續繁體中文搜尋、文章管理與原文高亮；HW2 分析和模型使用獨立固定快照。下載、統計及模型訓練以按鈕或 CLI 明確觸發。介面 AppTest、建議採用與其他新增模組測試已納入下節的完整回歸；命中與高亮只驗證功能一致性，不代表有人工相關性標註的檢索品質評估。

## 9. 正確性、重現與交付檔案

手算測試 [test_hw2_analysis.py](C:/成大專案/IR-HW2/tests/test_hw2_analysis.py) 已實跑 33 項通過，涵蓋 A／B 標點差異、CF／DF、ln(N／DF)、原文隔離、重複 PMID、空摘要、stemming、exact power-law 回歸、常數 R²=null、少點防呆及 CSV／JSON／PNG。合成資料位於測試情境，未充作 PubMed 正式語料。

原始 HW1 基線為 342 通過、6 個缺失 Git fixture 的 setup errors，並無 assertion failures；HW2 沒有複製 `ad8bf2b` Git 歷史與固定語料，所以這是 fixture 問題。修復採從 HW1 該歷史版本唯讀取出 15 份原始 XML，保存 SHA256 來源並使 fixture 可攜化，未刪除原測試或更改其 assertion。修復後原有 348 項全部通過；最終完整 suite 為 **444 passed in 48.47 seconds = 原有 348＋新增 96**，未發生本次新增失敗。完整分類及每項結果見 [validation_summary.json](C:/成大專案/IR-HW2/reports/hw2/validation_summary.json)。

```powershell
.\.venv-hw2\Scripts\python.exe -X utf8 -m pytest -q --basetemp tmp/pytest-final --junitxml=reports/hw2/pytest-final.xml
```

以下兩次正式命令使用同一固定快照，第二次只更換輸出目錄：

```powershell
Set-Location 'C:\成大專案\IR-HW2'
.\.venv-hw2\Scripts\python.exe -X utf8 -m ir_hw2.cli analyze
.\.venv-hw2\Scripts\python.exe -X utf8 -m ir_hw2.cli analyze --output tmp/hw2-reproduce
```

16 份 CSV、1 份 summary JSON 與 4 張 PNG 共 **21 個檔案逐位元一致**。不變量 `ΣCF=tokens`、`1≤DF≤min(CF,N)`、每篇 tokens 加總、詞彙數、ΣDF 與分段點數均通過；32 個選詞 IDF 也逐一核對。四張正式 PNG 已直接查看：標籤清楚、數值相符、沒有裁切或重疊，殘差圖與長尾平台可辨識。完整 SHA256 與視覺檢核說明保存於 [analysis_verification.json](C:/成大專案/IR-HW2/reports/hw2/analysis_verification.json)。Matplotlib 快取已固定於 HW2 的 `tmp/matplotlib`。

| 成果 | 位置／用途 |
| --- | --- |
| 固定語料與取得稽核 | `data/hw2/glp1-1000-20260929/`：原始 XML、PMID、查詢、納排、hash |
| A–D 完整統計 | `reports/hw2/experiment/summary.json`、`preprocessing_comparison.csv` |
| 各條件詞表及 Top 50 | `terms_A.csv`…`terms_D.csv`、`top50_A.csv`…`top50_D.csv` |
| 各文件 tokens／詞彙 | `documents_A.csv`…`documents_D.csv` |
| 完整及分段 Zipf | `regression.csv`、`rank_frequency.png`、`log_log.png`、`residuals.png` |
| CF／DF 與 IDF | `cf_df_comparison.csv`、`idf_terms.csv` |
| 模型、句子與參數 | `reports/hw2/model/` |
| 驗證證據 | `reports/hw2/analysis_verification.json` |

## 10. 規格差異、限制與待確認事項

9/22 原題第 1 頁包含 Zipf、Porter、Word2Vec 及拼字校正；9/29 詳細版第 2 頁明確以約 1,000 篇摘要為範圍，並未明確取消後兩者，因此保留實作。詳細版第 3–6 頁的 A–D、CF／DF、IDF 與 300–500 words IR 討論由本報告完成；第 8 頁要求的單獨一頁 Executive Summary 另交。兩領域比較在第 7 頁屬 optional challenge，本次未執行，不據此推論跨領域差異。

語料非隨機、只來自近期優先的單一主題；標點拆分會改變生醫名稱與小數；Porter 可能過度合併詞義；停用詞表是一個固定比較設定，不是普遍最佳詞表；log-space OLS 是描述性分析，沒有 power-law 統計證明或檢索相關性評估。Word2Vec 近鄰只代表本語料上下文，沒有臨床或語意正確性驗證。圖表與數字重現驗證僅涵蓋所記錄的本機環境。

待教師／使用者確認：是否要求自行撰寫 Porter 而不能使用已揭露的 NLTK 模式；最終繳交媒介、示範時長與是否另有更新截止日。現有原題截止日為 2026-10-06。上述待確認事項不把已完成的套件實作誤稱為手刻，也不自動把講義中所有延伸主題列成必做。

## 11. 規格與方法來源

1. [Homework-2-26-20260922-1.pdf](C:/成大專案/課程內容/IR/HW2/Homework-2-26-20260922-1.pdf)，第 1 頁：原題範圍、Porter、Word2Vec、拼字校正及截止日期。
2. [project-2-details-20260929-1.pdf](C:/成大專案/課程內容/IR/HW2/project-2-details-20260929-1.pdf)，第 1–2 頁：研究目標、約 1,000 篇語料、Zipf；第 3–4 頁：前處理、CF／DF、回歸與區段；第 5–6 頁：指定 IDF 與 IR 意義；第 7–8 頁：optional challenge、technical argument、RQ1–RQ5、一頁摘要。
3. [lecture-2-dictionary-20260922-1.pdf](C:/成大專案/課程內容/IR/HW2/lecture-2-dictionary-20260922-1.pdf)，第 7、10、36–46 頁：字詞與前處理；第 23–35 頁：向量詞表示；第 56–58 頁：Zipf；講義的其他延伸不自動列為必做。
4. [NCBI E-utilities 一般說明](https://www.ncbi.nlm.nih.gov/books/NBK25497/)、[參數文件](https://www.ncbi.nlm.nih.gov/books/NBK25499/)、[API key／速率說明](https://www.ncbi.nlm.nih.gov/books/NBK53593/pdf/Bookshelf_NBK53593.pdf)：下載方法與使用限制，查核日 2026-09-29。
5. [NLTK PorterStemmer 官方 API](https://www.nltk.org/api/nltk.stem.porter.html)：演算法模式；實際安裝版本另見本次 metadata。
6. [Gensim Word2Vec 官方 API](https://radimrehurek.com/gensim/models/word2vec.html)：有序句子輸入、參數、模型儲存與重現限制；網頁文件版本可能不同於本次安裝的 4.4.0，以本次 metadata 記錄執行版本。
