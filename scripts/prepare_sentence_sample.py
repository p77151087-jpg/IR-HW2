"""Select evaluation paragraphs without reading sentence-splitter output."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ir_hw1.storage import load_documents, write_json

rows = []
for doc in load_documents().values():
    candidates = [b for b in doc.blocks if b.kind == "body" and 180 <= len(b.text) <= 700 and b.text.count(".") >= 2]
    # First and last eligible body paragraphs; deterministic, across 15 articles.
    chosen = [candidates[0], candidates[-1]] if len(candidates) > 1 else candidates
    for block in chosen:
        rows.append({"sample_id": len(rows) + 1, "split": "development" if len(rows) % 3 == 0 else "test",
                     "pmcid": doc.pmcid, "block_id": block.id, "text": block.text})
write_json(ROOT / "reports/sentence_sample_unlabeled.json", rows)
for row in rows:
    print(f"[{row['sample_id']}] {row['pmcid']} {row['block_id']} {row['split']}\n{row['text']}\n")
