# Executive Summary

## 1,000 篇 GLP-1 摘要：前處理如何改變詞頻與檢索設計

2026-09-30 原切詞版｜Biomedical IR Homework 2｜固定 PubMed 英文摘要快照

**結論：以 HW1 原切詞→停用詞→Porter 比較，詞彙量及索引負擔皆會改變。詞頻呈現高頻集中與長尾，但高 R² 不能證明所有排名服從同一個 power law。**

**資料與方法。** 查詢 GLP-1／glucagon-like peptide-1、英文、有摘要及截至 2026-09-29 的出版日期；保存 1,200 候選，下載 1,100 筆，納入 1,000 唯一、非空摘要；排除 5 筆，另 195 筆不需納入。只分析摘要正文。主要比較 B 原 HW1 tokenizer、C 移除固定停用詞、D NLTK Porter；A 是標點前的空白切分參考。各條件共用 NFC／casefold 正規化，B 保留 GLP-1、小數及支援的內部撇號，不加入搜尋特徵展開。

| 條件 | Tokens | Unique terms | 全範圍 exponent | R² |
| --- | ---: | ---: | ---: | ---: |
| A | 244,477 | 29,203 | 1.081025 | 0.955040 |
| B | 246,256 | 17,910 | 1.278303 | 0.971602 |
| C | 179,304 | 17,792 | 1.235926 | 0.965673 |
| D | 179,304 | 14,305 | 1.304093 | 0.966623 |

**RQ1–RQ2｜Zipf 是局部近似。** 以 log10(CF)=a−b×log10(rank) 作 OLS，同頻依詞序給 ordinal rank。四組中頻段的 R² 最高、RMSE 最低；B 中頻 b=1.047878，全範圍為 1.278303。殘差仍有系統性彎曲與低頻平台，不能只用 R² 證明定律。

**RQ3｜常見詞承擔大量出現次數。** B→C 只移除實際出現的 118 種停用詞，卻刪除 66,952 tokens（27.188%）；C→D 不減 tokens，詞彙再少 19.599%。ΣDF 從 B 的 152,375 降至 D 的 121,831，是 postings 規模代理量，不是壓縮 bytes 或搜尋效能提升。

**RQ4–RQ5｜CF、DF 與 TF-IDF 各有用途。** semaglutide 的 CF=649、DF=228、IDF=log10(1000/228)=0.642065；and 的 DF=997、IDF=0.001305。CF 表示累積使用，DF 表示文件覆蓋，TF-IDF 結合文件內重複與區辨性。字典、長 postings、gap encoding 與停用詞策略需分別評估，保留否定詞及生醫名稱。

**系統成果。** Streamlit 保留搜尋與高亮，新增比較、Zipf、近鄰及可選拼字建議。Skip-gram 使用 10,843 句、246,256 個有序 tokens；100 維、window=5、min_count=2、epochs=30、seed=42、workers=1，模型詞彙 9,658。GLP-1 可直接查單詞近鄰；拼字採 Levenshtein DP 與 CF 排序，保護已知詞、數字及縮寫，不默改查詢。

**驗證與界線。** 483 項測試通過（原有 348＋HW2 135）；21 份分析輸出重跑逐位元一致；39 詞 CF／DF／IDF、16 個回歸及模型離線重載通過。單領域、日期排序樣本與切詞規則限制外推，近鄰不是語意正確率。Porter 由 NLTK 提供，是否課程要求自行實作仍待確認。

來源：HW2_REPORT.md；experiment/summary.json；model/metadata.json；formal-verification.json；tokenizer_verification.json。摘要 SHA256 前 16 碼：9738b68d03a6e39b。
