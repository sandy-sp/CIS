# processor/chunker.py
"""
Splits clean text into overlapping chunks for RAG.

Strategy:
1. Split on section headings (lines starting with # or ##) as primary boundaries
2. Within each section, do recursive character splitting at 800 chars with ~15% overlap (120 chars)
3. Each chunk gets metadata: chunk_index, chunk_total, section_heading
"""
from dataclasses import dataclass, field


_CHUNK_SIZE = 800       # target characters per chunk
_CHUNK_OVERLAP = 120    # ~15% overlap


@dataclass
class Chunk:
    url: str
    title: str
    page_type: str
    text: str
    chunk_index: int      # 0-based
    chunk_total: int      # total chunks for this page
    section_heading: str  # nearest preceding heading, or "" if none
    word_count: int = 0


class Chunker:
    """Splits clean text into overlapping chunks."""

    def chunk(self, text: str, url: str = "", title: str = "",
              page_type: str = "other") -> list[Chunk]:
        """
        Split text into chunks. Returns list of Chunk objects.
        Empty text returns empty list.
        """
        if not text or not text.strip():
            return []

        # Split into sections by heading lines (# or ## at start of line)
        sections = self._split_by_headings(text)

        raw_chunks: list[tuple[str, str]] = []  # (text, heading)
        for heading, section_text in sections:
            if not section_text.strip():
                continue
            pieces = self._split_text(section_text.strip(), _CHUNK_SIZE, _CHUNK_OVERLAP)
            for piece in pieces:
                if piece.strip():
                    raw_chunks.append((piece.strip(), heading))

        total = len(raw_chunks)
        return [
            Chunk(
                url=url,
                title=title,
                page_type=page_type,
                text=text_piece,
                chunk_index=i,
                chunk_total=total,
                section_heading=heading,
                word_count=len(text_piece.split()),
            )
            for i, (text_piece, heading) in enumerate(raw_chunks)
        ]

    def _split_by_headings(self, text: str) -> list[tuple[str, str]]:
        """Split text into (heading, content) sections at markdown heading lines."""
        lines = text.split("\n")
        sections: list[tuple[str, str]] = []
        current_heading = ""
        current_lines: list[str] = []

        for line in lines:
            stripped = line.strip()
            if stripped.startswith("#"):
                # Save previous section
                if current_lines or current_heading:
                    sections.append((current_heading, "\n".join(current_lines)))
                # Start new section
                current_heading = stripped.lstrip("#").strip()
                current_lines = []
            else:
                current_lines.append(line)

        # Save last section
        if current_lines or current_heading:
            sections.append((current_heading, "\n".join(current_lines)))

        return sections if sections else [("", text)]

    def _split_text(self, text: str, chunk_size: int, overlap: int) -> list[str]:
        """Recursively split text into chunks of at most chunk_size chars with overlap."""
        if len(text) <= chunk_size:
            return [text]

        chunks: list[str] = []
        start = 0
        while start < len(text):
            end = start + chunk_size
            if end >= len(text):
                chunks.append(text[start:])
                break
            # Try to break at a paragraph boundary (\n\n) within the last 200 chars
            break_pos = text.rfind("\n\n", start, end)
            if break_pos == -1 or break_pos <= start:
                # Fall back to sentence boundary (. followed by space)
                break_pos = text.rfind(". ", start, end)
                if break_pos == -1 or break_pos <= start:
                    break_pos = end
                else:
                    break_pos += 1  # include the period
            chunk = text[start:break_pos].strip()
            if chunk:
                chunks.append(chunk)
            start = break_pos - overlap
            if start < 0:
                start = 0

        return chunks
