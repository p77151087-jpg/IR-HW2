"""Traditional Chinese, entirely local Streamlit demonstration."""
import html
import json
import math
import os
from pathlib import Path

import pandas as pd
import streamlit as st
from streamlit.runtime.scriptrunner import get_script_run_ctx
import truststore
from filelock import Timeout

from ir_hw1.index import INDEX_VERSION, build_index, load_snapshot
from ir_hw1.search import search
from ir_hw1.sentence_splitter import split_sentences
from ir_hw1.snippets import highlight, hit_locations, make_snippets
from ir_hw1.storage import DEFAULT_DATA, StorageError, load_documents, read_manifest
from ir_hw1.sync import raw_signature, sync_raw_folder
from ir_hw1.ui_management import show_management
from ir_hw1.xml_parser import PARSER_VERSION

# Application entry point: use the Windows/system CA store for PMC HTTPS.
truststore.inject_into_ssl()

st.set_page_config(page_title="BioSearch｜生醫文章搜尋", page_icon="🔬", layout="wide")
st.markdown("""<style>
.block-container{max-width:1180px;padding-top:4rem}
.eyebrow{font-size:.8rem;letter-spacing:.16em;color:#087f8c;font-weight:700}
.intro{color:#526a7a;font-size:1.03rem;margin-bottom:1.4rem}
.passage{font-family:Georgia,'Times New Roman',serif;font-size:1.06rem;line-height:1.8;color:#243d50;overflow-wrap:anywhere}
.article-text .passage{margin-bottom:1rem;white-space:pre-wrap}
.article-section{font-weight:700;margin:1rem 0}
.article-heading{font-size:.875rem;color:#526a7a;margin:.5rem 0}
mark{background:#ffdf7e;color:#142e45;padding:1px 3px;border-radius:3px}
.result-title{font-size:1.12rem;font-weight:650;line-height:1.55;margin-bottom:.5rem}
[data-testid="stMetric"]{background:#fff;border:1px solid #dbe6ed;border-radius:10px;padding:14px}
/* Keep every view at normal brightness during full and fragment reruns. */
[data-testid="stElementContainer"][data-stale="true"]{opacity:1!important;transition:none!important;animation:none!important}
</style>""", unsafe_allow_html=True)

DATA_DIR = Path(os.environ.get("IR_HW1_DATA_DIR", str(DEFAULT_DATA)))


@st.cache_resource(show_spinner="載入本機文章與索引…")
def cached_snapshot(data_dir: str, signature: tuple):
    path = Path(data_dir)
    if not load_documents(path):
        return {}, build_index({})
    return load_snapshot(path)


def file_signature() -> tuple:
    paths = [DATA_DIR / name for name in ("processed/articles.jsonl", "index.json",
             "deleted_articles.json", "purge_pending.json", "raw_sync_state.json")]
    return tuple((p.stat().st_mtime_ns, p.stat().st_size) if p.exists() else None for p in paths)


def reset_search_page() -> None:
    st.session_state["result_page"] = 1
    st.session_state.pop("selected_result", None)


def adopt_spelling_suggestion(original: str, suggestion: str) -> None:
    # A delayed click must never replace a newer draft with an old suggestion.
    if st.session_state.get("query", "") != original:
        return
    st.session_state["query"] = suggestion
    st.session_state["active_search"] = suggestion
    st.session_state["search_controls"] = {"query": suggestion}
    st.session_state["adopted_spelling"] = (original, suggestion)
    st.session_state["search_results_pending"] = True
    reset_search_page()


@st.cache_resource(show_spinner=False, max_entries=4)
def spelling_index(corpus_version: str, preprocessing_version: tuple[str, ...], _documents: dict):
    # A fixed corpus can produce different vocabulary after tokenizer changes.
    # Include the token contract in Streamlit's cache key across UI reruns.
    from ir_hw2.spelling import SpellingIndex, build_vocabulary
    return SpellingIndex(build_vocabulary(_documents))


@st.cache_data(show_spinner=False, max_entries=128)
def spelling_preview(query: str, corpus_version: str, preprocessing_version: tuple[str, ...], _spelling_index) -> dict:
    from ir_hw2.spelling import suggest_query
    return suggest_query(query, _spelling_index)


@st.fragment
def show_search_controls(corpus_version: str, token_contract: tuple[str, ...], prepared_spelling) -> None:
    """Only the query and suggestions rerun while typing; results stay put."""
    # The three-second folder watcher handles external changes. Search/adoption
    # triggers a full run and synchronizes before reading results. Typing needs
    # neither a filesystem scan nor vocabulary preparation.
    # Adoption changes the input in a callback, so its button disappears on the
    # next fragment run. Escalate here even when that button is no longer drawn.
    if st.session_state.get("search_results_pending", False):
        st.rerun()
    with st.container(border=True):
        query = st.text_input(
            "輸入英文關鍵字", placeholder="例如：insulinn、cancer treatment 或 GLP-1",
            key="query", max_chars=2000, live="200ms",
        )
        st.session_state["search_controls"] = {"query": query}
        if st.button("搜尋", type="primary", key="submit_search"):
            st.session_state["active_search"] = query
            st.session_state.pop("adopted_spelling", None)
            reset_search_page()
            st.rerun()
        st.caption("打字稍停就會顯示拼字建議，點選即可套用並搜尋。也可以直接搜尋原本的文字。")
        if not query.strip():
            return
        suggestion = spelling_preview(query, corpus_version, token_contract, prepared_spelling)
        if suggestion["changes"]:
            st.markdown("**你是不是想找：**")
            # A single typo offers up to three words. Multiple typos offer the
            # complete corrected query so adopting one does not lose other words.
            choices = [suggestion["suggested_query"]]
            if len(suggestion["changes"]) == 1:
                change = suggestion["changes"][0]
                for candidate in change.get("candidates", [])[1:]:
                    word = candidate["term"]
                    if change["original"].istitle():
                        word = word.capitalize()
                    choices.append(query[:change["start"]] + word + query[change["end"]:])
            with st.container(horizontal=True):
                for number, choice in enumerate(choices):
                    label = choice if len(choice) <= 70 else choice[:67] + "…"
                    st.button(label, key="adopt_spelling" if number == 0 else f"adopt_spelling_{number}",
                              help=f"改用「{choice}」搜尋", on_click=adopt_spelling_suggestion,
                              args=(query, choice))
            with st.expander("查看拼字比較"):
                rows = [
                    {"輸入": change["original"], "候選詞": candidate["term"],
                     "編輯距離": candidate["distance"], "語料出現次數（CF）": candidate["cf"]}
                    for change in suggestion["changes"] for candidate in change.get("candidates", [])
                ]
                st.dataframe(pd.DataFrame(rows), hide_index=True)
                st.caption("依編輯距離、語料詞頻排序。未知生醫詞不一定拼錯，可保留原詞搜尋。")
        elif suggestion.get("unresolved_terms"):
            st.caption("目前沒有合適的拼字候選，可以保留原詞搜尋。")


def show_detail(doc_id: str, terms: list[str], *, stemming: bool = False,
                locations: dict[str, list[tuple[int, int]]] | None = None, relevance: bool = False,
                query: str | None = None) -> None:
    document = documents[doc_id]
    abstract_only = document.content_scope == "abstract"
    hits = locations if locations is not None else hit_locations(
        index, doc_id, terms, stemming=stemming, relevance=relevance, query=query, document=document)
    st.caption(f"{document.pmcid} · {document.year or '年份未標示'} · {document.language}")
    title_hits = [span for block in document.blocks if block.kind == "title" for span in hits.get(block.id, [])]
    st.markdown("<h3>" + highlight(document.title, title_hits) + "</h3>", unsafe_allow_html=True)
    cols = st.columns(4)
    for column, label, key in zip(cols, ["字元數（含空白）", "字元數（不含空白）", "單字數", "句子數"],
                                  ["characters", "characters_no_whitespace", "words", "sentences"]):
        column.metric(label, f"{document.statistics[key]:,}")
    st.caption("讀取範圍：摘要正文。搜尋與統計不含文章標題及摘要小標題，小標題僅供閱讀導覽。單字數以空白分隔計數。" if abstract_only else
               "讀取範圍：全文。搜尋、字元與單字包含標題、摘要、正文與圖表文字。")
    st.caption("句子只計敘述文字，不含標題與表格儲存格。")
    content, sentences, metadata = st.tabs(["摘要" if abstract_only else "摘要與全文", "分句與區塊統計", "來源與授權"])
    with content:
        only_hits = st.checkbox("只顯示命中區塊", key=f"hits_{doc_id}", disabled=not bool(terms))
        selected = [b for b in document.blocks if b.kind != "title" and (not only_hits or b.id in hits)]
        sections = list(dict.fromkeys(b.section for b in selected))
        section = st.selectbox("閱讀章節", ["全部章節"] + sections, key=f"section_{doc_id}")
        previous = ""
        paragraphs = []
        for block in selected:
            if section != "全部章節" and block.section != section:
                continue
            if block.section != previous:
                paragraphs.append('<p class="article-section">' + html.escape(block.section) + '</p>')
                previous = block.section
            if block.kind == "heading":
                paragraphs.append('<p class="article-heading">' + html.escape(block.text) + '</p>')
            else:
                paragraphs.append('<div class="passage">' + highlight(block.text, hits.get(block.id, [])) + '</div>')
        if paragraphs:
            st.markdown('<div class="article-text">' + ''.join(paragraphs) + '</div>', unsafe_allow_html=True)
        elif not document.blocks:
            st.info("這篇文章的 XML 未提供摘要。")
    with sentences:
        st.caption("位置為區塊內 Unicode 字元索引，起點含、終點不含；非空尾段以 paragraph_end 計入。")
        narrative = [b for b in document.blocks if b.narrative]
        if narrative:
            block_id = st.selectbox("敘述區塊", [b.id for b in narrative],
                                    format_func=lambda bid: next(f"{b.id} · {b.section} · {b.text[:65]}…" for b in narrative if b.id == bid),
                                    key=f"sentence_block_{doc_id}")
            block = next(b for b in narrative if b.id == block_id)
            for number, sentence in enumerate(split_sentences(block.text), 1):
                st.markdown(f"**{number}.** `{sentence.start}:{sentence.end}` · `{sentence.rule}`")
                st.text(sentence.text)
        st.dataframe(pd.DataFrame(document.statistics["blocks"]).rename(columns={"block_id": "區塊", "kind": "類型", "section": "章節", "characters": "字元", "words": "單字", "sentences": "句子", "narrative": "敘述"}), hide_index=True)
    with metadata:
        if doc_id.startswith("PMC"):
            st.link_button("查看 PMC 原始文章", f"https://pmc.ncbi.nlm.nih.gov/articles/{doc_id}/")
        if document.pmid:
            st.link_button("查看 PubMed 紀錄", f"https://pubmed.ncbi.nlm.nih.gov/{document.pmid}/")
        st.text("授權：" + (document.license or "未提供"))
        if document.license_url.startswith(("https://", "http://")):
            st.link_button("閱讀授權條款", document.license_url)
        st.json({"文章 ID": doc_id, "PMID": document.pmid, "DOI": document.doi,
                 "讀取範圍": "摘要" if abstract_only else "全文",
                 "來源 URL": document.source_url, "取得時間 UTC": document.acquired_at,
                 "原始 XML": document.raw_path, "SHA-256": document.sha256})
        st.caption("參考文獻不納入搜尋及統計；圖片 OCR 與外部補充檔不在處理範圍。")


def ensure_reader_current() -> None:
    # Full runs already scanned and synchronized the files above the navigation.
    # Only an independently rerun fragment needs to repeat that freshness check.
    context = get_script_run_ctx()
    if context is None or not context.fragment_ids_this_run:
        return
    # Switching articles need not rescan/rebuild the corpus. Escalate to a full
    # rerun only when the files or published snapshot have actually changed.
    if raw_signature(DATA_DIR) != observed_raw or file_signature() != loaded_signature:
        st.rerun()


@st.fragment
def browse_articles() -> None:
    ensure_reader_current()
    with st.container(key="article_reader"):
        doc_id = st.selectbox("選擇文章", list(documents),
                              format_func=lambda key: f"{key} · {documents[key].title}", key="article_choice")
        with st.empty().container():
            show_detail(doc_id, [])


@st.fragment
def show_result_articles(response, query: str) -> None:
    ensure_reader_current()
    with st.container(key="article_reader"):
        page_count = math.ceil(len(response.document_ids) / 5)
        page = st.number_input("結果頁碼", min_value=1, max_value=page_count, step=1, key="result_page")
        for doc_id in response.document_ids[(page - 1) * 5:page * 5]:
            document = documents[doc_id]
            with st.container(border=True):
                st.caption(f"{doc_id} · {document.year} · {document.statistics['words']:,} 個單字")
                if response.ranking == "tfidf":
                    st.caption(f"相關性：{response.scores[doc_id]:.0%}")
                st.markdown('<div class="result-title">' + html.escape(document.title) + '</div>', unsafe_allow_html=True)
                for snippet in make_snippets(document, index, response.terms, stemming=response.stemming,
                                             relevance=response.relevance, query=query):
                    st.caption(snippet["section"])
                    st.markdown('<div class="passage">' + snippet["html"] + '</div>', unsafe_allow_html=True)
                if st.button("開啟文章 " + doc_id, key="open_" + doc_id):
                    st.session_state["selected_result"] = doc_id
        selected = st.session_state.get("selected_result")
        with st.empty().container():
            if selected in response.document_ids:
                st.divider()
                st.markdown("### 已開啟的文章")
                show_detail(selected, response.terms, stemming=response.stemming,
                            relevance=response.relevance, query=query)


st.markdown('<div class="eyebrow">IR HW2 · BIOMEDICAL SEARCH & EXPERIMENTS</div>', unsafe_allow_html=True)
st.title("生醫文章搜尋")
st.markdown('<div class="intro">輸入 PMID 讀取摘要，輸入 PMCID 讀取全文。從關鍵字找到文章，再回到原文核對。</div>', unsafe_allow_html=True)
# Stable slots keep notices from shifting the watcher/navigation/page paths.
with st.container(key="sync_status"):
    observed_raw = raw_signature(DATA_DIR)
    try:
        try:
            observed_signature = (str(DATA_DIR.resolve()), observed_raw, file_signature(), PARSER_VERSION, INDEX_VERSION)
            if st.session_state.get("synced_signature") != observed_signature:
                synced = sync_raw_folder(DATA_DIR)
                # Only a successful, stable scan can be reused. Read failures
                # are retried on the next run without freezing an error in cache.
                st.session_state["sync_errors"] = synced.errors
                if not synced.errors:
                    st.session_state["synced_signature"] = (str(DATA_DIR.resolve()), observed_raw, file_signature(), PARSER_VERSION, INDEX_VERSION)
                else:
                    st.session_state.pop("synced_signature", None)
                if synced.rebuilt:
                    st.success(f"已自動更新搜尋索引（新增 {synced.imported} 篇、更新 {synced.updated} 篇、移除 {synced.removed} 篇、重新加入 {synced.restored} 篇）。")
                    st.session_state.pop("result_page", None)
                    st.session_state.pop("selected_result", None)
            if st.session_state.get("sync_errors"):
                st.warning("部分 XML 未能匯入；僅保留有有效 XML 來源的文章供搜尋。")
                with st.expander("查看未匯入的檔案與原因"):
                    for error in st.session_state["sync_errors"]:
                        st.text(error)
        except Timeout:
            st.info("文章正在由另一個程序更新，請稍後重新整理；暫不顯示可能過期的搜尋結果。")
            st.stop()
        loaded_signature = file_signature()
        documents, index = cached_snapshot(str(DATA_DIR), loaded_signature)
    except (StorageError, OSError) as exc:
        st.warning(str(exc))
        st.info("把 XML 放進下方資料夾，系統會自動匯入；PMC XML 讀全文，PubMed XML 讀摘要。")
        st.code(str(DATA_DIR / "raw"), language=None)
        st.stop()

@st.fragment(run_every=3)
def watch_raw_folder():
    # Keep a real element in this otherwise empty timer fragment. Without it,
    # frontend cleanup can prune its slot and the next tick writes to a stale
    # delta path, crashing the entire page after an unrelated navigation.
    st.empty()
    ensure_reader_current()


watch_raw_folder()

if st.session_state.get("view") == "HW2 實驗室":
    st.session_state["view"] = "實驗室"

with st.container(border=True):
    view = st.radio("功能導覽", ["搜尋文章", "文章詳情", "語料概覽", "文章管理", "實驗室"], key="view", horizontal=True)
    st.caption(f"本機文章 {len(documents)} 篇 · 索引詞彙 {len(index['porter_relevance_postings']):,} · 資料已保存，可離線搜尋")
    st.caption("範圍依文章設定：PMID 讀摘要，PMCID 讀全文。搜尋自動忽略常見停用詞，支援連字號及字母與數字交界的詞彙匹配。")
    st.caption("data/raw 自動同步：移入會加入搜尋，移出／刪除會移除；頁面開啟時約每 3 秒檢查，搜尋前也會同步。")

if st.session_state.get("corpus_version") != index["corpus_sha256"]:
    reset_search_page()
    st.session_state["corpus_version"] = index["corpus_sha256"]

# Restore the adopted text on the full run, after the fragment has requested it.
# An interrupted fragment must not consume the widget's pending value update.
if st.session_state.pop("search_results_pending", False):
    st.session_state["query"] = st.session_state["active_search"]

# Replace the complete view before rendering a different page or a shorter result.
page = st.empty()
with page.container(key="page_content"):
    if view == "實驗室":
        from ir_hw2.ui import show_lab
        show_lab(DATA_DIR)
        st.stop()
    if view == "文章管理":
        show_management(DATA_DIR, documents)
        st.stop()
    if not documents:
        st.warning("尚無文章，請到「文章管理」上傳 XML 或輸入 PMID／PMCID 取得文章。")
        st.stop()

    if view == "搜尋文章":
        # Streamlit removes widget state while another view is displayed.
        for key, value in st.session_state.get("search_controls", {}).items():
            if key == "query" and key not in st.session_state:
                st.session_state[key] = value
        st.session_state.pop("mode", None)
        if "stemming" in st.session_state or "stemming" in st.session_state.get("search_controls", {}):
            reset_search_page()
        st.session_state.pop("stemming", None)
        st.caption("搜尋會自動合併部分英文詞形，例如 therapy／therapies；原文與字數統計保持原樣。")
        from ir_hw2.analysis import baseline_tokenizer_spec
        from ir_hw2.spelling import SPELLING_INDEX_VERSION, SPELLING_VERSION
        token_contract = (SPELLING_VERSION, SPELLING_INDEX_VERSION,
                          json.dumps(baseline_tokenizer_spec(), sort_keys=True))
        # Warm once on opening Search, before the first live input event.
        prepared_spelling = spelling_index(index["corpus_sha256"], token_contract, documents)
        show_search_controls(index["corpus_sha256"], token_contract, prepared_spelling)
        if "active_search" not in st.session_state:
            st.info("輸入一個或多個英文關鍵字，開始搜尋本機文章。")
            st.markdown("**你可以在這裡核對**：命中片段、讀取範圍內的字元與單字數，以及規則判斷的句界。")
        else:
            active_query = st.session_state["active_search"]
            # Migrate a session opened before the matching-mode selector was removed.
            if isinstance(active_query, (tuple, list)):
                active_query = active_query[0]
                st.session_state["active_search"] = active_query
            if adopted := st.session_state.get("adopted_spelling"):
                st.caption(f"原查詢：{adopted[0]} → 已由你選用：{adopted[1]}")
            st.caption("目前搜尋結果：" + active_query)
            try:
                response = search(index, active_query, "RELEVANCE", stemming=True, documents=documents)
            except ValueError as exc:
                st.warning(str(exc))
                st.stop()
            if response.warning:
                st.warning(response.warning)
            if not response.terms:
                st.info(response.query_message)
            else:
                a, b = st.columns(2)
                a.metric("符合文章", len(response.document_ids))
                b.metric("搜尋耗時", f"{response.elapsed_ms:.2f} ms")
                st.caption("有效關鍵字：" + " · ".join(response.terms) + "　｜　相關性排序（由高到低）")
                st.caption("相關性介於 0%–100%，越高表示文章的詞彙越接近查詢；不是正確率。同分依文章編號排列。")
                if response.missing_terms:
                    st.warning("語料中沒有的詞：" + "、".join(response.missing_terms))
                if not response.document_ids:
                    st.info("找不到相關文章，請嘗試其他主題關鍵字。")
                else:
                    show_result_articles(response, active_query)
    elif view == "文章詳情":
        browse_articles()
    else:
        st.subheader("語料概覽")
        a, b, c = st.columns(3)
        a.metric("本機文章", len(documents))
        b.metric("總單字數", f"{sum(d.statistics['words'] for d in documents.values()):,}")
        c.metric("總句子數", f"{sum(d.statistics['sentences'] for d in documents.values()):,}")
        st.caption("固定本機快照；載入時間不包含在搜尋耗時。搜尋、原文及統計僅使用本機檔案。")
        rows = [{"PMCID": d.pmcid, "標題": d.title, "年份": d.year, "字元": d.statistics["characters"],
                 "單字": d.statistics["words"], "句子": d.statistics["sentences"], "授權": d.license_url,
                 "取得時間": d.acquired_at} for d in documents.values()]
        st.dataframe(pd.DataFrame(rows), hide_index=True)
        st.markdown("#### 匯入紀錄")
        try:
            records = read_manifest(DATA_DIR)
            latest = {}
            for record in records:
                latest[record.get("pmcid") or record.get("source_url")] = record
            successful = sum(r["status"] in {"imported", "updated", "duplicate", "restored", "source_restored"} for r in latest.values())
            failed = sum(r["status"] in {"failed", "download_failed", "deleted"} for r in latest.values())
            removed = sum(r["status"] in {"user_deleted", "skipped_deleted", "source_removed"} for r in latest.values())
            purged = sum(r["status"] == "purged" for r in latest.values())
            st.caption(f"各來源最新狀態：成功／重複 {successful} 筆，失敗／排除 {failed} 筆，已移至回收筒 {removed} 筆，永久刪除 {purged} 筆。歷次事件共 {len(records)} 筆。")
            st.dataframe(pd.DataFrame(records), hide_index=True)
        except StorageError as exc:
            st.warning(str(exc))
        with st.expander("統計定義與限制"):
            st.write("字元以 Unicode code point 計數，區塊內空白壓成一格，區塊間加入一個換行。摘要單字以空白分隔計數，IgG/IgM 算一詞，獨立符號也算一個單位。全文單字維持 Unicode 分詞規則。")
            st.write("句子以 . ? ! 與段落結尾判定，保護小數、URL、DOI、姓名首字母與常見縮寫。縮寫句尾具有歧義，規則法可能誤判。")
            st.write("參考文獻、其他 back matter、圖片內文字與外部補充檔不在搜尋範圍。未加入語意或同義詞搜尋。")
