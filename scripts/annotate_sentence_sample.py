"""AI-reviewed reference labels, entered from text without running the splitter.

These labels are NOT an independent human gold standard. The student should
review reports/sentence_gold.json before reporting human evaluation results.
Each suffix below identifies a reviewed internal sentence end; final ends are
the trimmed paragraph end. No prediction is consulted to construct the labels.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ir_hw1.storage import write_json

ENDINGS = {
    1: ["those affected 1 .", "HIV/AIDS (PWH)."],
    2: ["well-known."],
    3: ["population health.", "Appleton, 2007 ).", "police and hospital records."],
    4: ["data collection.", "data collection efficiency."],
    5: ["extraordinary person.", "influential scientist."],
    6: ["HPA axis in mammals.", "has consequences."],
    7: ["was Pak1.", "migration [ 16 ].", "cancer [ 6 , 17 , 18 ]."],
    8: ["cancer [ 103 – 106 ].", "cells [ 107 – 109 ].", "cardiovascular applications."],
    9: ["for 20 days.", "with BIC/FTC/TAF.", "tobacco smoking."],
    10: ["fibrinolytic enzymes.", "patients with HIV."],
    11: ["regimens [ 9 ]."],
    12: ["daily clinical practice."],
    13: ["immunocompromised individuals.", "condition [ 1 ].", "nature [ 2 , 3 ]."],
    14: ["living with HIV.", "these challenging cases."],
    15: ["49 years [ 4 ].", "15–49 years [ 5 ].", "limited [ 6 ]."],
    16: ["at MHC.", "has collected data."],
    17: ["virus [ 1 ].", "elusive [ 2 ].", "(PLHIV) [ 3 , 4 ].", "population [ 3 , 8 ]."],
    18: ["this study.", "factors for hypertension.", "both diseases."],
    19: ["infection [ 1 ]."],
    20: ["in the hospital."],
    21: ["studies [ 12 ].", "interventions [ 13 , 14 ].", "health care providers."],
    22: ["service delivery.", "ask questions.", "should be considered."],
    23: ["reconstitution [ 6 ].", "HIV [ 7 , 8 ].", "75% [ 9 ].", "(77%) [ 10 ]."],
    24: [],
    25: ["challenge in Zanzibar.", "respectively [ 5 ]."],
    26: ["comprehensive interventions.", "its key populations."],
    27: ["Table 1 )."],
    28: ["main characteristics."],
    29: ["0-14years [ 9 , 10 ].", "feeding [ 11 ]."],
    30: ["slightly above average.", "place of residence.", "HIV among children."],
}

samples = json.loads((ROOT / "reports/sentence_sample_unlabeled.json").read_text(encoding="utf-8"))
for row in samples:
    start, ends = 0, []
    for ending in ENDINGS[row["sample_id"]]:
        pos = row["text"].index(ending, start)
        start = pos + len(ending)
        ends.append(start)
    ends.append(len(row["text"].rstrip()))
    row["boundaries"] = ends
    row["annotation"] = "AI-reviewed reference, independently entered from paragraph text; pending student/human review"
write_json(ROOT / "reports/sentence_gold.json", samples)
print(f"Wrote {len(samples)} reviewed paragraphs; not a human gold standard.")
