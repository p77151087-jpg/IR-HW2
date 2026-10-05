"""Check current report tables, model inputs, tests and exported PDF provenance.

Run after verify_hw2_tokenizer.py, verify_hw2.py, the full JUnit test run and
build_hw2_reports.py. This standard-library verifier does not rerun experiments,
train models, access the network, or replace visual inspection of the PDFs.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports/hw2"
LABELS = ("A", "B", "C", "D")
EXPECTED_PIPELINE = "hw2-hw1-four-conditions-v5-log10"


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def number(cell):
    return float(cell.replace(",", "").replace("`", "").strip())


def numeric(cell):
    try:
        number(cell)
        return True
    except ValueError:
        return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--junit", type=Path, default=REPORTS / "pytest-hw1-tokenizer.xml",
                        help="The completed full-regression JUnit XML; test totals are read from this file.")
    args = parser.parse_args()
    summary = read(REPORTS / "experiment/summary.json")
    proof = read(REPORTS / "tokenizer_verification.json")
    assert proof["passed"] and proof["reproduction"]["all_bytes_identical"]
    assert proof["pipeline_version"] == summary["metadata"]["pipeline_version"] == EXPECTED_PIPELINE
    assert tuple(summary["conditions"]) == LABELS
    assert tuple(proof["conditions"]) == LABELS
    assert summary["metadata"]["primary_comparison"] == proof["primary_comparison"] == list(LABELS)
    assert summary["metadata"]["reference_condition"] is proof["reference_condition"] is None
    assert proof["default_condition"] == "A"
    assert proof["reproduction"]["artifacts_checked"] == len(proof["reproduction"]["artifacts"]) == 21
    assert proof["independent_regression"]["fits_checked"] == 16
    assert proof["selected_terms"]["condition"] == "B"
    assert proof["previous_pipeline_comparison"]["mapping_current_to_previous"] == {label: label for label in LABELS}
    assert all(item["all_condition_data_equal"] for item in proof["previous_pipeline_comparison"]["conditions"].values())
    for row in proof["reproduction"]["artifacts"]:
        assert digest(REPORTS / "experiment" / row["file"]) == row["sha256"]
    assert digest(ROOT / "ir_hw1/preprocessing.py") == proof["source"]["hw1_preprocessing_sha256"]
    assert digest(ROOT / "ir_hw2/analysis.py") == proof["source"]["analysis_code_sha256"]
    assert digest(ROOT / "scripts/verify_hw2_tokenizer.py") == proof["source"]["verifier_sha256"]

    report_path = REPORTS / "HW2_REPORT.md"
    report = report_path.read_text(encoding="utf-8")
    rows = [[cell.strip().strip("`") for cell in line.strip().strip("|").split("|")]
            for line in report.splitlines() if line.startswith("|")]
    statistics_rows = [row for row in rows if len(row) == 9 and row[0] in ("A", "B", "C", "D")]
    assert [row[0] for row in statistics_rows] == list(LABELS), "Report must contain exactly four A/B/C/D statistics rows"
    regression_rows = [row for row in rows if len(row) == 8 and any(row[0].startswith(label + " ") for label in ("A", "B", "C", "D"))]
    assert len(regression_rows) == 16, "Report must contain exactly 16 fits"
    assert len(summary["selected_terms"]) == 39
    assert all(row["condition"] == "B" for row in summary["selected_terms"])
    selected_checks = 0
    for term in summary["selected_terms"]:
        matches = [row for row in rows if len(row) == 4 and row[0] == term["term"]
                   and all(numeric(cell) for cell in row[1:])]
        assert len(matches) == 1, term["term"]
        values = list(map(number, matches[0][1:]))
        assert values[:2] == [term["cf"], term["df"]], term["term"]
        assert math.isclose(values[2], term["idf"], abs_tol=0.000000501), term["term"]
        selected_checks += 1
    fits_checked = 0
    for label, value in summary["conditions"].items():
        stats = next(row for row in rows if len(row) == 9 and row[0] == label)
        assert list(map(number, stats[1:6])) == [value[key] for key in (
            "documents", "tokens", "unique_terms", "average_tokens_per_document", "singleton_terms")]
        assert number(stats[-1]) == value["postings_entries"]
        for scope, fit in {"全部": value["regression"], "高頻": value["segments"]["head"],
                           "中頻": value["segments"]["middle"], "低頻": value["segments"]["tail"]}.items():
            actual = next(row for row in rows if len(row) == 8 and row[0] == f"{label} {scope}")
            assert number(actual[2]) == fit["points"]
            for cell, metric in zip(actual[3:], ("slope", "intercept", "zipf_exponent", "r_squared", "rmse")):
                assert math.isclose(number(cell), fit[metric], abs_tol=0.000000501), (label, scope, metric)
            fits_checked += 1
    assert fits_checked == 16

    top50_checks = 0
    for label in LABELS:
        block = report.split(f"<!-- TOP50_{label}_START -->")[1].split(f"<!-- TOP50_{label}_END -->")[0]
        table = [[cell.strip() for cell in line.strip().strip('|').split('|')]
                 for line in block.splitlines() if line.startswith('|')]
        actual = {}
        for row in table:
            if len(row) == 6 and row[0].isdigit() and row[3].isdigit():
                for offset in (0, 3):
                    rank = int(row[offset])
                    assert rank not in actual
                    actual[rank] = (row[offset + 1], int(row[offset + 2].replace(',', '')))
        assert set(actual) == set(range(1, 51)), label
        for term in summary['conditions'][label]['top50']:
            assert actual[term['rank']] == (term['term'], term['cf']), (label, term['term'])
            top50_checks += 1

    comparisons = read(REPORTS / 'comparison_figures.json')
    assert digest(ROOT / comparisons['source']) == comparisons['source_sha256']
    assert len(comparisons['figures']) == 5
    for item in [*comparisons['figures'], *comparisons['code']]:
        assert digest(ROOT / item['path']) == item['sha256']

    assert report.count("<!-- IR_ENGLISH_START -->") == report.count("<!-- IR_ENGLISH_END -->") == 1
    discussion = report.split("<!-- IR_ENGLISH_START -->")[1].split("<!-- IR_ENGLISH_END -->")[0].strip()
    word_count = len(discussion.split())
    assert 300 <= word_count <= 500
    assert f"{word_count} words" in report
    for question in range(1, 6):
        assert f"RQ{question}" in report

    junit_path = args.junit.resolve()
    junit_root = ET.parse(junit_path).getroot()
    suites = [suite for suite in junit_root.iter("testsuite") if suite.findall("testcase")]
    assert suites, "JUnit XML has no suites containing test cases"
    assert all(int(suite.attrib.get(key, 0)) == 0 for suite in suites for key in ("failures", "errors", "skipped"))
    cases = list(junit_root.iter("testcase"))
    assert cases and not any(case.find(tag) is not None for case in cases for tag in ("failure", "error", "skipped"))
    assert sum(int(suite.attrib["tests"]) for suite in suites) == len(cases)
    assert f"{len(cases)} passed" in report
    original_files = []
    for row in read(REPORTS / "validation_summary.json")["original_test_files"]:
        current = digest(ROOT / row["path"])
        assert current == row["sha256"], row["path"]
        original_files.append({"path": row["path"], "sha256": current, "unchanged": True})
    original_modules = [Path(row["path"]).with_suffix("").as_posix().replace("/", ".") for row in original_files]
    original = sum(any(case.attrib["classname"] == module or case.attrib["classname"].startswith(module + ".")
                       for module in original_modules) for case in cases)
    assert original == 348

    metadata = read(REPORTS / "model/metadata.json")
    assert metadata["baseline_tokenizer"] == summary["metadata"]["baseline_tokenizer"]
    assert metadata["corpus_sha256"] == summary["metadata"]["corpus_sha256"]
    assert digest(REPORTS / "model/word2vec.model") == metadata["model_sha256"]
    assert digest(REPORTS / "model/sentences.jsonl") == metadata["sentences_sha256"]
    cf = Counter()
    sentence_count = 0
    pmids = set()
    for line in (REPORTS / "model/sentences.jsonl").read_text(encoding="utf-8").splitlines():
        sentence = json.loads(line)
        cf.update(sentence["tokens"])
        pmids.add(sentence["pmid"])
        sentence_count += 1
    assert cf == summary["conditions"]["B"]["cf"]
    assert sentence_count == metadata["sentences"]
    assert len(pmids) == metadata["documents"] == 1000
    assert sum(cf.values()) == metadata["training_tokens"]
    assert sum(count >= metadata["config"]["min_count"] for count in cf.values()) == metadata["vocabulary_size"]
    formal = read(REPORTS / "formal-verification.json")
    assert formal["network_blocked"] and formal["word2vec_reload"] == "passed"
    assert formal["word2vec_vectors_sha256"] == metadata["vectors_sha256"]
    assert formal["corpus_sha256"] == metadata["corpus_sha256"]

    exported = read(REPORTS / "pdf_export.json")
    for item in exported["outputs"]:
        assert digest(Path(item["source"])) == item["source_sha256"]
        assert digest(Path(item["output"])) == item["pdf_sha256"]
        for figure in item["figures"]:
            assert digest(Path(figure["source"])) == figure["sha256"]
    executive = [item for item in exported["outputs"] if Path(item["source"]).name == "EXECUTIVE_SUMMARY.md"]
    assert len(executive) == 1 and executive[0]["pages"] == 1
    result = {
        "verified_at_utc": datetime.now(timezone.utc).isoformat(), "passed": True,
        "pipeline_version": summary["metadata"]["pipeline_version"],
        "primary_comparison": list(LABELS), "reference_condition": None,
        "tokenizer_verification": {"path": "reports/hw2/tokenizer_verification.json", "sha256": digest(REPORTS / "tokenizer_verification.json"),
                                   "documents_checked": 1000, "reproduced_files": 21, "independent_fits": 16,
                                   "mapped_previous_conditions": {label: label for label in LABELS}},
        "report": {"path": str(report_path.relative_to(ROOT)), "sha256": digest(report_path),
                   "cf_df_idf_rows_checked": selected_checks, "regression_rows_checked": fits_checked,
                   "statistics_rows_checked": len(statistics_rows), "selected_terms_condition": "B",
                   "top50_rows_checked": top50_checks, "additional_comparison_figures": len(comparisons['figures']),
                   "english_words": word_count, "english_sha256": hashlib.sha256(discussion.encode()).hexdigest()},
        "tests": {"passed": len(cases), "original_hw1": original, "hw2": len(cases) - original,
                  "failures": 0, "errors": 0, "skipped": 0, "junit_seconds": sum(float(suite.attrib["time"]) for suite in suites),
                  "junit_path": str(junit_path), "junit_sha256": digest(junit_path)},
        "original_test_files": original_files,
        "word2vec": {"ordered_sentences": sentence_count, "tokens": sum(cf.values()),
                     "vocabulary": metadata["vocabulary_size"], "sentence_cf_equals_analysis_B": True,
                     "vectors_sha256": metadata["vectors_sha256"], "offline_reload": "passed"},
        "pdf_export": {"sha256": digest(REPORTS / "pdf_export.json"), "current_source_and_figure_hashes": "passed",
                       "pages": [item["pages"] for item in exported["outputs"]],
                       "visual_qa": "Separate visual inspection evidence: reports/hw2/pdf_qa.json"},
        "limitations": "Counts and regression are descriptive; these checks do not establish retrieval or semantic accuracy.",
    }
    output = REPORTS / "analysis_verification.json"
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"passed": True, "tests": len(cases), "english_words": word_count,
                      "report_selected_terms": selected_checks, "output": str(output)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
