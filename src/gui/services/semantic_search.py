"""Optional semantic-search skeleton with a deterministic offline embedder."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Protocol, Sequence

import numpy as np


class Embedder(Protocol):
    """Convert text into fixed-size embedding vectors."""

    @property
    def dimension(self) -> int:
        ...

    def embed(self, texts: Sequence[str]) -> np.ndarray:
        ...


class StubEmbedder:
    """Deterministic local embedder for tests and CI.

    It uses SHA-256-derived values rather than a downloaded ML model. The
    output is stable across runs and machines for the same input text.
    """

    def __init__(self, dimension: int = 64) -> None:
        if dimension <= 0:
            raise ValueError("dimension must be positive")
        self._dimension = int(dimension)

    @property
    def dimension(self) -> int:
        return self._dimension

    def embed(self, texts: Sequence[str]) -> np.ndarray:
        vectors = []
        for text in texts:
            seed = hashlib.sha256(text.strip().lower().encode("utf-8")).digest()
            raw = bytearray()
            counter = 0
            while len(raw) < self._dimension * 4:
                raw.extend(hashlib.sha256(seed + counter.to_bytes(4, "big")).digest())
                counter += 1
            values = np.frombuffer(bytes(raw[: self._dimension * 4]), dtype=np.uint32)
            vector = (values.astype(np.float32) / np.float32(2**31)) - np.float32(1.0)
            norm = float(np.linalg.norm(vector))
            if norm:
                vector /= norm
            vectors.append(vector)
        if not vectors:
            return np.empty((0, self._dimension), dtype=np.float32)
        return np.vstack(vectors).astype(np.float32)


@dataclass(frozen=True)
class SemanticResult:
    """One ranked semantic-search result."""

    item_id: int | str
    score: float


class SemanticSearchIndex:
    """Small in-memory vector index for the Week 6 skeleton."""

    def __init__(self, embedder: Embedder) -> None:
        self.embedder = embedder
        self._ids: list[int | str] = []
        self._vectors = np.empty((0, embedder.dimension), dtype=np.float32)

    def add(self, item_ids: Sequence[int | str], texts: Sequence[str]) -> None:
        if len(item_ids) != len(texts):
            raise ValueError("item_ids and texts must have the same length")
        if not texts:
            return
        vectors = self.embedder.embed(texts)
        if vectors.shape != (len(texts), self.embedder.dimension):
            raise ValueError("embedder returned an unexpected shape")
        self._ids.extend(item_ids)
        self._vectors = np.vstack([self._vectors, vectors])

    def search(self, query: str, limit: int = 10) -> list[SemanticResult]:
        if limit <= 0 or not self._ids:
            return []
        query_vector = self.embedder.embed([query])[0]
        scores = self._vectors @ query_vector
        order = np.argsort(-scores, kind="stable")[:limit]
        return [SemanticResult(self._ids[int(index)], float(scores[int(index)])) for index in order]


class SentenceTransformerEmbedder:
    """Opt-in real embedder using a locally provided model."""
    def __init__(self, model_path: str) -> None:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise RuntimeError("install the semantic-search optional extra") from exc

        self._model = SentenceTransformer(model_path, local_files_only=True)
        self._dimension = int(self._model.get_sentence_embedding_dimension())

    @property
    def dimension(self) -> int:
        return self._dimension

    def embed(self, texts: Sequence[str]) -> np.ndarray:
        return np.asarray(self._model.encode(list(texts), convert_to_numpy=True, normalize_embeddings=True), dtype=np.float32)
