from dataclasses import asdict, dataclass, field


@dataclass
class TextBlock:
    id: str
    kind: str
    section: str
    text: str
    narrative: bool = True


@dataclass
class Document:
    pmcid: str
    title: str
    blocks: list[TextBlock]
    pmid: str = ""
    doi: str = ""
    year: str = ""
    language: str = "en"
    license: str = ""
    license_url: str = ""
    source_url: str = ""
    acquired_at: str = ""
    raw_path: str = ""
    sha256: str = ""
    back_blocks: list[TextBlock] = field(default_factory=list)
    statistics: dict = field(default_factory=dict)
    content_scope: str = "full"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict) -> "Document":
        value = dict(value)
        for key in ("blocks", "back_blocks"):
            value[key] = [TextBlock(**b) for b in value.get(key, [])]
        return cls(**value)


@dataclass(frozen=True)
class Token:
    text: str
    term: str
    start: int
    end: int


@dataclass(frozen=True)
class SentenceSpan:
    start: int
    end: int
    text: str
    rule: str
