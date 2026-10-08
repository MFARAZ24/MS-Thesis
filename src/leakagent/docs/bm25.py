"""A minimal BM25 implementation with no external dependencies."""

import math
import re
from collections import Counter
from dataclasses import asdict, dataclass

TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]{1,}")

STOPWORDS = frozenset(
    """a an and are as at be by for from has have in is it its of on or that the
    to was were will with this these those they them their there than then into
    about over under during before after between but not no nor so such can could
    should would may might must do does did done being been has had
    """.split()
)


def tokenize(text: str) -> list[str]:
    return [t for t in (m.group(0).lower() for m in TOKEN_RE.finditer(text))
            if t not in STOPWORDS]


@dataclass
class Doc:
    doc_id: str
    title: str
    url: str
    text: str


@dataclass
class Hit:
    doc_id: str
    title: str
    url: str
    score: float
    snippet: str

    def to_dict(self) -> dict:
        return asdict(self)


class BM25:
    def __init__(self, k1: float = 1.5, b: float = 0.75) -> None:
        self.k1 = k1
        self.b = b
        self.docs: dict[str, Doc] = {}
        self.doc_len: dict[str, int] = {}
        self.term_freq: dict[str, Counter] = {}
        self.df: Counter = Counter()
        self.avg_len: float = 0.0
        self.N: int = 0

    def add(self, doc: Doc) -> None:
        tokens = tokenize(f"{doc.title}\n{doc.text}")
        if not tokens:
            return
        self.docs[doc.doc_id] = doc
        self.doc_len[doc.doc_id] = len(tokens)
        tf = Counter(tokens)
        self.term_freq[doc.doc_id] = tf
        for term in tf:
            self.df[term] += 1
        self.N = len(self.docs)
        self.avg_len = sum(self.doc_len.values()) / self.N

    def _idf(self, term: str) -> float:
        n = self.df.get(term, 0)
        return math.log((self.N - n + 0.5) / (n + 0.5) + 1.0)

    def search(self, query: str, top_k: int = 5) -> list[Hit]:
        q_terms = tokenize(query)
        if not q_terms or not self.docs:
            return []
        scores: dict[str, float] = {}
        for term in set(q_terms):
            idf = self._idf(term)
            if idf <= 0:
                continue
            for doc_id, tf in self.term_freq.items():
                f = tf.get(term, 0)
                if not f:
                    continue
                dl = self.doc_len[doc_id]
                denom = f + self.k1 * (1.0 - self.b + self.b * dl / self.avg_len)
                scores[doc_id] = scores.get(doc_id, 0.0) + idf * (f * (self.k1 + 1.0)) / denom
        ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)[:top_k]
        return [self._make_hit(doc_id, score, q_terms) for doc_id, score in ranked]

    def _make_hit(self, doc_id: str, score: float, q_terms: list[str]) -> Hit:
        doc = self.docs[doc_id]
        return Hit(
            doc_id=doc_id,
            title=doc.title,
            url=doc.url,
            score=score,
            snippet=self._snippet(doc.text, q_terms),
        )

    @staticmethod
    def _snippet(text: str, q_terms: list[str], window: int = 240) -> str:
        low = text.lower()
        for term in q_terms:
            idx = low.find(term)
            if idx >= 0:
                start = max(0, idx - window // 2)
                end = min(len(text), idx + window // 2)
                prefix = "..." if start > 0 else ""
                suffix = "..." if end < len(text) else ""
                return prefix + text[start:end].strip() + suffix
        return text[:window].strip() + ("..." if len(text) > window else "")