# 固定真實語料

`raw/` 含 15 篇 PMC 官方 OAI-PMH GetRecord 原始回應，保留 XML 包裝與授權；每篇都有正文。

來源、文章標題、PMCID、取得時間與全文授權紀錄見 `../reports/corpus_inventory.json` 及本資料夾的 `manifest.jsonl`。原始檔 bytes 的 SHA-256 可由 `scripts/verify_corpus.py` 核對。

14 篇為 CC BY 4.0，PMC7617274 為 CC BY-NC 4.0（非商業用途）。請保留文章作者與原文授權署名；XML front 中保存原作者資訊，PMCID 可連回原文。這份資料是課堂與本機非商業 demo 用集合，不是本專案自行創作的文章。文章內容未被改寫；processed 文字做空白正規化、抽取、分詞及統計。

`processed/articles.jsonl` 和 `index.json` 是可重建的快照；`manifest.jsonl` 是下載／匯入事件紀錄。`download_state.json` 是可過期的本機 OAI 接續狀態，不隨版本控制保存。

`rejected/` 僅在此開發電腦保留未通過 demo 授權篩選的 XML，不加入搜尋或版本控制；對照 manifest 的 failed 記錄。重新匯入請使用 `raw/`，不要把 rejected 混入固定展示集合。

合成測試資料位於 `tests/fixtures/`，不在此資料夾。PMC1–PMC3 是測試代碼；此處 15 篇才是真實 PMC 文章。
