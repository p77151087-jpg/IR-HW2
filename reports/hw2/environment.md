# HW2 環境與修改前測試基線

驗證日：2026-09-29。所有寫入位於 `C:/成大專案/IR-HW2`；原始 HW1 僅唯讀讀取固定 Git fixture。

## 環境

- 新建 `.venv-hw2`，Python 3.13.14；`sys.executable` 與 `sys.prefix` 均為 HW2 路徑。
- 複製來的 `.venv/pyvenv.cfg` command 仍有 HW1 建置路徑，故完整保留但不採用。
- 新 pip.exe 與 streamlit.exe 的 shebang 都是 `C:/成大專案/IR-HW2/.venv-hw2/Scripts/python.exe`。module 與 launcher 均實際啟動驗證。
- 既有 requirements.txt 未變動；新增 requirements-hw2.txt 固定 matplotlib 3.11.2、SciPy 1.18.1、gensim 4.4.0 及其新增依賴。numpy 2.5.3、NLTK 3.9.2、Streamlit 1.63.0 保留原版本。
- `pip check` 通過；gensim 使用明確標註的最小測試序列成功訓練 8 維向量。此為套件相容性檢查，不是正式實驗結果。
- scripts/setup_hw2.ps1 已實際重跑成功且保持同一環境；證據為 environment-setup-validation.log。原有 18 個 test 檔 SHA256 修復前後全部相同。
- 完整版本、命令結果與 launcher 路徑：environment.json；完整安裝版號：environment-freeze.txt。安裝詳細紀錄為 environment-install-baseline.log 與 environment-install-hw2.log。
- Codex default sandbox 無法執行使用者 Python／其 venv 啟動器；透過 require_escalated 執行後正常。這是沙箱 process 權限限制，不是專案測試失敗；一般 PowerShell 可直接執行。
- 安裝 cache 與 TEMP/TMP 都設為 HW2/tmp。重建入口：`powershell -ExecutionPolicy Bypass -File scripts/setup_hw2.ps1`。若沒有 `py`，用 `-Python '完整/python.exe/路徑'` 指定可用的 Python 3.13。

## 基線與精確 fixture 修復

| 實際執行 | 結果 | 時間 | 證據 |
| --- | --- | --- | --- |
| 原始 18 個 test 檔、原 fixture、原 requirements | 342 passed、6 setup errors，總共 348 項 | 27.88s | pytest-baseline-original.log / .xml |
| 使用 HW2/tmp/pycache-hw2 全新 bytecode cache，原 fixture | 342 passed、相同 6 setup errors | 28.93s | pytest-baseline-clean-cache.log / .xml |
| 加入固定 fixture 可攜副本後，同一組原有測試 | **348 passed** | 34.83s | pytest-baseline-portable.log / .xml |

六項原始錯誤都是 `real_corpus` fixture 執行 `git show ad8bf2b:data/raw/PMC7616680.xml` 失敗：HW2 新儲存庫沒有 HW1 commit 歷史，live raw 亦為空。它們分別影響 phrase 1 項、real_corpus 2 項、stemming 1 項、tfidf 2 項。原始基線沒有測試 assertion failure，不能將缺 fixture 的六項宣稱為原樣通過。

修復方法：唯讀取得 HW1 commit `ad8bf2bdde3b395f9d71c9d64ce9c28612688ab1` 中原指定 15 個 XML，原封不動存入 `tests/fixtures/hw1-real/`。總大小 1,394,785 bytes；manifest.json 記錄來源 commit、時間、路徑與每檔 SHA256。conftest.py 優先採固定副本且先驗證 SHA256；只在副本不存在時保留原 fallback。沒有改動 18 個 test 檔的斷言、沒有下載替代文章、沒有寫入 HW1，也未把這 15 篇全文當成 HW2 正式摘要語料。

pytest-baseline-manifest.json 記錄第一次執行前所有原有 test 檔 SHA256。複製來的既有 bytecode 含 HW1 `co_filename`，故第一次 verbose log 可見歷史路徑；全新 pycache 後標示正常且結果一致，排除把 HW1 模組當 HW2 執行的疑慮。

Graph Tier 2 使用 HW2 project；相關 Python 檔 coverage 沒有記錄缺漏，scripts/start_demo.ps1 第 4 行 partial 已完整直接讀取。新檔與修改後檔案以來源、執行結果為準；graph 的 Windows Git metadata root_exists=false 不作 repo 不存在的證據。
