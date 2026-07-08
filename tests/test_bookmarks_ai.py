"""
Tests for AI turn detection in bookmarks and navigation.

RED phase: all tests written before implementation.
Covers: _auto_label AI role detection, list_ai_turns, AiTurnListDialog wiring.
"""
import sys
from unittest.mock import Mock, MagicMock, patch
import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_manager_with_buffer(buffer_lines, cursor_line_idx=0):
    """Create a BookmarkManager with a mock terminal whose buffer is buffer_lines.

    Returns (manager, mock_pos).
    """
    from lib.navigation import BookmarkManager

    terminal = Mock()
    manager = BookmarkManager(terminal)

    line_text = buffer_lines[cursor_line_idx] if cursor_line_idx < len(buffer_lines) else ""
    mock_pos = Mock()
    mock_pos.bookmark = "bm_obj"
    mock_pos.text = line_text

    move_count = [0]
    def fake_move_back(unit, count):
        if count == -1 and move_count[0] < cursor_line_idx:
            move_count[0] += 1
            return -1
        return 0

    expanded_copy = Mock()
    expanded_copy.text = line_text
    def fake_expand(unit):
        expanded_copy.text = line_text
    expanded_copy.expand = fake_expand
    expanded_copy.collapse = Mock()
    expanded_copy.move = fake_move_back

    mock_pos.copy = Mock(return_value=expanded_copy)
    mock_pos.collapse = Mock()
    mock_pos.move = fake_move_back

    manager._buffer_lines = buffer_lines

    return manager, mock_pos


# ---------------------------------------------------------------------------
# 1. Auto-label: AI user prompt with chevron
# ---------------------------------------------------------------------------

def test_auto_label_ai_user_chevron():
    """Lines starting with the chevron marker get label 'user: <text>'."""
    from lib.navigation import BookmarkManager

    buffer = [
        "\u276f hello world, how are you today?",
    ]
    manager, mock_pos = _make_manager_with_buffer(buffer, cursor_line_idx=0)

    label = manager._auto_label(buffer[0], 0, buffer)
    assert label.startswith("user: ")
    assert "hello world" in label


def test_auto_label_ai_user_gt():
    """Lines starting with '> ' get label 'user: <text>'."""
    from lib.navigation import BookmarkManager

    buffer = [
        "> tell me about Python",
    ]
    manager, _ = _make_manager_with_buffer(buffer, cursor_line_idx=0)

    label = manager._auto_label(buffer[0], 0, buffer)
    assert label.startswith("user: ")
    assert "tell me about Python" in label


def test_auto_label_ai_user_you_colon():
    """Lines starting with 'You:' get label 'user: <text>'."""
    from lib.navigation import BookmarkManager

    buffer = [
        "You: explain recursion to me",
    ]
    manager, _ = _make_manager_with_buffer(buffer, cursor_line_idx=0)

    label = manager._auto_label(buffer[0], 0, buffer)
    assert label.startswith("user: ")
    assert "explain recursion" in label


# ---------------------------------------------------------------------------
# 2. Auto-label: AI assistant responses
# ---------------------------------------------------------------------------

def test_auto_label_ai_assistant_claude():
    """Lines starting with 'Claude:' get label 'assistant: <text>'."""
    from lib.navigation import BookmarkManager

    buffer = [
        "Claude: Here is a summary of the changes I made",
    ]
    manager, _ = _make_manager_with_buffer(buffer, cursor_line_idx=0)

    label = manager._auto_label(buffer[0], 0, buffer)
    assert label.startswith("assistant: ")
    assert "Here is a summary" in label


def test_auto_label_ai_assistant_generic():
    """Lines starting with 'Assistant:' get label 'assistant: <text>'."""
    from lib.navigation import BookmarkManager

    buffer = [
        "Assistant: I can help with that request",
    ]
    manager, _ = _make_manager_with_buffer(buffer, cursor_line_idx=0)

    label = manager._auto_label(buffer[0], 0, buffer)
    assert label.startswith("assistant: ")
    assert "I can help" in label


def test_auto_label_ai_assistant_chatgpt():
    """Lines starting with 'ChatGPT:' get label 'assistant: <text>'."""
    from lib.navigation import BookmarkManager

    buffer = [
        "ChatGPT: The answer to your question is 42",
    ]
    manager, _ = _make_manager_with_buffer(buffer, cursor_line_idx=0)

    label = manager._auto_label(buffer[0], 0, buffer)
    assert label.startswith("assistant: ")
    assert "The answer" in label


# ---------------------------------------------------------------------------
# 3. Auto-label: system role
# ---------------------------------------------------------------------------

def test_auto_label_ai_system():
    """Lines starting with 'System:' get label 'system: <text>'."""
    from lib.navigation import BookmarkManager

    buffer = [
        "System: Connection established to model gpt-4",
    ]
    manager, _ = _make_manager_with_buffer(buffer, cursor_line_idx=0)

    label = manager._auto_label(buffer[0], 0, buffer)
    assert label.startswith("system: ")
    assert "Connection established" in label


# ---------------------------------------------------------------------------
# 4. Auto-label: code block detection
# ---------------------------------------------------------------------------

def test_auto_label_code_block_with_language():
    """Code block start with language gets label 'code: <lang> block'."""
    from lib.navigation import BookmarkManager

    buffer = [
        "```python",
        "def hello():",
        "    print('hi')",
        "```",
    ]
    manager, _ = _make_manager_with_buffer(buffer, cursor_line_idx=0)

    label = manager._auto_label(buffer[0], 0, buffer)
    assert label == "code: python block"


def test_auto_label_code_block_no_language():
    """Code block start without language gets a generic code label."""
    from lib.navigation import BookmarkManager

    buffer = [
        "```",
        "some code here",
        "```",
    ]
    manager, _ = _make_manager_with_buffer(buffer, cursor_line_idx=0)

    label = manager._auto_label(buffer[0], 0, buffer)
    # Should still indicate a code block
    assert "code:" in label


def test_auto_label_truncates_at_40_chars():
    """AI turn labels truncate the preview portion at 40 characters."""
    from lib.navigation import BookmarkManager

    long_text = "a" * 80
    buffer = [
        f"Claude: {long_text}",
    ]
    manager, _ = _make_manager_with_buffer(buffer, cursor_line_idx=0)

    label = manager._auto_label(buffer[0], 0, buffer)
    assert label.startswith("assistant: ")
    # The total label should be within the _LABEL_MAX_LENGTH (50)
    assert len(label) <= BookmarkManager._LABEL_MAX_LENGTH


# ---------------------------------------------------------------------------
# 5. list_ai_turns: correct roles and line numbers
# ---------------------------------------------------------------------------

def test_list_ai_turns_returns_correct_entries():
    """list_ai_turns returns dicts with role, line_num, preview for each turn."""
    from lib.navigation import BookmarkManager

    buffer = [
        "\u276f what is Python?",
        "Claude: Python is a programming language",
        "that was created by Guido van Rossum.",
        "\u276f tell me more",
        "Claude: Python supports multiple paradigms",
    ]
    terminal = Mock()
    manager = BookmarkManager(terminal)

    turns = manager.list_ai_turns(buffer)

    assert len(turns) == 4  # 2 user + 2 assistant
    assert turns[0]["role"] == "user"
    assert turns[0]["line_num"] == 0
    assert "what is Python" in turns[0]["preview"]
    assert turns[1]["role"] == "assistant"
    assert turns[1]["line_num"] == 1
    assert turns[3]["role"] == "assistant"
    assert turns[3]["line_num"] == 4


def test_list_ai_turns_detects_system():
    """list_ai_turns detects system role lines."""
    from lib.navigation import BookmarkManager

    buffer = [
        "System: Initializing session",
        "\u276f hello",
        "Claude: Hi there!",
    ]
    terminal = Mock()
    manager = BookmarkManager(terminal)

    turns = manager.list_ai_turns(buffer)

    roles = [t["role"] for t in turns]
    assert "system" in roles
    assert "user" in roles
    assert "assistant" in roles


def test_list_ai_turns_detects_code_blocks():
    """list_ai_turns includes code block entries."""
    from lib.navigation import BookmarkManager

    buffer = [
        "Claude: Here is an example:",
        "```python",
        "print('hello')",
        "```",
    ]
    terminal = Mock()
    manager = BookmarkManager(terminal)

    turns = manager.list_ai_turns(buffer)

    # Should have assistant + code entries at minimum
    roles = [t["role"] for t in turns]
    assert "assistant" in roles
    assert "code" in roles


# ---------------------------------------------------------------------------
# 6. Filter by role
# ---------------------------------------------------------------------------

def test_list_ai_turns_filter_user_only():
    """Filtering list_ai_turns by 'user' returns only user turns."""
    from lib.navigation import BookmarkManager

    buffer = [
        "\u276f first question",
        "Claude: first answer",
        "\u276f second question",
        "Claude: second answer",
    ]
    terminal = Mock()
    manager = BookmarkManager(terminal)

    all_turns = manager.list_ai_turns(buffer)
    user_turns = [t for t in all_turns if t["role"] == "user"]

    assert len(user_turns) == 2
    for t in user_turns:
        assert t["role"] == "user"


def test_list_ai_turns_filter_assistant_only():
    """Filtering by 'assistant' returns only assistant turns."""
    from lib.navigation import BookmarkManager

    buffer = [
        "\u276f question",
        "Assistant: answer one",
        "\u276f question two",
        "ChatGPT: answer two",
    ]
    terminal = Mock()
    manager = BookmarkManager(terminal)

    all_turns = manager.list_ai_turns(buffer)
    assistant_turns = [t for t in all_turns if t["role"] == "assistant"]

    assert len(assistant_turns) == 2


# ---------------------------------------------------------------------------
# 7. Fallback: no AI turns
# ---------------------------------------------------------------------------

def test_list_ai_turns_empty_buffer():
    """list_ai_turns returns empty list for empty buffer."""
    from lib.navigation import BookmarkManager

    terminal = Mock()
    manager = BookmarkManager(terminal)

    turns = manager.list_ai_turns([])
    assert turns == []


def test_list_ai_turns_no_ai_content():
    """list_ai_turns returns empty list when buffer has no AI turn markers."""
    from lib.navigation import BookmarkManager

    buffer = [
        "user@host:~$ ls",
        "file1.txt  file2.txt",
        "user@host:~$ pwd",
        "/home/user",
    ]
    terminal = Mock()
    manager = BookmarkManager(terminal)

    turns = manager.list_ai_turns(buffer)
    assert turns == []


def test_list_ai_turns_with_ansi_codes():
    """list_ai_turns must detect roles even when lines contain ANSI color codes."""
    from lib.navigation import BookmarkManager

    buffer = [
        "\x1b[1;32m❯\x1b[0m what is Python?",
        "",
        "\x1b[1;34mClaude:\x1b[0m Python is a programming language.",
        "It was created by Guido.",
    ]
    terminal = Mock()
    manager = BookmarkManager(terminal)

    turns = manager.list_ai_turns(buffer)
    roles = [t["role"] for t in turns]
    assert "user" in roles, f"Expected 'user' role but got {roles}"
    assert "assistant" in roles, f"Expected 'assistant' role but got {roles}"


# ---------------------------------------------------------------------------
# 8. Existing bookmark behavior not regressed
# ---------------------------------------------------------------------------

def test_set_bookmark_still_works():
    """Basic set_bookmark continues to work after AI changes."""
    from lib.navigation import BookmarkManager

    terminal = Mock()
    manager = BookmarkManager(terminal)

    mock_pos = Mock()
    mock_pos.bookmark = "bm_obj"
    mock_pos.text = "some output line"

    expanded = Mock()
    expanded.text = "some output line"
    expanded.expand = Mock()
    expanded.collapse = Mock()
    expanded.move = Mock(return_value=0)
    mock_pos.copy = Mock(return_value=expanded)

    with patch('api.getReviewPosition', return_value=mock_pos):
        result = manager.set_bookmark("1")
    assert result is True
    assert manager.has_bookmark("1")


def test_jump_to_bookmark_still_works():
    """jump_to_bookmark continues to work after AI changes."""
    from lib.navigation import BookmarkManager

    terminal = Mock()
    mock_textinfo = Mock()
    mock_textinfo.bookmark = "bm_obj"
    terminal.makeTextInfo = Mock(return_value=mock_textinfo)
    manager = BookmarkManager(terminal)

    mock_pos = Mock()
    mock_pos.bookmark = "bm_obj"
    mock_pos.text = "line text"
    expanded = Mock()
    expanded.text = "line text"
    expanded.expand = Mock()
    expanded.collapse = Mock()
    expanded.move = Mock(return_value=0)
    mock_pos.copy = Mock(return_value=expanded)

    with patch('api.getReviewPosition', return_value=mock_pos):
        manager.set_bookmark("1")

    with patch('api.setReviewPosition') as mock_set:
        result = manager.jump_to_bookmark("1")
    assert result is True
    mock_set.assert_called_once()


def test_delete_bookmark_still_works():
    """remove_bookmark continues to work after AI changes."""
    from lib.navigation import BookmarkManager

    terminal = Mock()
    manager = BookmarkManager(terminal)

    mock_pos = Mock()
    mock_pos.bookmark = "bm_obj"
    mock_pos.text = "line"
    expanded = Mock()
    expanded.text = "line"
    expanded.expand = Mock()
    expanded.collapse = Mock()
    expanded.move = Mock(return_value=0)
    mock_pos.copy = Mock(return_value=expanded)

    with patch('api.getReviewPosition', return_value=mock_pos):
        manager.set_bookmark("x")

    assert manager.has_bookmark("x")
    result = manager.remove_bookmark("x")
    assert result is True
    assert not manager.has_bookmark("x")


def test_list_bookmarks_still_works():
    """list_bookmarks returns structured data after AI changes."""
    from lib.navigation import BookmarkManager

    terminal = Mock()
    manager = BookmarkManager(terminal)

    mock_pos = Mock()
    mock_pos.bookmark = "bm_obj"
    mock_pos.text = "content"
    expanded = Mock()
    expanded.text = "content"
    expanded.expand = Mock()
    expanded.collapse = Mock()
    expanded.move = Mock(return_value=0)
    mock_pos.copy = Mock(return_value=expanded)

    with patch('api.getReviewPosition', return_value=mock_pos):
        manager.set_bookmark("1")
        manager.set_bookmark("2")

    bm_list = manager.list_bookmarks()
    assert len(bm_list) == 2
    assert all("name" in bm and "label" in bm for bm in bm_list)


# ---------------------------------------------------------------------------
# 9. Auto-label: AI detection takes priority over generic labels
# ---------------------------------------------------------------------------

def test_auto_label_ai_priority_over_generic():
    """AI role detection should take priority over fallback labeling."""
    from lib.navigation import BookmarkManager

    # The '> ' prefix is also a prompt pattern in _PROMPT_COMMAND_RE,
    # but for AI CLIs it should map to user role.
    buffer = [
        "> explain quantum computing in simple terms",
    ]
    manager, _ = _make_manager_with_buffer(buffer, cursor_line_idx=0)

    label = manager._auto_label(buffer[0], 0, buffer)
    # Should be detected as AI user, not as a generic prompt
    assert label.startswith("user: ")


def test_auto_label_ai_with_ansi_codes():
    """AI role markers with ANSI color codes should still be detected."""
    from lib.navigation import BookmarkManager

    buffer = [
        "\x1b[1;34mClaude:\x1b[0m Here is the answer",
    ]
    manager, _ = _make_manager_with_buffer(buffer, cursor_line_idx=0)

    label = manager._auto_label(buffer[0], 0, buffer)
    assert label.startswith("assistant:"), f"Expected 'assistant:' prefix but got '{label}'"


def test_auto_label_strips_ansi_from_all_label_text():
    """Labels should never contain raw ANSI escape codes."""
    from lib.navigation import BookmarkManager

    # Error line with ANSI color codes
    buffer = [
        "\x1b[31mError: connection refused\x1b[0m",
    ]
    manager, _ = _make_manager_with_buffer(buffer, cursor_line_idx=0)

    label = manager._auto_label(buffer[0], 0, buffer)
    assert "\x1b" not in label, f"Label contains raw ANSI: {repr(label)}"
    assert "Error" in label


def test_auto_label_prompt_strips_ansi():
    """Prompt labels should not contain ANSI escape codes."""
    from lib.navigation import BookmarkManager

    buffer = [
        "\x1b[32muser@host:~$\x1b[0m ls -la",
    ]
    manager, _ = _make_manager_with_buffer(buffer, cursor_line_idx=0)

    label = manager._auto_label(buffer[0], 0, buffer)
    assert "\x1b" not in label, f"Label contains raw ANSI: {repr(label)}"


def test_auto_label_non_ai_line_unchanged():
    """Lines without AI markers should still get normal auto-labeling."""
    from lib.navigation import BookmarkManager

    buffer = [
        "user@host:~/project$ cargo build",
        "   Compiling myproject v0.1.0",
    ]
    manager, _ = _make_manager_with_buffer(buffer, cursor_line_idx=0)

    label = manager._auto_label(buffer[0], 0, buffer)
    # Should be the normal prompt label, not an AI label
    assert label.startswith("prompt: ")
    assert "cargo build" in label
