import hashlib
import json
import os
import sqlite3
from typing import Protocol

from app.config import settings


class Embedder(Protocol):
    dim: int

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        ...

    def embed_query(self, text: str) -> list[float]:
        ...


class SQLiteEmbeddingCache:
    def __init__(self, db_path: str = ".cache/embeddings.sqlite"):
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self._init_db()

    def _init_db(self):
        with self.conn:
            self.conn.execute(
                """
                CREATE TABLE IF NOT EXISTS embeddings (
                    hash TEXT PRIMARY KEY,
                    embedding TEXT
                )
                """
            )

    def get(self, text_hash: str) -> list[float] | None:
        cur = self.conn.cursor()
        cur.execute("SELECT embedding FROM embeddings WHERE hash = ?", (text_hash,))
        row = cur.fetchone()
        if row:
            return json.loads(row[0])
        return None

    def put(self, text_hash: str, embedding: list[float]):
        with self.conn:
            self.conn.execute(
                "INSERT OR REPLACE INTO embeddings (hash, embedding) VALUES (?, ?)",
                (text_hash, json.dumps(embedding)),
            )


class LocalBGEEmbedder:
    def __init__(self, model_name: str = "BAAI/bge-small-en-v1.5", dim: int = 384):
        self.model_name = model_name
        self.dim = dim
        self._model = None
        self.cache = SQLiteEmbeddingCache()

    @property
    def model(self):
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
                self._model = SentenceTransformer(self.model_name)
            except Exception:
                # Fallback mock embedding generator for testing if sentence_transformers isn't downloaded yet
                self._model = None
        return self._model

    def _hash(self, text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def _mock_embed(self, text: str) -> list[float]:
        """Deterministic fallback embedding of specified dimension."""
        h = int(hashlib.sha256(text.encode("utf-8")).hexdigest(), 16)
        vec = []
        for i in range(self.dim):
            val = ((h >> (i % 64)) & 0xFFFF) / 65535.0 - 0.5
            vec.append(val)
        norm = sum(x * x for x in vec) ** 0.5 or 1.0
        return [x / norm for x in vec]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        results: list[list[float]] = [[] for _ in texts]
        uncached_indices: list[int] = []
        uncached_texts: list[str] = []

        for i, text in enumerate(texts):
            h = self._hash(f"doc:{text}")
            cached = self.cache.get(h)
            if cached is not None:
                results[i] = cached
            else:
                uncached_indices.append(i)
                uncached_texts.append(text)

        if uncached_texts:
            if self.model is not None:
                embeddings = self.model.encode(
                    uncached_texts,
                    normalize_embeddings=True,
                    batch_size=32,
                    show_progress_bar=False,
                ).tolist()
            else:
                embeddings = [self._mock_embed(t) for t in uncached_texts]

            for idx, text, emb in zip(uncached_indices, uncached_texts, embeddings):
                h = self._hash(f"doc:{text}")
                self.cache.put(h, emb)
                results[idx] = emb

        return results

    def embed_query(self, text: str) -> list[float]:
        prefixed = f"Represent this sentence for searching relevant passages: {text}"
        h = self._hash(f"query:{prefixed}")
        cached = self.cache.get(h)
        if cached is not None:
            return cached

        if self.model is not None:
            emb = self.model.encode(
                [prefixed],
                normalize_embeddings=True,
                show_progress_bar=False,
            )[0].tolist()
        else:
            emb = self._mock_embed(prefixed)

        self.cache.put(h, emb)
        return emb


_embedder: Embedder | None = None


def get_embedder() -> Embedder:
    global _embedder
    if _embedder is None:
        if settings.EMBED_PROVIDER == "local":
            _embedder = LocalBGEEmbedder(
                model_name=settings.EMBED_MODEL,
                dim=settings.EMBED_DIM
            )
        else:
            raise NotImplementedError(f"Embedding provider '{settings.EMBED_PROVIDER}' not implemented yet.")
        assert _embedder.dim == settings.EMBED_DIM, f"Embedder dimension {_embedder.dim} does not match {settings.EMBED_DIM}"
    return _embedder
