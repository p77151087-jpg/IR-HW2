"""Traditional Chinese HW2 laboratory; expensive operations require a button."""
import json
import os
from pathlib import Path
import sys

import pandas as pd
import requests
import streamlit as st
from filelock import Timeout

from .analysis import CONDITIONS, PIPELINE_VERSION, baseline_tokenizer_spec, tokenize
from .cli import DEFAULT_MODEL, DEFAULT_OUTPUT, DEFAULT_SNAPSHOT, ROOT, snapshot_hash
from . import comparisons as charts


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def show_lab(data_dir: Path) -> None:
    snapshot = Path(os.environ.get("IR_HW2_SNAPSHOT", DEFAULT_SNAPSHOT))
    output = Path(os.environ.get("IR_HW2_OUTPUT", DEFAULT_OUTPUT))
    model_dir = Path(os.environ.get("IR_HW2_MODEL", DEFAULT_MODEL))
    # Start the comparison at A, including sessions that still remember a
    # selection from the earlier UI. Preserve later explicit user choices.
    if st.session_state.get("hw2_condition_defaults") != "ABCD-start-at-A-v2":
        st.session_state["hw2_top_condition"] = "A"
        st.session_state["hw2_segment_condition"] = "A"
        st.session_state["hw2_condition_defaults"] = "ABCD-start-at-A-v2"
    st.subheader("實驗室")
    st.caption("正式分析使用固定的 PubMed 摘要快照；文章管理的增刪不會改變本次實驗。下載、統計與模型訓練皆由按鈕明確啟動。")
    section = st.radio("實驗功能", ["語料與前處理", "Zipf 分析", "CF／DF 與 IDF", "Word2Vec", "方法與報告"], horizontal=True, key="hw2_section")
    try:
        manifest = _json(snapshot / "snapshot.json") if (snapshot / "snapshot.json").exists() else None
        summary = _json(output / "summary.json") if (output / "summary.json").exists() else None
        if manifest and summary and summary.get("metadata", {}).get("corpus_sha256") != manifest.get("sha256"):
            st.warning("分析輸出與目前快照不同，請重新執行 A–D 實驗。")
            summary = None
        if summary and any(str(summary.get("conditions", {}).get(c, {}).get("regression", {}).get("log_base")) != "10" for c in CONDITIONS):
            st.warning("分析輸出使用舊版對數底數或不完整的條件，請重新執行 A–D 實驗，以 log 更新統計表與圖表。")
            summary = None
        if summary and (summary.get("metadata", {}).get("pipeline_version") != PIPELINE_VERSION
                        or summary.get("metadata", {}).get("baseline_tokenizer") != baseline_tokenizer_spec()):
            st.warning("分析輸出使用不同的切詞規則或條件標示，請重新執行作業要求的 A–D 四組實驗。")
            summary = None
        if section == "語料與前處理":
            _show_corpus(snapshot, manifest, data_dir, output, summary)
        elif section == "Zipf 分析":
            _show_zipf(summary, output)
        elif section == "CF／DF 與 IDF":
            _show_frequencies(summary, output)
        elif section == "Word2Vec":
            _show_embeddings(snapshot, manifest, model_dir)
        else:
            _show_report(summary)
    except (ValueError, OSError, KeyError, RuntimeError, requests.RequestException, Timeout) as exc:
        st.error(f"HW2 操作未完成：{exc}")
        st.caption("已完成的語料快取仍保留。請檢查檔案或稍後以相同指令續傳。")


def _show_corpus(snapshot, manifest, data_dir, output, summary):
    overview, high, top, rules = st.tabs(["前處理比較", "高頻詞比較", "Top 50 詞彙", "語料與規則"])
    with overview:
        st.markdown("#### 相同摘要，四種累積處理")
        st.caption("A 基本切詞 → B 標點處理 → C 移除停用詞 → D Porter。各圖沿用相同的 A–D 顏色。")
        if summary:
            metric = st.radio("比較指標", list(charts.METRICS), format_func=charts.METRICS.get,
                              horizontal=True, key="hw2_count_metric")
            st.altair_chart(charts.count_chart(summary, metric), width="stretch")
            a, b, c, d = [summary["conditions"][key] for key in CONDITIONS]
            st.write(f"A→B：不同詞數由 {a['unique_terms']:,} 變為 {b['unique_terms']:,}；標點處理會合併表面形式，也可能拆開未保留的分隔字元。")
            removed = b['tokens'] - c['tokens']
            ratio = removed / b['tokens'] if b['tokens'] else 0
            st.write(f"B→C：移除 {removed:,} 次出現（{ratio:.1%}），不同詞數減少 {b['unique_terms'] - c['unique_terms']:,}。少數常見詞可占大量 tokens。")
            st.write(f"C→D：tokens 為 {c['tokens']:,} → {d['tokens']:,}，不同詞數為 {c['unique_terms']:,} → {d['unique_terms']:,}；stemming 合併詞型。")
            st.caption("ΣDF 是詞－文件配對數，可作 postings 規模代理量；不是實際壓縮 bytes，也不是搜尋品質分數。")
            with st.expander("查看四組完整統計"):
                _summary_table(summary)
        else:
            st.info("尚無分析結果；請在「語料與規則」取得快照並執行實驗。")
    with high:
        st.markdown("#### A–D 的高頻詞如何改變？")
        if summary:
            labels = {"A": "基本切詞", "B": "＋標點處理", "C": "＋移除停用詞", "D": "＋Porter"}
            for pair in ("AB", "CD"):
                for column, condition in zip(st.columns(2), pair):
                    with column:
                        st.altair_chart(charts.top_terms_chart(summary, condition, 10, shared_scale=True)
                                        .properties(height=300, title=f"{condition}：{labels[condition]}"), width="stretch")
            st.caption("每組列前 10 名，共用 CF 刻度。各條件獨立排名；A／B 以功能詞為主，移除停用詞後可比較 C／D 的領域詞與 stem。滑鼠移到長條可看精確次數。")
            st.write("圖上的詞形也有意義：D 的 stem 可能不是完整英文單字。高頻詞改變不代表檢索品質必然提升。")
        else:
            st.info("完成分析後可比較 A–D 的高頻詞。")
    with top:
        st.markdown("#### 哪些詞最常見？")
        if summary:
            condition = st.selectbox("查看 Top 50 條件", list(CONDITIONS), index=0, key="hw2_top_condition")
            st.altair_chart(charts.top_terms_chart(summary, condition), width="stretch")
            st.caption("圖顯示前 15 名，完整 Top 50 在下表。各條件獨立排名；相同名次不一定是同一個詞。")
            frame = pd.DataFrame(summary["conditions"][condition]["top50"])
            st.dataframe(frame, hide_index=True, height=390)
            st.download_button(f"下載 {condition} 組 Top 50", frame.to_csv(index=False).encode("utf-8-sig"),
                               f"top50_{condition}.csv", "text/csv", key="hw2_top50_download")
        else:
            st.info("完成分析後可查看 A–D 的高頻詞。")
    with rules:
        _show_corpus_controls(snapshot, manifest, data_dir, output)
        st.markdown("#### 試試看前處理規則")
        example = st.text_input("前處理比較文字", "The patients' GLP-1 therapies reduced 3.5 mg.", key="hw2_token_example")
        st.dataframe(pd.DataFrame([{"條件": c, "token 數": len(tokenize(example, c)), "序列": " | ".join(tokenize(example, c))} for c in CONDITIONS]), hide_index=True)
        st.caption("A 按空白切詞並統一大小寫。B 保留 glp-1、3.5 與 il6；C 移除固定停用詞，保留 no／not／without；D 對純 ASCII 英文字母做 Porter。")
        st.caption("各組共用 HW1 NFC／casefold 正規化，不加入搜尋專用的複合詞展開。Porter 使用 NLTK MARTIN_EXTENSIONS。")


def _show_corpus_controls(snapshot, manifest, data_dir, output):
    from .corpus import DEFAULT_QUERY, fetch_corpus, load_corpus
    st.markdown("#### 固定 GLP-1 摘要語料")
    if manifest:
        st.success(f"固定快照：{len(manifest.get('selected_pmids', [])):,} 篇；一個 PMID 為一篇文件。")
    st.caption("僅納入英文、非空摘要正文，不含文章標題、小標題或全文。搜尋文章庫的增刪不影響快照。")
    with st.expander("來源、查詢與資料管理"):
        st.code(manifest.get("query", DEFAULT_QUERY) if manifest else DEFAULT_QUERY, language=None)
        st.markdown("[NCBI 使用與版權聲明](https://www.ncbi.nlm.nih.gov/home/about/policies/) · [E-utilities 使用規範](https://www.ncbi.nlm.nih.gov/books/NBK25497/)")
        if manifest:
            st.json(manifest)
            if st.button("驗證快照並加入搜尋文章庫", key="hw2_publish"):
                from .integration import publish_search_copy
                with st.spinner("驗證來源並建立搜尋副本…"):
                    result = publish_search_copy(snapshot, data_dir)
                st.success(f"已發布 {result['published']} 篇搜尋副本。")
        offline = os.environ.get("IR_HW1_OFFLINE_DEMO") == "1"
        if st.button("下載／續傳 1,000 篇 GLP-1 摘要", key="hw2_fetch", disabled=bool(manifest) or offline):
            progress = st.empty()
            with st.spinner("批次下載中，成功批次會保存供續傳…"):
                fetch_corpus(snapshot, count=1000, progress=progress.info)
            st.rerun()
        if st.button("執行 A–D 統計與 Zipf 實驗", key="hw2_analyze", disabled=not bool(manifest)):
            from .analysis import run_experiment
            with st.spinner("計算固定語料的 A–D 統計與圖表…"):
                run_experiment(load_corpus(snapshot), output, snapshot_hash(snapshot))
            st.rerun()


def _summary_table(summary):
    keys = ("documents", "tokens", "unique_terms", "average_tokens_per_document")
    labels = {"A": "基本切詞＋小寫", "B": "標點處理", "C": "B + 移除停用詞", "D": "C + Porter"}
    rows = [{"條件": name, "處理方式": labels[name], **{key: value[key] for key in keys}} for name, value in summary["conditions"].items()]
    st.dataframe(pd.DataFrame(rows).rename(columns={"documents": "篇數", "tokens": "tokens", "unique_terms": "不同詞數", "average_tokens_per_document": "平均 tokens／篇"}), hide_index=True)


def _show_zipf(summary, output):
    if not summary:
        st.info("請先在「語料與前處理」完成語料與 A–D 實驗。")
        return
    distribution, regression, segments = st.tabs(["詞頻分布", "回歸與殘差", "高／中／低頻比較"])
    with distribution:
        st.markdown("#### 少數高頻詞，大量低頻詞")
        st.caption("橫軸為線性排名；縱軸 CF 採 log 刻度。底部平台表示出現 1 次，曲線越長表示不同詞彙越多。")
        if (output / "rank_frequency.png").exists():
            st.image(str(output / "rank_frequency.png"))
        st.write("這張圖呈現整體形狀；是否近似 Zipf，還要一起看回歸、殘差與不同區段。")
        with st.expander("四組語料統計"):
            _summary_table(summary)
    with regression:
        st.caption("log(CF) = intercept + slope × log(rank)；Zipf exponent = −slope。log 統一以 10 為底，R² 與 RMSE 皆在 log(CF) 空間計算。同頻依詞彙順序給不同名次。")
        view = st.radio("比較視角", ["回歸線", "殘差"], horizontal=True, key="hw2_fit_view")
        name = "log_log.png" if view == "回歸線" else "residuals.png"
        if (output / name).exists():
            st.image(str(output / name))
        st.caption("同類子圖使用相同座標範圍，可直接比較斜率或殘差大小。")
        if view == "回歸線":
            st.write("彩色點是實測詞頻，黑線是全範圍回歸。指數接近 1 與 R² 高是兩個不同的判準，不能解讀成搜尋效果較好。")
        else:
            st.write("殘差 = 觀察 log(CF) − 預測 log(CF)。0 表示吻合；正值為實際頻率較高，負值較低。虛線標示區段邊界；彎曲表示全域直線存在系統性偏差。")
        st.warning("高 R² 不能單獨證明 Zipf's Law；它不是『符合定律的機率』。須一起看指數、殘差與區段。")
        with st.expander("完整回歸數據：slope、intercept、exponent、R²、RMSE"):
            rows = [{"condition": c, **value["regression"]} for c, value in summary["conditions"].items()]
            st.dataframe(pd.DataFrame(rows).replace({"rmse_space": {"log10(CF)": "log(CF)"}}), hide_index=True)
            st.caption("points 是參與回歸的不同詞數，不是文章篇數。")
    with segments:
        st.markdown("#### 哪個頻率區段更接近直線？")
        metric = st.radio("區段比較指標", ["r_squared", "rmse"],
                          format_func=lambda x: "R²：越高越好" if x == "r_squared" else "RMSE：越低越好",
                          horizontal=True, key="hw2_segment_metric")
        st.altair_chart(charts.segment_chart(summary, metric), width="stretch")
        conclusions = charts.best_segments(summary)
        for row in conclusions:
            if row["best"]:
                names = "、".join(charts.SEGMENTS[name] for name in row["best"])
                st.write(f"{row['condition']}：{names}區段同時具有最高 R² 與最低 RMSE。")
            else:
                st.write(f"{row['condition']}：區段指標不足或兩個判準未指向同一區段，無法指定共同最佳區段。")
        st.caption("高頻＝前 1% 排名；中頻＝其後至 10%；低頻＝其餘。各區段分別回歸，各條件百分位不代表相同詞或相同數值範圍，結論屬描述性比較。")
        with st.expander("查看分段指數及完整數據"):
            condition = st.selectbox("區段比較條件", list(CONDITIONS), index=0, key="hw2_segment_condition")
            st.dataframe(pd.DataFrame([{"區段": name, **fit} for name, fit in summary["conditions"][condition]["segments"].items()])
                         .replace({"rmse_space": {"log10(CF)": "log(CF)"}}), hide_index=True)
            st.download_button("下載 A–D 全部區段", pd.DataFrame(charts.segment_rows(summary)).to_csv(index=False).encode("utf-8-sig"),
                               "segment_comparison.csv", "text/csv", key="hw2_segment_download")
        st.caption("低頻平台即使 RMSE 小或指數接近 1，也不能單憑一項指標認定最符合 Zipf。CF／DF 與 IDF 請看上方獨立專頁。")


def _show_frequencies(summary, output):
    if not summary:
        st.info("請先完成 A–D 實驗，再比較 CF、DF 與 IDF。")
        return
    rows = charts.selected_term_rows(summary)
    if not rows:
        st.info("目前沒有可比較的選詞資料。")
        return
    frame = pd.DataFrame(rows)
    all_rows = charts.all_term_rows(summary)
    n = summary["conditions"]["B"]["documents"]
    st.caption(f"處理條件 B：標點處理，保留停用詞、未做 stemming；文章數 N = {n:,} 篇摘要。log 以 10 為底。")
    scope = st.radio("顯示詞彙範圍", ["全部詞彙", "選定詞彙"], horizontal=True, key="hw2_vocabulary_scope")
    shown = all_rows if scope == "全部詞彙" else rows
    cfdf_count = len(charts.frequency_bubbles(shown, ("cf", "df")))
    idf_count = len(charts.frequency_bubbles(shown, ("df",)))
    for column, label, value in zip(st.columns(3),
                                     ["目前顯示詞彙總數", "CF–DF 合併後座標點數", "DF–IDF 合併後座標點數"],
                                     [len(shown), cfdf_count, idf_count]):
        column.metric(label, f"{value:,}")
    st.caption(f"B 條件全部 {len(all_rows):,} 詞；原本選定 {len(rows):,} 詞。兩張氣泡圖共用上方設定，一個氣泡可能代表多個詞。氣泡面積依詞數線性縮放，保留最小尺寸方便查看。")
    cfdf, idf, table = st.tabs(["CF 與 DF", "IDF 與 TF-IDF", "詞表與下載"])
    with cfdf:
        st.markdown("#### 常出現，是否也出現在很多篇文章？")
        st.altair_chart(charts.cf_df_chart(summary, shown), width="stretch")
        st.caption("兩軸皆採 log 刻度。虛線為 CF=DF（命中的每篇恰好出現一次）；越高於虛線，命中文件內的平均重複越多。CF、DF 都相同的詞合併為氣泡；滑鼠移到氣泡可查看詞數及最多 5 個範例。")
        st.markdown("##### 作業範例：原本選定詞彙")
        terms = frame['term'].tolist()
        term = st.selectbox("查看詞彙", terms, index=terms.index("semaglutide") if "semaglutide" in terms else 0, key="hw2_cfdf_term")
        row = next(row for row in rows if row['term'] == term)
        for col, label, value in zip(st.columns(4), ["CF：出現次數", "DF：文件數", "文件覆蓋率", "命中文件平均次數"],
                                     [f"{row['cf']:,}", f"{row['df']:,}", f"{row['coverage']:.1%}", f"{row['occurrences_per_document']:.2f}"]):
            col.metric(label, value)
        st.write("**為何 CF 高但 DF 相對低？** 同一篇摘要可以多次使用同一詞；每次都增加 CF，但該篇只增加一次 DF。")
        st.write("**哪個指標表示分布廣度？** DF 或 DF/N。CF 表示累積使用量，DF 表示跨文件覆蓋；兩者不能互相取代。")
    with idf:
        st.caption("CF 計重複出現；DF 計不同文章。IDF = log(N/DF)，log 以 10 為底，不平滑、不加 1。")
        view = st.radio("IDF 比較方式", ["文件覆蓋與 IDF", "代表詞比較"], horizontal=True, key="hw2_idf_view")
        if view == "文件覆蓋與 IDF":
            st.caption("DF 相同的詞具有相同 IDF，因此會重疊；氣泡越大，代表該位置的詞越多。")
            st.altair_chart(charts.idf_curve_chart(summary, shown), width="stretch")
        else:
            st.caption("作業範例：沿用原本選定詞彙中的代表詞比較。上方範圍設定適用於 CF–DF 與 DF–IDF 氣泡圖。")
            st.altair_chart(charts.idf_terms_chart(summary), width="stretch")
        st.write(f"**為什麼常見詞 IDF 低？** 出現在越多文件，DF 越接近 N={n:,}，N/DF 越接近 1，因此 IDF 越接近 0。這裡的『常見』指跨文件普遍出現；只在少數文章重複很多次的高 CF 詞，不一定有低 IDF。")
        st.write("**與 TF-IDF 有何關係？** 文件內 TF 衡量這篇文件用了幾次，IDF 衡量跨文件的區辨能力。TF-IDF 結合兩者，降低廣泛常見詞的權重；Zipf 的 CF 排名不能替代 DF。高 IDF 也可能來自錯字或極稀有詞，不等於一定相關。")
        st.caption("氣泡依目前範圍的詞彙合併；灰線為 IDF = log(N/DF)。既有搜尋使用獨立的平滑 TF-IDF，不混用本作業的 IDF 數值。")
    with table:
        _show_vocabulary_table(pd.DataFrame(all_rows))
        st.markdown("#### 原本選定詞彙比較表")
        st.write(f"目前列出 {len(rows)} 個詞；正式語料要求至少 20 詞比較 CF／DF、至少 10 詞計算 IDF。")
        if len(rows) < 20:
            st.warning("目前選詞不足 20 個，尚不足以完成正式作業的選詞要求。")
        columns = ["term", "cf", "df", "idf"]
        st.dataframe(frame[columns].rename(columns={"term": "詞彙", "cf": "CF", "df": "DF", "idf": "IDF"}), hide_index=True, height=450)
        _download_tables(output)


def _reset_vocabulary_page():
    st.session_state["hw2_vocabulary_page"] = 1


@st.fragment
def _show_vocabulary_table(frame):
    """Search/paginate locally without rerendering the two charts or scanning XML."""
    st.markdown("#### B 條件完整詞表")
    st.download_button(f"下載 B 條件全部詞彙 CSV（{len(frame):,} 詞）",
                       frame[["rank", "term", "cf", "df", "idf"]].to_csv(index=False).encode("utf-8-sig"),
                       "terms_B.csv", "text/csv", key="hw2_all_terms_download", on_click="ignore")
    query = st.text_input("搜尋完整詞表", placeholder="輸入完整詞或部分文字，例如 insulin",
                          key="hw2_vocabulary_query", on_change=_reset_vocabulary_page).strip()
    filtered = frame[frame["term"].str.contains(query, case=False, regex=False)] if query else frame
    size_column, page_column = st.columns(2)
    per_page = size_column.selectbox("每頁詞數", [50, 100, 200], key="hw2_vocabulary_page_size", on_change=_reset_vocabulary_page)
    pages = max(1, (len(filtered) + per_page - 1) // per_page)
    if st.session_state.get("hw2_vocabulary_page", 1) > pages:
        _reset_vocabulary_page()
    page = page_column.number_input("詞表頁碼", min_value=1, max_value=pages, step=1, key="hw2_vocabulary_page")
    start = (page - 1) * per_page
    st.caption(f"符合 {len(filtered):,}／{len(frame):,} 詞；第 {page:,}／{pages:,} 頁。搜尋與分頁只影響下表；CSV 一律包含 B 條件全部詞彙。")
    if filtered.empty:
        st.info("沒有符合的詞彙，請更換搜尋文字。")
    else:
        st.dataframe(filtered.iloc[start:start + per_page][["rank", "term", "cf", "df", "idf"]]
                     .rename(columns={"rank": "排名", "term": "詞彙", "cf": "CF", "df": "DF", "idf": "IDF"}),
                     hide_index=True, height=390)


def _download_tables(output):
    for filename in ("cf_df_comparison.csv", "idf_terms.csv"):
        path = output / filename
        if path.exists():
            st.download_button("下載 " + filename, path.read_bytes(), filename, "text/csv", key="download_" + filename)
    with st.expander("下載全部詞表與設定"):
        for path in sorted(output.glob("*.csv")):
            if path.name not in {"cf_df_comparison.csv", "idf_terms.csv"}:
                st.download_button(path.name, path.read_bytes(), path.name, "text/csv", key="csv_" + path.name)
        if (output / "summary.json").exists():
            st.download_button("summary.json", (output / "summary.json").read_bytes(), "summary.json", "application/json")


def _show_embeddings(snapshot, manifest, model_dir):
    st.markdown("#### Skip-gram 詞向量")
    st.write("從原始摘要的有序句子訓練，保留文件、區塊與句子邊界；使用 B（HW1 原本切詞及標點處理），保留停用詞及詞序。")
    st.caption("vector size 100 · window 5 · min_count 2 · epochs 30 · seed 42 · workers 1 · negative 5")
    if not manifest:
        st.info("請先完成正式語料快照。")
        return
    try:
        from .embeddings import load_word2vec, neighbors, train_word2vec
    except ImportError as exc:
        st.error("Word2Vec 套件無法載入，請用 HW2 專用環境啟動網站。")
        st.write("先停止目前網站，再於 PowerShell 執行下列指令。已保存的語料與模型可繼續使用，不必重新下載或訓練。")
        st.code(f"Set-Location -LiteralPath '{ROOT}'\n"
                ".\\scripts\\setup_hw2.ps1\n.\\scripts\\start_demo.ps1", language="powershell")
        with st.expander("環境診斷"):
            st.text(f"目前 Python：{sys.executable}\n套件載入錯誤：{exc}")
        return
    if st.button("訓練／重新訓練 Word2Vec", key="hw2_train"):
        from .corpus import load_corpus
        with st.spinner("正在訓練並保存模型，完成後可離線重載…"):
            train_word2vec(load_corpus(snapshot), model_dir, snapshot_hash(snapshot))
        st.success("模型已保存。")
    if not (model_dir / "metadata.json").exists():
        st.info("尚未訓練模型；頁面重跑不會自動訓練。")
        return
    metadata = _json(model_dir / "metadata.json")
    if metadata.get("baseline_tokenizer") != baseline_tokenizer_spec():
        st.warning("這個模型使用不同的切詞規則；請按上方按鈕重新訓練，才能與目前 B 條件一致。")
        return
    st.caption(f"已訓練詞彙 {metadata['vocabulary_size']:,} 個 · {metadata['sentences']:,} 句 · 語料 {metadata['documents']:,} 篇")
    with st.expander("模型設定與來源"):
        st.json(metadata)
    with st.form("hw2_neighbors_form"):
        query = st.text_input("近鄰詞彙", "semaglutide", key="hw2_neighbor_query")
        requested = st.form_submit_button("查詢近鄰")
    if requested:
        model, _ = load_word2vec(model_dir, snapshot_hash(snapshot))
        result = neighbors(model, query)
        st.info(result["message"])
        if result["neighbors"]:
            st.dataframe(pd.DataFrame(result["neighbors"]), hide_index=True)
    st.caption("近鄰 cosine 不是正確率；小型單領域語料、規則句界及 min_count 均限制結果。GLP-1 會保留為 glp-1，可直接查詢；此處一次輸入一個切詞後的詞彙。")


def _show_report(summary=None):
    answers, discussion, deliverables = st.tabs(["RQ1–RQ5 作業解答", "IR 討論", "報告下載與展示"])
    report = ROOT / "reports/hw2/HW2_REPORT.md"
    with answers:
        if not summary:
            st.info("完成正式實驗後，可在這裡查看資料支持的作業結論。")
        else:
            st.markdown("#### RQ1｜語料是否符合 Zipf？")
            st.write("請以詞頻圖、回歸、殘差及分段結果一起判讀。固定 1,000 篇正式語料呈現 Zipf 式的不均勻分布，中頻區有良好局部近似；頭尾仍有偏離，不能宣稱全排名服從單一精確定律。")
            if any(data['documents'] != 1000 for data in summary['conditions'].values()):
                st.warning("目前載入的不是 1,000 篇正式規模；上段正式結論需以隨附固定快照重現。下列數字來自目前資料。")
            st.markdown("#### RQ2｜指數是多少？")
            values = []
            for c, data in summary['conditions'].items():
                b = data['regression']['zipf_exponent']
                values.append(f"{c}：{b:.4f}" if b is not None else f"{c}：資料不足")
            st.write("全範圍指數為 " + "；".join(values) + "。必須連同條件及排名範圍報告，不能以中頻指數代替全範圍指數。")
            st.markdown("#### RQ3｜前處理如何影響結果？")
            st.write("比較不同詞數、高頻詞、指數與曲線形狀：標點處理合併部分表面形式，也可能拆開 token；停用詞移除降低高頻端及 tokens；Porter 合併詞型。請在「語料與前處理」比較數量與 Top 50，再到 Zipf 頁核對指數及形狀。詞彙變少不代表搜尋品質必然提高。")
            st.markdown("#### RQ4｜CF 與 DF 的關係？")
            st.write("CF 是累積出現次數，DF 是含詞文件數；同一文件重複使用會增加 CF，卻不再增加 DF。DF/N 表示覆蓋率。詳見「CF／DF 與 IDF」散點圖、逐詞範例及完整選詞表。")
            st.markdown("#### RQ5｜對 Information Retrieval 有何意義？")
            st.write("高頻詞會增加 token 處理及 postings 負擔，稀有詞長尾則擴大字典。可據此考慮停用詞策略、倒排索引及壓縮；TF-IDF 用 DF 區分跨文件普遍程度。近似 Zipf 仍可協助容量規劃，但實際效能、壓縮量及相關性仍需另行量測。")
    with discussion:
        st.markdown("#### 為什麼近似規律仍有工程價值？")
        st.write("即使沒有一個精確指數解釋所有詞，仍能預期少數高頻詞與大量低頻詞帶來不同成本。常見詞需要考慮長 postings 與快取；稀有詞需要考慮字典與短清單的固定開銷。壓縮可利用排序 docID 的 gaps、變長整數及字典前綴，但不能把 ΣDF 直接當成壓縮 bytes。")
        st.write("停用詞移除可能降低成本，也可能損失片語或否定資訊；本專案保留 no、not、without。TF-IDF 降低廣泛出現詞的權重，仍需要 relevance judgments 才能評估檢索品質。")
        if report.exists():
            text = report.read_text(encoding="utf-8")
            if "<!-- IR_ENGLISH_START -->" in text and "<!-- IR_ENGLISH_END -->" in text:
                english = text.split("<!-- IR_ENGLISH_START -->", 1)[1].split("<!-- IR_ENGLISH_END -->", 1)[0].strip()
                st.caption(f"以下英文討論共 {len(english.split())} words；作業要求 300–500 words。內容取自固定語料正式報告。")
                with st.expander("閱讀完整英文 IR 討論", expanded=True):
                    st.markdown(english)
    with deliverables:
        st.markdown("#### 作業內容與展示位置")
        st.dataframe(pd.DataFrame([
            {"需求": "資料來源、1,000 篇、唯一 PMID／英文摘要", "位置": "語料與前處理 → 語料與規則；報告第 1 節"},
            {"需求": "A–D 前處理、基本統計、Top 50", "位置": "語料與前處理 → 比較／詞彙；報告第 2–3 節及附錄"},
            {"需求": "詞頻圖、log–log 回歸與五項指標", "位置": "Zipf 分析 → 分布／回歸；報告第 4 節"},
            {"需求": "R² 是否充分、高中低頻比較", "位置": "Zipf 分析 → 殘差／區段；報告第 4 節"},
            {"需求": "至少 20 詞 CF／DF、至少 10 詞 IDF", "位置": "CF／DF 與 IDF → 三個分頁；報告第 5 節"},
            {"需求": "IR 討論 300–500 words、technical argument", "位置": "IR 討論；報告第 6 節"},
            {"需求": "Word2Vec", "位置": "Word2Vec → 查詢近鄰；報告第 7 節"},
            {"需求": "拼字校正、原文命中展示", "位置": "搜尋文章 → insulinn → 採用建議並搜尋 → 開啟文章"},
            {"需求": "Executive Summary、系統說明及 demo", "位置": "下方 PDF／Markdown；docs/HW2_DEMO.md"},
        ]), hide_index=True)
        st.caption("兩領域比較為 optional。本次 Porter 為 NLTK MARTIN_EXTENSIONS 套件模組；未宣稱自行重寫演算法。")
        for label, name, pdf_name in [("分析報告與 RQ1–RQ5", "HW2_REPORT.md", "HW2_REPORT.pdf"), ("Executive Summary", "EXECUTIVE_SUMMARY.md", "HW2_EXECUTIVE_SUMMARY.pdf")]:
            path = ROOT / "reports/hw2" / name
            pdf = ROOT / "output/pdf" / pdf_name
            st.markdown(f"**{label}（固定 1,000 篇正式語料）**")
            if pdf.exists():
                st.download_button("下載 PDF：" + label, pdf.read_bytes(), pdf_name, "application/pdf", key="pdf_" + pdf_name)
            if path.exists():
                st.download_button("下載 Markdown：" + label, path.read_bytes(), name, "text/markdown", key="md_" + name)
        with st.expander("離線重現指令"):
            st.code(".\\.venv-hw2\\Scripts\\python.exe -m ir_hw2.cli verify\n"
                    ".\\.venv-hw2\\Scripts\\python.exe -m ir_hw2.cli analyze\n"
                    ".\\.venv-hw2\\Scripts\\python.exe -m ir_hw2.cli neighbors semaglutide", language="powershell")
