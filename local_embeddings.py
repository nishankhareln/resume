"""
local_embeddings
================

A thin wrapper around `sentence-transformers` that exposes the same
interface as langchain's `GoogleGenerativeAIEmbeddings`. The rest of the
code (main_job_matcher.py) was written against `embed_documents([texts])`
and `embed_query(text)` — this class implements those two methods so the
switch is invisible upstream.

Defaults to `sentence-transformers/all-MiniLM-L6-v2` — 90 MB model,
~384-dim vectors, fast on CPU, well-tested. Override via env:

    LOCAL_EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2

First call triggers a one-time download to the HuggingFace cache
(usually ~/.cache/huggingface/). After that it runs fully offline.
"""

from __future__ import annotations

import logging
import os
from functools import lru_cache
from typing import List

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "sentence-transformers/all-MiniLM-L6-v2"


@lru_cache(maxsize=2)
def _load_model(name: str):
    """Lazily load and cache a sentence-transformers model. Wrapped in
    lru_cache so repeated calls (different LocalEmbeddings instances) share
    one in-memory copy."""
    # Imports inside the function so importing this module doesn't pull
    # torch unless we actually use it.
    from sentence_transformers import SentenceTransformer
    logger.info(f"Loading sentence-transformers model: {name} (first run may download weights)")
    model = SentenceTransformer(name)
    dim_fn = getattr(model, "get_embedding_dimension", None) or model.get_sentence_embedding_dimension
    logger.info(f"Loaded {name}. Embedding dim = {dim_fn()}")
    return model


class LocalEmbeddings:
    """Drop-in replacement for langchain GoogleGenerativeAIEmbeddings.

    Implements:
        embed_documents(texts: List[str]) -> List[List[float]]
        embed_query(text: str)            -> List[float]
    """

    def __init__(self, model_name: str | None = None):
        self.model_name = model_name or os.getenv("LOCAL_EMBEDDING_MODEL", DEFAULT_MODEL)
        # eager load so any errors surface at startup, not mid-pipeline
        self._model = _load_model(self.model_name)

    @property
    def dimension(self) -> int:
        m = self._model
        fn = getattr(m, "get_embedding_dimension", None) or m.get_sentence_embedding_dimension
        return int(fn())

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        if not texts:
            return []
        # normalize_embeddings=True makes cosine similarity equivalent to dot product
        # and matches the convention most sentence-transformers models expect.
        vecs = self._model.encode(
            texts,
            show_progress_bar=False,
            convert_to_numpy=True,
            normalize_embeddings=True,
        )
        return vecs.tolist()

    def embed_query(self, text: str) -> List[float]:
        return self.embed_documents([text])[0]
