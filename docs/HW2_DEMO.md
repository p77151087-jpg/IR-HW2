# HW2 操作展示（約 7 分鐘）

目前版本：`hw2-hw1-four-conditions-v5-log10`。依作業要求比較 A 基本切詞→B 標點處理→C 停用詞→D Porter 四組。介面條件選單預設 A，可依序切換，不會直接跳到 C。

本輪調整與驗證詳見 [HW2_CHANGELOG](HW2_CHANGELOG.md)。三組試行已撤回，展示時以本頁四組流程為準。

## 準備

日常展示可直接雙擊根目錄的 [start_hw2.cmd](../start_hw2.cmd)，它固定使用 `.venv-hw2`。保持啟動視窗開啟；若 8501 已有舊網站，先在舊啟動視窗按 Ctrl+C。環境已建置時不必重跑安裝，也不必重新訓練模型。

在 `C:\成大專案\IR-HW2` 執行 `scripts/setup_hw2.ps1`、`scripts/start_demo.ps1`，開啟 <http://127.0.0.1:8501>。快照、結果與模型均已保存，demo 不必重抓或重訓。需先認識圖表時，可打開[互動讀圖指南](../output/visualizations/zipf-reading-guide.html)。

讀圖指南示範正式 A 組（244,477 tokens、29,203 詞），預設 `semaglutide` 為 rank 49、CF 488；下面 CF／DF 選詞表使用 B 組，該詞 CF 為 649。A 保留附著標點，因此兩組數字不同，展示時先說明目前條件。

## 1. 搜尋與拼字（1 分鐘）

「搜尋文章」輸入 `insulinn`，先不要按搜尋或移開游標；停頓 200 ms 後開始更新提示，即可看到 `insulin`、`insulins`、`inulin` 等拼字候選。點選 `insulin` 會直接填回輸入框並搜尋，現有搜尋副本有 203 篇；「查看拼字比較」可核對 edit distance 1、B 語料 CF=431。也可按「搜尋」保留原查詢。開啟文章核對原文高亮，說明這是功能命中數，不是 precision／recall。快速改字或清空時，建議會跟著更新；`GLP-1`、`IL-6` 等生醫詞保留原樣。若用 `semaglutid`，既有 Porter 已可能產生命中，仍可顯示正確拼字建議。

`GLP-1` 580 篇且不改寫；`zzzznotincorpus` 0 篇，明示無候選。數字術語、已知詞及縮寫受保護，未知詞不必然是錯字。命中數依目前搜尋副本，日後增刪可能改變；固定實驗快照不變。

## 2. 原切詞、停用詞與 Porter（2 分鐘）

「HW2 實驗室」→「語料與前處理」：先在「前處理比較」切換 tokens、不同詞數、ΣDF，再在「高頻詞比較」看 A–D Top 10 並排圖。「Top 50 詞彙」可逐組查看／下載完整清單；「語料與規則」查看 1,000 篇、查詢、SHA，輸入 `The patients GLP-1 improved 3.5 mg.`：

- A 是基本空白切詞，`mg.` 保留句點。
- B 沿用 HW1 原切詞處理標點，共用 NFC／casefold，保留 `the`、`glp-1`、`3.5`，移除 `mg` 後句點。
- C 在 B 上去掉 `the`；固定詞表保留 no／not／without。
- D 在 C 上將 `patients`→`patient`、`improved`→`improv`；GLP-1 與小數保持完整。

A有244,477 tokens／29,203詞，B標點處理後為246,256 tokens／17,910詞。B→C 移除 66,952 tokens（27.188%），詞彙只少 118；C→D tokens 同為 179,304，詞彙由 17,792 降至 14,305。指著比較圖說：tokens 變少是刪除出現次數，詞彙變少而 tokens 不變則是合併詞型。

只計摘要正文，不計標題、小標題或全文；沒有搜尋複合詞展開或孤立字過濾。展示各組 Top 50 及 CSV。下載／重算明確按鈕觸發，demo 讀保存的結果。

## 3. Zipf 與 CF／DF（2 分鐘）

「Zipf 分析」依序使用三個分頁，一次展示一個比較主題：

1. 「詞頻分布」：單張排名圖，橫軸為線性 rank、縱軸為 log 刻度 CF。排名越前越常見，少數很高、大多數很低；CF=1 長尾平台表示出現一次。
2. 「回歸與殘差」：切換回歸線／殘差。log 以 10 為底，每增加 1 是十倍；彩色點是實測，黑線是全範圍回歸。B 全域 b=1.2783、R²=0.9716。殘差 0 表示吻合，正／負表示實際較高／低；彎曲提醒我們高 R² 不能證明定律。
3. 「高／中／低頻比較」：群組長條一次比較四條件的三區段，切換 R²／RMSE。四組中頻均同時 R² 最高、RMSE 最低。B 中頻 rank 180–1791，b=1.0479、R²=0.9965、RMSE=0.0160（log CF）；展開表格核對精確數值。

切換獨立「CF／DF 與 IDF」頁。「CF 與 DF」散點圖比較 39 詞；選 semaglutide，CF=649、DF=228、覆蓋率22.8%，命中文件平均2.85次。「IDF 與 TF-IDF」切換 DF–IDF 關係圖及12代表詞長條；IDF=log(1000/228)=0.642065。il6 與 pathway-specific 都 CF=2，DF 分別1與2，所以 IDF 不同。「完整選詞與下載」保存39列與CSV。搜尋命中數與分析 DF 的規則不同。

## 4. Word2Vec（1 分鐘）

若出現 `No module named 'gensim'` 或「Word2Vec 套件無法載入」，先停止舊網站，回到專案執行 `scripts/start_demo.ps1`；若啟動檢查失敗再執行 `scripts/setup_hw2.ps1`。本功能需 `.venv-hw2`，複製的 `.venv` 缺少相關套件。保存模型可直接重載，不需因啟動環境錯誤而重新訓練。

查 `semaglutide`，第一近鄰 `liraglutide` cosine 約 0.6704；查 `GLP-1` 可得到完整單詞近鄰。`GLP-1 receptor` 提示多詞輸入限制，`zzzznotincorpus` 展示 OOV。

模型以 10,843 個原文有序句子、246,256 tokens 訓練，保留文件／句界，沒用排序詞頻表；100 維、window=5、min_count=2、epochs=30、seed=42、workers=1，詞彙9,658。近鄰代表上下文相似，不等於同義詞、醫學關係或語意正確率。保存的B模型訓練耗時17.7362秒只是當時本機單次觀測；本版重用相同tokenizer契約的模型並重新驗證重載，沒有再次訓練。

## 5. 報告與驗證（1 分鐘）

開啟「方法與報告」的三個分頁：RQ1–RQ5 作業解答、IR 討論、報告下載與展示。英文 IR 討論389 words；可直接下載主報告與一頁摘要 PDF。主報告有9張圖和A–D各50詞附錄；新圖皆取自既有正式資料。21份正式分析輸出重跑逐位元一致，16個回歸另以NumPy核對；本輪測試證據見 `reports/hw2/comparisons-pytest.xml`。

README 提供 verify、analyze、train、neighbors、spell；新版獨立分析驗證為 `scripts/verify_hw2_tokenizer.py`，正式模型／搜尋／拼字離線核對為 `scripts/verify_hw2.py`。更新報告／PDF後才執行 `scripts/verify_hw2_delivery.py` 作整合交付核對。可用 `scripts/run_offline_demo.py` 限制Python對外連線（先結束原8501程序）。

## 限制與操作證據

Porter採套件，是否須手刻待確認；單領域與日期排序限制外推，原切詞仍不是生醫實體辨識；沒有人工相關性／語意gold standard。兩領域optional未執行，合成資料僅用測試。

**歷史瀏覽器紀錄（2026-09-29）。** 當時 In-app Browser 核對 A–D、Zipf、模型重載、未知詞及拼字採用，保存於 `reports/hw2/browser-validation.json`／`screenshots/`。這些畫面是初版，不當成新版操作證據。

**本版已執行。** Streamlit AppTest、正式離線搜尋／高亮／模型／拼字核對、4張PNG視覺查看通過；讀圖指南在760px明暗主題及360px手機尺寸完成視覺核對，記於 `reports/hw2/tokenizer_guide_qa.json`。本版未重新操作真實瀏覽器走完上述demo，示範前仍可依本流程演練。

**2026-09-30 Word2Vec 修復補驗。** 已在真實瀏覽器重現舊環境的 gensim 缺失，切換 `.venv-hw2` 後操作 Word2Vec 查詢；證據位於 `reports/hw2/word2vec-fix/`。新增 5 項 UI 回歸後全套 492 passed in 56.72s。只有 Word2Vec 流程補做瀏覽器驗證，其他 demo 的操作證據範圍如上。
