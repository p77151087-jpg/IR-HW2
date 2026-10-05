"""Historical verifier for the v2 log10 migration (before HW1 tokenizer reuse).

Prerequisites: run analyze twice (second output: tmp/hw2-log10-reproduce),
then pytest with --junitxml=reports/hw2/pytest-log10.xml. Never downloads,
rebuilds the search index, trains a model, or rewrites the experiment itself.
"""
import csv
import hashlib
import json
import math
import re
import socket
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def main():
    def blocked(*args, **kwargs):
        raise AssertionError("Verification must remain offline")
    socket.socket.connect = socket.socket.connect_ex = blocked
    folder = ROOT / "reports/hw2/experiment"
    archive = ROOT / "reports/hw2/history/natural-log-20260929"
    summary = read_json(folder / "summary.json")
    if summary["metadata"].get("pipeline_version") != "hw2-abstract-cumulative-v2-log10":
        raise SystemExit("此為 v2 log10 遷移的歷史驗證器；目前切詞版本請執行 scripts/verify_hw2_tokenizer.py。歷史數值見 reports/hw2/history/unicode-split-log10-20260930/。")
    old = read_json(archive / "experiment/summary.json")
    assert summary["metadata"]["log_base"] == 10
    assert summary["metadata"]["analysis_code_sha256"] == digest(ROOT / "ir_hw2/analysis.py")
    for key in ("corpus_sha256", "source_text_sha256", "pmids", "conditions", "stopwords", "stemming"):
        assert summary["metadata"][key] == old["metadata"][key], key
    files = []
    for path in sorted(folder.iterdir()):
        other = ROOT / "tmp/hw2-log10-reproduce" / path.name
        assert path.read_bytes() == other.read_bytes(), path.name
        files.append({"file": path.name, "sha256": digest(path), "bytes": path.stat().st_size,
                      "repeated_sha256": digest(other), "identical": True})
    assert len(files) == 21
    invariants, fits, idf_count = {}, [], 0
    report = (ROOT / "reports/hw2/HW2_REPORT.md").read_text(encoding="utf-8")
    for c, result in summary["conditions"].items():
        previous = old["conditions"][c]
        for key in ("documents", "tokens", "unique_terms", "average_tokens_per_document", "cf", "df", "per_document"):
            assert result[key] == previous[key], (c, key)
        n = result["documents"]
        checks = {"N_is_1000": n == 1000, "sum_cf_equals_tokens": sum(result["cf"].values()) == result["tokens"],
                  "cf_ge_df_and_df_le_N": all(1 <= df <= min(n, result["cf"][t]) for t, df in result["df"].items()),
                  "vocabulary_matches": len(result["cf"]) == result["unique_terms"],
                  "postings_sum": sum(result["df"].values()) == result["postings_entries"],
                  "document_token_sum": sum(row["tokens"] for row in result["per_document"]) == result["tokens"],
                  "rank_segments_partition": sum(f["points"] for f in result["segments"].values()) == result["unique_terms"]}
        assert all(checks.values())
        invariants[c] = checks
        with (folder / f"terms_{c}.csv").open(encoding="utf-8-sig", newline="") as stream:
            for row in csv.DictReader(stream):
                assert math.isclose(float(row["idf"]), math.log10(n / int(row["df"])), abs_tol=1e-14)
                idf_count += 1
        for segment, fit in {"full": result["regression"], **result["segments"]}.items():
            prev = previous["regression"] if segment == "full" else previous["segments"][segment]
            assert fit["log_base"] == 10 and fit["rmse_space"] == "log10(CF)"
            for key in ("slope", "zipf_exponent", "r_squared"):
                assert math.isclose(fit[key], prev[key], abs_tol=1e-12), (c, segment, key)
            for key in ("intercept", "rmse"):
                assert math.isclose(fit[key], prev[key] / math.log(10), abs_tol=1e-12), (c, segment, key)
            label = {"full": "全部", "head": "高頻", "middle": "中頻", "tail": "低頻"}[segment]
            line = next(line for line in report.splitlines() if line.startswith(f"| {c} {label} |"))
            cells = [cell.strip() for cell in line.strip("|").split("|")]
            assert cells[3:] == [f"{fit[key]:.6f}" for key in ("slope", "intercept", "zipf_exponent", "r_squared", "rmse")]
            fits.append({"condition": c, "segment": segment, "base_conversion_verified": True, "report_matches": True})
    for row in summary["selected_terms"]:
        assert f"| {row['term']} | {row['cf']} | {row['df']} | {row['idf']:.6f} |" in report
    english = report.split("<!-- IR_ENGLISH_START -->")[1].split("<!-- IR_ENGLISH_END -->")[0].strip()
    words = len(english.split())
    assert 300 <= words <= 500
    junit = ROOT / "reports/hw2/pytest-log10.xml"
    suites = ET.parse(junit).getroot()
    tests = list(suites.iter("testcase"))
    assert tests and all(not any(case.find(tag) is not None for tag in ("failure", "error", "skipped")) for case in tests)
    initial = read_json(archive / "validation_summary.json")
    original = initial["original_test_files"]
    assert all(digest(ROOT / row["path"]) == row["sha256"] for row in original)
    old_classes = {row["path"].removesuffix(".py").replace("/", ".") for row in original}
    old_count = sum(case.get("classname") in old_classes for case in tests)
    pytest_log = (ROOT / "reports/hw2/pytest-log10.log").read_text(encoding="utf-8-sig")
    match = re.search(r"(\d+) passed in ([\d.]+)s", pytest_log)
    assert match and int(match[1]) == len(tests)
    from ir_hw2.cli import DEFAULT_MODEL, DEFAULT_SNAPSHOT, snapshot_hash
    from ir_hw2.corpus import load_corpus
    from ir_hw2.embeddings import load_word2vec, neighbors
    documents = load_corpus(DEFAULT_SNAPSHOT)
    assert len(documents) == 1000 and snapshot_hash(DEFAULT_SNAPSHOT) == summary["metadata"]["corpus_sha256"]
    model, model_meta = load_word2vec(DEFAULT_MODEL, snapshot_hash(DEFAULT_SNAPSHOT))
    assert neighbors(model, "zzzznotincorpus")["status"] == "oov"
    result = {"recorded_at_utc": datetime.now(timezone.utc).isoformat(), "log_base": 10,
              "command": ".venv-hw2/Scripts/python.exe -X utf8 scripts/verify_hw2_log10.py",
              "pipeline_version": summary["metadata"]["pipeline_version"], "network_blocked": True,
              "previous_ln_archive": str(archive.relative_to(ROOT)), "files": files,
              "all_21_outputs_identical": True, "invariants": invariants, "all_invariants_passed": True,
              "unchanged_corpus_and_tokenization": True, "regressions": fits, "idf_values_verified": idf_count,
              "selected_idf_report_rows_verified": len(summary["selected_terms"]),
              "english_discussion": {"word_count": words, "sha256": hashlib.sha256(english.encode()).hexdigest(), "meets_300_500": True},
              "tests": {"passed": len(tests), "old_passed": old_count, "hw2_passed": len(tests) - old_count,
                        "failures": 0, "errors": 0, "skipped": 0, "seconds": float(match[2]),
                        "original_18_assertion_files_unchanged": True, "junit_sha256": digest(junit)},
              "word2vec_reload": "passed without retraining", "word2vec_vectors_sha256": model_meta["vectors_sha256"],
              "report_sha256": digest(ROOT / "reports/hw2/HW2_REPORT.md"),
              "visual_qa_record": "reports/hw2/log10_visual_qa.json", "pdf_qa_record": "reports/hw2/pdf_qa.json"}
    for filename in ("log10_verification.json", "analysis_verification.json"):
        (ROOT / "reports/hw2" / filename).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"outputs": len(files), "idf_values": idf_count, "regressions": len(fits),
                      "words": words, "tests": result["tests"], "word2vec_reload": result["word2vec_reload"]}, indent=2))


if __name__ == "__main__":
    main()
