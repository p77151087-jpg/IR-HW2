# Executive Summary

## 1,000 篇 GLP-1 摘要：前處理如何改變詞頻與檢索設計

2026-09-30 更新｜Biomedical IR Homework 2｜固定 PubMed 英文摘要快照

**結論：語料呈現 Zipf 式的高頻集中與長尾，但高 R² 並不能證明所有排名服從同一個 power law。前處理選擇會明顯改變詞彙量、exponent 與倒排索引負擔。**

**資料與方法。** 以 GLP-1／glucagon-like peptide-1、英文、有摘要及截至 2026-09-29 的出版日期查詢，保存 1,200 個候選 PMID，下載 1,100 筆，納入 1,000 篇唯一、英文非空摘要；排除 5 筆，另 195 筆不需納入。只分析摘要正文，不混入標題、摘要小標題或全文。A 空白斷詞與 lowercase；B 再拆標點；C 再移除固定停用詞；D 再套用 NLTK Porter MARTIN_EXTENSIONS。

| 條件 | Tokens | Unique terms | 全範圍 exponent | R² |
| --- | ---: | ---: | ---: | ---: |
| A | 244,477 | 29,255 | 1.080311 | 0.954883 |
| B | 266,039 | 13,338 | 1.399350 | 0.967425 |
| C | 198,384 | 13,220 | 1.353468 | 0.960945 |
| D | 198,384 | 9,613 | 1.467445 | 0.959162 |

**RQ1–RQ2｜Zipf 是局部近似。** 以以 10 為底的對數 OLS 擬合 log10(CF)=a-b×log10(rank)，同頻依詞彙順序給 ordinal rank。四組皆以預先定義的中頻段得到最高 R² 與最低 log-space RMSE；B 中頻 b=0.997343，全範圍卻為 1.399350。系統性殘差彎曲與低頻平台仍在，因此不能只用 R² 宣稱證明 Zipf。

**RQ3｜少量常見詞承擔大量出現次數。** B→C 只移除實際出現的 118 種停用詞，卻刪掉 67,655 tokens（25.431%）；C→D 不減 tokens，但詞彙減少 27.284%。ΣDF 從 B 的 157,621 降至 D 的 126,120，可描述 postings 規模，尚不是壓縮後 bytes 或搜尋效能提升。

**RQ4–RQ5｜CF、DF 與 TF-IDF 各有用途。** semaglutide 的 CF=682、DF=234、指定 IDF=log10(1000/234)=0.630784；and 的 DF=997、IDF=0.001305。CF 表示累積使用量，DF 表示文件覆蓋，TF-IDF 才結合個別文件重複與區辨性。長尾字典、長 postings、gap encoding 與停用詞策略應分別評估，保留否定詞及生醫名稱。

**系統成果。** Streamlit 保留搜尋與原文高亮，新增統計比較、Zipf、Word2Vec 與選擇性拼字建議。Skip-gram 以 10,843 句、266,039 個有序 tokens 訓練，100 維、window=5、min_count=2、epochs=30、seed=42、workers=1，模型詞彙 8,473。拼字採手刻 Levenshtein DP 與語料 CF 排序，保護已知詞、數字、基因樣式及縮寫，不默改查詢。

**驗證與界線。** 450 項測試通過（原有 348＋HW2 102）；21 份分析輸出重跑逐位元一致；正式語料、搜尋及模型離線重載通過。單領域、近期優先樣本與 tokenizer 規則限制外推，近鄰並非語意正確率。Porter 由 NLTK 提供，未冒稱手刻；是否課程要求自行實作仍待確認。

來源：HW2_REPORT.md；experiment/summary.json；model/metadata.json；formal-verification.json；log10_verification.json。摘要快照 SHA256 前 16 碼：9738b68d03a6e39b。
