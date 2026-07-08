"""Code block detection and smart reading for terminal output.

Finds fenced code blocks (triple backtick) in terminal buffer lines,
extracts metadata (language, boundaries, line count), and provides
navigation, copy, and offline explanation helpers.
"""

import re
from typing import List, Optional, Tuple

from lib.text_processing import ANSIParser


# Compiled patterns for the explain heuristic
_IMPORT_PATTERN = re.compile(r'^\s*(import\s+\w+|from\s+\w+\s+import\s+)')
_FUNCTION_DEF_PATTERN = re.compile(r'^\s*(?:def|fn|function|func)\s+(\w+)')
_CLASS_DEF_PATTERN = re.compile(r'^\s*(?:class|struct|impl)\s+(\w+)')
_LOOP_PATTERN = re.compile(r'^\s*(?:for|while|loop)\s')
_CONDITIONAL_PATTERN = re.compile(r'^\s*(?:if|elif|else|match|switch)\s')
_TRY_EXCEPT_PATTERN = re.compile(r'^\s*(?:try|except|catch|finally|rescue)\s*:?\s*')
_FENCE_OPEN_PATTERN = re.compile(r'^```(\w*)\s*$')
_FENCE_CLOSE_PATTERN = re.compile(r'^```\s*$')

# Copy truncation cap in characters
COPY_CAP = 5000


class CodeBlock:
    """Represents a single fenced code block detected in a buffer."""

    __slots__ = ("language", "start_line", "end_line")

    def __init__(self, language: Optional[str], start_line: int, end_line: int) -> None:
        self.language = language if language else None
        self.start_line = start_line
        self.end_line = end_line

    @property
    def line_count(self) -> int:
        """Number of content lines inside the fences (excluding fence lines)."""
        return self.end_line - self.start_line - 1

    @property
    def first_content_line(self) -> int:
        """Index of the first content line (line after the opening fence)."""
        return self.start_line + 1

    @property
    def last_content_line(self) -> int:
        """Index of the last content line (line before the closing fence)."""
        return self.end_line - 1

    def announce(self) -> str:
        """Return a metadata announcement string for screen reader output.

        Examples: 'Python block, 8 lines' or 'Code block, 2 lines'.
        """
        if self.language:
            label = self.language.capitalize() + " block"
        else:
            label = "Code block"
        count = self.line_count
        unit = "line" if count == 1 else "lines"
        return f"{label}, {count} {unit}"

    def get_line(self, line_idx: int, buffer: List[str]) -> str:
        """Return the content of a line within this block, ANSI-stripped.

        Args:
            line_idx: Absolute line index in the buffer.
            buffer: The full terminal buffer.

        Returns:
            Cleaned line text, or empty string if out of range.
        """
        if line_idx < self.first_content_line or line_idx > self.last_content_line:
            return ""
        return ANSIParser.stripANSI(buffer[line_idx])

    def next_line(self, current: int) -> Optional[int]:
        """Return the next content line index, or None if at the boundary."""
        nxt = current + 1
        if nxt > self.last_content_line:
            return None
        return nxt

    def prev_line(self, current: int) -> Optional[int]:
        """Return the previous content line index, or None if at the boundary."""
        prv = current - 1
        if prv < self.first_content_line:
            return None
        return prv

    def copy_text(self, buffer: List[str]) -> Tuple[str, bool]:
        """Return the content lines joined as text, truncated at COPY_CAP.

        Returns:
            Tuple of (text, truncated). truncated is True when the text
            was cut short at the cap.
        """
        content_lines = []
        for i in range(self.first_content_line, self.last_content_line + 1):
            content_lines.append(ANSIParser.stripANSI(buffer[i]))
        text = "\n".join(content_lines)
        if len(text) > COPY_CAP:
            return text[:COPY_CAP], True
        return text, False

    def explain(self, buffer: List[str]) -> str:
        """Return a concise offline explanation of the block content.

        Callers should check PrivacyGuard before calling this method.
        Heuristic detects: imports, function defs, class defs, loops,
        conditionals, and error handling. Returns a single sentence.
        """
        lines = []
        for i in range(self.first_content_line, self.last_content_line + 1):
            lines.append(ANSIParser.stripANSI(buffer[i]))

        return _build_explanation(lines)


class CodeBlockDetector:
    """Detects fenced code blocks in a terminal buffer."""

    def detect(self, buffer: List[str]) -> List[CodeBlock]:
        """Scan buffer lines and return a list of CodeBlock objects.

        Handles multiple adjacent blocks. ANSI codes are stripped before
        checking for fence markers.
        """
        blocks: List[CodeBlock] = []
        i = 0
        while i < len(buffer):
            clean = ANSIParser.stripANSI(buffer[i])
            m = _FENCE_OPEN_PATTERN.match(clean)
            if m:
                lang = m.group(1) or None
                open_idx = i
                # Search for closing fence
                j = i + 1
                while j < len(buffer):
                    close_clean = ANSIParser.stripANSI(buffer[j])
                    if _FENCE_CLOSE_PATTERN.match(close_clean):
                        blocks.append(CodeBlock(lang, open_idx, j))
                        i = j + 1
                        break
                    j += 1
                else:
                    # No closing fence found, skip this opening marker
                    i += 1
                continue
            i += 1
        return blocks

    @staticmethod
    def find_block_at(line_idx: int, blocks: List[CodeBlock]) -> Optional[CodeBlock]:
        """Return the CodeBlock containing line_idx, or None."""
        for block in blocks:
            if block.start_line <= line_idx <= block.end_line:
                return block
        return None


def _build_explanation(lines: List[str]) -> str:
    """Build a single-sentence explanation from code content lines.

    Detects imports, function definitions, class definitions, loops,
    conditionals, and error handling (try/except). Combines findings
    into one concise sentence.
    """
    imports = []
    functions = []
    classes = []
    has_loops = False
    has_conditionals = False
    has_error_handling = False

    for line in lines:
        if not line.strip():
            continue
        if _IMPORT_PATTERN.match(line):
            imports.append(line.strip())
        m_func = _FUNCTION_DEF_PATTERN.match(line)
        if m_func:
            functions.append(m_func.group(1))
        m_cls = _CLASS_DEF_PATTERN.match(line)
        if m_cls:
            classes.append(m_cls.group(1))
        if _LOOP_PATTERN.match(line):
            has_loops = True
        if _CONDITIONAL_PATTERN.match(line):
            has_conditionals = True
        if _TRY_EXCEPT_PATTERN.match(line):
            has_error_handling = True

    parts = []

    # Build the main subject
    if classes and functions:
        parts.append(
            f"Defines class {classes[0]} and function {functions[0]}"
        )
    elif classes:
        parts.append(f"Defines class {classes[0]}")
    elif functions:
        parts.append(f"Defines function {functions[0]}")
    elif imports:
        parts.append(f"Imports {len(imports)} module{'s' if len(imports) != 1 else ''}")
    else:
        # Include line count and first non-empty line for context
        non_empty = [l for l in lines if l.strip()]
        count = len(non_empty)
        if non_empty:
            first = non_empty[0].strip()[:40]
            parts.append(f"{count} lines, starting with: {first}")
        else:
            parts.append("Empty block")

    # Append qualifiers
    qualifiers = []
    if has_error_handling:
        qualifiers.append("error handling")
    if has_loops:
        qualifiers.append("loops")
    if has_conditionals and not has_error_handling:
        qualifiers.append("conditionals")
    if imports and (classes or functions):
        qualifiers.append(f"{len(imports)} import{'s' if len(imports) != 1 else ''}")

    if qualifiers:
        parts.append("with " + " and ".join(qualifiers))

    return " ".join(parts)
