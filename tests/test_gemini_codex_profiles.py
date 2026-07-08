"""
Tests for Gemini CLI and OpenAI Codex CLI profiles.

These AI CLIs should have the same level of support as Claude, Aider,
ChatGPT, Copilot, and Ollama.
"""
from unittest.mock import Mock
import pytest

from lib.profiles import ProfileManager, _BUILTIN_PROFILE_NAMES


class TestGeminiProfile:
    """Gemini CLI should have a built-in profile."""

    def test_gemini_in_builtin_names(self):
        assert "gemini" in _BUILTIN_PROFILE_NAMES

    def test_gemini_profile_exists(self):
        mgr = ProfileManager()
        profile = mgr.get_profile("gemini")
        assert profile is not None

    def test_gemini_display_name(self):
        mgr = ProfileManager()
        profile = mgr.get_profile("gemini")
        assert "Gemini" in profile.displayName

    def test_gemini_punctuation_most(self):
        mgr = ProfileManager()
        profile = mgr.get_profile("gemini")
        assert profile.punctuationLevel == 2  # PUNCT_MOST

    def test_gemini_detected_from_title(self):
        mgr = ProfileManager()
        obj = Mock()
        obj.appModule = Mock()
        obj.appModule.appName = "windowsterminal"
        obj.name = "gemini - conversation"
        assert mgr.detect_application(obj) == "gemini"

    def test_gemini_detected_in_tmux(self):
        mgr = ProfileManager()
        obj = Mock()
        obj.appModule = Mock()
        obj.appModule.appName = "windowsterminal"
        obj.name = "tmux: gemini session"
        assert mgr.detect_application(obj) == "gemini"


class TestCodexProfile:
    """OpenAI Codex CLI should have a built-in profile."""

    def test_codex_in_builtin_names(self):
        assert "codex" in _BUILTIN_PROFILE_NAMES

    def test_codex_profile_exists(self):
        mgr = ProfileManager()
        profile = mgr.get_profile("codex")
        assert profile is not None

    def test_codex_display_name(self):
        mgr = ProfileManager()
        profile = mgr.get_profile("codex")
        assert "Codex" in profile.displayName

    def test_codex_punctuation_most(self):
        mgr = ProfileManager()
        profile = mgr.get_profile("codex")
        assert profile.punctuationLevel == 2  # PUNCT_MOST

    def test_codex_detected_from_title(self):
        mgr = ProfileManager()
        obj = Mock()
        obj.appModule = Mock()
        obj.appModule.appName = "windowsterminal"
        obj.name = "codex - project"
        assert mgr.detect_application(obj) == "codex"

    def test_codex_detected_in_tmux(self):
        mgr = ProfileManager()
        obj = Mock()
        obj.appModule = Mock()
        obj.appModule.appName = "windowsterminal"
        obj.name = "tmux: codex session"
        assert mgr.detect_application(obj) == "codex"


class TestAITurnTokenizerRecognition:
    """AI turn tokenizer should recognize Gemini and Codex markers."""

    def test_gemini_assistant_marker(self):
        from lib.ai_turn_tokenizer import AITurnTokenizer
        tok = AITurnTokenizer()
        turns = tok.tokenize(["You: hello", "Gemini: Here is my response"])
        assert any(t.role == "assistant" for t in turns)

    def test_codex_assistant_marker(self):
        from lib.ai_turn_tokenizer import AITurnTokenizer
        tok = AITurnTokenizer()
        turns = tok.tokenize(["You: hello", "Codex: Here is the code"])
        assert any(t.role == "assistant" for t in turns)


class TestBookmarkAILabeling:
    """Bookmark auto-labeling should recognize Gemini and Codex."""

    def test_gemini_label(self):
        from lib.navigation import BookmarkManager
        result = BookmarkManager._classify_ai_turn("Gemini: Here is my response to your question")
        assert result is not None
        role, preview = result
        assert role == "assistant"

    def test_codex_label(self):
        from lib.navigation import BookmarkManager
        result = BookmarkManager._classify_ai_turn("Codex: function fibonacci(n) {")
        assert result is not None
        role, preview = result
        assert role == "assistant"
