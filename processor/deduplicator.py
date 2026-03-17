# processor/deduplicator.py
"""
Near-duplicate detection using MinHash (datasketch).

Two chunks are near-duplicates if their Jaccard similarity >= 0.85.
Uses word-level shingles (2-grams) for comparison.
"""
from datasketch import MinHash, MinHashLSH


_JACCARD_THRESHOLD = 0.85
_NUM_PERM = 128      # number of permutations for MinHash (accuracy vs. speed)
_SHINGLE_SIZE = 2    # word n-grams


def _shingles(text: str, size: int = _SHINGLE_SIZE) -> set[str]:
    """Extract word n-gram shingles from text."""
    words = text.lower().split()
    if len(words) < size:
        return {text.lower()}
    return {" ".join(words[i:i+size]) for i in range(len(words) - size + 1)}


def _minhash(text: str) -> MinHash:
    m = MinHash(num_perm=_NUM_PERM)
    for shingle in _shingles(text):
        m.update(shingle.encode("utf8"))
    return m


class Deduplicator:
    """
    Near-duplicate detector using MinHash LSH.

    Usage:
        dedup = Deduplicator()
        unique_chunks = dedup.deduplicate(chunks)
    """

    def __init__(self, threshold: float = _JACCARD_THRESHOLD):
        self.threshold = threshold
        self._lsh = MinHashLSH(threshold=threshold, num_perm=_NUM_PERM)
        self._seen: dict[str, MinHash] = {}

    def is_duplicate(self, text: str) -> bool:
        """True if text is a near-duplicate of something already seen."""
        m = _minhash(text)
        key = f"doc_{len(self._seen)}"
        result = bool(self._lsh.query(m))
        if not result:
            self._lsh.insert(key, m)
            self._seen[key] = m
        return result

    def deduplicate(self, chunks: list) -> list:
        """
        Filter a list of Chunk objects, removing near-duplicates.
        Returns only unique chunks (first occurrence wins).
        """
        unique = []
        for chunk in chunks:
            if not self.is_duplicate(chunk.text):
                unique.append(chunk)
        return unique

    def reset(self) -> None:
        """Reset the deduplicator state (for processing a new batch)."""
        self._lsh = MinHashLSH(threshold=self.threshold, num_perm=_NUM_PERM)
        self._seen = {}
