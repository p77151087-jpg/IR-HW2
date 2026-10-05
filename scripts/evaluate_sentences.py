import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ir_hw1.sentence_splitter import SENTENCE_VERSION, split_sentences
from ir_hw1.storage import write_json


def naive_ends(text):
    # Baseline: cut at every ASCII period; include nonempty tail.
    points = [m.end() for m in re.finditer(r"\.", text)]
    if not points or points[-1] != len(text):
        points.append(len(text))
    return points


def main():
    rows = json.loads((ROOT / "reports/sentence_gold.json").read_text(encoding="utf-8"))
    metrics = {}
    for split in ("development", "test"):
        for method in ("rules", "period_baseline"):
            tp = fp = fn = count_error = total = 0
            failures = []
            for row in (r for r in rows if r["split"] == split):
                total += 1
                predicted = {s.end for s in split_sentences(row["text"])} if method == "rules" else set(naive_ends(row["text"]))
                gold = set(row["boundaries"])
                tp += len(predicted & gold)
                fp += len(predicted - gold)
                fn += len(gold - predicted)
                count_error += abs(len(predicted) - len(gold))
                if predicted != gold:
                    failures.append({"sample_id": row["sample_id"], "extra_ends": sorted(predicted - gold), "missed_ends": sorted(gold - predicted)})
            precision = tp / (tp + fp) if tp + fp else 0
            recall = tp / (tp + fn) if tp + fn else 0
            metrics[f"{split}_{method}"] = {"paragraphs": total, "tp": tp, "fp": fp, "fn": fn,
                "precision": precision, "recall": recall, "f1": 2 * precision * recall / (precision + recall) if precision + recall else 0,
                "absolute_sentence_count_error": count_error, "failures": failures}
    adversarial = [
        {"text": "The U.S. Food and Drug Administration approved it.", "expected": 1, "reason": "縮寫後接大寫專有名詞，誤認為句首"},
        {"text": "Read the label etc. next we tested it.", "expected": 2, "reason": "縮寫句尾後以小寫開新句，規則合併（刻意非典型大小寫）"},
    ]
    for case in adversarial:
        case["predicted"] = [s.text for s in split_sentences(case["text"])]
    result = {"version": SENTENCE_VERSION, "reference_quality": "AI reviewed, not independently human annotated",
              "selection": "First and last body paragraph with 180–700 characters and >=2 periods per article; 15 articles, 30 paragraphs",
              "limitations": "Small, convenience sample; split by paragraph, not article; model-written labels may be correlated with rules. No claim of general accuracy.",
              "metrics": metrics, "synthetic_known_failures": adversarial}
    write_json(ROOT / "reports/sentence_evaluation.json", result)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
