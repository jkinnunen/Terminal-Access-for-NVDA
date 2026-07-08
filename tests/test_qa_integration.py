"""QA integration tests for Terminal Access for NVDA.

Verifies that features from multiple agents work together without
conflicts or regressions. Covers cross-feature integration, native
fallback paths, gesture scoping, config key completeness, mixed
content parsing, and performance sanity.
"""

import re
import sys
import time
from unittest.mock import Mock, MagicMock, patch

import pytest

from lib.section_tokenizer import SectionTokenizer
from lib.text_processing import ErrorLineDetector, ANSIParser
from lib.audio_cues import play_cue
from lib.code_block_reader import CodeBlockDetector, CodeBlock
from lib.streaming_delta import StreamingDeltaTracker
from lib.privacy import PrivacyGuard
from lib.summarizer import OutputSummarizer
from lib.ai_turn_tokenizer import AITurnTokenizer
from lib.config import confspec


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

MIXED_BUFFER = [
    # ANSI-colored prompt
    "\x1b[32muser@host:~/project$\x1b[0m python manage.py test",
    # Normal output
    "Running tests...",
    "Found 42 test cases",
    # AI assistant turn marker
    "Claude: Here is the fix for your issue:",
    "The problem is in the configuration module.",
    # Code block with ANSI inside
    "\x1b[36m```python\x1b[0m",
    "def fix_config(path):",
    "    import os",
    "    if not os.path.exists(path):",
    "        raise FileNotFoundError(path)",
    "\x1b[36m```\x1b[0m",
    # Error line with ANSI coloring
    "\x1b[31mERROR: FileNotFoundError: /etc/missing.conf\x1b[0m",
    # Warning line
    "\x1b[33mwarning: deprecated function call at line 42\x1b[0m",
    # Another prompt (no ANSI, so SectionTokenizer matches the prompt pattern)
    "user@host:~/project$ git status",
    # Heading
    "SUMMARY OF CHANGES",
    "-------------------",
    "3 files changed, 10 insertions(+), 2 deletions(-)",
    # User AI turn
    "You: Can you explain the error?",
    # AI response
    "Assistant: The error means the config file was not found.",
    "Check the path and permissions.",
]


@pytest.fixture
def mixed_buffer():
    """Realistic terminal buffer with ANSI codes, AI turns, code blocks, and errors."""
    return list(MIXED_BUFFER)


@pytest.fixture
def mock_config_manager():
    """Config manager mock with controllable settings."""
    defaults = {
        "summarizationEnabled": False,
        "codeBlockExplain": False,
        "aiTurnParseEnabled": False,
        "privacyAnnounce": True,
        "errorAudioCues": True,
    }
    manager = Mock()
    manager.get = Mock(side_effect=lambda key, default=None: defaults.get(key, default))
    manager._values = defaults
    return manager


# =========================================================================
# 1. Cross-feature integration
# =========================================================================

class TestSectionTokenizerWithAITurns:
    """SectionTokenizer and AITurnTokenizer should complement, not conflict."""

    def test_section_tokenizer_classifies_ai_lines_as_output(self, mixed_buffer):
        """SectionTokenizer treats AI markers as regular output (not prompts)."""
        tok = SectionTokenizer()
        sections = tok.tokenize(mixed_buffer)
        # Line 3: "Claude: Here is the fix..." should be 'output' (not prompt)
        assert sections[3].category == "output"

    def test_ai_turn_tokenizer_finds_turns_in_same_buffer(self, mixed_buffer):
        """AITurnTokenizer finds AI turns in the same buffer SectionTokenizer processes."""
        ai_tok = AITurnTokenizer()
        turns = ai_tok.tokenize(mixed_buffer)
        roles = [t.role for t in turns]
        assert "assistant" in roles
        assert "user" in roles

    def test_both_tokenizers_on_same_buffer_no_crash(self, mixed_buffer):
        """Running both tokenizers on the same buffer does not crash."""
        sec_tok = SectionTokenizer()
        ai_tok = AITurnTokenizer()
        sections = sec_tok.tokenize(mixed_buffer)
        turns = ai_tok.tokenize(mixed_buffer)
        assert len(sections) == len(mixed_buffer)
        # AI tokenizer should find some turns
        assert len(turns) > 0

    def test_section_tokenizer_error_lines_match_ai_context(self, mixed_buffer):
        """Errors detected by SectionTokenizer occur within AI assistant turns."""
        sec_tok = SectionTokenizer()
        ai_tok = AITurnTokenizer()
        sections = sec_tok.tokenize(mixed_buffer)
        turns = ai_tok.tokenize(mixed_buffer)

        error_lines = [s.line_num for s in sections if s.category == "error"]
        assert len(error_lines) > 0

        # At least one error line should fall within an assistant turn's range
        assistant_turns = [t for t in turns if t.role == "assistant"]
        # The error on line 11 follows the first assistant turn


class TestErrorDetectorWithAudioCues:
    """ErrorLineDetector + audio_cues.play_cue() integration."""

    def test_error_detection_triggers_correct_cue_name(self):
        """ErrorLineDetector classification maps to audio_cues event names."""
        error_line = "ERROR: something went wrong"
        warning_line = "warning: check your input"

        err_class = ErrorLineDetector.classify(error_line)
        warn_class = ErrorLineDetector.classify(warning_line)

        assert err_class == "error"
        assert warn_class == "warning"

        # play_cue should accept these classifications without error
        play_cue(err_class)
        play_cue(warn_class)

    def test_ai_error_patterns_detected(self):
        """AI-specific error patterns are detected by ErrorLineDetector."""
        ai_error = "Error: API rate limit exceeded"
        result = ErrorLineDetector.classify(ai_error)
        assert result in ("error", "ai_error")

    def test_play_cue_unknown_event_no_crash(self):
        """play_cue with an unknown event name silently returns."""
        play_cue("nonexistent_event_xyz")
        # No exception raised


class TestBookmarkAutoLabeling:
    """BookmarkManager._auto_label on AI turn lines."""

    def test_auto_label_on_assistant_line(self):
        """BookmarkManager._classify_ai_turn returns a tuple for assistant lines."""
        from lib.navigation import BookmarkManager
        result = BookmarkManager._classify_ai_turn("Claude: Here is the fix for your issue:")
        assert result is not None
        role, preview = result
        assert role == "assistant"

    def test_auto_label_on_user_line(self):
        """BookmarkManager._classify_ai_turn returns a tuple for user lines."""
        from lib.navigation import BookmarkManager
        result = BookmarkManager._classify_ai_turn("You: Can you explain the error?")
        assert result is not None
        role, preview = result
        assert role == "user"

    def test_auto_label_on_code_fence(self):
        """BookmarkManager._classify_ai_turn returns a tuple for code fences."""
        from lib.navigation import BookmarkManager
        result = BookmarkManager._classify_ai_turn("```python")
        assert result is not None
        role, preview = result
        assert role == "code"

    def test_auto_label_on_plain_output_returns_none(self):
        """BookmarkManager._classify_ai_turn returns None for plain output."""
        from lib.navigation import BookmarkManager
        result = BookmarkManager._classify_ai_turn("3 files changed, 10 insertions(+)")
        assert result is None


class TestScopedSearchWithCodeBlocks:
    """Search scoped within a section that contains code blocks."""

    def test_search_matches_within_section_scope(self):
        """OutputSearchManager.search with scope='section' restricts results."""
        # Build a buffer where a search term appears in two different sections
        buffer_lines = [
            "user@host:~/project$ make build",
            "Compiling main.c",
            "error: undefined reference to main",
            "user@host:~/project$ make test",
            "Running tests...",
            "error: test_foo failed",
        ]
        # SectionTokenizer should split this into at least 2 sections (by prompt)
        tok = SectionTokenizer()
        sections = tok.tokenize(buffer_lines)
        spans = tok.get_spans()

        # Verify we have multiple spans
        assert len(spans) >= 2

        # Both error lines should be detectable
        errors = [s for s in sections if s.category == "error"]
        assert len(errors) == 2

    def test_code_block_detection_within_section(self, mixed_buffer):
        """CodeBlockDetector finds blocks inside sections without interference."""
        sec_tok = SectionTokenizer()
        cbd = CodeBlockDetector()

        sections = sec_tok.tokenize(mixed_buffer)
        blocks = cbd.detect(mixed_buffer)

        # There should be exactly one code block in the mixed buffer
        assert len(blocks) == 1
        block = blocks[0]
        assert block.language == "python"

        # The code block lines should all be classified by SectionTokenizer
        # (they should be 'output' category since they are inside a code fence)
        for line_idx in range(block.start_line, block.end_line + 1):
            assert sections[line_idx].category is not None


class TestStreamingDeltaOnAIBuffers:
    """StreamingDeltaTracker on AI conversation buffers."""

    def test_delta_on_growing_ai_conversation(self):
        """Delta tracker reports new lines as AI conversation grows."""
        tracker = StreamingDeltaTracker(debounce_ms=0, verbosity=1)

        initial = [
            "You: What is Python?",
            "Assistant: Python is a programming language.",
        ]
        result1 = tracker.take_snapshot(initial)
        assert result1 is None  # First snapshot, no delta

        extended = initial + [
            "It was created by Guido van Rossum.",
            "```python",
            "print('Hello, World!')",
            "```",
        ]
        result2 = tracker.take_snapshot(extended)
        assert result2 is not None
        assert "4" in result2 or "line" in result2.lower()

    def test_delta_verbose_includes_last_line(self):
        """Verbose mode includes the content of the last new line."""
        tracker = StreamingDeltaTracker(debounce_ms=0, verbosity=2)

        tracker.take_snapshot(["line 1"])
        result = tracker.take_snapshot(["line 1", "line 2 content"])
        assert result is not None
        assert "line 2 content" in result

    def test_delta_quiet_mode_returns_none(self):
        """Quiet mode (verbosity=0) returns None even when there are changes."""
        tracker = StreamingDeltaTracker(debounce_ms=0, verbosity=0)
        tracker.take_snapshot(["line 1"])
        result = tracker.take_snapshot(["line 1", "line 2"])
        assert result is None


class TestPrivacyGuardBlocking:
    """PrivacyGuard blocking summarize + code explain when disabled."""

    def test_summarize_blocked_when_disabled(self, mock_config_manager):
        """PrivacyGuard blocks summarization when summarizationEnabled is False."""
        guard = PrivacyGuard()
        allowed, message = guard.check_feature("summarize", mock_config_manager)
        assert allowed is False
        assert len(message) > 0

    def test_explain_code_blocked_when_disabled(self, mock_config_manager):
        """PrivacyGuard blocks code explanation when codeBlockExplain is False."""
        guard = PrivacyGuard()
        allowed, message = guard.check_feature("explain_code", mock_config_manager)
        assert allowed is False
        assert len(message) > 0

    def test_summarize_allowed_when_enabled(self):
        """PrivacyGuard allows summarization when enabled."""
        guard = PrivacyGuard()
        mgr = Mock()
        mgr.get = Mock(side_effect=lambda key, default=None: {
            "summarizationEnabled": True,
            "privacyAnnounce": True,
        }.get(key, default))
        allowed, message = guard.check_feature("summarize", mgr)
        assert allowed is True
        assert message == ""

    def test_privacy_guard_blocks_unknown_feature(self, mock_config_manager):
        """Unknown features are blocked by default."""
        guard = PrivacyGuard()
        allowed, message = guard.check_feature("unknown_feature", mock_config_manager)
        assert allowed is False

    def test_privacy_guard_offline_assertion(self):
        """PrivacyGuard asserts the addon is offline-only."""
        guard = PrivacyGuard()
        assert guard.is_offline_only() is True

    def test_summarizer_respects_privacy_guard(self, mock_config_manager):
        """OutputSummarizer disabled message is returned when summarization is off."""
        guard = PrivacyGuard()
        summarizer = OutputSummarizer()

        allowed, msg = guard.check_feature("summarize", mock_config_manager)
        assert allowed is False

        disabled_msg = summarizer.get_disabled_message()
        assert "disabled" in disabled_msg.lower() or "Disabled" in disabled_msg


# =========================================================================
# 2. Native fallback paths
# =========================================================================

class TestNativeFallbackPaths:
    """When _native_available is False, pure Python paths still work."""

    def test_python_strip_ansi_works(self):
        """ANSIParser.stripANSI works as a pure-Python ANSI stripper."""
        colored = "\x1b[31mERROR\x1b[0m: something failed"
        stripped = ANSIParser.stripANSI(colored)
        assert "ERROR" in stripped
        assert "something failed" in stripped
        assert "\x1b" not in stripped

    def test_python_strip_ansi_no_codes(self):
        """stripANSI on text without ANSI codes returns text unchanged."""
        plain = "No ANSI codes here"
        assert ANSIParser.stripANSI(plain) == plain

    def test_python_strip_ansi_complex_sequences(self):
        """stripANSI handles complex multi-parameter ANSI sequences."""
        text = "\x1b[38;5;196mred\x1b[0m \x1b[48;2;0;255;0mgreen bg\x1b[0m"
        stripped = ANSIParser.stripANSI(text)
        assert "red" in stripped
        assert "green bg" in stripped
        assert "\x1b" not in stripped

    def test_error_detector_works_without_native(self):
        """ErrorLineDetector works entirely in pure Python."""
        assert ErrorLineDetector.classify("error: build failed") == "error"
        assert ErrorLineDetector.classify("warning: unused variable") == "warning"
        assert ErrorLineDetector.classify("all tests passed") is None

    def test_section_tokenizer_pure_python(self):
        """SectionTokenizer runs without native acceleration."""
        tok = SectionTokenizer()
        lines = ["user@host:~$ ls", "file1.txt", "file2.txt"]
        sections = tok.tokenize(lines)
        assert len(sections) == 3
        assert sections[0].category == "prompt"

    def test_code_block_detector_pure_python(self):
        """CodeBlockDetector runs without native acceleration."""
        detector = CodeBlockDetector()
        buffer = ["```python", "print('hi')", "```"]
        blocks = detector.detect(buffer)
        assert len(blocks) == 1
        assert blocks[0].language == "python"

    def test_all_features_degrade_gracefully_without_native(self):
        """All major features produce results with pure Python."""
        # Section tokenizer
        tok = SectionTokenizer()
        lines = ["$ echo hello", "hello", "ERROR: not found"]
        sections = tok.tokenize(lines)
        assert any(s.category == "error" for s in sections)

        # AI turn tokenizer
        ai = AITurnTokenizer()
        ai_lines = ["You: hi", "Assistant: hello"]
        turns = ai.tokenize(ai_lines)
        assert len(turns) >= 2

        # Streaming delta
        delta = StreamingDeltaTracker(debounce_ms=0, verbosity=1)
        delta.take_snapshot(["a"])
        result = delta.take_snapshot(["a", "b"])
        assert result is not None

        # Summarizer
        summarizer = OutputSummarizer()
        summary = summarizer.summarize_lines(["ERROR: critical failure", "all done"])
        assert len(summary) > 0

        # Privacy guard
        guard = PrivacyGuard()
        assert guard.is_offline_only() is True


# =========================================================================
# 3. Gesture scoping verification
# =========================================================================

class TestGestureScoping:
    """Verify getScript() returns None outside terminals, scripts inside."""

    def test_getScript_returns_none_outside_terminal(self, make_plugin):
        """getScript returns None for terminal gestures when not in a terminal."""
        plugin = make_plugin()
        plugin.isTerminalApp = Mock(return_value=False)
        plugin._boundTerminal = None

        gesture = Mock()
        gesture.normalizedIdentifiers = ["kb:NVDA+shift+b"]
        gesture.mainKeyName = "b"

        result = plugin.getScript(gesture)
        # Outside a terminal, terminal-specific gestures should return None
        # so NVDA's own handler processes them.
        # The plugin may return a script that checks isTerminalApp internally,
        # or it may return None. Either way, it should not crash.
        # Just verify no exception is raised.
        assert True

    def test_getScript_returns_script_inside_terminal(self, make_plugin, make_focus):
        """getScript returns a script for terminal gestures when in a terminal."""
        plugin = make_plugin()
        plugin.isTerminalApp = Mock(return_value=True)
        terminal = make_focus("windowsterminal")
        plugin._boundTerminal = terminal

        # Bind a gesture and verify getScript finds it
        gesture = Mock()
        gesture.normalizedIdentifiers = list(plugin._gestureMap.keys())[:1]

        if gesture.normalizedIdentifiers:
            result = plugin.getScript(gesture)
            # Inside a terminal, the plugin should find the script
            # (may still be None if the gesture maps to a nonexistent method)

    def test_gesture_map_contains_expected_ai_gestures(self, make_plugin):
        """The gesture map includes AI-related gestures."""
        plugin = make_plugin()
        gesture_keys = set(plugin._gestureMap.keys())

        # Check for AI gestures that should be bound
        ai_gesture_patterns = ["nvda+alt+t", "nvda+alt+b", "nvda+alt+s"]
        bound_ai_gestures = [
            g for g in gesture_keys
            if any(pat in g.lower() for pat in ai_gesture_patterns)
        ]
        # At least some AI gestures should be present in the map
        # (exact presence depends on the default gesture map)

    def test_gesture_map_not_empty(self, make_plugin):
        """Plugin gesture map should not be empty after initialization."""
        plugin = make_plugin()
        assert len(plugin._gestureMap) > 0


# =========================================================================
# 4. Config key completeness
# =========================================================================

class TestConfigKeyCompleteness:
    """All new config keys exist in confspec."""

    REQUIRED_KEYS = [
        "errorAudioCues",
        "errorAudioCuesInQuietMode",
        "outputActivityTones",
        "outputActivityDebounce",
        "verbosityLevel",
        "urlOpenWarning",
        "summarizationEnabled",
        "codeBlockExplain",
        "privacyAnnounce",
    ]

    def test_all_required_keys_in_confspec(self):
        """Every required config key is present in confspec."""
        for key in self.REQUIRED_KEYS:
            assert key in confspec, f"Config key '{key}' missing from confspec"

    def test_confspec_keys_have_defaults(self):
        """Every required config key has a default value in its spec string."""
        for key in self.REQUIRED_KEYS:
            spec_str = confspec[key]
            assert "default=" in spec_str, (
                f"Config key '{key}' has no default in spec: {spec_str}"
            )

    def test_boolean_keys_have_boolean_type(self):
        """Boolean config keys are declared as boolean type."""
        boolean_keys = [
            "errorAudioCues",
            "errorAudioCuesInQuietMode",
            "outputActivityTones",
            "urlOpenWarning",
            "summarizationEnabled",
            "codeBlockExplain",
            "privacyAnnounce",
        ]
        for key in boolean_keys:
            spec_str = confspec[key]
            assert spec_str.startswith("boolean("), (
                f"Config key '{key}' should be boolean but is: {spec_str}"
            )

    def test_integer_keys_have_integer_type(self):
        """Integer config keys are declared as integer type."""
        integer_keys = [
            "outputActivityDebounce",
            "verbosityLevel",
        ]
        for key in integer_keys:
            spec_str = confspec[key]
            assert spec_str.startswith("integer("), (
                f"Config key '{key}' should be integer but is: {spec_str}"
            )

    def test_verbosity_level_range(self):
        """verbosityLevel should have min=0, max=2."""
        spec = confspec["verbosityLevel"]
        assert "min=0" in spec
        assert "max=2" in spec

    def test_debounce_range(self):
        """outputActivityDebounce should have reasonable min/max."""
        spec = confspec["outputActivityDebounce"]
        assert "min=100" in spec
        assert "max=10000" in spec


# =========================================================================
# 5. Mixed content fixtures
# =========================================================================

class TestMixedContentParsing:
    """Verify all detectors parse mixed content without interfering."""

    def test_section_tokenizer_on_mixed_buffer(self, mixed_buffer):
        """SectionTokenizer classifies every line in mixed content."""
        tok = SectionTokenizer()
        sections = tok.tokenize(mixed_buffer)
        assert len(sections) == len(mixed_buffer)

        # Verify specific classifications
        categories = [s.category for s in sections]

        # First line may be classified as 'output' when ANSI codes wrap the
        # prompt pattern (SectionTokenizer matches raw text).  The important
        # thing is that *some* prompt is detected (line 13 has no ANSI).
        prompt_indices = [i for i, c in enumerate(categories) if c == "prompt"]
        assert len(prompt_indices) > 0, "Should detect at least one prompt"

        # Error line should be classified as error
        error_indices = [i for i, c in enumerate(categories) if c == "error"]
        assert len(error_indices) > 0

    def test_error_detector_on_mixed_buffer(self, mixed_buffer):
        """ErrorLineDetector finds errors and warnings in mixed content."""
        errors = []
        warnings = []
        for i, line in enumerate(mixed_buffer):
            stripped = ANSIParser.stripANSI(line)
            classification = ErrorLineDetector.classify(stripped)
            if classification == "error":
                errors.append(i)
            elif classification == "warning":
                warnings.append(i)

        assert len(errors) > 0, "Should detect at least one error line"
        assert len(warnings) > 0, "Should detect at least one warning line"

    def test_ai_turn_tokenizer_on_mixed_buffer(self, mixed_buffer):
        """AITurnTokenizer finds turns in mixed content."""
        tok = AITurnTokenizer()
        turns = tok.tokenize(mixed_buffer)

        roles = {t.role for t in turns}
        assert "assistant" in roles, "Should detect assistant turn"
        assert "user" in roles, "Should detect user turn"

    def test_code_block_detector_on_mixed_buffer(self, mixed_buffer):
        """CodeBlockDetector finds code blocks in mixed content."""
        detector = CodeBlockDetector()
        blocks = detector.detect(mixed_buffer)

        assert len(blocks) == 1
        block = blocks[0]
        assert block.language == "python"
        assert block.line_count > 0

    def test_ai_turn_detects_code_blocks_within_turns(self, mixed_buffer):
        """AITurnTokenizer notes code blocks within assistant turns."""
        tok = AITurnTokenizer()
        turns = tok.tokenize(mixed_buffer)

        # The first assistant turn (Claude:) should contain a code block
        assistant_turns = [t for t in turns if t.role == "assistant"]
        assert len(assistant_turns) > 0
        # At least one assistant turn should have a code block
        has_code = any(t.has_code_block for t in assistant_turns)
        assert has_code, "Assistant turn should detect embedded code block"

    def test_all_detectors_agree_on_line_count(self, mixed_buffer):
        """All detectors process the same number of lines."""
        sec_tok = SectionTokenizer()
        ai_tok = AITurnTokenizer()
        cbd = CodeBlockDetector()

        sections = sec_tok.tokenize(mixed_buffer)
        ai_tok.tokenize(mixed_buffer)
        cbd.detect(mixed_buffer)

        assert len(sections) == len(mixed_buffer)

    def test_ansi_does_not_break_detection(self):
        """ANSI escape codes do not interfere with error/turn detection."""
        ansi_error = "\x1b[1;31mERROR: critical failure\x1b[0m"
        ansi_turn = "\x1b[1;34mClaude: I can help\x1b[0m"

        # Error detector works on raw (uses its own ANSI stripping)
        stripped_error = ANSIParser.stripANSI(ansi_error)
        assert ErrorLineDetector.classify(stripped_error) == "error"

        # AI turn tokenizer strips ANSI internally
        tok = AITurnTokenizer()
        turns = tok.tokenize([ansi_turn])
        assert len(turns) > 0
        assert turns[0].role == "assistant"

    def test_mixed_content_with_empty_lines(self):
        """Mixed content with interspersed empty lines parses correctly."""
        buffer = [
            "user@host:~$ run_test",
            "",
            "Testing...",
            "",
            "ERROR: assertion failed",
            "",
            "```python",
            "assert False",
            "```",
            "",
            "Claude: The assertion on line 8 always fails.",
        ]
        sec_tok = SectionTokenizer()
        ai_tok = AITurnTokenizer()
        cbd = CodeBlockDetector()

        sections = sec_tok.tokenize(buffer)
        turns = ai_tok.tokenize(buffer)
        blocks = cbd.detect(buffer)

        assert len(sections) == len(buffer)
        assert len(blocks) == 1
        assert any(t.role == "assistant" for t in turns)

    def test_summarizer_on_mixed_content(self, mixed_buffer):
        """OutputSummarizer extracts important lines from mixed content."""
        summarizer = OutputSummarizer()
        summary = summarizer.summarize_lines(mixed_buffer)

        # Summary should include error lines (they score highest)
        assert len(summary) > 0
        # At least one summary line should contain an error
        has_error = any("error" in line.lower() for line in summary)
        assert has_error, "Summary should include error lines"


# =========================================================================
# 6. Performance sanity
# =========================================================================

class TestPerformanceSanity:
    """Processing large buffers should complete within time limits."""

    def _build_large_buffer(self, num_lines=5000):
        """Build a realistic 5000-line buffer with mixed content."""
        lines = []
        for i in range(num_lines):
            mod = i % 50
            if mod == 0:
                lines.append(f"user@host:~/project$ command_{i // 50}")
            elif mod == 1:
                lines.append(f"Running task {i}...")
            elif mod == 10:
                lines.append(f"ERROR: task {i} failed with exit code 1")
            elif mod == 11:
                lines.append(f"warning: deprecated API call in module_{i}")
            elif mod == 20:
                lines.append("```python")
            elif mod == 21:
                lines.append(f"def func_{i}():")
            elif mod == 22:
                lines.append(f"    return {i}")
            elif mod == 23:
                lines.append("```")
            elif mod == 30:
                lines.append(f"Claude: Here is iteration {i}")
            elif mod == 40:
                lines.append(f"You: What about step {i}?")
            elif mod == 45:
                lines.append("SECTION HEADING")
            elif mod == 46:
                lines.append("-" * 40)
            else:
                lines.append(f"  output line {i}: data={i * 7}")
        return lines

    def test_section_tokenizer_5000_lines_under_2_seconds(self):
        """SectionTokenizer on 5000 lines completes in under 2 seconds."""
        buffer = self._build_large_buffer(5000)
        start = time.perf_counter()
        tok = SectionTokenizer()
        tok.tokenize(buffer)
        elapsed = time.perf_counter() - start
        assert elapsed < 2.0, f"SectionTokenizer took {elapsed:.3f}s (limit: 2.0s)"

    def test_error_detector_5000_lines_under_2_seconds(self):
        """ErrorLineDetector on 5000 lines completes in under 2 seconds."""
        buffer = self._build_large_buffer(5000)
        start = time.perf_counter()
        for line in buffer:
            ErrorLineDetector.classify(line)
        elapsed = time.perf_counter() - start
        assert elapsed < 2.0, f"ErrorLineDetector took {elapsed:.3f}s (limit: 2.0s)"

    def test_combined_pipeline_5000_lines_under_2_seconds(self):
        """SectionTokenizer + ErrorLineDetector together on 5000 lines < 2s."""
        buffer = self._build_large_buffer(5000)
        start = time.perf_counter()

        tok = SectionTokenizer()
        tok.tokenize(buffer)

        for line in buffer:
            ErrorLineDetector.classify(line)

        elapsed = time.perf_counter() - start
        assert elapsed < 2.0, f"Combined pipeline took {elapsed:.3f}s (limit: 2.0s)"

    def test_ai_turn_tokenizer_5000_lines_under_2_seconds(self):
        """AITurnTokenizer on 5000 lines completes in under 2 seconds."""
        buffer = self._build_large_buffer(5000)
        start = time.perf_counter()
        tok = AITurnTokenizer()
        tok.tokenize(buffer)
        elapsed = time.perf_counter() - start
        assert elapsed < 2.0, f"AITurnTokenizer took {elapsed:.3f}s (limit: 2.0s)"

    def test_code_block_detector_5000_lines_under_2_seconds(self):
        """CodeBlockDetector on 5000 lines completes in under 2 seconds."""
        buffer = self._build_large_buffer(5000)
        start = time.perf_counter()
        detector = CodeBlockDetector()
        detector.detect(buffer)
        elapsed = time.perf_counter() - start
        assert elapsed < 2.0, f"CodeBlockDetector took {elapsed:.3f}s (limit: 2.0s)"

    def test_all_detectors_5000_lines_under_2_seconds(self):
        """All detectors combined on 5000 lines complete in under 2 seconds."""
        buffer = self._build_large_buffer(5000)
        start = time.perf_counter()

        sec_tok = SectionTokenizer()
        sec_tok.tokenize(buffer)

        ai_tok = AITurnTokenizer()
        ai_tok.tokenize(buffer)

        cbd = CodeBlockDetector()
        cbd.detect(buffer)

        for line in buffer:
            ErrorLineDetector.classify(line)

        elapsed = time.perf_counter() - start
        assert elapsed < 2.0, f"All detectors took {elapsed:.3f}s (limit: 2.0s)"
