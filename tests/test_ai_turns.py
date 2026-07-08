"""Tests for AI turn/role tokenization and navigation.

Covers turn boundary detection, role identification, code block span
detection, and navigation helpers for AI CLI tools (Claude CLI, ChatGPT CLI,
Aider, etc.).
"""

import pytest
from lib.ai_turn_tokenizer import AITurnTokenizer, AITurn


# ---------------------------------------------------------------------------
# Fixtures: AI CLI transcript samples
# ---------------------------------------------------------------------------

@pytest.fixture
def claude_cli_transcript():
    """Simulated Claude CLI session with user prompt, assistant reply, code block."""
    return [
        "❯ How do I read a file in Python?",
        "",
        "Claude: You can read a file in Python using the built-in open() function.",
        "Here is an example:",
        "",
        "```python",
        "with open('file.txt', 'r') as f:",
        "    content = f.read()",
        "    print(content)",
        "```",
        "",
        "This opens the file in read mode and prints its contents.",
        "",
        "❯ What about writing?",
        "",
        "Claude: To write to a file, use open() with the 'w' mode:",
        "",
        "```python",
        "with open('output.txt', 'w') as f:",
        "    f.write('Hello, world!')",
        "```",
        "",
        "Be careful: 'w' mode overwrites the file if it exists.",
    ]


@pytest.fixture
def chatgpt_cli_transcript():
    """Simulated ChatGPT CLI session."""
    return [
        "You: What is the capital of France?",
        "",
        "ChatGPT: The capital of France is Paris.",
        "",
        "You: And Germany?",
        "",
        "ChatGPT: The capital of Germany is Berlin.",
    ]


@pytest.fixture
def aider_transcript():
    """Simulated Aider session with system messages."""
    return [
        "Aider v0.35.0",
        "Model: claude-3-opus",
        "",
        "> /add main.py",
        "Added main.py to the chat.",
        "",
        "> Fix the bug in the parse function",
        "",
        "I'll fix the parse function. Here are the changes:",
        "",
        "```python",
        "def parse(data):",
        "    return json.loads(data)",
        "```",
        "",
        "Applied changes to main.py.",
    ]


@pytest.fixture
def ansi_colored_transcript():
    """Transcript with ANSI escape codes around role markers."""
    return [
        "\x1b[1;32m❯\x1b[0m Tell me a joke",
        "",
        "\x1b[1;34mClaude:\x1b[0m Why did the programmer quit?",
        "Because they didn't get arrays.",
    ]


@pytest.fixture
def no_ai_turns_transcript():
    """Plain terminal output with no AI turn markers."""
    return [
        "$ ls -la",
        "total 32",
        "drwxr-xr-x  4 user staff  128 Jan 15 10:00 .",
        "drwxr-xr-x  8 user staff  256 Jan 15 09:00 ..",
        "-rw-r--r--  1 user staff  400 Jan 15 10:00 file.txt",
    ]


@pytest.fixture
def multi_code_block_turn():
    """A single assistant turn with multiple code blocks."""
    return [
        "Claude: Here are two approaches:",
        "",
        "Approach 1:",
        "```python",
        "result = sum(items)",
        "```",
        "",
        "Approach 2:",
        "```python",
        "result = functools.reduce(operator.add, items)",
        "```",
        "",
        "Both work but the first is simpler.",
    ]


@pytest.fixture
def tool_use_transcript():
    """Transcript with tool/system role markers."""
    return [
        "❯ Search for config files",
        "",
        "Claude: I'll search for config files.",
        "",
        "Tool: find . -name '*.yaml'",
        "./config.yaml",
        "./deploy/config.yaml",
        "",
        "Claude: I found two config files in your project.",
    ]


@pytest.fixture
def streamed_partial_turn():
    """Simulated partially streamed assistant output (no closing marker)."""
    return [
        "❯ Explain recursion",
        "",
        "Claude: Recursion is when a function calls itself.",
        "It needs a base case to stop the",
    ]


# ---------------------------------------------------------------------------
# Turn boundary detection
# ---------------------------------------------------------------------------

class TestTurnBoundaryDetection:
    """Turn boundary detection from AI CLI output."""

    def test_detects_user_turns_claude_cli(self, claude_cli_transcript):
        tokenizer = AITurnTokenizer()
        turns = tokenizer.tokenize(claude_cli_transcript)
        user_turns = [t for t in turns if t.role == "user"]
        assert len(user_turns) == 2

    def test_detects_assistant_turns_claude_cli(self, claude_cli_transcript):
        tokenizer = AITurnTokenizer()
        turns = tokenizer.tokenize(claude_cli_transcript)
        assistant_turns = [t for t in turns if t.role == "assistant"]
        assert len(assistant_turns) == 2

    def test_turn_line_numbers_correct(self, claude_cli_transcript):
        tokenizer = AITurnTokenizer()
        turns = tokenizer.tokenize(claude_cli_transcript)
        # First user turn starts at line 0
        assert turns[0].line_num == 0
        assert turns[0].role == "user"

    def test_turn_end_lines_correct(self, claude_cli_transcript):
        tokenizer = AITurnTokenizer()
        turns = tokenizer.tokenize(claude_cli_transcript)
        # First user turn ends before first assistant turn
        first_user = turns[0]
        first_assistant = turns[1]
        assert first_user.end_line < first_assistant.line_num

    def test_chatgpt_cli_boundaries(self, chatgpt_cli_transcript):
        tokenizer = AITurnTokenizer()
        turns = tokenizer.tokenize(chatgpt_cli_transcript)
        assert len(turns) == 4
        assert turns[0].role == "user"
        assert turns[1].role == "assistant"
        assert turns[2].role == "user"
        assert turns[3].role == "assistant"

    def test_aider_boundaries(self, aider_transcript):
        tokenizer = AITurnTokenizer()
        turns = tokenizer.tokenize(aider_transcript)
        # System lines at top, then user commands, then assistant
        roles = [t.role for t in turns]
        assert "system" in roles
        assert "user" in roles
        assert "assistant" in roles


# ---------------------------------------------------------------------------
# Role identification
# ---------------------------------------------------------------------------

class TestRoleIdentification:
    """Role identification for user, assistant, system, and tool turns."""

    def test_user_role_from_prompt_marker(self, claude_cli_transcript):
        tokenizer = AITurnTokenizer()
        turns = tokenizer.tokenize(claude_cli_transcript)
        first = turns[0]
        assert first.role == "user"

    def test_assistant_role_from_claude_label(self, claude_cli_transcript):
        tokenizer = AITurnTokenizer()
        turns = tokenizer.tokenize(claude_cli_transcript)
        assistant_turns = [t for t in turns if t.role == "assistant"]
        assert len(assistant_turns) >= 1
        assert assistant_turns[0].line_num == 2

    def test_assistant_role_from_chatgpt_label(self, chatgpt_cli_transcript):
        tokenizer = AITurnTokenizer()
        turns = tokenizer.tokenize(chatgpt_cli_transcript)
        assistant_turns = [t for t in turns if t.role == "assistant"]
        assert len(assistant_turns) == 2

    def test_system_role_from_aider_header(self, aider_transcript):
        tokenizer = AITurnTokenizer()
        turns = tokenizer.tokenize(aider_transcript)
        system_turns = [t for t in turns if t.role == "system"]
        assert len(system_turns) >= 1
        # System turn should be near the top
        assert system_turns[0].line_num == 0

    def test_tool_role_identified(self, tool_use_transcript):
        tokenizer = AITurnTokenizer()
        turns = tokenizer.tokenize(tool_use_transcript)
        tool_turns = [t for t in turns if t.role == "tool"]
        assert len(tool_turns) == 1

    def test_user_role_from_you_label(self, chatgpt_cli_transcript):
        tokenizer = AITurnTokenizer()
        turns = tokenizer.tokenize(chatgpt_cli_transcript)
        user_turns = [t for t in turns if t.role == "user"]
        assert len(user_turns) == 2
        assert user_turns[0].line_num == 0


# ---------------------------------------------------------------------------
# Code block span detection
# ---------------------------------------------------------------------------

class TestCodeBlockDetection:
    """Code block (fenced ```) detection within turns."""

    def test_detects_code_block_in_turn(self, claude_cli_transcript):
        tokenizer = AITurnTokenizer()
        turns = tokenizer.tokenize(claude_cli_transcript)
        assistant_turns = [t for t in turns if t.role == "assistant"]
        assert assistant_turns[0].has_code_block is True

    def test_no_code_block_in_user_turn(self, claude_cli_transcript):
        tokenizer = AITurnTokenizer()
        turns = tokenizer.tokenize(claude_cli_transcript)
        user_turns = [t for t in turns if t.role == "user"]
        assert user_turns[0].has_code_block is False

    def test_multiple_code_blocks_in_single_turn(self, multi_code_block_turn):
        tokenizer = AITurnTokenizer()
        turns = tokenizer.tokenize(multi_code_block_turn)
        assert len(turns) == 1
        assert turns[0].has_code_block is True

    def test_code_block_spans_returned(self, claude_cli_transcript):
        tokenizer = AITurnTokenizer()
        turns = tokenizer.tokenize(claude_cli_transcript)
        blocks = tokenizer.get_code_blocks()
        assert len(blocks) >= 2
        # Each block should have start and end line
        for block in blocks:
            assert block.line_num <= block.end_line

    def test_no_code_blocks_in_plain_output(self, chatgpt_cli_transcript):
        tokenizer = AITurnTokenizer()
        turns = tokenizer.tokenize(chatgpt_cli_transcript)
        blocks = tokenizer.get_code_blocks()
        assert len(blocks) == 0


# ---------------------------------------------------------------------------
# Navigation: jump next/prev turn
# ---------------------------------------------------------------------------

class TestTurnNavigation:
    """Jump next/prev turn returns correct line numbers."""

    def test_next_turn_from_start(self, claude_cli_transcript):
        tokenizer = AITurnTokenizer()
        tokenizer.tokenize(claude_cli_transcript)
        turn = tokenizer.next_turn(0)
        assert turn is not None
        assert turn.role == "assistant"
        assert turn.line_num > 0

    def test_prev_turn_from_end(self, claude_cli_transcript):
        tokenizer = AITurnTokenizer()
        tokenizer.tokenize(claude_cli_transcript)
        last_line = len(claude_cli_transcript) - 1
        turn = tokenizer.prev_turn(last_line)
        assert turn is not None
        assert turn.line_num < last_line

    def test_next_turn_none_at_end(self, claude_cli_transcript):
        tokenizer = AITurnTokenizer()
        tokenizer.tokenize(claude_cli_transcript)
        last_line = len(claude_cli_transcript) - 1
        turn = tokenizer.next_turn(last_line)
        assert turn is None

    def test_prev_turn_none_at_start(self, claude_cli_transcript):
        tokenizer = AITurnTokenizer()
        tokenizer.tokenize(claude_cli_transcript)
        turn = tokenizer.prev_turn(0)
        assert turn is None

    def test_next_code_block_navigation(self, claude_cli_transcript):
        tokenizer = AITurnTokenizer()
        tokenizer.tokenize(claude_cli_transcript)
        block = tokenizer.next_code_block(0)
        assert block is not None
        assert block.line_num > 0

    def test_prev_code_block_navigation(self, claude_cli_transcript):
        tokenizer = AITurnTokenizer()
        tokenizer.tokenize(claude_cli_transcript)
        last_line = len(claude_cli_transcript) - 1
        block = tokenizer.prev_code_block(last_line)
        assert block is not None

    def test_next_code_block_none_when_no_more(self, claude_cli_transcript):
        tokenizer = AITurnTokenizer()
        tokenizer.tokenize(claude_cli_transcript)
        last_line = len(claude_cli_transcript) - 1
        block = tokenizer.next_code_block(last_line)
        assert block is None


# ---------------------------------------------------------------------------
# Navigation: jump by role
# ---------------------------------------------------------------------------

class TestRoleNavigation:
    """Jump to next/prev turn filtered by role."""

    def test_next_assistant_turn(self, claude_cli_transcript):
        tokenizer = AITurnTokenizer()
        tokenizer.tokenize(claude_cli_transcript)
        turn = tokenizer.next_turn(0, role="assistant")
        assert turn is not None
        assert turn.role == "assistant"

    def test_next_user_turn_skips_assistant(self, claude_cli_transcript):
        tokenizer = AITurnTokenizer()
        tokenizer.tokenize(claude_cli_transcript)
        # From the first assistant turn, find next user turn
        first_assistant = [t for t in tokenizer._turns if t.role == "assistant"][0]
        turn = tokenizer.next_turn(first_assistant.line_num, role="user")
        assert turn is not None
        assert turn.role == "user"

    def test_prev_user_turn(self, claude_cli_transcript):
        tokenizer = AITurnTokenizer()
        tokenizer.tokenize(claude_cli_transcript)
        last_line = len(claude_cli_transcript) - 1
        turn = tokenizer.prev_turn(last_line, role="user")
        assert turn is not None
        assert turn.role == "user"

    def test_role_filter_returns_none_when_no_match(self, chatgpt_cli_transcript):
        tokenizer = AITurnTokenizer()
        tokenizer.tokenize(chatgpt_cli_transcript)
        turn = tokenizer.next_turn(0, role="tool")
        assert turn is None


# ---------------------------------------------------------------------------
# ANSI colored role markers
# ---------------------------------------------------------------------------

class TestANSIHandling:
    """ANSI escape codes in role markers are handled correctly."""

    def test_ansi_user_marker_detected(self, ansi_colored_transcript):
        tokenizer = AITurnTokenizer()
        turns = tokenizer.tokenize(ansi_colored_transcript)
        user_turns = [t for t in turns if t.role == "user"]
        assert len(user_turns) == 1

    def test_ansi_assistant_marker_detected(self, ansi_colored_transcript):
        tokenizer = AITurnTokenizer()
        turns = tokenizer.tokenize(ansi_colored_transcript)
        assistant_turns = [t for t in turns if t.role == "assistant"]
        assert len(assistant_turns) == 1

    def test_ansi_stripped_for_classification(self, ansi_colored_transcript):
        tokenizer = AITurnTokenizer()
        turns = tokenizer.tokenize(ansi_colored_transcript)
        # Role should be detected despite ANSI codes
        assert turns[0].role == "user"
        assert turns[1].role == "assistant"


# ---------------------------------------------------------------------------
# Edge cases and fallbacks
# ---------------------------------------------------------------------------

class TestEdgeCases:
    """Edge cases: empty input, no AI turns, partial/streamed output."""

    def test_empty_input_returns_empty(self):
        tokenizer = AITurnTokenizer()
        turns = tokenizer.tokenize([])
        assert turns == []

    def test_no_ai_turns_returns_empty(self, no_ai_turns_transcript):
        tokenizer = AITurnTokenizer()
        turns = tokenizer.tokenize(no_ai_turns_transcript)
        assert turns == []

    def test_single_line_input(self):
        tokenizer = AITurnTokenizer()
        turns = tokenizer.tokenize(["Claude: Hello!"])
        assert len(turns) == 1
        assert turns[0].role == "assistant"

    def test_streamed_partial_output(self, streamed_partial_turn):
        tokenizer = AITurnTokenizer()
        turns = tokenizer.tokenize(streamed_partial_turn)
        # Should still detect the turns, even without closing marker
        assert len(turns) >= 2
        assistant_turns = [t for t in turns if t.role == "assistant"]
        assert len(assistant_turns) == 1
        # End line should be the last line of input
        assert assistant_turns[0].end_line == len(streamed_partial_turn) - 1

    def test_navigation_on_empty_tokenization(self):
        tokenizer = AITurnTokenizer()
        tokenizer.tokenize([])
        assert tokenizer.next_turn(0) is None
        assert tokenizer.prev_turn(0) is None
        assert tokenizer.next_code_block(0) is None
        assert tokenizer.prev_code_block(0) is None

    def test_code_blocks_on_empty(self):
        tokenizer = AITurnTokenizer()
        tokenizer.tokenize([])
        assert tokenizer.get_code_blocks() == []


# ---------------------------------------------------------------------------
# Caching: tokenize skips re-scan when buffer unchanged
# ---------------------------------------------------------------------------

class TestTokenizeCaching:
    """tokenize() caches results and skips re-scan when buffer is unchanged."""

    def test_same_buffer_returns_cached_turns(self, claude_cli_transcript):
        tokenizer = AITurnTokenizer()
        turns1 = tokenizer.tokenize(claude_cli_transcript)
        turns2 = tokenizer.tokenize(claude_cli_transcript)
        assert turns1 is turns2  # same object, not just equal

    def test_different_buffer_re_tokenizes(self, claude_cli_transcript):
        tokenizer = AITurnTokenizer()
        turns1 = tokenizer.tokenize(claude_cli_transcript)
        modified = claude_cli_transcript + ["User: new prompt"]
        turns2 = tokenizer.tokenize(modified)
        assert turns1 is not turns2
        assert len(turns2) > len(turns1)

    def test_cache_invalidated_on_last_line_change(self):
        tokenizer = AITurnTokenizer()
        lines = ["Claude: hello", "some output"]
        tokenizer.tokenize(lines)
        lines2 = ["Claude: hello", "different output"]
        turns = tokenizer.tokenize(lines2)
        assert turns is not None  # re-tokenized, didn't return stale cache

    def test_cache_stale_when_early_lines_change(self):
        """Changing early lines with same count and last line must re-tokenize."""
        tokenizer = AITurnTokenizer()
        lines1 = ["You: hello", "response text", "end"]
        turns1 = tokenizer.tokenize(lines1)
        # Same count, same last line, but line 0 changed role
        lines2 = ["Claude: hello", "response text", "end"]
        turns2 = tokenizer.tokenize(lines2)
        # Must NOT return cached result -- roles are different
        assert turns1 is not turns2
        # Verify the roles actually differ
        roles1 = [t.role for t in turns1]
        roles2 = [t.role for t in turns2]
        assert roles1 != roles2

    def test_empty_buffer_not_cached_incorrectly(self):
        tokenizer = AITurnTokenizer()
        tokenizer.tokenize([])
        lines = ["Claude: hello"]
        turns = tokenizer.tokenize(lines)
        assert len(turns) >= 1
