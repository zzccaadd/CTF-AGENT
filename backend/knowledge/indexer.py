"""Deterministic markdown/text chunking for offline knowledge ingestion."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TextChunk:
    text: str
    ordinal: int
    section: str
    line_start: int
    line_end: int


def split_text(text: str, *, max_chars: int = 1600) -> list[TextChunk]:
    """Split documents at headings/blocks while keeping stable line provenance."""
    if max_chars < 200:
        raise ValueError("max_chars must be at least 200")
    lines = text.replace("\r\n", "\n").replace("\r", "\n").splitlines()
    if not lines:
        return []

    blocks: list[tuple[str, int, int, str]] = []
    section = ""
    block_lines: list[str] = []
    block_start = 1
    in_code = False

    def flush(end_line: int) -> None:
        nonlocal block_lines, block_start
        content = "\n".join(block_lines).strip()
        if content:
            blocks.append((content, block_start, end_line, section))
        block_lines = []

    for number, line in enumerate(lines, 1):
        stripped = line.strip()
        if stripped.startswith("```"):
            if not block_lines:
                block_start = number
            block_lines.append(line)
            in_code = not in_code
            if not in_code:
                flush(number)
            continue
        if not in_code and stripped.startswith("#"):
            flush(number - 1)
            section = stripped.lstrip("#").strip()
            block_start = number
            block_lines.append(line)
            continue
        if not in_code and not stripped:
            flush(number - 1)
            block_start = number + 1
            continue
        if not block_lines:
            block_start = number
        block_lines.append(line)
    flush(len(lines))

    chunks: list[TextChunk] = []
    current_text = ""
    current_start = 1
    current_end = 1
    current_section = ""

    def emit() -> None:
        nonlocal current_text
        if current_text.strip():
            chunks.append(
                TextChunk(
                    text=current_text.strip(),
                    ordinal=len(chunks),
                    section=current_section,
                    line_start=current_start,
                    line_end=current_end,
                )
            )
        current_text = ""

    for content, start, end, block_section in blocks:
        if len(content) > max_chars:
            emit()
            for offset in range(0, len(content), max_chars):
                part = content[offset : offset + max_chars].strip()
                if part:
                    chunks.append(
                        TextChunk(
                            text=part,
                            ordinal=len(chunks),
                            section=block_section,
                            line_start=start,
                            line_end=end,
                        )
                    )
            continue
        separator = "\n\n" if current_text else ""
        if current_text and block_section != current_section:
            emit()
            separator = ""
        if current_text and len(current_text) + len(separator) + len(content) > max_chars:
            emit()
            separator = ""
        if not current_text:
            current_start = start
            current_section = block_section
        current_text += separator + content
        current_end = end
    emit()
    return chunks
