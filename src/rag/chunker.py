"""Recursive chunker and document models for GreenSM Policy RAG."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Document:
    """Document chunk with unique ID, content, and metadata."""

    id: str
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)


class RecursiveChunker:
    """Recursively split policy text using hierarchical markdown and natural separators.

    Separators:
        1. "\n## " / "\n### " (markdown headers)
        2. "\n\n" (paragraphs)
        3. "\n" (line breaks)
        4. ". " (sentences)
        5. " " (words)
        6. "" (characters)
    """

    DEFAULT_SEPARATORS = ["\n## ", "\n### ", "\n\n", "\n", ". ", " ", ""]

    def __init__(
        self,
        chunk_size: int = 800,
        chunk_overlap: int = 100,
        separators: list[str] | None = None,
    ) -> None:
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.separators = separators or self.DEFAULT_SEPARATORS

    def split_text(self, text: str) -> list[str]:
        """Split raw text into chunks adhering to chunk_size and chunk_overlap."""
        if not text or not text.strip():
            return []
        return self._split(text.strip(), self.separators)

    def _split(self, current_text: str, remaining_separators: list[str]) -> list[str]:
        current_text = current_text.strip()
        if len(current_text) <= self.chunk_size:
            return [current_text] if current_text else []

        if not remaining_separators:
            # Fallback to hard character slicing with overlap
            chunks: list[str] = []
            step = max(1, self.chunk_size - self.chunk_overlap)
            for i in range(0, len(current_text), step):
                chunks.append(current_text[i : i + self.chunk_size])
                if i + self.chunk_size >= len(current_text):
                    break
            return chunks

        chosen_sep = None
        chosen_idx = len(remaining_separators)
        for i, sep in enumerate(remaining_separators):
            if sep == "" or sep in current_text:
                chosen_sep = sep
                chosen_idx = i + 1
                break

        if chosen_sep is None or chosen_sep == "":
            step = max(1, self.chunk_size - self.chunk_overlap)
            return [current_text[i : i + self.chunk_size] for i in range(0, len(current_text), step)]

        # Split on chosen separator
        if chosen_sep == ". ":
            raw_splits = re.split(r"(?<=\.) ", current_text)
        elif chosen_sep.startswith("\n#"):
            raw_splits = current_text.split(chosen_sep)
            # restore header prefix for subsequent parts
            raw_splits = [s if idx == 0 else f"{chosen_sep.strip()} {s}" for idx, s in enumerate(raw_splits)]
        else:
            raw_splits = current_text.split(chosen_sep)

        raw_splits = [s for s in raw_splits if s.strip()]

        # Now merge splits while respecting chunk_size
        docs: list[str] = []
        current_doc: list[str] = []
        total_len = 0
        join_sep = "" if chosen_sep == ". " else chosen_sep

        for piece in raw_splits:
            if len(piece) > self.chunk_size:
                # If a single piece is too large, recurse with remaining separators.
                # Use remaining_separators[chosen_idx:] so we advance past the separator
                # already tried.  If that sub-list is empty the base case (no separators)
                # triggers character slicing — no infinite recursion is possible.
                if current_doc:
                    docs.append(join_sep.join(current_doc).strip())
                    current_doc = []
                    total_len = 0
                next_seps = remaining_separators[chosen_idx:]
                sub_chunks = self._split(piece, next_seps)
                docs.extend(sub_chunks)
            else:
                sep_len = len(join_sep) if current_doc else 0
                if total_len + sep_len + len(piece) <= self.chunk_size:
                    current_doc.append(piece)
                    total_len += sep_len + len(piece)
                else:
                    if current_doc:
                        docs.append(join_sep.join(current_doc).strip())
                    current_doc = [piece]
                    total_len = len(piece)

        if current_doc:
            docs.append(join_sep.join(current_doc).strip())

        return [d for d in docs if d]

    def split_document(
        self,
        doc_id: str,
        content: str,
        base_metadata: dict[str, Any] | None = None,
    ) -> list[Document]:
        """Split document content into structured Document objects."""
        raw_chunks = self.split_text(content)
        docs: list[Document] = []
        base_meta = base_metadata or {}

        for idx, chunk_text in enumerate(raw_chunks):
            chunk_hash = hashlib.md5(chunk_text.encode()).hexdigest()[:8]
            chunk_id = f"{doc_id}#chunk_{idx:03d}"
            metadata = {
                **base_meta,
                "doc_id": doc_id,
                "chunk_index": idx,
                "total_chunks": len(raw_chunks),
                "chunk_hash": chunk_hash,
                "char_length": len(chunk_text),
            }
            docs.append(Document(id=chunk_id, content=chunk_text, metadata=metadata))
        return docs
