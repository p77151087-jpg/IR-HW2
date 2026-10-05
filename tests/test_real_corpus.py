import hashlib
import socket
import subprocess
import sys
from pathlib import Path

from streamlit.testing.v1 import AppTest

from ir_hw1.corpus import reusable_license
from ir_hw1.index import load_snapshot
from ir_hw1.preprocessing import tokenize
from ir_hw1.search import search
from ir_hw1.storage import DEFAULT_DATA, read_manifest

ROOT = Path(__file__).resolve().parents[1]


def test_real_corpus_source_and_body_only(real_corpus):
    documents, index = load_snapshot(real_corpus)
    assert len(documents) == 15
    # Trash and historical versions may retain additional XML files.
    assert len({doc.raw_path for doc in documents.values()}) == 15
    for doc in documents.values():
        assert reusable_license(doc)
        assert doc.sha256 == hashlib.sha256((real_corpus / doc.raw_path).read_bytes()).hexdigest()
        assert doc.content_scope == "full"
        assert any(b.kind == "body" for b in doc.blocks)
        assert any(r.get("pmcid") == doc.pmcid and r["status"] in {"imported", "updated", "duplicate"} for r in read_manifest(real_corpus))
    assert all("therapies" not in {t.term for b in d.blocks if b.kind in {"title", "abstract"} for t in tokenize(b.text)} for d in documents.values())
    assert search(index, "therapies").document_ids == ["PMC7616680"]
    assert search(index, "cancer treatment", "AND").document_ids == ["PMC7617276"]
    assert len(search(index, "cancer treatment", "OR").document_ids) == 13


def test_real_offline_app_and_fresh_process(monkeypatch, real_corpus):
    monkeypatch.setenv("IR_HW1_DATA_DIR", str(real_corpus))
    def block_network(*args, **kwargs):
        raise AssertionError("Offline test forbids outbound socket.connect")
    monkeypatch.setattr(socket.socket, "connect", block_network)
    app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30).run()
    app.text_input(key="query").set_value("tuberculous meningitis")
    app.button[0].click().run()
    app.button(key="open_PMC7616680").click().run()
    assert not app.exception
    assert any(m.label == "單字數" and m.value == "6,069" for m in app.metric)
    assert any(m.label == "句子數" and m.value == "237" for m in app.metric)
    app.radio(key="view").set_value("語料概覽").run()
    assert not app.exception
    # Separate interpreter cannot rely on the AppTest or index object in memory.
    script = "import socket; socket.socket.connect=lambda *a,**k: (_ for _ in ()).throw(RuntimeError('offline')); from ir_hw1.index import load_snapshot; from ir_hw1.search import search; d,i=load_snapshot(); assert search(i,'therapies').document_ids==['PMC7616680']; print(len(d))"
    script = "import sys; from pathlib import Path; " + script.replace("load_snapshot()", "load_snapshot(Path(sys.argv[1]))")
    result = subprocess.run([sys.executable, "-c", script, str(real_corpus)], cwd=ROOT, capture_output=True, text=True, check=True)
    assert result.stdout.strip() == "15"
