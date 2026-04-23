from __future__ import annotations

from abc import ABC, abstractmethod
from collections import Counter
import math
from pathlib import Path
import re


_TOKEN_PATTERN = re.compile(r"[a-z0-9]+")
_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "before",
    "by",
    "can",
    "during",
    "each",
    "for",
    "from",
    "how",
    "if",
    "in",
    "into",
    "is",
    "it",
    "of",
    "on",
    "or",
    "that",
    "the",
    "their",
    "them",
    "this",
    "to",
    "too",
    "use",
    "when",
    "with",
}
_NORMALIZED_TOKENS = {
    "approve": "approval",
    "approver": "approval",
    "approvers": "approval",
    "approving": "approval",
    "budgeting": "budget",
    "budgets": "budget",
    "buyers": "buyer",
    "buying": "buyer",
    "calls": "call",
    "concerns": "concern",
    "cost": "pricing",
    "costly": "pricing",
    "decisionmakers": "decisionmaker",
    "decisions": "decision",
    "discounting": "discount",
    "emails": "email",
    "expensive": "pricing",
    "followup": "follow",
    "goals": "goal",
    "meetings": "meeting",
    "nextstep": "next",
    "objections": "objection",
    "pains": "pain",
    "prices": "pricing",
    "pricing": "pricing",
    "priorities": "priority",
    "questions": "question",
    "risks": "risk",
    "stakeholders": "stakeholder",
    "steps": "step",
    "successes": "success",
    "teams": "team",
    "timelines": "timeline",
    "users": "user",
    "value": "value",
    "workflows": "workflow",
}


class EmbeddingService(ABC):
    @abstractmethod
    def embed(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError


class SeedCorpusTfidfEmbeddingProvider(EmbeddingService):
    def __init__(self, kb_seed_dir: Path) -> None:
        self._kb_seed_dir = kb_seed_dir
        self._vocabulary, self._idf_by_token = self._build_vocabulary()

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        return [self._embed_one(text) for text in texts]

    def _build_vocabulary(self) -> tuple[list[str], dict[str, float]]:
        corpus_documents = [
            path.read_text(encoding="utf-8")
            for path in sorted(self._kb_seed_dir.iterdir())
            if path.is_file() and path.name != ".gitkeep"
        ]

        if not corpus_documents:
            return [], {}

        document_count = len(corpus_documents)
        document_frequency: Counter[str] = Counter()

        for document in corpus_documents:
            document_frequency.update(set(self._tokenize(document)))

        vocabulary = sorted(document_frequency)
        idf_by_token = {
            token: math.log((1 + document_count) / (1 + document_frequency[token])) + 1.0
            for token in vocabulary
        }
        return vocabulary, idf_by_token

    def _embed_one(self, text: str) -> list[float]:
        tokens = self._tokenize(text)
        if not tokens or not self._vocabulary:
            return [0.0 for _ in self._vocabulary] or [0.0]

        token_counts = Counter(tokens)
        total_tokens = len(tokens)
        vector = [
            (token_counts[token] / total_tokens) * self._idf_by_token[token]
            for token in self._vocabulary
        ]
        magnitude = math.sqrt(sum(value * value for value in vector))
        if magnitude == 0:
            return vector

        return [value / magnitude for value in vector]

    def _tokenize(self, text: str) -> list[str]:
        tokens: list[str] = []
        for raw_token in _TOKEN_PATTERN.findall(text.lower()):
            normalized_token = _NORMALIZED_TOKENS.get(raw_token, raw_token)
            if normalized_token in _STOPWORDS:
                continue
            tokens.append(normalized_token)
        return tokens


def _resolve_repo_root(adapter_path: Path | None = None) -> Path:
    adapter_path = adapter_path or Path(__file__).resolve()

    for parent in adapter_path.parents:
        if (parent / "docker-compose.yml").is_file():
            return parent
        if (parent / "data" / "kb_seed").is_dir():
            return parent

    if len(adapter_path.parents) > 2:
        return adapter_path.parents[2]

    return adapter_path.parent


def build_embedding_service() -> EmbeddingService:
    kb_seed_dir = _resolve_repo_root() / "data" / "kb_seed"
    return SeedCorpusTfidfEmbeddingProvider(kb_seed_dir=kb_seed_dir)
