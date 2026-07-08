"""Tests for the CodeBlockDetector in lib/code_block_reader.py.

RED phase: all tests written before implementation exists.
"""
import sys
import pytest


# ---------------------------------------------------------------------------
# Fixtures: sample terminal buffers with fenced code blocks
# ---------------------------------------------------------------------------

PYTHON_BLOCK = [
    "Here is a Python example:",
    "```python",
    "import os",
    "import sys",
    "",
    "def calculate_total(items):",
    "    total = 0",
    "    for item in items:",
    "        total += item.price",
    "    return total",
    "```",
    "That was the example.",
]

RUST_BLOCK = [
    "Check this Rust snippet:",
    "```rust",
    "fn main() {",
    '    println!("hello");',
    "}",
    "```",
    "End of snippet.",
]

JS_BLOCK = [
    "```javascript",
    "const x = 42;",
    "if (x > 0) {",
    "  console.log(x);",
    "}",
    "```",
]

PLAIN_BLOCK = [
    "Some output:",
    "```",
    "line one",
    "line two",
    "```",
    "Done.",
]

ADJACENT_BLOCKS = [
    "First block:",
    "```python",
    "print('hello')",
    "```",
    "Second block:",
    "```rust",
    "fn foo() {}",
    "```",
    "End.",
]

ANSI_BLOCK = [
    "Result:",
    "```python",
    "\x1b[32mimport\x1b[0m os",
    "\x1b[31mprint\x1b[0m('hello')",
    "```",
]

BLOCK_WITH_IMPORTS_AND_CLASS = [
    "```python",
    "import os",
    "import json",
    "from pathlib import Path",
    "",
    "class DataProcessor:",
    "    def __init__(self):",
    "        self.data = []",
    "",
    "    def process(self):",
    "        for item in self.data:",
    "            if item.valid:",
    "                yield item",
    "```",
]

BLOCK_WITH_FUNCTION_AND_TRY = [
    "```python",
    "def calculate_total(items):",
    "    try:",
    "        total = sum(i.price for i in items)",
    "    except AttributeError:",
    "        return 0",
    "    return total",
    "```",
]

NO_BLOCKS = [
    "Just some plain text.",
    "No code fences here.",
    "More output.",
]


# ---------------------------------------------------------------------------
# Tests: Language detection from fence markers
# ---------------------------------------------------------------------------

class TestLanguageDetection:
    """Detect the language tag after the opening triple backtick."""

    def test_python_language(self):
        from lib.code_block_reader import CodeBlockDetector
        det = CodeBlockDetector()
        blocks = det.detect(PYTHON_BLOCK)
        assert len(blocks) >= 1
        assert blocks[0].language == "python"

    def test_rust_language(self):
        from lib.code_block_reader import CodeBlockDetector
        det = CodeBlockDetector()
        blocks = det.detect(RUST_BLOCK)
        assert blocks[0].language == "rust"

    def test_javascript_language(self):
        from lib.code_block_reader import CodeBlockDetector
        det = CodeBlockDetector()
        blocks = det.detect(JS_BLOCK)
        assert blocks[0].language == "javascript"

    def test_plain_no_language(self):
        from lib.code_block_reader import CodeBlockDetector
        det = CodeBlockDetector()
        blocks = det.detect(PLAIN_BLOCK)
        assert blocks[0].language is None or blocks[0].language == ""


# ---------------------------------------------------------------------------
# Tests: Block boundary detection (start/end lines)
# ---------------------------------------------------------------------------

class TestBlockBoundaries:
    """Detect the start and end line indices of fenced code blocks."""

    def test_python_block_start(self):
        from lib.code_block_reader import CodeBlockDetector
        det = CodeBlockDetector()
        blocks = det.detect(PYTHON_BLOCK)
        # Opening fence is at line index 1
        assert blocks[0].start_line == 1

    def test_python_block_end(self):
        from lib.code_block_reader import CodeBlockDetector
        det = CodeBlockDetector()
        blocks = det.detect(PYTHON_BLOCK)
        # Closing fence is at line index 10
        assert blocks[0].end_line == 10

    def test_js_block_boundaries(self):
        from lib.code_block_reader import CodeBlockDetector
        det = CodeBlockDetector()
        blocks = det.detect(JS_BLOCK)
        assert blocks[0].start_line == 0
        assert blocks[0].end_line == 5

    def test_no_blocks_returns_empty(self):
        from lib.code_block_reader import CodeBlockDetector
        det = CodeBlockDetector()
        blocks = det.detect(NO_BLOCKS)
        assert blocks == []


# ---------------------------------------------------------------------------
# Tests: Line count metadata
# ---------------------------------------------------------------------------

class TestLineCountMetadata:
    """line_count reports the number of content lines inside the fences."""

    def test_python_block_line_count(self):
        from lib.code_block_reader import CodeBlockDetector
        det = CodeBlockDetector()
        blocks = det.detect(PYTHON_BLOCK)
        # Lines between opening and closing fence (exclusive of fences)
        # indices 2..9 = 8 content lines
        assert blocks[0].line_count == 8

    def test_rust_block_line_count(self):
        from lib.code_block_reader import CodeBlockDetector
        det = CodeBlockDetector()
        blocks = det.detect(RUST_BLOCK)
        # indices 2..4 = 3 content lines
        assert blocks[0].line_count == 3

    def test_plain_block_line_count(self):
        from lib.code_block_reader import CodeBlockDetector
        det = CodeBlockDetector()
        blocks = det.detect(PLAIN_BLOCK)
        assert blocks[0].line_count == 2


# ---------------------------------------------------------------------------
# Tests: Metadata announcement string
# ---------------------------------------------------------------------------

class TestMetadataAnnouncement:
    """announce() returns a string like 'Python block, 8 lines'."""

    def test_python_block_announcement(self):
        from lib.code_block_reader import CodeBlockDetector
        det = CodeBlockDetector()
        blocks = det.detect(PYTHON_BLOCK)
        ann = blocks[0].announce()
        assert "Python" in ann or "python" in ann
        assert "8 lines" in ann

    def test_plain_block_announcement(self):
        from lib.code_block_reader import CodeBlockDetector
        det = CodeBlockDetector()
        blocks = det.detect(PLAIN_BLOCK)
        ann = blocks[0].announce()
        assert "2 lines" in ann
        # No language, should say "Code block" or similar
        assert "block" in ann.lower()

    def test_single_line_block_says_line_not_lines(self):
        """A block with 1 content line should say '1 line', not '1 lines'."""
        from lib.code_block_reader import CodeBlockDetector
        det = CodeBlockDetector()
        single_line_block = ["```python", "x = 1", "```"]
        blocks = det.detect(single_line_block)
        ann = blocks[0].announce()
        assert "1 line" in ann
        # Must not say "1 lines"
        assert "1 lines" not in ann


# ---------------------------------------------------------------------------
# Tests: Stepping within block boundaries
# ---------------------------------------------------------------------------

class TestSteppingWithinBlock:
    """next_line/prev_line stay within the content lines of the block."""

    def test_step_forward_within_block(self):
        from lib.code_block_reader import CodeBlockDetector
        det = CodeBlockDetector()
        blocks = det.detect(PYTHON_BLOCK)
        block = blocks[0]
        # Start at first content line
        line_idx = block.first_content_line
        text = block.get_line(line_idx, PYTHON_BLOCK)
        assert "import os" in text
        # Step forward
        next_idx = block.next_line(line_idx)
        assert next_idx == line_idx + 1
        text2 = block.get_line(next_idx, PYTHON_BLOCK)
        assert "import sys" in text2

    def test_step_forward_stops_at_end(self):
        from lib.code_block_reader import CodeBlockDetector
        det = CodeBlockDetector()
        blocks = det.detect(PYTHON_BLOCK)
        block = blocks[0]
        # Go to last content line
        last = block.last_content_line
        # Trying to step forward should return None (boundary)
        assert block.next_line(last) is None

    def test_step_backward_within_block(self):
        from lib.code_block_reader import CodeBlockDetector
        det = CodeBlockDetector()
        blocks = det.detect(PYTHON_BLOCK)
        block = blocks[0]
        second_line = block.first_content_line + 1
        prev = block.prev_line(second_line)
        assert prev == block.first_content_line

    def test_step_backward_stops_at_start(self):
        from lib.code_block_reader import CodeBlockDetector
        det = CodeBlockDetector()
        blocks = det.detect(PYTHON_BLOCK)
        block = blocks[0]
        first = block.first_content_line
        assert block.prev_line(first) is None


# ---------------------------------------------------------------------------
# Tests: Copy with truncation cap
# ---------------------------------------------------------------------------

class TestCopyTruncation:
    """copy_text() returns block content, truncated at 5000 chars with warning."""

    def test_short_block_not_truncated(self):
        from lib.code_block_reader import CodeBlockDetector
        det = CodeBlockDetector()
        blocks = det.detect(RUST_BLOCK)
        text, truncated = blocks[0].copy_text(RUST_BLOCK)
        assert truncated is False
        assert "fn main()" in text

    def test_long_block_truncated(self):
        from lib.code_block_reader import CodeBlockDetector
        det = CodeBlockDetector()
        # Build a block with content exceeding 5000 chars
        long_lines = ["```python"]
        for i in range(300):
            long_lines.append(f"x_{i} = 'a' * 50  # padding line number {i}")
        long_lines.append("```")
        blocks = det.detect(long_lines)
        text, truncated = blocks[0].copy_text(long_lines)
        assert truncated is True
        assert len(text) <= 5000

    def test_truncation_cap_value(self):
        """The cap should be exactly 5000 characters."""
        from lib.code_block_reader import CodeBlockDetector
        det = CodeBlockDetector()
        long_lines = ["```"]
        for i in range(500):
            long_lines.append("x" * 50)
        long_lines.append("```")
        blocks = det.detect(long_lines)
        text, truncated = blocks[0].copy_text(long_lines)
        if truncated:
            assert len(text) <= 5000


# ---------------------------------------------------------------------------
# Tests: Explain block heuristic
# ---------------------------------------------------------------------------

class TestExplainBlock:
    """explain() returns a concise offline summary of the block content."""

    def setup_method(self):
        import config as cfg
        cfg.conf["terminalAccess"]["codeBlockExplain"] = True

    def teardown_method(self):
        import config as cfg
        cfg.conf["terminalAccess"]["codeBlockExplain"] = False

    def test_explain_detects_function_def(self):
        from lib.code_block_reader import CodeBlockDetector
        det = CodeBlockDetector()
        blocks = det.detect(BLOCK_WITH_FUNCTION_AND_TRY)
        explanation = blocks[0].explain(BLOCK_WITH_FUNCTION_AND_TRY)
        assert "calculate_total" in explanation
        assert "function" in explanation.lower() or "def" in explanation.lower()

    def test_explain_detects_class_def(self):
        from lib.code_block_reader import CodeBlockDetector
        det = CodeBlockDetector()
        blocks = det.detect(BLOCK_WITH_IMPORTS_AND_CLASS)
        explanation = blocks[0].explain(BLOCK_WITH_IMPORTS_AND_CLASS)
        assert "DataProcessor" in explanation
        assert "class" in explanation.lower()

    def test_explain_detects_imports(self):
        from lib.code_block_reader import CodeBlockDetector
        det = CodeBlockDetector()
        blocks = det.detect(BLOCK_WITH_IMPORTS_AND_CLASS)
        explanation = blocks[0].explain(BLOCK_WITH_IMPORTS_AND_CLASS)
        assert "import" in explanation.lower()

    def test_explain_detects_error_handling(self):
        from lib.code_block_reader import CodeBlockDetector
        det = CodeBlockDetector()
        blocks = det.detect(BLOCK_WITH_FUNCTION_AND_TRY)
        explanation = blocks[0].explain(BLOCK_WITH_FUNCTION_AND_TRY)
        assert "error handling" in explanation.lower() or "try" in explanation.lower() or "except" in explanation.lower()

    def test_explain_returns_single_sentence(self):
        from lib.code_block_reader import CodeBlockDetector
        det = CodeBlockDetector()
        blocks = det.detect(BLOCK_WITH_FUNCTION_AND_TRY)
        explanation = blocks[0].explain(BLOCK_WITH_FUNCTION_AND_TRY)
        # Should be a single sentence (no period-separated multiple sentences,
        # allow one trailing period)
        stripped = explanation.rstrip(".")
        assert "." not in stripped


# ---------------------------------------------------------------------------
# Tests: Explain disabled when config key off
# ---------------------------------------------------------------------------

class TestExplainConfig:
    """explain is guarded by PrivacyGuard at the script level."""

    def test_privacy_guard_blocks_explain_when_disabled(self):
        """PrivacyGuard blocks explain_code when codeBlockExplain is False."""
        from unittest.mock import Mock
        from lib.privacy import PrivacyGuard
        guard = PrivacyGuard()
        mgr = Mock()
        mgr.get = Mock(side_effect=lambda k, d=None: {
            "codeBlockExplain": False,
            "privacyAnnounce": True,
        }.get(k, d))
        allowed, msg = guard.check_feature("explain_code", mgr)
        assert not allowed
        assert "disabled" in msg.lower() or "privacy" in msg.lower()

    def test_explain_returns_content_unconditionally(self):
        """explain() returns a real summary (guard is at call site)."""
        from lib.code_block_reader import CodeBlockDetector
        det = CodeBlockDetector()
        blocks = det.detect(BLOCK_WITH_FUNCTION_AND_TRY)
        result = blocks[0].explain(BLOCK_WITH_FUNCTION_AND_TRY)
        assert len(result) > 0


# ---------------------------------------------------------------------------
# Tests: ANSI codes stripped for processing
# ---------------------------------------------------------------------------

class TestANSIStripping:
    """ANSI escape codes in code blocks are stripped for content processing."""

    def test_ansi_stripped_in_detection(self):
        from lib.code_block_reader import CodeBlockDetector
        det = CodeBlockDetector()
        blocks = det.detect(ANSI_BLOCK)
        assert len(blocks) == 1
        assert blocks[0].language == "python"

    def test_ansi_stripped_in_copy(self):
        from lib.code_block_reader import CodeBlockDetector
        det = CodeBlockDetector()
        blocks = det.detect(ANSI_BLOCK)
        text, _ = blocks[0].copy_text(ANSI_BLOCK)
        # Should not contain escape sequences
        assert "\x1b" not in text
        assert "import" in text

    def test_ansi_stripped_in_get_line(self):
        from lib.code_block_reader import CodeBlockDetector
        det = CodeBlockDetector()
        blocks = det.detect(ANSI_BLOCK)
        line = blocks[0].get_line(blocks[0].first_content_line, ANSI_BLOCK)
        assert "\x1b" not in line
        assert "import" in line


# ---------------------------------------------------------------------------
# Tests: Nested/adjacent code blocks
# ---------------------------------------------------------------------------

class TestAdjacentBlocks:
    """Multiple code blocks in the same buffer are detected separately."""

    def test_two_adjacent_blocks_detected(self):
        from lib.code_block_reader import CodeBlockDetector
        det = CodeBlockDetector()
        blocks = det.detect(ADJACENT_BLOCKS)
        assert len(blocks) == 2

    def test_adjacent_blocks_languages(self):
        from lib.code_block_reader import CodeBlockDetector
        det = CodeBlockDetector()
        blocks = det.detect(ADJACENT_BLOCKS)
        assert blocks[0].language == "python"
        assert blocks[1].language == "rust"

    def test_adjacent_blocks_boundaries_no_overlap(self):
        from lib.code_block_reader import CodeBlockDetector
        det = CodeBlockDetector()
        blocks = det.detect(ADJACENT_BLOCKS)
        # First block ends before second block starts
        assert blocks[0].end_line < blocks[1].start_line

    def test_find_block_at_line(self):
        """find_block_at() returns the block containing a given line index."""
        from lib.code_block_reader import CodeBlockDetector
        det = CodeBlockDetector()
        blocks = det.detect(ADJACENT_BLOCKS)
        # Line 2 is inside the first block (content line "print('hello')")
        found = det.find_block_at(2, blocks)
        assert found is not None
        assert found.language == "python"

    def test_find_block_at_outside_returns_none(self):
        from lib.code_block_reader import CodeBlockDetector
        det = CodeBlockDetector()
        blocks = det.detect(ADJACENT_BLOCKS)
        # Line 4 is "Second block:" which is between the two blocks
        found = det.find_block_at(4, blocks)
        assert found is None
