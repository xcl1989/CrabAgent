"""Memory vector encoding module — lazy-loaded, graceful fallback.

Provides ``encode(text)`` → bytes and ``encode_query(text)`` → ndarray
for semantic similarity search.  If ``sentence-transformers`` is not
installed, both functions return ``None`` and callers should fall back
to SQL LIKE search.

The embedding model is loaded once on first use (lazy singleton).
Recommended model: ``paraphrase-multilingual-MiniLM-L12-v2`` (384-dim,
~120 MB, good Chinese + English coverage).

Environment variable ``CRAB_MEMORY_EMBEDDING`` controls behaviour:
  - "auto" (default): use vector search if model is available, else LIKE
  - "off": never attempt to load the model (skip entirely)
  - "on": require the model, log error on failure
"""

from __future__ import annotations

import logging
import os

import numpy as np

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


def _get_mode() -> str:
    """Return embedding mode from env var."""
    return os.environ.get("CRAB_MEMORY_EMBEDDING", "auto").lower()


def _ensure_model() -> bool:
    """Load the sentence-transformers model (lazy, once). Return True on success."""
    global _MODEL, _AVAILABLE, _LOAD_ATTEMPTED

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
        import signal

        def _timeout_handler(signum, frame):
            raise TimeoutError("model load timed out (30s)")

        # Set a 30-second timeout for model loading
        old_handler = signal.signal(signal.SIGALRM, _timeout_handler)
        signal.alarm(30)
        try:
            from sentence_transformers import SentenceTransformer

            _MODEL = SentenceTransformer(_MODEL_NAME)
            _AVAILABLE = True
            logger.info("embedding model loaded: %s", _MODEL_NAME)
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, old_handler)

    except ImportError:
        _AVAILABLE = False
        logger.info("sentence-transformers not installed, falling back to LIKE search")
    except TimeoutError:
        _AVAILABLE = False
        logger.warning("embedding model load timed out (network issue?), falling back to LIKE search")
    except Exception as exc:
        _AVAILABLE = False
        logger.warning("embedding model load failed: %s", exc)

    return _AVAILABLE or False


def is_available() -> bool:
    """Check whether vector encoding is available (without loading model)."""
    if _AVAILABLE is not None:
        return _AVAILABLE
    mode = _get_mode()
    if mode == "off":
        return False
    return _ensure_model()


def encode(text: str) -> bytes | None:
    """Encode *text* to a float32 vector serialized as bytes.

    Returns ``None`` when sentence-transformers is unavailable.
    """
    if not _ensure_model():
        return None
    vec = _MODEL.encode(text, normalize_embeddings=True)
    return np.array(vec, dtype=np.float32).tobytes()


def encode_query(text: str) -> np.ndarray | None:
    """Encode a query string to a float32 numpy array (384-dim).

    Returns ``None`` when sentence-transformers is unavailable.
    """
    if not _ensure_model():
        return None
    return _MODEL.encode(text, normalize_embeddings=True).astype(np.float32)


def decode_embedding(blob: bytes) -> np.ndarray:
    """Deserialize a BLOB back to a numpy float32 array."""
    return np.frombuffer(blob, dtype=np.float32)


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Compute cosine similarity between two vectors (already L2-normalised → dot product)."""
    return float(np.dot(a, b))


__all__ = [
    "is_available",
    "encode",
    "encode_query",
    "decode_embedding",
    "cosine_similarity",
]
