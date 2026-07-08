"""
Tests for AI CLI multiplexer profiles.

Covers profile existence, settings, window title detection,
multiplexer-nested detection (tmux + claude, screen + aider),
focusedPaneOnly behavior, debounce suppression, and profile
switch announcements.
"""

import unittest
from unittest.mock import Mock, MagicMock, patch
import sys
import time


class TestAIProfilesExist(unittest.TestCase):
	"""Verify that each AI CLI profile exists with correct settings."""

	def test_claude_profile_exists_with_correct_settings(self):
		"""Claude profile has PUNCT_MOST, keyEcho off, focusedPaneOnly True."""
		from lib.profiles import ProfileManager
		from lib.config import PUNCT_MOST

		pm = ProfileManager()
		profile = pm.get_profile('claude')
		self.assertIsNotNone(profile, "claude profile must exist")
		self.assertEqual(profile.punctuationLevel, PUNCT_MOST)
		self.assertFalse(profile.keyEcho)
		self.assertTrue(profile.focusedPaneOnly)

	def test_aider_profile_exists_with_correct_settings(self):
		"""Aider profile has PUNCT_MOST, focusedPaneOnly True."""
		from lib.profiles import ProfileManager
		from lib.config import PUNCT_MOST

		pm = ProfileManager()
		profile = pm.get_profile('aider')
		self.assertIsNotNone(profile, "aider profile must exist")
		self.assertEqual(profile.punctuationLevel, PUNCT_MOST)
		self.assertTrue(profile.focusedPaneOnly)

	def test_chatgpt_profile_exists_with_correct_settings(self):
		"""ChatGPT CLI profile has PUNCT_MOST."""
		from lib.profiles import ProfileManager
		from lib.config import PUNCT_MOST

		pm = ProfileManager()
		profile = pm.get_profile('chatgpt')
		self.assertIsNotNone(profile, "chatgpt profile must exist")
		self.assertEqual(profile.punctuationLevel, PUNCT_MOST)

	def test_copilot_profile_exists_with_correct_settings(self):
		"""GitHub Copilot CLI profile has PUNCT_MOST."""
		from lib.profiles import ProfileManager
		from lib.config import PUNCT_MOST

		pm = ProfileManager()
		profile = pm.get_profile('copilot')
		self.assertIsNotNone(profile, "copilot profile must exist")
		self.assertEqual(profile.punctuationLevel, PUNCT_MOST)

	def test_ollama_profile_exists_with_correct_settings(self):
		"""Ollama profile has PUNCT_MOST."""
		from lib.profiles import ProfileManager
		from lib.config import PUNCT_MOST

		pm = ProfileManager()
		profile = pm.get_profile('ollama')
		self.assertIsNotNone(profile, "ollama profile must exist")
		self.assertEqual(profile.punctuationLevel, PUNCT_MOST)


class TestAIProfilesInBuiltinNames(unittest.TestCase):
	"""Verify new AI CLI profiles are in _BUILTIN_PROFILE_NAMES."""

	def test_aider_in_builtin_names(self):
		from lib.profiles import _BUILTIN_PROFILE_NAMES
		self.assertIn('aider', _BUILTIN_PROFILE_NAMES)

	def test_chatgpt_in_builtin_names(self):
		from lib.profiles import _BUILTIN_PROFILE_NAMES
		self.assertIn('chatgpt', _BUILTIN_PROFILE_NAMES)

	def test_copilot_in_builtin_names(self):
		from lib.profiles import _BUILTIN_PROFILE_NAMES
		self.assertIn('copilot', _BUILTIN_PROFILE_NAMES)

	def test_ollama_in_builtin_names(self):
		from lib.profiles import _BUILTIN_PROFILE_NAMES
		self.assertIn('ollama', _BUILTIN_PROFILE_NAMES)

	def test_claude_already_in_builtin_names(self):
		"""Claude was already in _BUILTIN_PROFILE_NAMES before this work."""
		from lib.profiles import _BUILTIN_PROFILE_NAMES
		self.assertIn('claude', _BUILTIN_PROFILE_NAMES)


class TestWindowTitleDetection(unittest.TestCase):
	"""Test detect_application() matches AI CLI names in window titles."""

	def _make_focus(self, title, app_name='windowsterminal'):
		obj = Mock()
		obj.appModule = Mock()
		obj.appModule.appName = app_name
		obj.name = title
		return obj

	def test_detect_claude_from_window_title(self):
		"""Window title 'claude - my-project' detects claude profile."""
		from lib.profiles import ProfileManager
		pm = ProfileManager()
		obj = self._make_focus("claude - my-project")
		self.assertEqual(pm.detect_application(obj), 'claude')

	def test_detect_aider_from_window_title(self):
		"""Window title containing 'aider' detects aider profile."""
		from lib.profiles import ProfileManager
		pm = ProfileManager()
		obj = self._make_focus("aider v0.50 - repo")
		self.assertEqual(pm.detect_application(obj), 'aider')

	def test_detect_chatgpt_from_window_title(self):
		"""Window title containing 'chatgpt' detects chatgpt profile."""
		from lib.profiles import ProfileManager
		pm = ProfileManager()
		obj = self._make_focus("chatgpt session")
		self.assertEqual(pm.detect_application(obj), 'chatgpt')

	def test_detect_copilot_from_window_title(self):
		"""Window title containing 'copilot' detects copilot profile."""
		from lib.profiles import ProfileManager
		pm = ProfileManager()
		obj = self._make_focus("copilot suggest")
		self.assertEqual(pm.detect_application(obj), 'copilot')

	def test_detect_ollama_from_window_title(self):
		"""Window title containing 'ollama' detects ollama profile."""
		from lib.profiles import ProfileManager
		pm = ProfileManager()
		obj = self._make_focus("ollama run llama3")
		self.assertEqual(pm.detect_application(obj), 'ollama')


class TestMultiplexerNestedDetection(unittest.TestCase):
	"""When inside tmux/screen, AI CLI profile takes priority."""

	def _make_focus(self, title, app_name='windowsterminal'):
		obj = Mock()
		obj.appModule = Mock()
		obj.appModule.appName = app_name
		obj.name = title
		return obj

	def test_tmux_plus_claude_returns_claude(self):
		"""tmux title containing 'claude' returns claude, not tmux."""
		from lib.profiles import ProfileManager
		pm = ProfileManager()
		# Typical tmux title: "tmux: claude - my-project"
		obj = self._make_focus("tmux: claude - my-project")
		result = pm.detect_application(obj)
		self.assertEqual(result, 'claude')

	def test_tmux_plus_unknown_returns_tmux(self):
		"""tmux title without AI CLI name returns tmux profile."""
		from lib.profiles import ProfileManager
		pm = ProfileManager()
		obj = self._make_focus("tmux: bash - ~/code")
		result = pm.detect_application(obj)
		self.assertEqual(result, 'tmux')

	def test_screen_plus_aider_returns_aider(self):
		"""screen title containing 'aider' returns aider, not screen."""
		from lib.profiles import ProfileManager
		pm = ProfileManager()
		obj = self._make_focus("screen: aider v0.50")
		result = pm.detect_application(obj)
		self.assertEqual(result, 'aider')

	def test_tmux_plus_ollama_returns_ollama(self):
		"""tmux title containing 'ollama' returns ollama profile."""
		from lib.profiles import ProfileManager
		pm = ProfileManager()
		obj = self._make_focus("tmux: ollama run mistral")
		result = pm.detect_application(obj)
		self.assertEqual(result, 'ollama')


class TestFocusedPaneOnly(unittest.TestCase):
	"""Verify focusedPaneOnly is respected on AI profiles."""

	def test_claude_focused_pane_only(self):
		"""Claude profile has focusedPaneOnly = True."""
		from lib.profiles import ProfileManager
		pm = ProfileManager()
		profile = pm.get_profile('claude')
		self.assertTrue(profile.focusedPaneOnly)

	def test_aider_focused_pane_only(self):
		"""Aider profile has focusedPaneOnly = True."""
		from lib.profiles import ProfileManager
		pm = ProfileManager()
		profile = pm.get_profile('aider')
		self.assertTrue(profile.focusedPaneOnly)

	def test_chatgpt_no_focused_pane_only(self):
		"""ChatGPT profile does not set focusedPaneOnly (not multiplexer-oriented)."""
		from lib.profiles import ProfileManager
		pm = ProfileManager()
		profile = pm.get_profile('chatgpt')
		# chatgpt doesn't need focusedPaneOnly since it is not typically
		# run inside multiplexers the same way
		self.assertIsNone(profile.focusedPaneOnly)


class TestDebounceUpdate(unittest.TestCase):
	"""Test WindowMonitor.debounce_update suppresses repeated content."""

	def test_debounce_suppresses_identical_content(self):
		"""Calling debounce_update twice with same content only announces once."""
		from lib.window_management import WindowMonitor

		monitor = WindowMonitor(
			terminal_obj=Mock(),
			position_calculator=Mock(),
			debounce_ms=100,
		)
		monitor._announce_change = Mock()

		monitor.debounce_update("test", "hello world")
		monitor.debounce_update("test", "hello world")

		# Only one announcement for identical content
		self.assertEqual(monitor._announce_change.call_count, 1)

	def test_debounce_announces_different_content(self):
		"""Different content is announced even within debounce window."""
		from lib.window_management import WindowMonitor

		monitor = WindowMonitor(
			terminal_obj=Mock(),
			position_calculator=Mock(),
			debounce_ms=50,
		)
		monitor._announce_change = Mock()

		monitor.debounce_update("test", "first")
		# Wait for debounce window to elapse
		time.sleep(0.06)
		monitor.debounce_update("test", "second")

		self.assertEqual(monitor._announce_change.call_count, 2)


class TestProfileSwitchAnnouncement(unittest.TestCase):
	"""Profile switch triggers an announcement."""

	def test_profile_switch_announces_display_name(self):
		"""Switching to claude profile announces 'Claude CLI'."""
		from globalPlugins.terminalAccess import GlobalPlugin

		plugin = GlobalPlugin()
		# Simulate switching terminal apps
		plugin.lastTerminalAppName = 'default'
		plugin._currentProfile = plugin._profileManager.get_profile('claude')

		# _announceProfileIfNew should call ui.message with the display name
		obj = Mock()
		plugin._announceProfileIfNew(obj, 'claude')

		ui_mod = sys.modules['ui']
		ui_mod.message.assert_called()
		msg = ui_mod.message.call_args[0][0]
		self.assertIn('Claude', msg)

	def test_no_announcement_when_same_app(self):
		"""No announcement when terminal app hasn't changed."""
		from globalPlugins.terminalAccess import GlobalPlugin

		plugin = GlobalPlugin()
		plugin.lastTerminalAppName = 'claude'
		plugin._currentProfile = plugin._profileManager.get_profile('claude')

		ui_mod = sys.modules['ui']
		ui_mod.message.reset_mock()

		obj = Mock()
		plugin._announceProfileIfNew(obj, 'claude')

		ui_mod.message.assert_not_called()


if __name__ == '__main__':
	unittest.main()
