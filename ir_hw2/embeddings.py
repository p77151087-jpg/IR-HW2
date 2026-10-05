"""Sentence-bounded Skip-gram training and checked local model reloads."""
from dataclasses import asdict, dataclass
from hashlib import sha256
from importlib.metadata import version
import json
import os
from pathlib import Path
import platform
from time import perf_counter

from filelock import FileLock
from gensim.models import Word2Vec
import numpy as np

from ir_hw1.models import Document
from ir_hw1.sentence_splitter import SENTENCE_VERSION, split_sentences
from ir_hw1.storage import atomic_write, json_bytes, write_json
from .analysis import baseline_tokenizer_spec, tokenize


MODEL_SCHEMA_VERSION = 2


@dataclass(frozen=True)
class TrainingConfig:
    vector_size: int = 100
    window: int = 5
    min_count: int = 2
    epochs: int = 30
    seed: int = 42
    workers: int = 1
    sg: int = 1
    negative: int = 5
    sample: float = 0.001
    ns_exponent: float = 0.75
    alpha: float = 0.025
    min_alpha: float = 0.0001
    sorted_vocab: int = 1
    shrink_windows: bool = True

    def validate(self) -> None:
        if any(value < 1 for value in (self.vector_size, self.window, self.min_count, self.epochs, self.negative)):
            raise ValueError("vector_size、window、min_count、epochs、negative 必須為正整數。")
        if self.workers != 1 or self.sg != 1:
            raise ValueError("本實驗固定單一 worker 與 Skip-gram。")
        if self.sample < 0 or not 0 < self.min_alpha <= self.alpha or self.seed < 0:
            raise ValueError("Word2Vec 訓練設定無效。")


def stable_hash(value: str) -> int:
    """Stable across Python processes, unlike the default randomized hash()."""
    return int.from_bytes(sha256(value.encode("utf-8")).digest()[:8], "little")


def sentence_records(documents: dict[str, Document]) -> list[dict]:
    """Retain original document/block/sentence order; never use postings/CF."""
    seen = set()
    records = []
    for doc in sorted(documents.values(), key=lambda item: item.pmid):
        if not doc.pmid or doc.pmid in seen:
            raise ValueError("Word2Vec 需要不重複且非空的 PMID。")
        seen.add(doc.pmid)
        if doc.content_scope != "abstract":
            raise ValueError("Word2Vec 正式輸入必須為摘要快照。")
        for block in doc.blocks:
            if block.kind != "abstract":
                continue
            for number, sentence in enumerate(split_sentences(block.text)):
                tokens = tokenize(sentence.text, "B")
                if tokens:
                    records.append({"pmid": doc.pmid, "block_id": block.id,
                                    "sentence": number, "start": sentence.start,
                                    "end": sentence.end, "tokens": tokens})
    if not records:
        raise ValueError("沒有可供 Word2Vec 訓練的摘要句子。")
    return records


def train_word2vec(documents: dict[str, Document], output_dir: Path,
                   corpus_sha256: str = "", config: TrainingConfig | None = None) -> dict:
    config = config or TrainingConfig()
    config.validate()
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    with FileLock(str(output_dir / ".training.lock"), timeout=0):
        records = sentence_records(documents)
        sequences = [record["tokens"] for record in records]
        record_bytes = b"".join(json_bytes(record) + b"\n" for record in records)
        start = perf_counter()
        model = Word2Vec(**asdict(config), hashfxn=stable_hash)
        model.build_vocab(sequences)
        if len(model.wv) < 2 or not any(sum(t in model.wv for t in s) >= 2 for s in sequences):
            raise ValueError("min_count 過濾後沒有足夠詞彙／同句詞對，無法訓練。")
        effective, raw = model.train(sequences, total_examples=model.corpus_count, epochs=config.epochs)
        temporary = output_dir / "word2vec.pending.model"
        model.save(str(temporary), separately=[])
        model_path = output_dir / "word2vec.model"
        os.replace(temporary, model_path)
        atomic_write(output_dir / "sentences.jsonl", record_bytes)
        vectors_digest = sha256(model.wv.vectors.tobytes()).hexdigest()
        metadata = {
            "schema_version": MODEL_SCHEMA_VERSION, "algorithm": "Skip-gram with negative sampling (Gensim)",
            "config": asdict(config), "corpus_sha256": corpus_sha256,
            "preprocessing_condition": "B",
            "preprocessing": "HW2 condition B; original HW1 tokenizer and NFC/casefold normalization; keep stopwords; no stemming or search-feature expansion",
            "baseline_tokenizer": baseline_tokenizer_spec(),
            "sentence_rules": SENTENCE_VERSION,
            "boundary_policy": "No context crosses a document, abstract block, or detected sentence boundary.",
            "order": "PMID lexical order; source block/sentence/token order within each document",
            "sentences": len(records), "documents": len(documents),
            "training_tokens": sum(map(len, sequences)), "vocabulary_size": len(model.wv),
            "effective_training_words_all_epochs": effective, "raw_training_words_all_epochs": raw,
            "seconds": perf_counter() - start, "sentences_sha256": sha256(record_bytes).hexdigest(),
            "model_sha256": sha256(model_path.read_bytes()).hexdigest(), "vectors_sha256": vectors_digest,
            "versions": {name: version(name) for name in ("gensim", "numpy", "scipy", "regex")},
            "python": platform.python_version(), "platform": platform.platform(),
            "hash_function": "sha256-first-8-bytes-little-endian",
            "limitations": ["Small, single-topic corpus; neighbors are exploratory, not semantic accuracy.",
                            "Rule-based sentence boundaries can misread abbreviations.",
                            "HW1 tokenization preserves internal supported hyphens/apostrophes and decimals; punctuation not recognized by its regex can still split biomedical names.",
                            "Bitwise retraining reproducibility is scoped to the recorded software/platform."],
        }
        write_json(output_dir / "metadata.json", metadata)
        return metadata


def load_word2vec(output_dir: Path, expected_corpus_sha256: str | None = None):
    """Require current token semantics as well as corpus and artifact checksums.

    Models from the former L/M/N splitter must be retrained even when they used
    the same raw corpus. Statistical settings such as log base are deliberately
    absent from the tokenizer contract and do not invalidate compatible models.
    The former three-condition baseline label A also preserves this contract;
    older labels do not change the recorded sentence/vector content.
    """
    output_dir = Path(output_dir)
    with FileLock(str(output_dir / ".training.lock"), timeout=0):
        metadata = json.loads((output_dir / "metadata.json").read_text(encoding="utf-8"))
        if metadata.get("schema_version") != MODEL_SCHEMA_VERSION:
            raise ValueError("模型版本或 tokenizer 設定已更新，請依目前 HW1 切詞規則重新訓練。")
        if metadata.get("baseline_tokenizer") != baseline_tokenizer_spec():
            raise ValueError("模型缺少目前 tokenizer 來源紀錄，或切詞／正規化設定不符；即使語料相同也必須重新訓練。")
        if expected_corpus_sha256 is not None and metadata.get("corpus_sha256") != expected_corpus_sha256:
            raise ValueError("模型與目前正式語料快照不同，請重新訓練。")
        path = output_dir / "word2vec.model"
        if sha256(path.read_bytes()).hexdigest() != metadata.get("model_sha256"):
            raise ValueError("模型檔案 SHA-256 不符。")
        if sha256((output_dir / "sentences.jsonl").read_bytes()).hexdigest() != metadata.get("sentences_sha256"):
            raise ValueError("訓練句子檔案 SHA-256 不符。")
        model = Word2Vec.load(str(path))
        if (len(model.wv) != metadata["vocabulary_size"] or not np.isfinite(model.wv.vectors).all()
                or sha256(model.wv.vectors.tobytes()).hexdigest() != metadata["vectors_sha256"]):
            raise ValueError("模型向量與訓練紀錄不一致。")
        return model, metadata


def neighbors(model: Word2Vec, query: str, topn: int = 10) -> dict:
    terms = tokenize(query, "B")
    if len(terms) != 1:
        return {"query": query, "terms": terms, "status": "invalid_query", "neighbors": [],
                "message": "請輸入一個依 HW1 切詞規則保留的 B 條件詞彙，例如 GLP-1；GLP-1 receptor 含兩詞，不能作單詞近鄰查詢。"}
    term = terms[0]
    if term not in model.wv:
        return {"query": query, "term": term, "status": "oov", "neighbors": [],
                "message": "此詞不在模型詞彙中，可能未出現或低於 min_count；不以隨機向量替代。"}
    count = min(max(1, topn), max(0, len(model.wv) - 1))
    matches = model.wv.most_similar(term, topn=count) if count else []
    return {"query": query, "term": term, "status": "ok",
            "neighbors": [{"term": other, "cosine": float(score)} for other, score in matches],
            "message": "近鄰反映本語料的上下文相似性，不代表語意正確率。"}
