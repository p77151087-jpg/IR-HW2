"""Streamlit article management; storage and network logic live in library.py."""
import hashlib
import os
from pathlib import Path

import pandas as pd
import streamlit as st
from filelock import Timeout

from .library import delete_articles, download_pmid, download_pmids, restore_articles, upload_xml
from .pmid_list import parse_pmid_list
from .purge import purge_articles
from .storage import load_deleted

STATUS_LABELS = {"imported": "已加入", "updated": "已更新", "duplicate": "已存在",
                 "failed": "匯入失敗", "download_failed": "下載失敗", "skipped_deleted": "已在回收筒"}


def finish_action(message: str, records: list[dict] | None = None) -> None:
    st.session_state["library_notice"] = message
    st.session_state["library_results"] = records or []
    st.session_state["result_page"] = 1
    st.session_state.pop("selected_result", None)
    st.session_state["library_generation"] = st.session_state.get("library_generation", 0) + 1
    st.rerun()


def article_selection(rows: list[dict], prefix: str, generation: int) -> list[str]:
    """A shared selection for batch actions, stable across filters and table sorting."""
    query = st.text_input("篩選文章（文章 ID 或標題）", key=f"{prefix}_filter").strip().casefold()
    visible = [r for r in rows if query in (r["PMCID"] + " " + r["標題"]).casefold()]
    visible_ids = {r["PMCID"] for r in visible}
    selection_key = f"{prefix}_selected_{generation}"
    revision_key = f"{prefix}_revision_{generation}"
    selected = set(st.session_state.get(selection_key, [])) & {r["PMCID"] for r in rows}
    left, right = st.columns(2)
    if left.button("全選目前列表", key=f"{prefix}_all", disabled=not visible):
        selected.update(visible_ids)
        st.session_state[revision_key] = st.session_state.get(revision_key, 0) + 1
    if right.button("清除全部選取", key=f"{prefix}_clear", disabled=not rows):
        selected.clear()
        st.session_state[revision_key] = st.session_state.get(revision_key, 0) + 1
    if visible:
        frame = pd.DataFrame([{"選取": r["PMCID"] in selected, **r} for r in visible])
        scope = hashlib.sha256("|".join(r["PMCID"] for r in visible).encode()).hexdigest()[:12]
        edited = st.data_editor(frame, hide_index=True, disabled=[c for c in frame.columns if c != "選取"],
                                key=f"{prefix}_table_{generation}_{st.session_state.get(revision_key, 0)}_{scope}",
                                height=min(420, 38 + 35 * len(visible)),
                                column_config={"選取": st.column_config.CheckboxColumn("選取", width="small"),
                                               "PMCID": st.column_config.TextColumn("文章 ID")})
        selected = (selected - visible_ids) | set(edited.loc[edited["選取"], "PMCID"])
    else:
        st.info("目前沒有符合篩選條件的文章。")
    st.session_state[selection_key] = sorted(selected)
    st.caption(f"已選 {len(selected)} 篇／共 {len(rows)} 篇；目前列表 {len(visible)} 篇。篩選不會清除先前選取。")
    return sorted(selected)


def show_management(data_dir: Path, documents: dict) -> None:
    st.subheader("文章管理")
    offline_demo = os.environ.get("IR_HW1_OFFLINE_DEMO") == "1"
    if offline_demo:
        st.warning("目前是離線展示模式，已停用網路下載。請關閉離線展示程序，再以 scripts/start_demo.ps1 啟動一般模式。搜尋及本機管理仍可使用。")
    st.caption("加入或刪除後立即更新搜尋；上傳及本機管理可離線使用，新文章下載需要網路。")
    # Keep success/error feedback in one slot; tabs must not move between reruns.
    with st.container(key="management_feedback"):
        if notice := st.session_state.pop("library_notice", None):
            st.success(notice)
        if records := st.session_state.get("library_results"):
            st.dataframe(pd.DataFrame([{"文章": r.get("pmcid") or r.get("pmid") or r.get("filename", ""),
                                        "結果": STATUS_LABELS.get(r["status"], r["status"]),
                                        "說明": r.get("reason", "")} for r in records]), hide_index=True)
            if any(r["status"] in {"failed", "download_failed"} for r in records):
                st.warning("部分文章未能加入，請查看上方原因。")

    upload_tab, pmid_tab, delete_tab = st.tabs(["上傳 XML", "PMID／PMCID 下載", "刪除與還原"],
                                             key="management_tab", on_change="rerun")
    generation = st.session_state.get("library_generation", 0)
    try:
        with upload_tab:
            st.write("選擇 XML：PMC XML 讀全文，PubMed XML 讀摘要。可一次選多個檔案，每個檔案上限 25 MiB。")
            with st.form("upload_xml_form"):
                files = st.file_uploader("選擇 XML 檔案", type=["xml"], accept_multiple_files=True,
                                         max_upload_size=25, key=f"xml_upload_{generation}")
                submitted = st.form_submit_button("上傳並加入搜尋", key="import_xml", type="primary")
            if submitted:
                if not files:
                    st.warning("請先選擇 XML 檔案。")
                else:
                    results = []
                    with st.spinner("正在匯入文章並更新索引…"):
                        for file in files:
                            try:
                                results.extend(upload_xml(data_dir, file.name, file.getvalue()))
                            except ValueError as exc:
                                results.append({"filename": file.name, "status": "failed", "reason": str(exc)})
                    count = sum(r["status"] in {"imported", "updated"} for r in results)
                    finish_action(f"上傳處理完成，新增／更新 {count} 篇。可切換到「搜尋文章」查詢。", results)
        with pmid_tab:
            st.write("輸入 PMID（例如 23193287）讀取摘要；輸入 PMCID（例如 PMC3531190）讀取全文。")
            st.caption("摘要由 PubMed 提供；全文需有可取得的 PMC XML 與可辨識的 Creative Commons 授權。自動下載限定英文文章。")
            with st.form("pmid_download_form"):
                pmid = st.text_input("PMID 或 PMCID", placeholder="例如：23193287 或 PMC3531190", key="download_pmid", max_chars=40)
                requested = st.form_submit_button("下載並加入搜尋", key="fetch_pmid", type="primary", disabled=offline_demo)
            if requested:
                with st.spinner("正在取得文章並更新索引…"):
                    records = download_pmid(data_dir, pmid)
                finish_action("文章查詢完成，結果如下。", records)
            st.markdown("**從 TXT 批次下載 PMID 摘要**")
            st.caption("上傳每行一個 PMID 的 .txt 清單，先預覽再下載。每次最多 100 個不同 PMID、檔案上限 1 MiB；空行與重複項目會略過。")
            st.caption("每個 PMID 讀取摘要正文；已存全文的同篇文章也會切換為摘要範圍。成功的文章立即保存，失敗項目會列出原因，可重新上傳清單重試。")
            st.caption("每 20 個 PMID 合併下載，完成後統一更新索引；連線持續失敗時停止後續批次。")
            pmid_file = st.file_uploader("選擇 PMID 清單 TXT", type=["txt"], max_upload_size=1,
                                         key=f"pmid_list_upload_{generation}")
            pmid_list = None
            if pmid_file is not None:
                try:
                    pmid_list = parse_pmid_list(pmid_file.getvalue())
                except ValueError as exc:
                    st.warning(str(exc))
                else:
                    st.caption(f"共 {len(pmid_list.pmids)} 個不同 PMID；已略過 {pmid_list.duplicates} 個重複項目。")
                    with st.expander("預覽 PMID 清單"):
                        st.dataframe(pd.DataFrame({"PMID": pmid_list.pmids}), hide_index=True)
            if st.button("批次下載並加入搜尋", key="fetch_pmid_list", disabled=pmid_list is None or offline_demo):
                if pmid_list is not None:
                    progress = st.progress(0, text="準備下載 PMID 清單…")
                    def update_progress(done: int, total: int, pmid: str) -> None:
                        progress.progress(done / total, text=f"已處理 {done}/{total} 篇 · 正在處理 PMID {pmid}")
                    records = download_pmids(data_dir, pmid_list.pmids, progress=update_progress)
                    count = sum(r["status"] in {"imported", "updated"} for r in records)
                    existing = sum(r["status"] == "duplicate" for r in records)
                    failed = len(records) - count - existing
                    finish_action(f"清單處理完成：新增／更新 {count} 篇、已存在 {existing} 篇、失敗 {failed} 篇。", records)
        with delete_tab:
            st.write("刪除後文章會移到回收筒，不再出現在搜尋結果；重新整理或重啟也不會自動加回。")
            st.markdown("**本機文章：批次移至回收筒**")
            selected = article_selection([{"PMCID": k, "標題": d.title} for k, d in documents.items()], "active", generation)
            remove = st.button(f"移至回收筒（{len(selected)} 篇）", key="delete_articles", disabled=not selected)
            if remove:
                if not selected:
                    st.warning("請先選擇要刪除的文章。")
                else:
                    count = delete_articles(data_dir, selected)
                    finish_action(f"已刪除 {count} 篇文章，搜尋索引已更新；可在下方回收筒還原。")
            deleted = load_deleted(data_dir)
            with st.expander(f"回收筒（{len(deleted)} 篇）", expanded=True):
                st.caption("勾選一次即可批次還原或永久刪除；全選可一次處理整個回收筒。原始 XML 移出者須先放回。")
                trash_ids = article_selection([{"PMCID": k, "標題": e["document"]["title"],
                                                "移除原因": "XML 移出／失效" if e.get("reason") == "source_missing" else "手動移至回收筒"}
                                               for k, e in deleted.items()], "trash", generation)
                restore = st.button(f"還原選取文章（{len(trash_ids)} 篇）", key="restore_articles", disabled=not trash_ids)
                if restore:
                    count = restore_articles(data_dir, trash_ids)
                    finish_action(f"已還原 {count} 篇文章，可以重新搜尋。")
                st.markdown("**永久刪除**")
                st.caption("會刪除選定文章的備份及原始全文，無法從回收筒還原。共用 XML 中的其他文章會保留。")
                selected_token = hashlib.sha256("|".join(trash_ids).encode()).hexdigest()[:12]
                confirmed = st.checkbox("我了解永久刪除後無法還原", key=f"confirm_purge_{generation}_{selected_token}")
                purge = st.button(f"永久刪除選取文章（{len(trash_ids)} 篇）", key="purge_articles", disabled=not trash_ids)
                if purge:
                    if not confirmed:
                        st.warning("請勾選確認永久刪除後無法還原。")
                    else:
                        count = purge_articles(data_dir, trash_ids)
                        finish_action(f"已永久刪除 {count} 篇文章，原始全文、備份與索引已清理。")
    except Timeout:
        st.warning("其他程序正在更新文章或下載，請稍後再試。")
    except (ValueError, OSError) as exc:
        st.error(str(exc))
