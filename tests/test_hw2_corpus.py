import json

import pytest
import requests

from ir_hw2 import corpus


def article(pmid, language="eng", body="Alpha beta.", title="TITLE NOT ANALYSIS", label="LABEL NOT ANALYSIS"):
    return (f'<PubmedArticle><MedlineCitation><PMID>{pmid}</PMID><Article>'
            f'<ArticleTitle>{title}</ArticleTitle><Language>{language}</Language>'
            f'<Abstract><AbstractText Label="{label}">{body}</AbstractText></Abstract>'
            '<Journal><JournalIssue><PubDate><Year>2026</Year></PubDate></JournalIssue></Journal>'
            '</Article></MedlineCitation></PubmedArticle>')


class FakeClient:
    def __init__(self, ids, overrides=None, fail_batch=None):
        self.ids = ids
        self.overrides = overrides or {}
        self.calls = []
        self.fail_batch = fail_batch

    def get(self, endpoint, params):
        self.calls.append((endpoint, params))
        if "esearch" in endpoint:
            return json.dumps({"esearchresult": {"count": "9999", "idlist": self.ids,
                                                "querytranslation": "TEST QUERY"}}).encode()
        pmids = params["id"].split(",")
        if self.fail_batch == pmids[0]:
            raise requests.Timeout("fixture timeout")
        return ("<PubmedArticleSet>" + "".join(self.overrides.get(pmid, article(pmid)) for pmid in pmids)
                + "</PubmedArticleSet>").encode()


def test_body_only_language_nonempty_and_count_accounting(tmp_path, monkeypatch):
    client = FakeClient(["1", "2", "3", "4", "5"], {"1": article("1", "fra"), "2": article("2", body="")})
    monkeypatch.setattr(corpus, "NCBIClient", lambda: client)
    manifest = corpus.fetch_corpus(tmp_path / "snapshot", count=2)
    docs = corpus.load_corpus(tmp_path / "snapshot")
    assert list(docs) == ["3", "4"]
    assert [block.text for block in docs["3"].blocks] == ["Alpha beta."]
    assert all(block.kind == "abstract" for doc in docs.values() for block in doc.blocks)
    assert "TITLE" not in " ".join(block.text for block in docs["3"].blocks)
    assert "LABEL" not in " ".join(block.text for block in docs["3"].blocks)
    assert manifest["counts"] | {} == {"matched": 9999, "candidates": 5, "fetched": 5, "selected": 2,
                                      "excluded": 2, "not_needed": 1, "not_fetched": 0,
                                      "eligible_not_selected": 1, "duplicate_candidate_ids": 0,
                                      "duplicate_returned_records": 0}
    assert docs["3"].raw_path.startswith("raw-batches/efetch-")
    assert len(manifest["raw_files"]) == 2


def test_completed_snapshot_offline_idempotent_and_immutable(tmp_path, monkeypatch):
    client = FakeClient(["1"])
    monkeypatch.setattr(corpus, "NCBIClient", lambda: client)
    root = tmp_path / "snapshot"
    first = corpus.fetch_corpus(root, count=1)
    call_count = len(client.calls)
    assert corpus.fetch_corpus(root, count=1) == first
    assert len(client.calls) == call_count
    with pytest.raises(corpus.CorpusError, match="不可變更"):
        corpus.fetch_corpus(root, count=2)
    with pytest.raises(corpus.CorpusError, match="不可變更"):
        corpus.fetch_corpus(root, count=1, query="different")


def test_failed_download_resumes_without_refetching_first_batch(tmp_path, monkeypatch):
    ids = [str(n) for n in range(1, 106)]
    client = FakeClient(ids, fail_batch="101")
    monkeypatch.setattr(corpus, "NCBIClient", lambda: client)
    root = tmp_path / "snapshot"
    with pytest.raises(requests.Timeout):
        corpus.fetch_corpus(root, count=105)
    assert not (root / "snapshot.json").exists()
    assert json.loads((root / "acquisition.json").read_text())["status"] == "incomplete"
    client.fail_batch = None
    client.calls.clear()
    result = corpus.fetch_corpus(root, count=105)
    assert result["counts"]["selected"] == 105
    assert len(client.calls) == 1
    assert client.calls[0][1]["id"].startswith("101,")
    assert max(len(meta["params"]["id"].split(",")) for meta in result["raw_files"] if "id" in meta["params"]) == 100


@pytest.mark.parametrize("tamper", ["abstracts.jsonl", "selection.json", "raw"])
def test_hash_tampering_rejected(tmp_path, monkeypatch, tamper):
    monkeypatch.setattr(corpus, "NCBIClient", lambda: FakeClient(["1"]))
    root = tmp_path / "snapshot"
    manifest = corpus.fetch_corpus(root, count=1)
    target = root / (manifest["raw_files"][0]["file"] if tamper == "raw" else tamper)
    target.write_bytes(target.read_bytes() + b" ")
    with pytest.raises(corpus.CorpusError, match="雜湊"):
        corpus.load_corpus(root)


def test_interrupted_cache_corruption_is_not_silently_overwritten(tmp_path, monkeypatch):
    client = FakeClient([str(n) for n in range(1, 102)], fail_batch="101")
    monkeypatch.setattr(corpus, "NCBIClient", lambda: client)
    root = tmp_path / "snapshot"
    with pytest.raises(requests.Timeout):
        corpus.fetch_corpus(root, count=101)
    raw = root / "raw-batches/esearch-00000.json"
    raw.write_bytes(b"corrupt")
    with pytest.raises(corpus.CorpusError, match="快取雜湊"):
        corpus.fetch_corpus(root, count=101)
    assert raw.read_bytes() == b"corrupt"


def test_duplicate_candidate_pmids_are_deduplicated(tmp_path, monkeypatch):
    monkeypatch.setattr(corpus, "NCBIClient", lambda: FakeClient(["1", "1", "2"]))
    result = corpus.fetch_corpus(tmp_path / "snapshot", count=2)
    assert result["selected_pmids"] == ["1", "2"]
    assert result["counts"]["duplicate_candidate_ids"] == 1


def test_missing_language_does_not_use_parser_default_english(tmp_path, monkeypatch):
    unknown = article("1").replace("<Language>eng</Language>", "")
    monkeypatch.setattr(corpus, "NCBIClient", lambda: FakeClient(["1", "2"], {"1": unknown}))
    result = corpus.fetch_corpus(tmp_path / "snapshot", count=1)
    assert result["selected_pmids"] == ["2"]
    assert result["exclusion_reasons"] == {"language_not_confirmed_english": 1}


def test_book_records_are_explicitly_excluded_as_non_article(tmp_path, monkeypatch):
    book = '<PubmedBookArticle><BookDocument><PMID>1</PMID></BookDocument></PubmedBookArticle>'
    monkeypatch.setattr(corpus, "NCBIClient", lambda: FakeClient(["1", "2"], {"1": book}))
    result = corpus.fetch_corpus(tmp_path / "snapshot", count=1)
    assert result["selected_pmids"] == ["2"]
    assert result["exclusion_reasons"] == {"unsupported_book_record": 1}


def test_ambiguous_duplicate_record_is_excluded_not_silently_first_wins(tmp_path, monkeypatch):
    duplicate = article("1", body="First text.") + article("1", body="Different text.")
    monkeypatch.setattr(corpus, "NCBIClient", lambda: FakeClient(["1", "2"], {"1": duplicate}))
    result = corpus.fetch_corpus(tmp_path / "snapshot", count=1)
    assert result["selected_pmids"] == ["2"]
    assert result["exclusion_reasons"] == {"ambiguous_duplicate_record": 1}
    assert result["counts"]["duplicate_returned_records"] == 1


def test_offline_mode_blocks_new_download_but_allows_sealed_snapshot(tmp_path, monkeypatch):
    client = FakeClient(["1"])
    monkeypatch.setattr(corpus, "NCBIClient", lambda: client)
    root = tmp_path / "snapshot"
    corpus.fetch_corpus(root, count=1)
    monkeypatch.setenv("IR_HW1_OFFLINE_DEMO", "1")
    assert corpus.fetch_corpus(root, count=1)["counts"]["selected"] == 1
    with pytest.raises(corpus.CorpusError, match="離線模式"):
        corpus.fetch_corpus(tmp_path / "new", count=1)
    assert len(client.calls) == 2


def test_client_is_closed_on_success_and_failure(tmp_path, monkeypatch):
    client = FakeClient(["1"])
    closed = []
    client.close = lambda: closed.append(True)
    monkeypatch.setattr(corpus, "NCBIClient", lambda: client)
    corpus.fetch_corpus(tmp_path / "good", count=1)
    client.fail_batch = "1"
    with pytest.raises(requests.Timeout):
        corpus.fetch_corpus(tmp_path / "fail", count=1)
    assert closed == [True, True]


def test_no_network_for_invalid_count_or_query(tmp_path):
    for invalid in (0, -1, 10001, 1.5, True):
        with pytest.raises(ValueError):
            corpus.fetch_corpus(tmp_path, count=invalid)
    with pytest.raises(ValueError):
        corpus.fetch_corpus(tmp_path, query=" ")


class Response:
    def __init__(self, status=200, headers=None):
        self.status_code = status
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))

    def iter_content(self, size):
        yield b"test"


class Session:
    def __init__(self, responses):
        self.headers = {}
        self.responses = iter(responses)
        self.calls = 0

    def get(self, *args, **kwargs):
        self.calls += 1
        result = next(self.responses)
        if isinstance(result, Exception):
            raise result
        return result


def test_client_retries_and_rate_limits_429_5xx_timeout():
    waits = []
    session = Session([Response(429), Response(503), Response()])
    client = corpus.NCBIClient(session, waits.append, lambda: 0)
    assert client.get("https://example.test", {}) == b"test"
    assert session.calls == 3
    assert waits == [0.0, 2, 1.0, 4, 1.0]
    session = Session([requests.Timeout(), requests.Timeout(), requests.Timeout()])
    client = corpus.NCBIClient(session, lambda _: None, lambda: 0)
    with pytest.raises(requests.Timeout):
        client.get("https://example.test", {})
    assert session.calls == 3


def test_client_403_is_not_retried_and_long_retry_after_stops():
    session = Session([Response(403)])
    with pytest.raises(requests.HTTPError):
        corpus.NCBIClient(session, lambda _: None).get("https://example.test", {})
    assert session.calls == 1
    session = Session([Response(429, {"Retry-After": "120"})])
    with pytest.raises(corpus.CorpusError, match="等待"):
        corpus.NCBIClient(session, lambda _: None).get("https://example.test", {})


def test_download_lock_rejects_concurrent_downloader(tmp_path):
    with corpus._download_lock(tmp_path / ".lock"):
        with pytest.raises(corpus.CorpusError, match="另一個"):
            with corpus._download_lock(tmp_path / ".lock"):
                pytest.fail("must not obtain second lock")
