"""Document text extraction, cleaning, and sliding-window chunking."""

import re
from typing import List
from app.rag.models import DocumentChunk, RAGDocument


class TextChunker:
    """Configurable sliding-window text chunker with paragraph and sentence boundary preservation."""

    def __init__(self, chunk_size: int = 400, chunk_overlap: int = 80) -> None:
        """Initialize chunker.

        Args:
            chunk_size: Target character length per chunk (default 400).
            chunk_overlap: Overlapping character count between consecutive chunks (default 80).
        """
        if chunk_overlap >= chunk_size:
            raise ValueError("chunk_overlap must be strictly less than chunk_size")
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    @staticmethod
    def clean_text(text: str) -> str:
        """Normalize whitespace, remove non-printable characters, and trim text."""
        # Normalize CRLF and CR to LF
        cleaned = text.replace("\r\n", "\n").replace("\r", "\n")
        # Replace non-newline whitespace tabs etc with space
        cleaned = re.sub(r"[\t\f\v]", " ", cleaned)
        # Collapse multiple horizontal spaces
        cleaned = re.sub(r"[^\S\n]+", " ", cleaned)
        # Collapse spaces around newlines
        cleaned = re.sub(r" ?\n ?", "\n", cleaned)
        # Collapse excessive newlines (max 2 consecutive)
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
        return cleaned.strip()

    def chunk_document(self, document: RAGDocument) -> List[DocumentChunk]:
        """Split a RAGDocument into overlapping passage chunks."""
        cleaned_content = self.clean_text(document.content)
        if not cleaned_content:
            return []

        chunks: List[DocumentChunk] = []

        # If document is shorter than target chunk size, return as a single chunk
        if len(cleaned_content) <= self.chunk_size:
            chunk_id = f"{document.doc_id}#0"
            chunks.append(
                DocumentChunk(
                    chunk_id=chunk_id,
                    doc_id=document.doc_id,
                    title=document.title,
                    text=cleaned_content,
                    chunk_index=0,
                    metadata=dict(document.metadata),
                    token_count=len(cleaned_content.split()),
                )
            )
            return chunks

        start = 0
        step = self.chunk_size - self.chunk_overlap
        idx = 0

        while start < len(cleaned_content):
            end = min(start + self.chunk_size, len(cleaned_content))
            slice_text = cleaned_content[start:end]

            # If not at the end of text, attempt to break at a natural sentence or newline boundary
            if end < len(cleaned_content):
                # Search for sentence terminal (. ? !) or newline near the boundary
                last_punct = max(
                    slice_text.rfind(".\n"),
                    slice_text.rfind(". "),
                    slice_text.rfind("?\n"),
                    slice_text.rfind("? "),
                    slice_text.rfind("!\n"),
                    slice_text.rfind("! "),
                    slice_text.rfind("\n\n"),
                )
                if last_punct != -1 and last_punct > (self.chunk_size * 0.5):
                    # Cut right after punctuation
                    end = start + last_punct + 1
                    slice_text = cleaned_content[start:end]

            passage = slice_text.strip()
            if passage:
                chunk_id = f"{document.doc_id}#{idx}"
                chunks.append(
                    DocumentChunk(
                        chunk_id=chunk_id,
                        doc_id=document.doc_id,
                        title=document.title,
                        text=passage,
                        chunk_index=idx,
                        metadata=dict(document.metadata),
                        token_count=len(passage.split()),
                    )
                )
                idx += 1

            start += step
            # Avoid infinite loop if step didn't advance
            if start >= end and end < len(cleaned_content):
                start = end

        return chunks
