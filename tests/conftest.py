from pathlib import Path
import hashlib
import json
import subprocess
import asyncio
import socket
import sys
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from ir_hw1.index import build_index, save_index
import shutil
from ir_hw1.corpus import import_folder
from ir_hw1.storage import load_documents
from ir_hw1.xml_parser import articles_in_xml, parse_article


@pytest.fixture(autouse=True)
def windows_apptest_event_loop(monkeypatch):
    """Keep offline guards strict while AppTest creates its Windows self-pipe.

    Streamlit 1.64 creates a new asyncio loop before each test run. On Windows,
    Python implements its self-pipe with a loopback socket pair. Only that
    framework initialization may connect; restore the test's socket guard
    before any application code runs. No HW1 assertions or tests are changed.
    """
    if sys.platform != "win32":
        return
    from streamlit.testing.v1 import local_script_runner
    connect = socket.socket.connect

    def loopback_connect(sock, address):
        if not isinstance(address, tuple) or address[0] not in {"127.0.0.1", "::1"}:
            raise AssertionError("AppTest event-loop setup permits only a local self-pipe")
        return connect(sock, address)

    def new_event_loop():
        with patch.object(socket.socket, "connect", loopback_connect):
            return asyncio.new_event_loop()

    # Patch the testing adapter only, not the app's asyncio or socket APIs.
    monkeypatch.setattr(local_script_runner, "asyncio", SimpleNamespace(new_event_loop=new_event_loop))


@pytest.fixture
def synthetic():
    raw = (Path(__file__).parent / "fixtures/synthetic.xml").read_bytes()
    docs = {d.pmcid: d for d in map(parse_article, articles_in_xml(raw))}
    return docs, build_index(docs)


@pytest.fixture
def stored(tmp_path, synthetic):
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "synthetic.xml").write_bytes((Path(__file__).parent / "fixtures/synthetic.xml").read_bytes())
    import_folder(raw, tmp_path)
    save_index(tmp_path, build_index(load_documents(tmp_path)))
    return tmp_path


@pytest.fixture(scope="session")
def real_corpus(tmp_path_factory):
    """Fixed real corpus in a test copy; never read/write the user's live snapshots."""
    root = Path(__file__).resolve().parents[1]
    target = tmp_path_factory.mktemp("fixed-real-corpus")
    (target / "raw").mkdir()
    ids = (root / "resources/demo_pmcids.txt").read_text().split()
    portable = root / "tests/fixtures/hw1-real"
    manifest_path = portable / "manifest.json"
    expected = {
        item["path"]: item["sha256"]
        for item in json.loads(manifest_path.read_text(encoding="utf-8"))["files"]
    } if manifest_path.exists() else {}
    for pmcid in ids:
        source = root / "data/raw" / f"{pmcid}.xml"
        destination = target / "raw" / source.name
        fixed_source = portable / source.name
        if fixed_source.exists():
            # Exact bytes exported from the original HW1 commit, with provenance.
            # Keep regression tests independent of local library edits/Git history.
            raw = fixed_source.read_bytes()
            assert hashlib.sha256(raw).hexdigest() == expected[source.name], source.name
            destination.write_bytes(raw)
        elif source.exists():
            shutil.copyfile(source, destination)
        else:
            # The personal library may have been purged. Read the committed demo
            # into this test-only directory; never restore the user's raw folder.
            result = subprocess.run(
                ["git", "show", f"ad8bf2b:data/raw/{pmcid}.xml"], cwd=root,
                capture_output=True, check=True,
            )
            destination.write_bytes(result.stdout)
    import_folder(target / "raw", target)
    save_index(target, build_index(load_documents(target)))
    return target
