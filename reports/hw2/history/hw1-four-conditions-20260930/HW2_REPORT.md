# Biomedical IR Homework 2：1,000 篇 GLP-1 摘要的詞頻、Zipf 與檢索分析

語料取得：2026-09-29；HW1 原切詞版更新：2026-09-30。固定 1,000 篇 PubMed 英文非空摘要；分析中的 log 統一以 10 為底。主要比較 **B：HW1 原切詞 → C：移除停用詞 → D：Porter**；A 保留為課堂 A–D 所需的標點處理前參考。所有數值來自本版正式執行，合成資料只用於手算測試。本報告回答 9/29 詳細版 RQ1–RQ5，並保留 9/22 原題的 Word2Vec 與拼字校正。

**主要發現：停用詞移除減少 27.188% tokens，Porter 再減少 19.599% 詞彙。四組皆呈現少數高頻詞與大量稀有詞；中頻段的 R² 最高、log-space RMSE 最低。B 中頻 exponent=1.047878，全範圍則為 1.278303，不能用一條直線與高 R² 宣稱「證明 Zipf’s Law」。**

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

## 2. 沿用 HW1 原切詞的 B → C → D

A 是標點前參考；B、C、D 才是本次主要比較。各條件從同一份原始摘要建立，A 與 B 共用 HW1 正規化，B 不由 A 的 token 清單再次拼接。這讓標點處理的比較保留，同時以既有 tokenizer 作穩定基礎。

| 條件 | 本次實作與可重現定義 |
| --- | --- |
| A（參考） | 空白切分，每個 token 呼叫 HW1 `normalize`；保留附著及獨立標點。 |
| B（主要基準） | 直接呼叫 `ir_hw1.preprocessing.tokenize(text)` 取每個 `Token.term`，沿用原 regex 及 `normalize`，不重寫切詞規則。 |
| C | B 再移除固定 132 詞的 `hw2-function-words-v1`；保留 `no`、`not`、`without`。本語料實際出現其中 118 種。 |
| D | C 再直接呼叫 HW1 `stem_term`；只對純 ASCII 字母使用 NLTK Porter `MARTIN_EXTENSIONS`，複合詞、小數、撇號詞及非 ASCII token 保留。 |

共同正規化為 NFC、Unicode casefold，並將 `’` 轉為 `'`、`‐`／`‑` 轉為 `-`。B 原切詞規則保留內部支援的連字號、撇號、數字及小數，因此 `GLP-1`、`IL6`、`3.5`、`β-cells` 分別成為 `glp-1`、`il6`、`3.5`、`β-cells`；`patient’s` 成為 `patient's`。casefold 包含一般大小寫統一，另可將 `Straße` 變成 `strasse`；不是只對 ASCII 使用 lower。

以 `The patients GLP-1 improved 3.5 mg.` 為例：

| 條件 | 有序 tokens |
| --- | --- |
| A | `the, patients, glp-1, improved, 3.5, mg.`（最後一詞保留句點） |
| B | `the, patients, glp-1, improved, 3.5, mg` |
| C | `patients, glp-1, improved, 3.5, mg` |
| D | `patient, glp-1, improv, 3.5, mg` |

逗號只用來分隔表中各 token。這個小例子用來解釋規則，正式數值全部取自 PubMed 快照。B 保留停用詞，C／D 按上述順序累積；沒有搜尋用的 IL6 → il-6／il／6 特徵展開，沒有額外孤立字母、數字或生醫詞過濾，也沒有 stemming 後再刪一次停用詞。

每個 PMID 算一篇 document；同篇同詞重複出現仍只增加一次 DF。即使某篇 C／D tokens 全被移除，N 仍保留該篇。重複 PMID、無效 PMID 或空摘要明確報錯。

分析版本 `hw2-hw1-tokenizer-v3-log10`；原切詞版本 `unicode-word-v1`。`baseline_tokenizer_spec()` 保存實作、regex、NFC／casefold 規則、原始碼與依賴指紋，不含分析版本或 log 底數。原 `ir_hw1/preprocessing.py` SHA256 為 `f7108e87d1c19c43e012836adcb6d8b429e4d06c5cdc2bead4a06f71f04919c2`，本次未修改。停用詞表 SHA256 為 `d907482b2aabc0443ae05c95e0c9685ef6f8ff8789370a34c004a498d1abc406`。Python 3.13.14、NLTK 3.9.2、regex 2026.9.10、Matplotlib 3.11.2；完整設定及分析程式指紋見 [summary.json](C:/成大專案/IR-HW2/reports/hw2/experiment/summary.json)。

Porter 明確沿用 NLTK 的 Martin 擴充模式，**不是自行撰寫 Porter 演算法**；模式定義參見 [NLTK 官方文件](https://www.nltk.org/api/nltk.stem.porter.html)。先前全符號拆詞的 log10 實驗、模型、報告與 PDF 已封存於 `reports/hw2/history/unicode-split-log10-20260930/`，不與本版數值混用。

## 3. 詞彙與高頻詞：RQ3

| 條件 | Documents | Tokens | Unique terms | 平均 tokens／篇 | CF=1 詞數 | CF=1／詞彙 | Top 10／tokens | ΣDF |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| A | 1,000 | 244,477 | 29,203 | 244.477 | 17,363 | 59.456% | 18.012% | 162,028 |
| B | 1,000 | 246,256 | 17,910 | 246.256 | 8,252 | 46.075% | 17.950% | 152,375 |
| C | 1,000 | 179,304 | 17,792 | 179.304 | 8,248 | 46.358% | 5.730% | 128,458 |
| D | 1,000 | 179,304 | 14,305 | 179.304 | 6,847 | 47.864% | 6.844% | 121,831 |

單字數以各條件 tokens 為準，不沿用 HW1 介面顯示的空白字數。ΣDF 是不含位置的「詞—文件」postings entry 數量，可作索引大小的代理量，並非實際壓縮 bytes。

| 條件 | 依排名列出的 Top 10（括號為 CF） |
| --- | ---: |
| A | and (10,586), the (6,144), of (5,807), in (4,864), with (4,126), to (3,567), a (3,105), for (2,255), were (1,867), was (1,713) |
| B | and (10,658), the (6,149), of (5,808), in (4,871), with (4,132), to (3,572), a (3,150), for (2,257), were (1,870), glp-1 (1,736) |
| C | glp-1 (1,736), receptor (1,171), patients (1,096), weight (1,032), risk (968), obesity (959), diabetes (845), 95 (838), metabolic (823), agonists (807) |
| D | glp-1 (1,736), us (1,446), studi (1,262), patient (1,252), receptor (1,223), agonist (1,121), risk (1,075), weight (1,071), associ (1,046), obes (1,040) |

完整 Top 50 見 [A](C:/成大專案/IR-HW2/reports/hw2/experiment/top50_A.csv)、[B](C:/成大專案/IR-HW2/reports/hw2/experiment/top50_B.csv)、[C](C:/成大專案/IR-HW2/reports/hw2/experiment/top50_C.csv)、[D](C:/成大專案/IR-HW2/reports/hw2/experiment/top50_D.csv)；`terms_A.csv` 至 `terms_D.csv` 保存全部 rank、CF、DF 與 IDF。

![A 參考與 B–D 的計數、詞彙及索引代理量](C:/成大專案/IR-HW2/reports/hw2/experiment/preprocessing_comparison.png)

讀圖先比較 B 與 C：tokens 柱變短，表示刪除常見功能詞；再看 C 與 D：tokens 柱一樣高，但詞彙柱變短，表示詞型合併。不同圖框各有單位，不能直接比較不同圖框的柱高。

**A → B：原 tokenizer 處理標點後，表面詞型減少。** Tokens 增加 1,779（0.728%），詞彙減少 11,293（38.671%）；例如 `data,` 與 `data.` 可合成 `data`。原切詞也可能拆開斜線等未保留的分隔字元，因此 token 總數略增。`GLP-1` 及 `3.5` 仍完整保留，不能把這次變化說成拆開它們的結果。單次詞比例由 59.456% 降至 46.075%；這是表面差異減少的整體現象，未對每個稀有詞做因果歸因。

**B → C：少量詞型承擔大量出現次數。** 移除 118 種實際出現的停用詞，只減少 0.659% 詞彙，卻刪除 66,952 tokens（27.188%）；ΣDF 減少 23,917（15.696%）。Top 10 的份額由 17.950% 降至 5.730%，高頻端轉向 `glp-1`、`receptor`、`patients` 等領域詞。全範圍 exponent 由 1.278303 降至 1.235926，高頻段由 0.805420 降至 0.561696；移除停用詞不等於自動更符合 Zipf。

**C → D：stemming 合併詞型，不刪除 token。** Tokens 保持 179,304，詞彙由 17,792 降至 14,305（減少 19.599%）；ΣDF 再減少 6,627（5.159%）。不同詞型可能出現在同一文件，合併後的 DF 不能直接相加。D 的 `us` 由 `use` (632)、`using` (534)、`used` (262)、`useful` (10)、`uses` (8) 合併成 1,446 次；原代名詞 `us` 已於 C 移除。這說明先停用詞、後 stemming 可產生表面上像停用詞的 stem，本次未追加第二輪過濾。詞型減少不直接證明搜尋品質改善。

## 4. Zipf 方法、全範圍與分段結果：RQ1、RQ2

每個條件依 CF 遞減、同頻依 Unicode 詞彙順序穩定排序，給予 ordinal rank 1…V，不共用排名或取平均排名。包含所有 CF=1 詞。令 x=log10(rank)、y=log10(CF)，OLS 擬合 y=a+slope×x，Zipf exponent b=−slope，即 CF≈10^a×rank^(−b)。所有 log 底數皆為 10。

R²=1−Σ(y−ŷ)²／Σ(y−ȳ)²；RMSE=√[Σ(y−ŷ)²／n]。RMSE 在 **log10(CF) 空間**，分母為 n，不是 n−2，也不是原始 CF 空間。頻率相同而 y 無變異時 R²=null；少於兩點或 rank 不變不回報不存在的擬合參數。

預先分段：高頻為前 floor(1%×V) 名，中頻為其後至 floor(10%×V)，低頻為其餘 90%。極小測試另有最少兩點防呆；本次正式資料未觸發調整。各條件相同百分位不是同一組詞，CF 門檻也未必相同。

| 條件／區段 | Rank 範圍 | n | slope | intercept a | exponent b | R² | RMSE log10(CF) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| A 全部 | 1–29,203 | 29,203 | -1.081025 | 4.656952 | 1.081025 | 0.955040 | 0.101757 |
| A 高頻 | 1–292 | 292 | -0.844574 | 4.099240 | 0.844574 | 0.995932 | 0.022579 |
| A 中頻 | 293–2,920 | 2,628 | -1.065766 | 4.701534 | 1.065766 | 0.996408 | 0.016324 |
| A 低頻 | 2,921–29,203 | 26,283 | -0.974950 | 4.209155 | 0.974950 | 0.865330 | 0.098173 |
| B 全部 | 1–17,910 | 17,910 | -1.278303 | 5.318048 | 1.278303 | 0.971602 | 0.094762 |
| B 高頻 | 1–179 | 179 | -0.805420 | 4.087154 | 0.805420 | 0.992643 | 0.028555 |
| B 中頻 | 180–1,791 | 1,612 | -1.047878 | 4.685842 | 1.047878 | 0.996451 | 0.015952 |
| B 低頻 | 1,792–17,910 | 16,119 | -1.380549 | 5.719645 | 1.380549 | 0.947962 | 0.082557 |
| C 全部 | 1–17,792 | 17,792 | -1.235926 | 5.142569 | 1.235926 | 0.965673 | 0.101039 |
| C 高頻 | 1–177 | 177 | -0.561696 | 3.481014 | 0.561696 | 0.957182 | 0.048905 |
| C 中頻 | 178–1,779 | 1,602 | -0.990683 | 4.475025 | 0.990683 | 0.995123 | 0.017718 |
| C 低頻 | 1,780–17,792 | 16,013 | -1.357293 | 5.618940 | 1.357293 | 0.946702 | 0.082201 |
| D 全部 | 1–14,305 | 14,305 | -1.304093 | 5.284516 | 1.304093 | 0.966623 | 0.105044 |
| D 高頻 | 1–143 | 143 | -0.528432 | 3.513326 | 0.528432 | 0.952205 | 0.048316 |
| D 中頻 | 144–1,430 | 1,287 | -1.103262 | 4.795798 | 1.103262 | 0.991926 | 0.025380 |
| D 低頻 | 1,431–14,305 | 12,875 | -1.376586 | 5.559078 | 1.376586 | 0.940850 | 0.088105 |

完整精度見 [regression.csv](C:/成大專案/IR-HW2/reports/hw2/experiment/regression.csv)。表格四捨五入僅為閱讀；後續運算使用完整數值。

![Rank-frequency 全範圍與 CF 對數軸](C:/成大專案/IR-HW2/reports/hw2/experiment/rank_frequency.png)

圖 1：橫軸是排名，1 是最常見詞；縱軸是出現次數。左圖少數高頻詞很高、大部分詞接近底部；右圖只把 CF 軸改成對數，才能看清稀有詞的階梯。左圖長尾看似平坦，是尺度壓縮造成，不能解釋成每個詞一樣常見。

![以 10 為底的對數 Zipf 散點與全範圍 OLS](C:/成大專案/IR-HW2/reports/hw2/experiment/log_log.png)

圖 2：兩軸都取 log10，橫軸增加 1 表示 rank 增加十倍；縱軸增加 1 表示 CF 增加十倍。彩色點是實測詞頻，黑色實線是全範圍回歸。若 b=1，排名變十倍，預測頻率就變成十分之一。中段較接近直線，但頭尾有偏離；A 的全域 b 最接近 1，也不代表它是最佳文字處理方式。

![全範圍 OLS 殘差](C:/成大專案/IR-HW2/reports/hw2/experiment/residuals.png)

圖 3：縱軸為「觀察 log10(CF) − 全範圍預測 log10(CF)」，0 表示相符，負值表示實際頻率比直線預測低。虛線標記區段邊界，並非回歸線。四組皆有系統性彎曲，B–D 頭部尤其被全域直線高估；尾端整數 CF 形成斜帶。這不是各段重新擬合後的殘差。

**RQ1：是否符合 Zipf？** 可描述為 Zipf 式的不均勻詞頻，以及中頻區段的良好局部近似；不能宣稱所有 rank 服從同一精確 power law。結論同時使用圖形、分段 slope、R²、RMSE 與殘差。

**RQ2：exponent 是多少？** 必須連同處理方式及區間回答。A–D 全範圍依序為 1.081025、1.278303、1.235926、1.304093；主要基準 B 的中頻 b=1.047878，不能拿它替代 B 全範圍的 1.278303。

**哪段最好？** 在預先指定的三段中，四組中頻均同時具有最高 R²、最低 RMSE，b 介於 0.990683–1.103262。B 中頻 R²=0.996451、RMSE=0.015952，C 中頻 b=0.990683 最接近 1；「最接近 b=1」與「R² 最高」並非同一指標。各段 x／y 範圍不同，跨段 R² 並非完全等價，這仍是描述性比較。

**R² 是否充分？** 不充分。排序後的 rank／CF 不是獨立隨機觀測；OLS 對各詞型同權，長尾占多數；同頻詞分配不同 ordinal ranks 會形成平台。高 R² 只表示指定 log 空間的線性解釋程度，沒有比較替代分布、估計 cutoff 不確定性或完成 power-law 適合度檢定。若只挑 CF=1 平台，水平線 RMSE=0，但 R² 無定義、b=0，更不能當成理想 Zipf。本次沒有冒稱完成這些延伸統計證明。

## 5. CF、DF 與指定 IDF：RQ4

CF(t)=所有摘要中 t 的出現次數；DF(t)=包含 t 的不同 PMID 數。指定公式為 **IDF(t)=log10(1000／DF(t))**，不平滑、不加 1；HW1 搜尋的 `ln((N+1)/(DF+1))+1` 僅用於既有搜尋。

B 條件選出 39 個實際觀察的 terms：前 10 名、固定排名百分位，以及存在的領域／否定詞，涵蓋高、中、低頻。包含完整 `glp-1`、`glp-1ra`、`peptide-1`、`β-cells`、`il6`；數字及符號樣式也照實列出，沒有為美化結果而臨時過濾。兩表合計滿足至少 20 詞 CF／DF 及至少 10 詞 IDF 的要求。

### 5.1 選詞表（1／2）

| B term | CF | DF | IDF=log10(1000／DF) |
| --- | ---: | ---: | ---: |
| and | 10658 | 997 | 0.001305 |
| the | 6149 | 977 | 0.010105 |
| of | 5808 | 972 | 0.012334 |
| in | 4871 | 961 | 0.017277 |
| with | 4132 | 915 | 0.038579 |
| to | 3572 | 943 | 0.025488 |
| a | 3150 | 922 | 0.035269 |
| for | 2257 | 860 | 0.065502 |
| were | 1870 | 570 | 0.244125 |
| glp-1 | 1736 | 574 | 0.241088 |
| receptor | 1171 | 793 | 0.100727 |
| patients | 1096 | 405 | 0.392545 |
| obesity | 959 | 466 | 0.331614 |
| diabetes | 845 | 529 | 0.276544 |
| glucagon-like | 751 | 695 | 0.158015 |
| treatment | 744 | 412 | 0.385103 |
| peptide-1 | 691 | 644 | 0.191114 |
| semaglutide | 649 | 228 | 0.642065 |
| not | 572 | 366 | 0.436519 |
| glp-1ra | 490 | 140 | 0.853872 |

### 5.2 選詞表（2／2）

| B term | CF | DF | IDF=log10(1000／DF) |
| --- | ---: | ---: | ---: |
| insulin | 431 | 194 | 0.712198 |
| glp-1ras | 421 | 161 | 0.793174 |
| no | 328 | 242 | 0.616185 |
| glucose | 326 | 155 | 0.809668 |
| agonist | 312 | 245 | 0.610834 |
| without | 245 | 176 | 0.754487 |
| strategies | 185 | 145 | 0.838632 |
| because | 67 | 53 | 1.275724 |
| gaps | 40 | 35 | 1.455932 |
| play | 18 | 18 | 1.744727 |
| β-cells | 8 | 7 | 2.154902 |
| emphasized | 7 | 7 | 2.154902 |
| glp | 7 | 6 | 2.221849 |
| militaris | 4 | 2 | 2.698970 |
| 152 | 2 | 2 | 2.698970 |
| il6 | 2 | 1 | 3.000000 |
| pathway-specific | 2 | 2 | 2.698970 |
| endotyping | 1 | 1 | 3.000000 |
| ⁸ | 1 | 1 | 3.000000 |

可重用表格：[CF／DF CSV](C:/成大專案/IR-HW2/reports/hw2/experiment/cf_df_comparison.csv)、[IDF CSV](C:/成大專案/IR-HW2/reports/hw2/experiment/idf_terms.csv)。例如 semaglutide 的 IDF=log10(1000／228)=0.642065，and 的 IDF=log10(1000／997)=0.001305。

**高 CF、相對低 DF 為何出現？** 同篇文章可重複使用藥名，CF 增加但 DF 只加一次。semaglutide 出現 649 次、分布在 228 篇，命中文章平均約 2.85 次，覆蓋率 22.8%。這是局部重複及主題聚集，不表示每篇都重要。il6 的兩次集中於一篇，endotyping 只有一次，但兩者 DF=1，IDF 同為 3。

**哪個量表示分布廣度？** DF 或 DF／N，直接表示文件覆蓋。β-cells 的 CF=8、emphasized 的 CF=7，但 DF 同為 7，IDF 同為 2.154902；反過來，il6 與 pathway-specific 的 CF 都是 2，DF 分別 1、2，IDF 分別 3、2.698970。這些實例說明不能用 CF 取代 DF。

**為何兩者都重要？** CF 描述累積使用與 token 負擔，DF 對應 postings 文件覆蓋及 IDF，TF 保留個別文件重複程度。高 CF 不必然代表低 IDF；低 DF 的高 IDF 也可能來自錯字、數字或狹窄概念，不能直接當成相關性標籤。本次沒有人工 relevance judgments，未宣稱檢索準確率提升。

## 6. IR 意義與 technical argument：RQ5

B 前 10 個詞占 17.950% tokens；另一端 8,252 個單次詞占 46.075% 詞彙，卻僅占 3.351% tokens。字典長尾與常見詞長 postings 的成本來源不同，不能僅靠 tokens 或 vocabulary 一個數字描述全部儲存。

B→C 的 ΣDF 從 152,375 降至 128,458，表示移除常見詞可縮減 postings 的潛在負擔；本次未量測壓縮 bytes 或比較查詢延遲。高 DF 詞通常有較短 docID gaps，可考慮 gap encoding／變長整數；稀有詞則有字典與短清單開銷，可考慮字典前綴壓縮、分塊等。實際收益取決於文件排列、編碼與位置資訊，不能由 exponent 單獨預測。

TF-IDF 以文件內 TF 表示重複、以 IDF 表示跨文件區辨性；單看 CF 排名不足以替代。保留否定詞能減少語意損失，但沒有最佳停用詞表的普遍保證。Word2Vec 或拼字候選也不能把高頻等同正確。Zipf 即使只是近似，仍可協助容量估計、字典與 postings 分工、熱門詞快取與停用詞政策。

本次主要比較使用原 HW1 切詞，讓 B→C→D 的差異清楚歸屬於停用詞及 stemming；分析不混入搜尋特徵展開。**token 定義、處理順序與固定語料都是研究結論的一部分。** 實驗揭示工程取捨，沒有宣稱改善人工標註的檢索品質。

### English discussion: Why does Zipf’s Law matter to IR?

<!-- IR_ENGLISH_START -->
Zipf's law matters to information retrieval because vocabulary and occurrences impose different costs. In this fixed collection of 1,000 GLP-1 abstracts, the original HW1 tokenizer produces 246,256 tokens and 17,910 distinct terms in condition B. Its ten most frequent terms account for 17.950 percent of occurrences, while 8,252 terms occur only once. An average term cannot adequately describe both the concentrated head and the substantial vocabulary tail.

Stopword removal makes this distinction concrete. Moving from B to C removes 118 observed types, only 0.659 percent of the vocabulary, but removes 66,952 occurrences, or 27.188 percent of tokens. This can reduce processing and storage associated with frequent words. It does not establish better retrieval effectiveness: common words support phrases, and negation changes biomedical meaning. Our fixed stoplist therefore preserves no, not, and without. Porter stemming subsequently reduces vocabulary by 19.599 percent without reducing token counts, but merging forms may also obscure meaningful distinctions.

An inverted index represents both a dictionary and postings. Rare terms enlarge the dictionary even when their lists are short. Common terms create longer lists and can increase query processing costs. Removing stopwords reduces term-document postings from 152,375 to 128,458 in this experiment. These counts are storage proxies, not measured compressed bytes. Encoding sorted document identifier gaps, using variable-length integers, and compressing dictionary prefixes can exploit regularities. Actual savings still depend on document ordering, representation, and whether positions are stored.

TF-IDF addresses discrimination across documents. Under the assignment formula, and has DF 997 and IDF 0.001305, whereas semaglutide has DF 228 and IDF 0.642065. Repetition within relatively few documents can produce high CF without high DF. For example, il6 and pathway-specific each occur twice, but their document frequencies differ. Frequency ranking therefore cannot replace document-frequency weighting, and high IDF alone does not guarantee relevance or correctness.

Finally, Zipf provides an engineering approximation rather than a universal proof. Condition B has a full-range exponent of 1.278303 and a middle-segment exponent of 1.047878. Residual curvature and discrete tail plateaus remain despite high R-squared values. Keeping GLP-1 and decimal numbers intact makes the token contract explicit; it does not remove every linguistic ambiguity. Fixed snapshots, shared tokenizer provenance, and separate search features support reproducible comparisons. The practical lesson is to anticipate uneven resource demands and evaluate design choices with measurements while preserving distinctions that a convenient statistical model might hide.
<!-- IR_ENGLISH_END -->

英文段落按兩個標記間正文的空白分割機器計數為 **389 words**，符合 300–500 words，不包含標題或本句。正文與字數在交付核對時由 `scripts/verify_hw2_delivery.py` 檢查，輸出至 `reports/hw2/analysis_verification.json`。

## 7. Word2Vec：正式模型與探索性近鄰

採 Gensim Skip-gram with negative sampling，以中心詞預測周邊詞；沒有與 CBOW 做本次比較，不能宣稱更優。每篇摘要沿原始 block、句子及 B token 順序訓練，不由排序詞頻或 postings 重建句序；上下文不跨文件、摘要 block 或偵測句子邊界。API 參見 [Gensim 官方 Word2Vec 文件](https://radimrehurek.com/gensim/models/word2vec.html)。

| 正式訓練項目 | 實際設定／結果 |
| --- | --- |
| Documents／sentences／ordered tokens | 1,000／10,843／246,256 |
| 算法 | sg=1；negative=5；hs=0（Skip-gram 負採樣） |
| vector_size／window／min_count | 100／5／2 |
| epochs／seed／workers | 30／42／1 |
| sample／ns_exponent | 0.001／0.75 |
| alpha → min_alpha | 0.025 → 0.0001 |
| shrink_windows／sorted_vocab | true／1 |
| 模型詞彙 | 9,658 |
| 訓練耗時 | 17.7362 秒（本環境單次觀測） |
| Gensim／NumPy／SciPy | 4.4.0／2.5.3／1.18.1 |

9,658 正好等於 B 的 17,910 詞扣除 8,252 個單次詞。保存的句子仍保留全部 B tokens；Gensim 訓練時另外套用 min_count 與高頻下採樣，不能把輸入 tokens 直接視為有效訓練更新次數。保存檔為 [word2vec.model](C:/成大專案/IR-HW2/reports/hw2/model/word2vec.model)，[metadata.json](C:/成大專案/IR-HW2/reports/hw2/model/metadata.json) 保存 schema=2、原 tokenizer 契約、語料與句序 hash、穩定初始雜湊、平台及參數。缺少或不符 tokenizer 契約的舊模型會被拒絕，提示重新訓練；只改統計 log 底數不會使原切詞契約失效。

本次近鄰前三名如下；cosine 是向量夾角相似度，不是語意正確率：

| 查詢詞 | 第 1 近鄰／cosine | 第 2 近鄰／cosine | 第 3 近鄰／cosine |
| --- | ---: | ---: | ---: |
| semaglutide | liraglutide／0.670418 | tirzepatide／0.660938 | dulaglutide／0.613227 |
| insulin | resistance／0.742960 | secretion／0.564221 | glargine／0.552639 |
| obesity | overweight／0.623412 | tdt-induced／0.604472 | type-2／0.587148 |
| glp-1 | ras／0.696814 | ra／0.686772 | hepatotoxicity／0.644049 |
| liraglutide | dulaglutide／0.707752 | tirzepatide／0.685940 | semaglutide／0.670418 |

完整結果見 [neighbors.json](C:/成大專案/IR-HW2/reports/hw2/model/neighbors.json)。`GLP-1` 現在是一個完整 B token，與 `glp-1` 查詢結果相同；`GLP-1 receptor` 是兩詞，單詞近鄰介面明示 invalid_query；`zzzznotincorpus` 明示 OOV，不捏造向量。`obesity` 的 `tdt-induced`、`glp-1` 的 `hepatotoxicity` 等近鄰不能直接當成同義詞或已驗證醫學關係。1,000 篇單主題語料、縮寫斷句與低頻上下文都限制解讀。

正式模型已於封鎖網路的整合驗證中成功重載；vectors SHA256=`7de476d45de19d97d0572bbc561266ba6efac538c462a4f817144e647cae62f0`，結果見 [formal-verification.json](C:/成大專案/IR-HW2/reports/hw2/formal-verification.json)。固定 seed 與單 worker 方便同環境重現；不宣稱跨 BLAS、套件或平台逐位元重訓相同。

## 8. 拼字建議與介面整合

拼字採動態規劃 Levenshtein edit distance，以正式 B 語料詞彙找候選，依距離升冪、CF 降冪、穩定詞序排序。最多 3 候選、最大距離 2；長度不超過 5 的詞最多距離 1。詞彙與查詢共用 HW1 正規化，版本 `hw2-levenshtein-hw1-cf-v2`。原查詢與建議並列，使用者明確採用才搜尋；已知詞保留，未知詞不等於錯字，包含數字、非 ASCII、混合大小寫、全大寫縮寫與短詞有保護。

| 原查詢 | 實際建議／保留結果 | 檢核重點 |
| --- | --- | --- |
| semaglutide | 原樣保留 | known_word；正確詞不改寫 |
| semaglutid | semaglutide | 距離 1、CF=649 |
| insulinn | insulin | 距離 1、CF=431；次選 insulins 距離 1、CF=8；inulin 距離 2、CF=6 |
| zzzznotincorpus | 保留，標記 unresolved | 允許距離內無候選 |
| GLP-1 BRCA1 IL6 HbA1c | 整串原樣保留 | 四詞均為語料已知詞；未知含數字詞亦受保護 |
| Semaglutide treatment | 大小寫及原查詢保留 | 已知詞不額外改寫 |

正式離線搜尋及原文位置高亮通過：semaglutide 命中 234 篇、insulin 203 篇、obesity treatment 695 篇、GLP-1 580 篇、未知查詢 0 篇。這些是既有 HW1 搜尋規則的命中數，**不等於分析 B 的 DF**；例如 B insulin DF=194，B glp-1 DF=574，搜尋仍可因其既有特徵及處理方式命中不同集合。

Streamlit 保留繁體中文搜尋、文章管理與原文高亮，新增獨立快照的前處理比較、Zipf、近鄰和可選拼字建議。下載、統計及訓練由明確按鈕／CLI 觸發。UI 會核對分析版本、log 底數與 tokenizer 契約，拼字詞彙快取包含版本及契約，避免同一語料 rerun 沿用舊切詞結果。當前 6 項 AppTest 通過；2026-09-29 的真實瀏覽器紀錄只代表舊版本歷史，本次未冒稱重新完成瀏覽器操作驗證。

## 9. 正確性、重現與交付檔案

手算測試 `tests/test_hw2_analysis.py` 實跑 **46 項通過**，涵蓋逐詞對照 HW1、GLP-1／IL6／小數／Unicode／撇號、C／D 累積且不額外過濾、CF／DF、IDF log10(10)=1、DF=N 時為 0、exact power-law、常數 R²=null、少點防呆、摘要隔離與輸出。

原始基線為 342 passed、6 個缺 Git 歷史 fixture 的 setup errors，沒有 assertion failure。唯讀取出 HW1 歷史版本的 15 份 XML、保存 SHA256 並修復 fixture 可攜性後，原有 348 項通過，未刪除原測試或更改斷言。本版最終 **483 passed in 43.16 seconds = 原有 348＋HW2 135**，零失敗／錯誤／跳過；紀錄 `reports/hw2/pytest-hw1-tokenizer.xml` 及 `.log`。初版 444、log10 v2 的 450 均為歷史結果。

```powershell
Set-Location 'C:\成大專案\IR-HW2'
.\.venv-hw2\Scripts\python.exe -X utf8 -m pytest -q --basetemp tmp/pytest-hw1-tokenizer-final --junitxml=reports/hw2/pytest-hw1-tokenizer.xml
.\.venv-hw2\Scripts\python.exe -X utf8 scripts/verify_hw2_tokenizer.py
.\.venv-hw2\Scripts\python.exe -X utf8 scripts/verify_hw2.py
```

`verify_hw2_tokenizer.py` 已離線重新執行正式分析，16 CSV＋1 summary JSON＋4 PNG 共 **21 檔逐位元一致**；核對 1,000 篇各條件有序 tokens、ΣCF、DF 範圍、ΣDF、Top 50、39 選詞 IDF，並用獨立 NumPy OLS 核對全部 16 個擬合，最大絕對差約 1.954×10⁻¹⁴。完整結果在 [tokenizer_verification.json](C:/成大專案/IR-HW2/reports/hw2/tokenizer_verification.json)。快照 30 個檔案未改動；原 HW1 preprocessing 指紋未改動。四張正式 PNG 已逐張視覺查看，標籤清楚、無裁切；Matplotlib 快取位於 HW2 `tmp/matplotlib`。

重算命令為 `-m ir_hw2.cli analyze`；另存可加 `--output tmp/hw2-tokenizer-manual`。`scripts/verify_hw2_delivery.py` 在報告／PDF 重建後整合英文字數、報告數字、模型句序、測試及 PDF manifest，寫出 `analysis_verification.json`；一般分析驗證不必先重建 PDF。

| 成果 | 位置／用途 |
| --- | --- |
| 固定語料與來源稽核 | `data/hw2/glp1-1000-20260929/`：原始 XML、PMID、查詢、納排、hash |
| A–D 統計與比較 | `reports/hw2/experiment/summary.json`、`preprocessing_comparison.csv`／PNG |
| 各條件詞表與 Top 50 | `terms_A.csv`…`terms_D.csv`、`top50_A.csv`…`top50_D.csv` |
| 各文件 tokens／詞彙 | `documents_A.csv`…`documents_D.csv` |
| 全範圍及分段 Zipf | `regression.csv`、`rank_frequency.png`、`log_log.png`、`residuals.png` |
| CF／DF／IDF | `cf_df_comparison.csv`、`idf_terms.csv` |
| 模型、句子與參數 | `reports/hw2/model/` |
| 可重現與交付核對 | `tokenizer_verification.json`、`formal-verification.json`、`analysis_verification.json` |

## 10. 規格差異、限制與待確認事項

9/22 原題第 1 頁包含 Zipf、Porter、Word2Vec 及拼字校正；9/29 詳細版第 2 頁明確要求約 1,000 篇摘要，未明確取消後兩項，因此皆保留。詳細版第 3–6 頁的 A–D、CF／DF、IDF 及 300–500 words 討論在本文完成；第 8 頁的另外一頁 Executive Summary 分開交付。第 7 頁兩領域比較是 optional，本次未執行。

本版依使用者偏好以 B 原 HW1 切詞→C 停用詞→D Porter 為主要比較，A 保留標點前參考，所有分析 log10。語料只有單一主題、按日期排序而非隨機；原 tokenizer 雖保留 GLP-1、小數及支援的內部連字號，仍不是完整生醫實體辨識器，未支援的標點可能切開名稱。Porter 可能過度或不足合併；固定停用詞表不是普遍最佳設定。OLS 是描述性分析，近鄰沒有醫學語意 gold standard，搜尋沒有 relevance judgments；重現僅涵蓋記錄的本機環境。

待確認：教師是否要求自行撰寫 Porter；提交媒介、demo 時長及是否有更新截止日。原題截止日為 2026-10-06。NLTK 套件實作不冒稱手刻，講義延伸也不自動列為必做。

## 11. 規格與方法來源

1. [Homework-2-26-20260922-1.pdf](C:/成大專案/課程內容/IR/HW2/Homework-2-26-20260922-1.pdf)，第 1 頁：原題範圍、Porter、Word2Vec、拼字校正及截止日期。
2. [project-2-details-20260929-1.pdf](C:/成大專案/課程內容/IR/HW2/project-2-details-20260929-1.pdf)，第 1–2 頁：研究目標、約 1,000 篇語料、Zipf；第 3–4 頁：前處理、CF／DF、回歸與區段；第 5–6 頁：指定 IDF 與 IR 意義；第 7–8 頁：optional challenge、technical argument、RQ1–RQ5、一頁摘要。
3. [lecture-2-dictionary-20260922-1.pdf](C:/成大專案/課程內容/IR/HW2/lecture-2-dictionary-20260922-1.pdf)，第 7、10、36–46 頁：字詞與前處理；第 23–35 頁：向量詞表示；第 56–58 頁：Zipf；講義的其他延伸不自動列為必做。
4. [NCBI E-utilities 一般說明](https://www.ncbi.nlm.nih.gov/books/NBK25497/)、[參數文件](https://www.ncbi.nlm.nih.gov/books/NBK25499/)、[API key／速率說明](https://www.ncbi.nlm.nih.gov/books/NBK53593/pdf/Bookshelf_NBK53593.pdf)：下載方法與使用限制，查核日 2026-09-29。
5. [NLTK PorterStemmer 官方 API](https://www.nltk.org/api/nltk.stem.porter.html)：演算法模式；實際安裝版本另見本次 metadata。
6. [Gensim Word2Vec 官方 API](https://radimrehurek.com/gensim/models/word2vec.html)：有序句子輸入、參數、模型儲存與重現限制；網頁文件版本可能不同於本次安裝的 4.4.0，以本次 metadata 記錄執行版本。
