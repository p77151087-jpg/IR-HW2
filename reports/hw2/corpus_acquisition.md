# GLP-1 正式語料取得與稽核

取得日期：2026-09-29（UTC）。完成時間：2026-09-29T01:50:43.670501+00:00；最終離線稽核時間與機器可讀數值見 `corpus_acquisition.json`。

## 語料來源與固定方法

固定快照：`data/hw2/glp1-1000-20260929/`。`abstracts.jsonl` 有 **1,000 篇**唯一 PMID、具明確 `eng` 語言欄位及非空摘要正文的 PubMed 期刊文章。此快照與可增刪的 HW1 搜尋庫分開，實驗重跑不重新查詢 PubMed。

查詢式原文：

```text
("GLP-1"[Title/Abstract] OR "glucagon-like peptide-1"[Title/Abstract]) AND english[Language] AND hasabstract AND ("1900/01/01"[Date - Publication] : "2026/09/29"[Date - Publication])
```

ESearch 使用 `db=pubmed`、`retmode=json`、`sort=pub date`、`retstart=0`、`retmax=1200`、`tool=ir_hw2`。`NCBI_EMAIL` 沒有設定，因此未虛構電子郵件；未使用 API key。保存 API 回傳的查詢轉譯與候選順序，依其順序選取最早滿足條件的 1,000 篇。這是出版日期排序的近期同主題便利樣本，**不是隨機抽樣，不能代表全部 PubMed 或所有 GLP-1 文獻**。重新查詢得到的排序和內容可能改變，因此正式分析只使用封存的 PMID、摘要及雜湊。

`hasabstract` 是 PubMed 官方文件支持的不帶欄位標籤篩選式。即使 ESearch 指示有摘要，仍逐篇確認 XML 的 `Article/Abstract/AbstractText` 正文；小標題 `Label`、文章標題及全文不納入分析。[PubMed Help](https://pubmed.ncbi.nlm.nih.gov/help/#text-availability-filters)

## 實際納排數量

| 項目 | 數量 | 定義 |
| --- | ---: | --- |
| 查詢符合 | 30,622 | ESearch 回應中的總符合數 |
| 固定候選 | 1,200 | 本次保存的唯一候選 PMID |
| 已請求／取得記錄 | 1,100 | 11 個 EFetch 批次，每批 100 個 PMID |
| 正式納入 | 1,000 | 英文、非空摘要、期刊文章、唯一 PMID |
| 排除 | 5 | 2 筆書籍章節、3 筆無可用摘要正文 |
| 合格但未納入 | 95 | 最後一批中達到 1,000 篇之後的合格文章 |
| 未下載的候選 | 100 | 已達目標，不再請求最後 100 個候選 |
| 不再需要 | 195 | 95 已下載合格但未納入 + 100 未下載 |
| 重複候選／重複回傳記錄 | 0／0 | 此次實際值 |

數量關係：1,200 = 1,000 納入 + 5 排除 + 195 不再需要；1,100 已請求 = 1,000 納入 + 5 排除 + 95 合格但未納入。未下載的 100 篇沒有逐篇驗證，不能稱其皆合格。

| PMID | 排除原因 |
| --- | --- |
| 36251836 | `PubmedBookArticle`，不在本次期刊摘要規格範圍 |
| 25905364 | `PubmedBookArticle`，不在本次期刊摘要規格範圍 |
| 42684696 | `Article/Abstract/AbstractText` 無非空正文 |
| 42671848 | `Article/Abstract/AbstractText` 無非空正文 |
| 42584884 | `Article/Abstract/AbstractText` 無非空正文 |

逐候選判定保存於 `selection.json`。初版沿用的 XML 迭代器沒有列出書籍元素，曾將兩筆書籍記為 `missing_from_efetch`；已檢查原始 XML，將 metadata 理由更正為 `unsupported_book_record`。更正前 metadata 保存在 `audit/acquisition-v1/`，更正記錄在 `snapshot.json.metadata_amendments`。**摘要、順序、PMID、API 原始 bytes 和摘要 SHA-256 都未改動**。模組現在直接辨識書籍元素，不會再誤標。

## 日期與篩選限制

998 篇的卷期年份為 2026，2 篇為 2027。PMID 42503322 的電子出版日為 2026-07-26，PMID 42545731 為 2026-08-03。PubMed Publication Date 篩選同時涵蓋電子與紙本日期，因此它們仍符合 2026-09-29 的查詢上限；`Document.year` 沿用既有 parser，表示期刊卷期年份，不能解讀成語料取得日期或唯一出版日期。[PubMed Help：Publication date filters](https://pubmed.ncbi.nlm.nih.gov/help/#publication-date-filters)

語言要求由 XML 明確 `Language=eng` 驗證，缺少語言欄位不採 parser 的預設英文。這是來源 metadata 驗證，沒有另訓練自動語言辨識器或人工逐句證明英文品質。

## 快取、限速及重現

- 保存 12 份原始回應：1 份 ESearch JSON、11 份 EFetch XML，合計 **26,412,048 bytes**。每份另有 endpoint、請求參數、URL、UTC 取得時間、byte size、SHA-256 metadata。
- 每篇 `Document.raw_path` 為相對快照根目錄的 `raw-batches/efetch-XXXX-<hash>.xml`；`Document.sha256` 是該完整原始批次的雜湊。
- 摘要 SHA-256：`9738b68d03a6e39bed010803aa878cfdc66e0bbcaf005e8ee83d3bcfeb7b2631`。
- 使用單線 1 request/s，比 NCBI 無 API key 的每秒 3 次上限保守。每批最多 100 個 PMID；429、5xx 與連線／逾時最多 **3 次總嘗試**，指數退避，遵守合理 `Retry-After`；大於 60 秒則保存進度停止。無效的 403 不反覆重試。官方有 API key 時每秒可達 10 次，但本模組仍固定使用 1 request/s、無 key。[NCBI E-utilities 使用規範](https://www.ncbi.nlm.nih.gov/books/NBK25497/)
- 原始 bytes 與 metadata 採原子寫入。快取命中時驗證請求參數與 SHA-256；損壞時拒絕靜默覆寫。已完成快照同參數只驗證並重載，不發出網路請求；不同參數須指定新目錄。
- OS 下載鎖位於快照目錄的父目錄，不使用 HW1 或使用者家目錄。崩潰後 OS 釋放鎖；有效快取可續傳。離線模式 `IR_HW1_OFFLINE_DEMO=1` 禁止新下載／續傳，仍允許驗證完成的快照。
- 重複候選 PMID 去重；單次 EFetch 對同一 PMID 回傳多個 record 時以 `ambiguous_duplicate_record` 排除，避免默默選任一版本。
- 保留資料供本機課程分析；PubMed 摘要可能受原出版者版權保護，不聲稱全部內容可自由再散布。

離線驗證與讀取：

```powershell
.\.venv-hw2\Scripts\python.exe -c "from ir_hw2.corpus import load_corpus; print(len(load_corpus()))"
```

明確觸發下載或續傳（預設已有快照會只驗證）：

```powershell
.\.venv-hw2\Scripts\python.exe -c "from ir_hw2.corpus import fetch_corpus; fetch_corpus(progress=print)"
```

## 測試與實測

最後執行 `tests/test_hw2_corpus.py`：**17 passed in 0.56s**（Python 3.13.14）。涵蓋摘要正文與語言篩選、空摘要、書籍排除、PMID 去重、歧義重複紀錄排除、100 篇分批、失敗續傳、完成快照重載、參數不可覆寫、原始／摘要／判定檔 hash、損壞快取、1 request/s 及重試、離線下載封鎖、資源釋放與互斥鎖。

正式快照另實際執行 `load_corpus()`，完整驗證原始 bytes、摘要與選擇清單 hash；`fetch_corpus()` 相同參數離線重載已通過，文件數為 1,000。合成 XML 只用於上述測試，正式統計資料全來自保存的 PubMed 回應。
