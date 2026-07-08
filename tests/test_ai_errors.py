"""Tests for AI CLI error/limit detection and length check utilities."""

import pytest
from unittest.mock import MagicMock, Mock, patch
from lib.text_processing import ErrorLineDetector


class TestAIErrorDetection:
	"""AI-specific error patterns must return 'ai_error'."""

	def setup_method(self):
		self.detector = ErrorLineDetector()

	# -- Rate limit patterns --

	def test_rate_limit_exceeded(self):
		assert self.detector.classify("Error: rate limit exceeded") == "ai_error"

	def test_too_many_requests(self):
		assert self.detector.classify("too many requests, please retry after 30s") == "ai_error"

	def test_http_429(self):
		"""HTTP 429 status in response should trigger ai_error."""
		assert self.detector.classify("HTTP/1.1 429 Too Many Requests") == "ai_error"

	def test_quota_exceeded(self):
		assert self.detector.classify("Error: quota exceeded for model gpt-4") == "ai_error"

	def test_throttled(self):
		assert self.detector.classify("Request throttled. Please wait.") == "ai_error"

	# -- Token limit patterns --

	def test_token_limit(self):
		assert self.detector.classify("token limit reached for this conversation") == "ai_error"

	def test_context_length_exceeded(self):
		assert self.detector.classify("Context length of 128000 tokens exceeded") == "ai_error"

	def test_maximum_tokens(self):
		assert self.detector.classify("maximum number of tokens has been reached") == "ai_error"

	def test_truncated_due_to(self):
		assert self.detector.classify("Response truncated due to length") == "ai_error"

	# -- API errors --

	def test_api_error(self):
		assert self.detector.classify("API error: 503 Service Unavailable") == "ai_error"

	def test_authentication_failed(self):
		assert self.detector.classify("authentication failed: invalid token") == "ai_error"

	def test_invalid_key(self):
		assert self.detector.classify("Error: invalid API key provided") == "ai_error"

	def test_connection_refused_ai(self):
		"""connection refused is already 'error'; AI-specific 'connection refused'
		with additional context should still be detected as some kind of error."""
		result = self.detector.classify("API connection refused by server")
		assert result in ("error", "ai_error")

	# -- Model errors --

	def test_model_not_found(self):
		assert self.detector.classify("model 'gpt-5' not found") == "ai_error"

	def test_model_unavailable(self):
		assert self.detector.classify("The model is currently unavailable") == "ai_error"

	def test_overloaded(self):
		assert self.detector.classify("Server overloaded, try again later") == "ai_error"


class TestAIWarningDetection:
	"""AI-specific warning patterns must return 'ai_warning'."""

	def setup_method(self):
		self.detector = ErrorLineDetector()

	def test_approaching_limit(self):
		assert self.detector.classify("Approaching rate limit for this endpoint") == "ai_warning"

	def test_nearing_quota(self):
		assert self.detector.classify("Warning: nearing quota for current billing period") == "ai_warning"


class TestAIFalsePositives:
	"""Normal AI output must NOT trigger ai_error or ai_warning."""

	def setup_method(self):
		self.detector = ErrorLineDetector()

	def test_normal_ai_prose_about_errors(self):
		"""AI discussing error handling triggers 'error' (existing behavior).

		The existing pattern \\berror\\b[\\[:\\s] matches "error " with
		trailing space. This is acceptable because the pattern was designed
		for structured error prefixes, and "error handling" in prose is
		uncommon in terminal output.
		"""
		result = self.detector.classify("The error handling code looks good")
		assert result == "error"

	def test_normal_ai_code_review(self):
		assert self.detector.classify("Consider adding rate limiting to your API") is None

	def test_normal_ai_token_discussion(self):
		assert self.detector.classify("You can use tokens for authentication") is None

	def test_normal_ai_model_discussion(self):
		assert self.detector.classify("This model works well for classification tasks") is None

	def test_normal_ai_truncation_discussion(self):
		"""Truncation in prose must NOT trigger ai_error.

		Only 'truncated due to' triggers, not bare 'truncated'.
		"""
		assert self.detector.classify("The string was truncated at position 50") is None


class TestExistingPatternsNotBroken:
	"""Existing error/warning patterns must still work after AI additions."""

	def setup_method(self):
		self.detector = ErrorLineDetector()

	def test_gcc_error_still_works(self):
		assert self.detector.classify("main.c:5:12: error: expected ';'") == "error"

	def test_python_traceback_still_works(self):
		assert self.detector.classify("Traceback (most recent call last):") == "error"

	def test_python_exception_still_works(self):
		assert self.detector.classify("ValueError: invalid literal") == "error"

	def test_rust_warning_still_works(self):
		assert self.detector.classify("warning: unused variable: `x`") == "warning"

	def test_npm_err_still_works(self):
		assert self.detector.classify("npm ERR! 404 Not Found") == "error"

	def test_segfault_still_works(self):
		assert self.detector.classify("Segmentation fault (core dumped)") == "error"

	def test_false_positive_mirror_still_clean(self):
		assert self.detector.classify("Downloading from mirror.example.com") is None

	def test_false_positive_forewarning_still_clean(self):
		assert self.detector.classify("This was a forewarning") is None


class TestLengthCheckUtility:
	"""Length check utility for warning about large inputs."""

	def test_estimate_prompt_length(self):
		from lib.text_processing import estimate_prompt_length
		text = "Hello, world!"
		assert estimate_prompt_length(text) == len(text)

	def test_estimate_prompt_length_multiline(self):
		from lib.text_processing import estimate_prompt_length
		text = "line one\nline two\nline three"
		assert estimate_prompt_length(text) == len(text)

	def test_should_warn_length_above_threshold(self):
		from lib.text_processing import should_warn_length
		text = "x" * 15000
		assert should_warn_length(text, threshold=10000) is True

	def test_should_warn_length_below_threshold(self):
		from lib.text_processing import should_warn_length
		text = "x" * 5000
		assert should_warn_length(text, threshold=10000) is False

	def test_should_warn_length_at_threshold(self):
		from lib.text_processing import should_warn_length
		text = "x" * 10000
		assert should_warn_length(text, threshold=10000) is False

	def test_should_warn_length_default_threshold(self):
		from lib.text_processing import should_warn_length
		text = "x" * 15000
		assert should_warn_length(text) is True

	def test_should_warn_length_short_text_default(self):
		from lib.text_processing import should_warn_length
		text = "short text"
		assert should_warn_length(text) is False

	def test_empty_string(self):
		from lib.text_processing import estimate_prompt_length, should_warn_length
		assert estimate_prompt_length("") == 0
		assert should_warn_length("") is False


class TestAIErrorAudioCues:
	"""AI error/warning tones must be distinct from regular error/warning."""

	def test_ai_error_tone_in_tone_map(self):
		from lib.audio_cues import _TONE_MAP
		assert "ai_error" in _TONE_MAP, "ai_error must have a tone definition"

	def test_ai_warning_tone_in_tone_map(self):
		from lib.audio_cues import _TONE_MAP
		assert "ai_warning" in _TONE_MAP, "ai_warning must have a tone definition"

	def test_ai_error_tone_distinct_from_error(self):
		from lib.audio_cues import _TONE_MAP
		assert _TONE_MAP["ai_error"] != _TONE_MAP["error"], (
			"ai_error tone must differ from regular error tone"
		)

	def test_ai_warning_tone_distinct_from_warning(self):
		from lib.audio_cues import _TONE_MAP
		assert _TONE_MAP["ai_warning"] != _TONE_MAP["warning"], (
			"ai_warning tone must differ from regular warning tone"
		)

	def test_ai_error_tone_plays_twice(self):
		"""ai_error should play a double beep for distinctiveness."""
		from lib.audio_cues import _TONE_MAP
		assert len(_TONE_MAP["ai_error"]) == 2, (
			"ai_error tone should consist of two beeps"
		)


class TestAIErrorIntegration:
	"""AI error classifications must be wired into audio cue playback."""

	def test_readLineWithIndentation_handles_ai_error(self):
		"""_readLineWithIndentation must play ai_error tone for AI errors."""
		import tones
		tones.beep = MagicMock()

		from globalPlugins.terminalAccess import GlobalPlugin
		plugin = GlobalPlugin()
		plugin.isTerminalApp = MagicMock(return_value=True)

		pos = MagicMock()
		line_info = MagicMock()
		line_info.text = "Error: rate limit exceeded"
		pos.copy.return_value = line_info
		plugin._getReviewPosition = MagicMock(return_value=pos)

		gesture = MagicMock()
		move_fn = MagicMock()
		plugin._readLineWithIndentation(gesture, move_fn)

		# Should have beeped (ai_error tone: 330 Hz played twice)
		assert tones.beep.call_count >= 1, "ai_error must produce at least one beep"

	def test_readLineWithIndentation_handles_ai_warning(self):
		"""_readLineWithIndentation must play ai_warning tone for AI warnings."""
		import tones
		tones.beep = MagicMock()

		from globalPlugins.terminalAccess import GlobalPlugin
		plugin = GlobalPlugin()
		plugin.isTerminalApp = MagicMock(return_value=True)

		pos = MagicMock()
		line_info = MagicMock()
		line_info.text = "Approaching rate limit for this endpoint"
		pos.copy.return_value = line_info
		plugin._getReviewPosition = MagicMock(return_value=pos)

		gesture = MagicMock()
		move_fn = MagicMock()
		plugin._readLineWithIndentation(gesture, move_fn)

		assert tones.beep.call_count >= 1, "ai_warning must produce at least one beep"

	def test_overlay_beepForClassification_handles_ai_error(self):
		"""Terminal overlay must play ai_error tones via audio_cues."""
		from lib.terminal_overlay import TerminalAccessTerminal

		obj = TerminalAccessTerminal()
		mock_tones = MagicMock()
		with patch("lib.audio_cues.tones", mock_tones):
			obj._beepForClassification("Error: rate limit exceeded")
			assert mock_tones.beep.call_count >= 1, (
				"overlay must beep for ai_error"
			)

	def test_overlay_beepForClassification_handles_ai_warning(self):
		"""Terminal overlay must play ai_warning tones via audio_cues."""
		from lib.terminal_overlay import TerminalAccessTerminal

		obj = TerminalAccessTerminal()
		mock_tones = MagicMock()
		with patch("lib.audio_cues.tones", mock_tones):
			obj._beepForClassification("Approaching rate limit")
			assert mock_tones.beep.call_count >= 1, (
				"overlay must beep for ai_warning"
			)

	def test_checkErrorAudioCue_handles_ai_error(self):
		"""_checkErrorAudioCue in GlobalPlugin must handle ai_error."""
		import tones
		tones.beep = MagicMock()

		from globalPlugins.terminalAccess import GlobalPlugin
		plugin = GlobalPlugin()
		plugin.isTerminalApp = MagicMock(return_value=True)

		pos = MagicMock()
		line_info = MagicMock()
		line_info.text = "Error: quota exceeded"
		pos.copy.return_value = line_info
		plugin._getReviewPosition = MagicMock(return_value=pos)

		plugin._checkErrorAudioCue()

		assert tones.beep.call_count >= 1, "ai_error must trigger beep in _checkErrorAudioCue"
