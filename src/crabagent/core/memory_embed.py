"""Memory vector encoding module — async lazy-loaded, graceful fallback.

Provides ``encode(text)`` → bytes and ``encode_query(text)`` → ndarray
for semantic similarity search.  If ``sentence-transformers`` is not
installed, both functions return ``None`` and callers should fall back
to SQL LIKE search.

The embedding model is loaded once on first use (lazy singleton) but
**offloaded to a thread** so it never blocks the async event loop.

Recommended model: ``paraphrase-multilingual-MiniLM-L12-v2`` (384-dim,
~120 MB, good Chinese + English coverage).

Environment variable ``CRAB_MEMORY_EMBEDDING`` controls behaviour:
  - "auto" (default): use vector search if model is available, else LIKE
  - "off": never attempt to load the model (skip entirely)
  - "on": require the model, log error on failure
"""

from __future__ import annotations

import asyncio
import logging
import os

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Model configuration
# ---------------------------------------------------------------------------

_MODEL_NAME = "paraphrase-multilingual-MiniLM-L12-v2"
_EMBEDDING_DIM = 384

# Singleton state
_MODEL = None
_AVAILABLE: bool | None = None
_LOAD_ATTEMPTED = False
_LOAD_LOCK = asyncio.Lock()


def _get_mode() -> str:
    """Return embedding mode from env var."""
    return os.environ.get("CRAB_MEMORY_EMBEDDING", "auto").lower()


async def _ensure_model() -> bool:
    """Load the sentence-transformers model in a thread (lazy, once).

    Returns ``True`` when the model is ready, ``False`` when
    sentence-transformers is unavailable or loading failed.
    Never blocks the event loop — the heavyweight
    ``SentenceTransformer(...)`` constructor runs via
    ``asyncio.to_thread()``.
    """
    global _MODEL, _AVAILABLE, _LOAD_ATTEMPTED

    if _AVAILABLE is not None:
        return _AVAILABLE

    if _LOAD_ATTEMPTED:
        return _AVAILABLE or False

    async with _LOAD_LOCK:
        # Double-check inside the lock
        if _AVAILABLE is not None:
            return _AVAILABLE
        if _LOAD_ATTEMPTED:
            return _AVAILABLE or False

        _LOAD_ATTEMPTED = True
        mode = _get_mode()

        if mode == "off":
            _AVAILABLE = False
            logger.info("embedding disabled via CRAB_MEMORY_EMBEDDING=off")
            return False

        try:
            from sentence_transformers import SentenceTransformer

            logger.info("loading embedding model %s (async in thread)...", _MODEL_NAME)
            _MODEL = await asyncio.to_thread(SentenceTransformer, _MODEL_NAME)
            _AVAILABLE = True
            logger.info("embedding model loaded: %s", _MODEL_NAME)

        except ImportError:
            _AVAILABLE = False
            logger.info(
                "sentence-transformers not installed, falling back to LIKE search"
            )
        except Exception as exc:
            _AVAILABLE = False
            logger.warning("embedding model load failed: %s", exc)

    return _AVAILABLE or False


async def encode(text: str) -> bytes | None:
    """Encode *text* to a float32 vector serialized as bytes.

    Returns ``None`` when sentence-transformers is unavailable.
    """
    if not await _ensure_model():
        return None
    import numpy as np

    vec = await asyncio.to_thread(
        _MODEL.encode, text, normalize_embeddings=True
    )
    return np.array(vec, dtype=np.float32).tobytes()


async def encode_query(text: str):
    """Encode a query string to a float32 numpy array (384-dim).

    Returns ``None`` when sentence-transformers is unavailable.
    """
    if not await _ensure_model():
        return None
    import numpy as np

    vec = await asyncio.to_thread(
        _MODEL.encode, text, normalize_embeddings=True
    )
    return vec.astype(np.float32)


def decode_embedding(blob: bytes):
    """Deserialize a BLOB back to a numpy float32 array."""
    import numpy as np

    return np.frombuffer(blob, dtype=np.float32)


def cosine_similarity(a, b) -> float:
    """Compute cosine similarity between two vectors (already L2-normalised → dot product)."""
    import numpy as np

    return float(np.dot(a, b))


__all__ = [
    "encode",
    "encode_query",
    "decode_embedding",
    "cosine_similarity",
]
