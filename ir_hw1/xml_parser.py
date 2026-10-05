"""Safe JATS parsing, independent of namespace prefixes and OAI wrappers."""
import re
from xml.etree.ElementTree import Element

from defusedxml import ElementTree as SafeET

from .models import Document, TextBlock
from .statistics import compute_statistics

MAX_XML_BYTES = 25 * 1024 * 1024
PARSER_VERSION = "jats-source-scope-v6"
BLOCK_TAGS = {"p", "title", "article-title", "td", "th", "label", "disp-formula", "preformat"}
CONTAINERS = {"sec", "list", "list-item", "fig", "fig-group", "table-wrap", "table", "caption", "boxed-text", "disp-quote"}
SKIP_TAGS = {"supplementary-material", "inline-supplementary-material", "graphic", "media", "tex-math"}


class ParseError(ValueError):
    pass


def local_name(node: Element) -> str:
    return node.tag.rsplit("}", 1)[-1]


def descendants(node: Element, tag: str) -> list[Element]:
    return [n for n in node.iter() if local_name(n) == tag]


def first(node: Element, tag: str) -> Element | None:
    return next((n for n in node.iter() if local_name(n) == tag), None)


def readable(node: Element | None) -> str:
    if node is None:
        return ""
    def flatten(n: Element) -> str:
        pieces = [n.text or ""]
        for child in n:
            tag = local_name(child)
            if tag not in SKIP_TAGS:
                value = flatten(child)
                separate = tag in {"break", "td", "th", "p", "xref", "ext-link"}
                pieces.append(" " + value + " " if separate else value)
            pieces.append(child.tail or "")
        return "".join(pieces)
    return " ".join(flatten(node).split())


def parse_xml_root(raw: bytes) -> Element:
    if len(raw) > MAX_XML_BYTES:
        raise ParseError("XML 超過 25 MiB 上限")
    try:
        return SafeET.fromstring(raw, forbid_entities=True, forbid_external=True)
    except Exception as exc:
        raise ParseError(f"無法安全解析 XML：{exc}") from exc


def extract_blocks(root: Element, kind: str, section: str, seen: set[str]) -> list[TextBlock]:
    blocks = []

    def add(text: str, block_kind: str, path: str, narrative: bool) -> None:
        text = " ".join(text.split())
        if text:
            blocks.append(TextBlock("", block_kind, path, text, narrative))

    def visit(node: Element, path: str, inherited: str) -> None:
        tag = local_name(node)
        if tag in SKIP_TAGS or tag in {"sub-article", "response"}:
            return
        identity = node.get("id")
        if identity:
            if identity in seen:
                return
            seen.add(identity)
        if tag == "sec":
            heading = next((c for c in node if local_name(c) == "title"), None)
            if heading is not None:
                path = f"{path} / {readable(heading)}"
        if tag == "caption":
            inherited = "caption"
        if tag in {"td", "th"}:
            add(readable(node), "table", path, False)
            return
        is_block = tag in BLOCK_TAGS
        contains_blocks = any(local_name(n) in BLOCK_TAGS | CONTAINERS for n in node.iter() if n is not node)
        if is_block and not contains_blocks:
            block_kind = "heading" if tag in {"title", "label"} else inherited
            add(readable(node), block_kind, path, block_kind not in {"title", "heading", "table"})
            return
        # Flush mixed text around nested structural elements, exactly once.
        pending = [node.text or ""]
        for child in node:
            child_tag = local_name(child)
            if child_tag in BLOCK_TAGS | CONTAINERS or any(local_name(n) in BLOCK_TAGS for n in child.iter()):
                add("".join(pending), inherited, path, inherited not in {"title", "heading", "table"})
                pending = []
                visit(child, path, inherited)
            elif child_tag not in SKIP_TAGS:
                pending.append(readable(child))
            pending.append(child.tail or "")
        add("".join(pending), inherited, path, inherited not in {"title", "heading", "table"})

    visit(root, section, kind)
    return blocks


def parse_article(article: Element, *, content_scope: str = "full") -> Document:
    if content_scope not in {"full", "abstract"}:
        raise ParseError("無效的文章讀取範圍")
    if local_name(article) == "PubmedArticle":
        return parse_pubmed_article(article)
    if local_name(article) != "article":
        raise ParseError("找不到 JATS article")
    front = next((c for c in article if local_name(c) == "front"), None)
    meta = first(front, "article-meta") if front is not None else None
    if meta is None:
        raise ParseError("缺少 article-meta")
    identifiers = {n.get("pub-id-type", ""): readable(n) for n in descendants(meta, "article-id")}
    pmcid = identifiers.get("pmcid", identifiers.get("pmc", "")).upper()
    if pmcid.isdigit():
        pmcid = "PMC" + pmcid
    if not re.fullmatch(r"PMC[1-9]\d*", pmcid):
        raise ParseError("缺少或無效的唯一 PMCID")
    title = readable(first(meta, "article-title"))
    if not title:
        raise ParseError(f"{pmcid} 缺少標題")
    license_node = first(meta, "license")
    license_text = readable(license_node)
    urls = []
    if license_node is not None:
        for element in license_node.iter():
            urls.extend(v for k, v in element.attrib.items() if k.rsplit("}", 1)[-1] == "href")
        urls.extend(re.findall(r"https?://creativecommons.org/[^\s<>]+", license_text))
    license_url = next((u for u in urls if "creativecommons.org/" in u), urls[0] if urls else "")
    seen: set[str] = set()
    blocks = [TextBlock("", "title", "標題", title, False)] if content_scope == "full" else []
    for abstract in [n for n in meta if local_name(n) == "abstract"]:
        abstract_blocks = extract_blocks(abstract, "abstract", "摘要", seen)
        # Section labels remain in block.section for navigation, not searchable text.
        blocks.extend(block for block in abstract_blocks
                      if content_scope == "full" or block.kind == "abstract")
    back_blocks = []
    if content_scope == "full":
        body = next((c for c in article if local_name(c) == "body"), None)
        if body is not None:
            blocks.extend(extract_blocks(body, "body", "正文", seen))
        for floats in [n for n in article if local_name(n) == "floats-group"]:
            blocks.extend(extract_blocks(floats, "body", "圖表", seen))
        back = next((n for n in article if local_name(n) == "back"), None)
        back_blocks = extract_blocks(back, "back", "附錄與參考文獻", set()) if back is not None else []
    for i, block in enumerate(blocks):
        block.id = f"b{i}"
    for i, block in enumerate(back_blocks):
        block.id = f"back{i}"
    pubdate = first(meta, "pub-date")
    document = Document(pmcid, title, blocks, pmid=identifiers.get("pmid", ""), doi=identifiers.get("doi", ""),
                        year=readable(first(pubdate, "year")) if pubdate is not None else "",
                        language=article.get("{http://www.w3.org/XML/1998/namespace}lang", "en"),
                        license=license_text, license_url=license_url,
                        back_blocks=back_blocks, content_scope=content_scope)
    document.statistics = compute_statistics(document)
    return document


def pubmed_identifiers(article: Element) -> tuple[str, str, str]:
    citation = first(article, "MedlineCitation")
    pmid = readable(next((n for n in citation if local_name(n) == "PMID"), None)) if citation is not None else ""
    data = next((n for n in article if local_name(n) == "PubmedData"), None)
    id_list = next((n for n in data if local_name(n) == "ArticleIdList"), None) if data is not None else None
    # References carry their own ArticleIdList; never use their identifiers.
    ids = {n.get("IdType"): readable(n) for n in id_list if local_name(n) == "ArticleId"} if id_list is not None else {}
    pmcid = ids.get("pmc", "").upper()
    if not re.fullmatch(r"PMC[1-9]\d*", pmcid):
        pmcid = ""
    return pmid, pmcid, ids.get("doi", "")


def parse_pubmed_article(article: Element) -> Document:
    pmid, pmcid, doi = pubmed_identifiers(article)
    if not re.fullmatch(r"[1-9]\d*", pmid):
        raise ParseError("缺少或無效的 PMID")
    citation = first(article, "MedlineCitation")
    content = first(citation, "Article")
    if content is None or not (title := readable(first(content, "ArticleTitle"))):
        raise ParseError(f"PMID {pmid} 缺少標題")
    blocks = []
    abstract = first(content, "Abstract")
    if abstract is not None:
        for node in [n for n in abstract if local_name(n) == "AbstractText"]:
            label = node.get("Label", "").strip()
            section = "摘要" + (" / " + label if label else "")
            if text := readable(node):
                blocks.append(TextBlock("", "abstract", section, text))
    for number, block in enumerate(blocks):
        block.id = f"b{number}"
    pubdate = first(content, "PubDate")
    year = readable(first(pubdate, "Year")) if pubdate is not None else ""
    if not year and pubdate is not None:
        match = re.search(r"\b\d{4}\b", readable(first(pubdate, "MedlineDate")))
        year = match.group() if match else ""
    doc = Document(pmcid or "PMID" + pmid, title, blocks, pmid=pmid, doi=doi, year=year,
                   language=readable(first(content, "Language")) or "en",
                   license=readable(first(content, "CopyrightInformation")), content_scope="abstract")
    doc.statistics = compute_statistics(doc)
    return doc


def articles_in_xml(raw: bytes) -> list[Element]:
    root = parse_xml_root(raw)
    errors = descendants(root, "error")
    if errors:
        raise ParseError("PMC API：" + "; ".join(f"{e.get('code')}: {readable(e)}" for e in errors))
    articles = ([root] if local_name(root) in {"article", "PubmedArticle"}
                else descendants(root, "article") + descendants(root, "PubmedArticle"))
    if not articles:
        deleted = any(n.get("status") == "deleted" for n in descendants(root, "header"))
        raise ParseError("紀錄已刪除" if deleted else "XML 內沒有 JATS article")
    return articles
