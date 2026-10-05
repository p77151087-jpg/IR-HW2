from .models import Document
from .preprocessing import tokenize
from .sentence_splitter import split_sentences


def compute_statistics(document: Document) -> dict:
    text = "\n".join(block.text for block in document.blocks)
    details = []
    for block in document.blocks:
        # Abstract display counts whitespace-separated units, independently of
        # the tokenizer used by retrieval and full-text statistics.
        words = len(block.text.split()) if document.content_scope == "abstract" else len(tokenize(block.text))
        details.append({"block_id": block.id, "kind": block.kind, "section": block.section,
                        "characters": len(block.text), "words": words,
                        "sentences": len(split_sentences(block.text)) if block.narrative else 0,
                        "narrative": block.narrative})
    return {"characters": len(text), "characters_no_whitespace": sum(not c.isspace() for c in text),
            "words": sum(b["words"] for b in details), "sentences": sum(b["sentences"] for b in details),
            "blocks": details}
