# IR-HW1 生醫文章搜尋

> **2026-09-18 通用詞彙匹配已完成。** 已移除 COVID 專用別名表，改用連字號與字母／數字交界規則，索引 v5，完整回歸 320 項通過。完整規則見 [搜尋調整規格](docs/SEARCH_REDESIGN.md)，驗證見 [成果紀錄](reports/RESULTS.md#2026-09-18-通用詞彙匹配)。

> **2026-09-19 更新：網頁搜尋固定啟用 Porter 詞幹還原，已移除開關。** 搜尋、排序、片段與內文高亮共用 Porter 索引；舊工作階段的關閉設定會自動清除。驗證見 [固定 Porter 成果](reports/RESULTS.md#2026-09-19-網頁固定啟用-porter)。

Python + Streamlit 的本機文章搜尋系統，繁體中文介面、英文 PubMed／PMC 文章。自行實作 Unicode 分詞、倒排索引、停用詞與通用複合詞處理、TF-IDF cosine 排名、原文位置高亮及規則斷句。

## 作業報告

以下為一頁 Word 報告的完整文字內容，可直接在 GitHub 閱讀。另可下載 [Word 報告](reports/BioSearch_作業一實作報告.docx)。

### 生醫文獻檢索系統實作報告

本作業使用 Python 與 Streamlit 建立 BioSearch，並以 Codex 協助開發與測試。系統將生醫 XML 轉成可搜尋文字，提供關鍵字檢索、相關性排序、命中高亮及文件統計。

#### 資料來源與解析

系統支援 PubMed 摘要 XML 與 PMC 全文 XML。輸入 PMID 讀取摘要正文，PMCID 讀取全文；原始 XML 保留於本機。解析時擷取文字區塊及章節資訊，避免重複收錄；摘要模式不將文章標題及摘要小標題納入搜尋與統計。

#### 分詞與前處理

以 Unicode 正規表示式辨識字母、數字與小數，保留詞內連字號及撇號，再統一大小寫與字元形式。自動過濾 and、of、the 等停用詞與孤立英文字母，但保留 vitamin C、T cell 等名稱中的字母。依連字號及字母與數字交界分析複合詞，讓 covid 可匹配 COVID-19；完整 HIV-1 不會誤配 HIV-2。網頁固定使用 NLTK Porter 詞幹演算法，將 antibody／antibodies 等英文詞形合併。

#### 規則斷句與文件統計

以句點、問號、驚嘆號及段落結尾判斷句界，另以規則處理縮寫、小數、網址等例外。統計與搜尋前處理分開：字元數分含空白與不含空白；摘要單字數依空白切分，全文依分詞器計算；句數由規則斷句產生，標題及表格儲存格不計句。

#### 建立倒排索引

自行建立「詞彙 → 文件編號 → 詞頻與原文位置」的倒排索引，位置包含文字區塊及字元起訖點。文件保存完整複合詞與有效組件，並預先計算 IDF 及文件向量長度。索引以 JSON 儲存；資料異動時更新，可在本機離線重用。

#### 搜尋與相關性排序

查詢套用相同的正規化、過濾與詞幹規則，並去除重複關鍵字。以倒排清單聯集取得至少符合一個有效詞的文章，再用 TF-IDF（對數 TF 與平滑 IDF）建立向量，依餘弦相似度由高到低排序。畫面顯示「相關性：10%」等百分比，並依索引位置高亮原文；搜尋 covid 只標示 COVID-19 中的 COVID。

#### 執行結果與限制

目前示範資料為 4 篇摘要，共 1,087 個單字、53 句；搜尋 antibody 與 antibodies 均命中相同兩篇，相關性為 16% 與 10%。截至 2026 年 9 月 19 日，320 項回歸測試通過。系統採詞彙檢索，尚未加入語意模型；相似度不是正確率，規則斷句與詞幹化仍可能有誤判。

## 功能與搜尋規則

**依輸入 ID 決定讀取範圍**：`23193287` 或 `PMID:23193287` 從 PubMed 讀摘要；`PMC3531190` 從 PMC 讀全文，PMC 前綴不分大小寫。純數字一律視為 PMID，不猜測它是否其實是省略前綴的 PMCID。搜尋、字元數、單字數及句數都依各篇保存的範圍計算；摘要模式的文章標題僅供辨識。上傳／資料夾中的 PMC JATS XML 預設讀全文，PubMed XML 讀摘要。重新整理、原始檔更新、還原及重啟保留範圍，原始 XML 不裁切。

PMID 直接呼叫 [PubMed EFetch](https://www.ncbi.nlm.nih.gov/books/NBK25499/)，不要求有 PMCID 或公開全文。若 PubMed 本篇紀錄有 PMCID 就沿用該 ID，否則使用 `PMID` 加數字作為本機文章 ID；不把參考文獻的 ID 當成本篇。沒有摘要時保留 metadata，摘要統計為 0。已存同一個文章 ID 時，重新輸入另一種 ID 會更新讀取範圍與索引，能使用本機 XML 時不重新下載。

**摘要模式只計摘要正文**：文章標題及 `PURPOSE`、`METHODS` 等摘要小標題不納入字元、單字、句子統計或搜尋；小標題仍作閱讀章節名稱。摘要單字數以空白分隔計數，例如 `IgG/IgM` 算一詞，獨立的 `=` 或 `±` 也各算一個單位，與參考畫面的口徑一致。搜尋在原本 tokenizer 之後另做停用詞／孤立字母過濾與複合詞處理；這些處理不影響統計，全文模式的單字數也維持原規則。本次 v5 升級只從既有本機文章重建搜尋索引，不重新下載或重算文章統計。

直接輸入 `cancer treatment` 並按「搜尋」，至少符合一個有效詞的文章即可列入候選，再依相關性排序。畫面沒有 AND／OR／精準片語選單，也沒有新增進階模式選單。`the treatment of cancer` 與 `treatment cancer` 使用相同有效關鍵字。只有 `the and of` 或單獨 `a` 時提示補充關鍵字，`b`、`c`、`a b c` 則提示查詢過於簡短，不會列出整個文章庫。

搜尋依連字號（`-`、`‐`、`‑`）及字母／數字交界辨識完整詞與組成部分，沒有 COVID 專用對照表。例如 `COVID19`、`COVID-19` 都正規化為完整詞 `covid-19`，另供 `covid` 或 `19` 匹配；相同規則也適用 `IL6`／`IL-6`、`BRCA1` 及 `high-risk`。搜尋 `covid` 只高亮原文的 `COVID`；搜尋 `covid19`／`covid-19` 高亮完整詞。完整查詢保留數字條件，因此不會命中只有 `covid` 的文章，`HIV-1` 也不會命中只有 `HIV-2` 的文章。

`vitamin A/B/C`、`hepatitis B/C`、`B cell`、`T cell` 等已登錄上下文保留有意義的字母；其他孤立 ASCII 英文字母及停用詞不作獨立搜尋特徵。`no`、`not` 保留為普通詞，並不執行否定運算。專案自訂停用詞與字母上下文仍保存在 `resources/search_vocabulary.json`，來源、版本及內容 SHA-256 均可追蹤；通用邊界規則實作於 `ir_hw1/relevance.py`。

這是詞彙相關性搜尋；不作任意子字串比對，`HIV-1`／`HIV-2` 保留區別，不會因相同前綴而合併。引號、括號及大寫布林字樣會提示其特殊語法未啟用，仍按一般關鍵字搜尋。後端／CLI 的舊 AND／OR／PHRASE 保留相容性，網頁不再提供模式切換。

網頁搜尋**自動使用 Porter 詞幹還原，不提供開關**。例如 `therapy`／`therapies`、`antibody`／`antibodies` 使用相同詞幹匹配；畫面仍高亮原文完整詞形。改動搜尋框後按「搜尋」即可，跨頁與重新開啟網站都維持此行為。Porter 只合併部分英文詞形，不代表語意理解，也不保證一定增加命中或提高相關性。

原詞與 Porter 的相關性索引、各自的 IDF／範數及舊匹配索引一併保存在 `data/index.json`；網頁直接使用現有 Porter 資料，此次不升版或重建索引，新增／更新文章時仍同步建立各組資料。文章只保存一份，高亮顯示原字詞，字元、單字及句子統計保持原定義。Porter 使用 NLTK 3.9.2 的 `MARTIN_EXTENSIONS`，不需下載語料或模型；相關性模式完成邊界分析及停用詞過濾後，只對純 ASCII 字母特徵套用 Porter，含連字號或數字的完整詞不做詞幹還原。舊 API／CLI 參數保留相容性，CLI 要與網頁一致時使用 `--stemming`。

原始驗證使用 15 篇有 Creative Commons 授權的 PMC XML；個人文章庫可自行增刪。準備好 Python 環境後，已保存的摘要及索引可離線搜尋，不必重新下載。

搜尋後會自動顯示每篇文章的 **「相關性：10%」** 並由高到低排序，不需開關或排序選單。分數是 cosine similarity 的百分比，不是正確率或相關機率；同分依文章編號排列。候選必須至少命中一個有效詞且分數大於 0，不設 10% 等固定門檻；低正分數可能四捨五入顯示為 0%，排序仍使用完整精度。CLI `search` 預設同樣使用此流程。

TF-IDF 使用對數詞頻 `1 + ln(tf)`、平滑 IDF `ln((N + 1) / (df + 1)) + 1`。文件向量包含完整詞與有效組成部分：`IL6` 會提供 `il-6`、`il`、`6` 三個不同特徵，各自計算 TF／DF，普通詞只產生一個特徵。查詢保留每個輸入 token 的完整條件，正規化後去重；`IL6 IL-6` 不會重複加權，`covid` 和 `covid-19` 則是不同條件。全文有效特徵均納入向量範數，因此此次更新可能改變百分比。未知詞不產生候選，全部未知時回傳無結果。索引 v5 保存新版原詞／Porter 相關性資料及舊模式資料，版本或詞彙規則不合時從本機文章重建。

## 快速開始（Windows PowerShell）

在 Python 3.13 環境驗證；本次實測為 Python 3.13.14、Windows 11。所有直接與間接依賴版本鎖定於 `requirements.txt`。

```powershell
Set-Location -LiteralPath 'C:\成大專案\IR-HW1'
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m streamlit run app.py
```

開啟 <http://127.0.0.1:8501>。使用終端機的 `Ctrl+C` 關閉；再次執行最後一行便可重啟。無須啟用 PowerShell 虛擬環境腳本，也無須改 ExecutionPolicy。若 8501 已在執行本系統，直接開啟網址即可；可用 `--server.port 8502` 指定另一埠。

自行從終端機啟動的程序使用 `Ctrl+C` 關閉。網站只監聽本機 127.0.0.1；請使用正常啟動方式展示 PMID 下載，離線測試啟動器會刻意阻擋對外連線。

請在專案根目錄啟動，讓 Streamlit 載入 `.streamlit/config.toml`；其中已停用快速並行重跑，避免連點搜尋／下載時互相搶鎖及畫面殘留。程式檔使用 `poll` 監看，讓重新執行頁面時能載入更新後的 Python 模組。修改這份設定後需停止並重新啟動網站程序。若從舊版（`fileWatcherType = "none"`）更新，必須先重啟 Streamlit；只按瀏覽器 F5 可能仍使用記憶體中的舊函式，出現 `unexpected keyword argument 'ranking'`。

本機已建立 `.venv`；交付或搬移專案時**不要搬移 `.venv`**，應以上述指令重新建立。程式依 `app.py` 的位置定位資料，並支援環境變數 `IR_HW1_DATA_DIR` 改用其他資料目錄。

## 在網頁新增、下載與刪除文章

開啟上方的 **「文章管理」**：

1. **上傳 XML**：選擇一個或多個 PMC/JATS XML，按「上傳並加入搜尋」。完成後直接切到「搜尋文章」，不用重啟或手動建索引。每檔上限 25 MiB，需有 PMCID 與標題；按檔案實際提供的內容顯示與搜尋，相同內容去重，同 PMCID 的新內容會更新。
2. **PMID／PMCID 下載**：輸入 PMID 取得摘要，或輸入 PMC 開頭的 PMCID 取得全文，按「下載並加入搜尋」。系統保存來源 XML、讀取範圍與來源資訊，並更新四組索引。
3. **批次刪除與還原**：在表格勾選多篇，或按「全選目前列表」，再按「移至回收筒（N 篇）」；回收筒也有相同的表格，可一次「還原選取文章（N 篇）」。支援依 PMCID／標題篩選及清除全部選取，篩選不會清掉先前選取；按鈕會顯示總選取篇數。
4. **批次永久刪除**：使用回收筒的同一組選取，勾選「我了解永久刪除後無法還原」，再按「永久刪除選取文章（N 篇）」。先全選即可一次清空回收筒；變更選取範圍須重新勾選確認。會清掉本機文章備份、索引及可辨識的原始 XML 版本；共用 XML 只移除所選篇，其他篇保留。

### 匯入 PMID 文字清單

「文章管理」→「PMID／PMCID 下載」也支援上傳 `.txt`，例如 `pmid-covid-set.txt`。每行一個 PMID：

```text
33126180
39283431
33496842
```

選擇檔案後先顯示不同 PMID 數量、重複項目數及清單預覽，按「批次下載並加入搜尋」才開始下載。空行與重複項目會略過，保留首次出現順序；也接受 `PMID: 33126180`。支援 UTF-8（可含 BOM）與帶 BOM 的 UTF-16，每檔上限 1 MiB、每次最多 100 個不同 PMID。非有效 PMID 會指出行號，整份清單修正後才可下載；不接受 PMCID、CSV 或任意文章文字。

此功能依 PMID 取得**摘要正文**，同篇已存全文時會沿用單篇 PMID 下載規則切換為摘要。每 20 個待下載 PMID 合併為一次 PubMed EFetch 請求，使用同一下載連線與限速器，整批共用 100 次 HTTP 嘗試上限（重試也計入）。批次回應按篇保存為 XML，保留文章原文、結構與來源 URL；每篇完成後保存文章，整批結束時統一更新索引，包含後續下載失敗的情況。完成後列出新增／更新、已存在及失敗數量與原因。重新上傳同一清單可重試，已存在的同範圍文章不重複下載；已在回收筒的文章會依明確下載操作重新加入。清單本身不放入 `data/raw`，該資料夾仍只處理 XML。

遇到連線持續失敗時，共用下載器最多嘗試 3 次後停止後續批次，不對清單每篇重新等待與重試。若畫面顯示「離線展示模式」，下載按鈕會停用；需先關閉 `scripts/run_offline_demo.py` 啟動的程序，再用一般 Streamlit 指令或 `scripts/start_demo.ps1` 啟動。網頁重新整理不會解除離線測試程序的連線封鎖。

新文章下載需要網路；PubMed 摘要不受 PMC 全文可用性限制。PMCID 全文仍需可取得的英文 XML 與可辨識 CC 授權；摘要自動下載亦限定英文。可選擇以 `$env:NCBI_EMAIL = '你的聯絡信箱'` 提供下載器聯絡資訊；來源 URL 會記錄此值。

上傳、搜尋、刪除與還原可離線使用；結果保存於資料目錄，關閉、重啟後仍有效。回收筒保留原始 XML 及 `data/deleted_articles.json` 備份，避免自動同步又把刪除文章加回；永久刪除才清除備份與全文。此檔是本機狀態，不隨 Git 提交；搬移個人語料與刪除狀態時，請完整備份資料目錄。

**直接操作資料夾也會同步**：移入 XML 會加入搜尋，移出／刪除後，沒有其他有效來源的文章會退出搜尋；放回有效 XML 就會重新加入。移除時先保留回收筒備份，可再永久清理。同篇還有另一份有效 XML 時仍可搜尋，會改用實際存在的版本；改名不會產生重複文章。由網頁手動移到回收筒的文章仍需明確還原／上傳，不會被背景同步加回。還原必須有 raw 內的有效全文，缺檔時先放回或重新上傳。

永久刪除只操作本資料目錄 `raw`／`rejected` 直下的 XML，不碰你上傳前的外部原檔或 Git 歷史。manifest 會保留來源與操作紀錄，沒有文章全文，也不會使文章復活。永久刪除中斷時，網站重新整理會依 `purge_pending.json` 接續清理；未完成前暫停讀取不一致的資料。不要手動刪除這份恢復紀錄。損壞的共用 XML 會先提示處理，不直接刪掉可能包含其他篇的檔案。

## 資料下載（CLI）

展示使用隨附固定清單。下載至另一個目錄可避免改動既有 demo：

```powershell
$demoIds = Get-Content -LiteralPath resources\demo_pmcids.txt
.\.venv\Scripts\python.exe -X utf8 -m ir_hw1.cli --data-dir data-new download --count 15 --pmcids $demoIds
.\.venv\Scripts\python.exe -X utf8 -m ir_hw1.cli --data-dir data-new build
```

下載器會自動匯入成功文章。網站啟動或重新整理時會自動更新索引；若只使用 CLI 搜尋，則執行上面的 `build`。使用 `data-new` 時，先設定 `$env:IR_HW1_DATA_DIR = 'data-new'` 再啟動網站。既有 PMCID 預設跳過；`--refresh` 重新取得並更新該文章。

也可利用官方 OAI 集合探索資料，例如本次已驗證的 AIDS Research and Therapy 期刊集合：

```powershell
.\.venv\Scripts\python.exe -X utf8 -m ir_hw1.cli download --count 10 --set aidsresther --from-date 2024-01-01 --until-date 2025-12-31
```

不指定 `--set` 時使用 `pmc-open`。日期是 **OAI 更新日期**，不是出版日期。`download_state.json` 保存集合、日期、待處理 PMCID 與 resumptionToken；相同查詢接續執行。若伺服器 token 過期，先備份並移走該狀態檔，再重新探索；成功的文章會去重。

遵循 [PMC 開發者規範](https://pmc.ncbi.nlm.nih.gov/tools/developers/) 與 [OAI-PMH 文件](https://pmc.ncbi.nlm.nih.gov/tools/oai/)（核對日期 2026-09-14）：使用目前的 `https://pmc.ncbi.nlm.nih.gov/api/oai/v1/mh/`、`metadataPrefix=pmc`；單線、至多每秒一請求，gzip/deflate，429／5xx／連線錯誤最多三次嘗試，遵守 Retry-After，單次執行最多 100 次 HTTP 嘗試。以每個作業系統使用者的檔案鎖避免同時啟動多個下載器。

官方要求超過 100 次請求的批次避開美東週一至週五 05:00–21:00，不能透過重複啟動小批次規避；若擴充到數百篇，請自行安排離峰。本次超過 100 次的資料準備在美東離峰完成。未使用舊 FTP 或 OA Web Service；它們已於 [2026 年 8 月服務變更](https://pmc.ncbi.nlm.nih.gov/tools/cloud/)中淘汰。

CLI 與網站使用作業系統憑證庫 `truststore`，保留 TLS 驗證。若仍有憑證錯誤，應修正 OS／組織 CA 設定；不要關閉憑證驗證。

## 本機 XML 匯入與重建

一般使用只要兩步：

1. 把 PMC 全文 `.xml` 檔直接放進專案的 `data/raw`，也就是 `C:\成大專案\IR-HW1\data\raw`。
2. 網頁開著時約每 3 秒自動檢查；也可按 F5 或直接搜尋。系統同步新增、內容變更與移出的 XML，必要時建立索引。

不需要另外建立 `C:\my-articles`，也不需要手動匯入或建索引。頁面開啟期間每 3 秒輪詢，瀏覽器背景分頁／休眠可能延遲；每次搜尋及 CLI 的 search／stats／build 都會先同步。此流程完全使用本機檔案，不會自動下載文章。

只讀取 `data/raw` 直下的 XML（不遞迴；副檔名不分大小寫），目前不接受 PDF、Word 或一般文字檔。移到 raw 子資料夾也視為移出。未變更的內容會略過；XML 損壞或移除其中一篇時，不繼續搜尋已失效的舊全文，修正後自動重試。移出文章的備份可在回收筒看到。

若需要從其他資料夾匯入，或只使用 CLI，可選擇以下進階指令：

```powershell
# 匯入一個檔案或資料夾中的 *.xml（不遞迴）
.\.venv\Scripts\python.exe -X utf8 -m ir_hw1.cli import data\raw
.\.venv\Scripts\python.exe -X utf8 -m ir_hw1.cli build
```

支援 JATS、OAI 包裝、namespace、多篇包裝與 PubMed PubmedArticle XML。JATS 需要 PMCID 和標題，body 可省略；PubMed 需要 PMID 和標題。摘要模式只擷取 abstract／AbstractText，不以正文補齊；全文模式擷取標題、摘要、正文與圖表文字。拒絕外部實體、外部 DTD 存取及超過 25 MiB 的 XML。壞檔案列入 manifest，成功文章保留。相同文章 ID 與內容去重，內容或範圍更新則替換後重建索引。

外部本機 XML 會複製至 `data/raw/local-<hash>.xml`；使用者應確認匯入檔案的使用權利。缺授權的本機檔案可匯入，但 manifest 會記錄提醒。**官方下載的主要 demo 語料**則需有可辨識的 CC 授權 URL 且文章語言為英文，未通過的檔案放在 `data/rejected`，不納入搜尋，也不隨版本控制分發。

每篇成功文章保留原始 XML SHA-256、來源 API URL、PMCID、PMID／DOI（若有）、授權全文及 URL、取得時間、語言。`manifest.jsonl` 保存歷次匯入／重複／更新／失敗事件。無效 XML 或下載失敗不會建立文章；正常文章的搜尋與統計依實際可抽取的內容計算。

## 指令與測試

```powershell
.\.venv\Scripts\python.exe -X utf8 -m ir_hw1.cli search 'cancer treatment' --mode AND
.\.venv\Scripts\python.exe -X utf8 -m ir_hw1.cli search 'cancer treatment' --mode OR
.\.venv\Scripts\python.exe -X utf8 -m ir_hw1.cli search 'cancer treatment' --mode PHRASE
.\.venv\Scripts\python.exe -X utf8 -m ir_hw1.cli search 'therapies' --stemming
.\.venv\Scripts\python.exe -X utf8 -m ir_hw1.cli stats
.\.venv\Scripts\python.exe -X utf8 -m pytest -q --junitxml=reports\pytest-results.xml
.\.venv\Scripts\python.exe -X utf8 scripts\verify_corpus.py
.\.venv\Scripts\python.exe -X utf8 scripts\evaluate_sentences.py
.\.venv\Scripts\python.exe -m pip check
```

`tests/fixtures/synthetic.xml` 及 `tests/test_phrase.py` 的小型 PMC 識別碼 **是合成識別碼，並非真實 PMC 文章**，只在測試的暫存資料夾使用。真實語料測試依賴交付的 15 篇固定集合；原始檔已從個人文章庫移除時，會從 Git 提交 `ad8bf2b` 讀取到 pytest 暫存目錄，不放回個人 raw。此備援需本機 Git 與該提交；沒有 Git 歷史的交付包須保留固定 XML 才能執行真實語料回歸測試。

`verify_corpus.py` 依各篇保存的範圍核對 SHA、来源、解析結果、統計及 50 組搜尋與逐篇掃描結果，寫入 `reports/verification-source-scope.json`；不下載文章、不改固定測試文章清單。測速只量 matching，片段、Streamlit rendering 與網頁傳輸不在 warm query 時間內。

`reports/sentence_gold.json` 是 **AI 閱讀標註的參考集，待學生人工覆核**。30 段依固定條件選取，10 段 development、20 段 test；分割單位是段落，不是文章。規則凍結後才建立標註及量測，沒有用這 20 段調參。它不是獨立人工金標，不可推論整體生醫文章的斷句準確率。`annotate_sentence_sample.py` 會覆蓋標註，人工修改後不要重跑它；只重跑評估器。

## 離線展示

資料準備完成後，搜尋、上傳與本機文章管理不需網路；PMID 下載仍需連線。另提供可重現的測試啟動方式，阻擋該 Python 程序對 loopback 以外的 socket 連線：

```powershell
.\.venv\Scripts\python.exe -X utf8 scripts\run_offline_demo.py
```

這不變更 Windows 防火牆或其他程式的連線。搜尋、全文、統計與斷句仍可操作；外部 PMC／授權連結需瀏覽器有網路。正式驗證也在全封鎖 socket.connect 的 AppTest 與新 Python 程序中完成。初次安裝套件及下載資料仍需網路。

## 文件與專案結構

- `app.py`：四個檢視——搜尋、文章詳情、語料概覽、文章管理。
- `ir_hw1/library.py`、`ir_hw1/ui_management.py`、`ir_hw1/purge.py`：上傳、PMID 下載、刪除／還原、永久刪除及介面。
- `ir_hw1/`：XML 解析、分詞、斷句、統計、索引、匹配、高亮、持久化及 CLI。
- `data/raw/`、`data/processed/articles.jsonl`、`data/index.json`：可離線重載的固定資料。
- `resources/demo_pmcids.txt`：固定真實語料清單。
- [系統架構與方法](docs/SYSTEM.md)：演算法、統計範圍、規則與調整點。
- [搜尋調整規格（已完成驗證）](docs/SEARCH_REDESIGN.md)：新版搜尋介面、停用詞、詞彙變體及驗收案例。
- [實測結果與限制](reports/RESULTS.md)：合成測試、真實語料、效能與 UI 實測。
- [五分鐘個人 demo](docs/DEMO.md)：逐步操作與解說重點。
- [開發與 AI 協助紀錄](docs/DEVELOPMENT.md)：完成範圍、方案對應與後續事項。

原方案實際檔名是根目錄的 `DEVELOPMENT_PLAN.md`；原始方案內容作為歷史紀錄保留，最新搜尋決策由上述規格補充。既有 P0、固定 Porter 詞幹搜尋、TF-IDF cosine 排名及新版相關性搜尋已實作並完成驗證。詞頻圖及專用搜尋結果 CSV 匯出暫緩；Streamlit 資料表內建的 CSV 下載可使用，但不宣稱完成 P1 搜尋匯出。
