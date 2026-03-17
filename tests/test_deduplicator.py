# tests/test_deduplicator.py
import pytest
from processor.deduplicator import Deduplicator, _shingles


@pytest.fixture
def dedup():
    return Deduplicator()


def test_shingles_generates_bigrams():
    result = _shingles("the quick brown fox")
    assert "the quick" in result
    assert "quick brown" in result
    assert "brown fox" in result


def test_is_duplicate_false_for_first_text(dedup):
    assert not dedup.is_duplicate("Hello world this is some content about our services.")


def test_is_duplicate_true_for_same_text(dedup):
    text = "Hello world this is some content about our services."
    dedup.is_duplicate(text)  # first: not a duplicate, adds to seen
    assert dedup.is_duplicate(text)  # second: IS a duplicate


def test_is_duplicate_false_for_different_text(dedup):
    dedup.is_duplicate("First document about cloud computing services.")
    assert not dedup.is_duplicate("Second document about consulting and strategy.")


def test_deduplicate_removes_near_duplicates(dedup):
    from processor.chunker import Chunk
    chunk_a = Chunk(url="a", title="A", page_type="other", text="Cloud services help businesses migrate infrastructure efficiently.",
                    chunk_index=0, chunk_total=1, section_heading="")
    # Nearly identical text
    chunk_b = Chunk(url="b", title="B", page_type="other", text="Cloud services help businesses migrate infrastructure efficiently.",
                    chunk_index=0, chunk_total=1, section_heading="")
    chunk_c = Chunk(url="c", title="C", page_type="other", text="Strategic consulting drives organizational transformation and growth.",
                    chunk_index=0, chunk_total=1, section_heading="")

    result = dedup.deduplicate([chunk_a, chunk_b, chunk_c])
    assert len(result) == 2  # chunk_b should be removed as duplicate of chunk_a
    assert result[0].url == "a"
    assert result[1].url == "c"


def test_reset_clears_seen_state(dedup):
    text = "Some content about cloud services and digital transformation."
    dedup.is_duplicate(text)
    assert dedup.is_duplicate(text)  # IS duplicate now
    dedup.reset()
    assert not dedup.is_duplicate(text)  # NOT duplicate after reset
