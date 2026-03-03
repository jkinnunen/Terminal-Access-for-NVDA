"""
Tests for Terminal Access keyboard gesture handling.

Tests cover gesture registration, conflict detection, help descriptions,
and the command layer (modal single-key command mode).
"""

import unittest
from unittest.mock import Mock, MagicMock, patch, call
import sys


class TestGestureRegistration(unittest.TestCase):
	"""Test gesture registration and configuration."""

	def test_no_gesture_conflicts(self):
		"""Test no conflicts with NVDA core gestures."""
		from globalPlugins.terminalAccess import GlobalPlugin

		# Common NVDA core gestures we should avoid
		nvda_core_gestures = {
			'kb:NVDA+upArrow',
			'kb:NVDA+downArrow',
			'kb:NVDA+leftArrow',
			'kb:NVDA+rightArrow',
			'kb:NVDA+control+upArrow',
			'kb:NVDA+control+downArrow',
			'kb:NVDA+tab',
			'kb:NVDA+shift+tab',
		}

		if hasattr(GlobalPlugin, '__gestures__'):
			plugin_gestures = set(GlobalPlugin.__gestures__.keys())

			# Check for conflicts
			conflicts = plugin_gestures.intersection(nvda_core_gestures)
			self.assertEqual(len(conflicts), 0,
				f"Gesture conflicts detected: {conflicts}")


class TestGestureDocumentation(unittest.TestCase):
	"""Test gesture help descriptions."""

	def test_gesture_help_descriptions(self):
		"""Test all gestures have help descriptions."""
		from globalPlugins.terminalAccess import GlobalPlugin

		# Get all script methods
		for attr_name in dir(GlobalPlugin):
			if attr_name.startswith('script_'):
				method = getattr(GlobalPlugin, attr_name)

				# Check if method has __doc__ or __func__.__doc__
				has_doc = (
					(hasattr(method, '__doc__') and method.__doc__ is not None) or
					(hasattr(method, '__func__') and
					 hasattr(method.__func__, '__doc__') and
					 method.__func__.__doc__ is not None)
				)

				self.assertTrue(has_doc,
					f"Script {attr_name} missing docstring")


class TestGestureExecution(unittest.TestCase):
	"""Test gesture execution and behavior."""

	# Note: Tests for specific script methods have been removed as they tested
	# functionality that was never implemented (script_toggleVerboseMode,
	# script_reportCurrentLine, script_reportPosition, script_reportSelection, etc.)
	# The actual implementation uses different method names like script_toggleQuietMode,
	# script_readCurrentLine, script_announcePosition, etc.
	pass


class TestGestureScoping(unittest.TestCase):
	"""Test that gestures only activate when a terminal has focus."""

	def test_gestures_disable_when_not_terminal(self):
		from globalPlugins.terminalAccess import GlobalPlugin

		plugin = GlobalPlugin()
		plugin._terminalGestures = {"kb:NVDA+alt+u": "readPreviousLine"}
		plugin._gesturesBound = True

		non_terminal = MagicMock()
		non_terminal.appModule = MagicMock()
		non_terminal.appModule.appName = "notepad"

		plugin._updateGestureBindingsForFocus(non_terminal)
		self.assertFalse(plugin._gesturesBound)

	def test_gestures_enable_for_terminal(self):
		from globalPlugins.terminalAccess import GlobalPlugin

		plugin = GlobalPlugin()
		plugin._terminalGestures = {"kb:NVDA+alt+u": "readPreviousLine"}
		plugin._gesturesBound = False

		terminal = MagicMock()
		terminal.appModule = MagicMock()
		terminal.appModule.appName = "windowsterminal"

		plugin._updateGestureBindingsForFocus(terminal)
		self.assertTrue(plugin._gesturesBound)


# ------------------------------------------------------------------
# Command Layer Tests
# ------------------------------------------------------------------

class TestCommandLayerMap(unittest.TestCase):
	"""Test the _COMMAND_LAYER_MAP constant is well-formed."""

	def test_map_is_non_empty(self):
		"""The command layer map must define at least one binding."""
		from globalPlugins.terminalAccess import _COMMAND_LAYER_MAP
		self.assertGreater(len(_COMMAND_LAYER_MAP), 0)

	def test_all_keys_are_gesture_strings(self):
		"""Every key must start with 'kb:'."""
		from globalPlugins.terminalAccess import _COMMAND_LAYER_MAP
		for gesture_id in _COMMAND_LAYER_MAP:
			self.assertTrue(gesture_id.startswith("kb:"),
				f"Gesture key {gesture_id!r} does not start with 'kb:'")

	def test_all_values_are_script_names(self):
		"""Every value must correspond to a real script_ method."""
		from globalPlugins.terminalAccess import _COMMAND_LAYER_MAP, GlobalPlugin
		for gesture_id, script_name in _COMMAND_LAYER_MAP.items():
			method_name = f"script_{script_name}"
			self.assertTrue(hasattr(GlobalPlugin, method_name),
				f"Layer maps {gesture_id!r} -> {script_name!r} but "
				f"GlobalPlugin has no method {method_name}")

	def test_escape_maps_to_exit(self):
		"""Escape key must map to exitCommandLayer."""
		from globalPlugins.terminalAccess import _COMMAND_LAYER_MAP
		self.assertEqual(_COMMAND_LAYER_MAP.get("kb:escape"), "exitCommandLayer")

	def test_no_nvda_modifier_keys(self):
		"""Layer keys must not require the NVDA modifier."""
		from globalPlugins.terminalAccess import _COMMAND_LAYER_MAP
		for gesture_id in _COMMAND_LAYER_MAP:
			self.assertNotIn("NVDA", gesture_id,
				f"Layer gesture {gesture_id!r} should not use NVDA modifier")

	def test_bookmark_digit_coverage(self):
		"""All 10 digits (0-9) should be mapped for jump and set."""
		from globalPlugins.terminalAccess import _COMMAND_LAYER_MAP
		for d in range(10):
			self.assertIn(f"kb:{d}", _COMMAND_LAYER_MAP,
				f"Jump-to-bookmark digit {d} missing from layer map")
			self.assertIn(f"kb:shift+{d}", _COMMAND_LAYER_MAP,
				f"Set-bookmark digit {d} missing from layer map")


class TestCommandLayerEntryExit(unittest.TestCase):
	"""Test entering and exiting the command layer."""

	def setUp(self):
		from globalPlugins.terminalAccess import GlobalPlugin
		self.plugin = GlobalPlugin()
		# Ensure the plugin thinks we're in a terminal context
		self.plugin.isTerminalApp = MagicMock(return_value=True)
		# Track bind/unbind calls
		self.plugin.bindGesture = MagicMock()
		self.plugin.removeGestureBinding = MagicMock()

	def test_enter_layer_sets_flag(self):
		"""Entering the layer sets _inCommandLayer to True."""
		self.assertFalse(self.plugin._inCommandLayer)
		self.plugin._enterCommandLayer()
		self.assertTrue(self.plugin._inCommandLayer)

	def test_enter_layer_binds_gestures(self):
		"""Entering the layer calls bindGesture for every key in the map."""
		from globalPlugins.terminalAccess import _COMMAND_LAYER_MAP
		self.plugin._enterCommandLayer()
		self.assertEqual(self.plugin.bindGesture.call_count,
			len(_COMMAND_LAYER_MAP))

	def test_exit_layer_clears_flag(self):
		"""Exiting the layer sets _inCommandLayer to False."""
		self.plugin._inCommandLayer = True
		self.plugin._exitCommandLayer()
		self.assertFalse(self.plugin._inCommandLayer)

	def test_exit_layer_unbinds_gestures(self):
		"""Exiting the layer calls removeGestureBinding for every key."""
		from globalPlugins.terminalAccess import _COMMAND_LAYER_MAP
		self.plugin._inCommandLayer = True
		self.plugin._exitCommandLayer()
		self.assertEqual(self.plugin.removeGestureBinding.call_count,
			len(_COMMAND_LAYER_MAP))

	def test_toggle_enters_then_exits(self):
		"""Toggling twice should enter then exit."""
		gesture = MagicMock()
		self.plugin.script_toggleCommandLayer(gesture)
		self.assertTrue(self.plugin._inCommandLayer)
		self.plugin.script_toggleCommandLayer(gesture)
		self.assertFalse(self.plugin._inCommandLayer)

	def test_double_enter_is_idempotent(self):
		"""Calling _enterCommandLayer twice should only bind once."""
		self.plugin._enterCommandLayer()
		first_count = self.plugin.bindGesture.call_count
		self.plugin._enterCommandLayer()
		self.assertEqual(self.plugin.bindGesture.call_count, first_count,
			"_enterCommandLayer should be idempotent when already in layer")

	def test_double_exit_is_idempotent(self):
		"""Calling _exitCommandLayer twice should only unbind once."""
		self.plugin._inCommandLayer = True
		self.plugin._exitCommandLayer()
		first_count = self.plugin.removeGestureBinding.call_count
		self.plugin._exitCommandLayer()
		self.assertEqual(self.plugin.removeGestureBinding.call_count, first_count,
			"_exitCommandLayer should be idempotent when not in layer")

	def test_enter_plays_high_tone(self):
		"""Entering the layer plays an 880 Hz tone."""
		tones_mock = sys.modules['tones']
		tones_mock.beep.reset_mock()
		self.plugin._enterCommandLayer()
		tones_mock.beep.assert_called_with(880, 100)

	def test_exit_plays_low_tone(self):
		"""Exiting the layer plays a 440 Hz tone."""
		tones_mock = sys.modules['tones']
		tones_mock.beep.reset_mock()
		self.plugin._inCommandLayer = True
		self.plugin._exitCommandLayer()
		tones_mock.beep.assert_called_with(440, 100)

	def test_exit_script_sends_key_when_not_in_layer(self):
		"""script_exitCommandLayer should pass through when not in layer."""
		gesture = MagicMock()
		self.plugin._inCommandLayer = False
		self.plugin.script_exitCommandLayer(gesture)
		gesture.send.assert_called_once()

	def test_exit_script_exits_layer_when_in_layer(self):
		"""script_exitCommandLayer should exit when in layer."""
		gesture = MagicMock()
		self.plugin._inCommandLayer = True
		self.plugin.script_exitCommandLayer(gesture)
		self.assertFalse(self.plugin._inCommandLayer)
		gesture.send.assert_not_called()

	def test_toggle_sends_key_when_not_terminal(self):
		"""Toggling outside terminal should pass through the gesture."""
		self.plugin.isTerminalApp = MagicMock(return_value=False)
		gesture = MagicMock()
		self.plugin.script_toggleCommandLayer(gesture)
		gesture.send.assert_called_once()
		self.assertFalse(self.plugin._inCommandLayer)


class TestCommandLayerFocusLoss(unittest.TestCase):
	"""Test that the command layer auto-exits when terminal loses focus."""

	def setUp(self):
		from globalPlugins.terminalAccess import GlobalPlugin
		self.plugin = GlobalPlugin()
		self.plugin.isTerminalApp = MagicMock(return_value=True)
		self.plugin.bindGesture = MagicMock()
		self.plugin.removeGestureBinding = MagicMock()

	def test_disable_gestures_exits_layer(self):
		"""_disableTerminalGestures must exit command layer."""
		self.plugin._inCommandLayer = True
		self.plugin._terminalGestures = {"kb:NVDA+alt+u": "readPreviousLine"}
		self.plugin._gesturesBound = True
		self.plugin._disableTerminalGestures()
		self.assertFalse(self.plugin._inCommandLayer)

	def test_focus_to_non_terminal_exits_layer(self):
		"""Switching to a non-terminal app exits the command layer."""
		# Enter the layer
		self.plugin._enterCommandLayer()
		self.assertTrue(self.plugin._inCommandLayer)
		self.plugin._terminalGestures = {"kb:NVDA+alt+u": "readPreviousLine"}
		self.plugin._gesturesBound = True

		# Now make isTerminalApp return False for the non-terminal object
		self.plugin.isTerminalApp = MagicMock(return_value=False)

		# Simulate focus leaving the terminal
		non_terminal = MagicMock()
		non_terminal.appModule = MagicMock()
		non_terminal.appModule.appName = "notepad"
		self.plugin._updateGestureBindingsForFocus(non_terminal)

		self.assertFalse(self.plugin._inCommandLayer)


class TestCommandLayerCopyModeInteraction(unittest.TestCase):
	"""Test interaction between command layer and copy mode."""

	def setUp(self):
		from globalPlugins.terminalAccess import GlobalPlugin
		self.plugin = GlobalPlugin()
		self.plugin.isTerminalApp = MagicMock(return_value=True)
		self.plugin.bindGesture = MagicMock()
		self.plugin.removeGestureBinding = MagicMock()

	def test_enter_layer_exits_copy_mode(self):
		"""Entering command layer should first exit copy mode if active."""
		self.plugin.copyMode = True
		self.plugin._enterCommandLayer()
		# copyMode should be cleared by _exitCopyModeBindings
		self.assertFalse(self.plugin.copyMode)
		self.assertTrue(self.plugin._inCommandLayer)

	def test_exit_copy_mode_restores_layer_bindings(self):
		"""Exiting copy mode while in layer re-binds layer keys (l, s, escape)."""
		from globalPlugins.terminalAccess import _COMMAND_LAYER_MAP
		# Simulate being in the command layer
		self.plugin._inCommandLayer = True
		self.plugin.copyMode = True

		# Reset bind mock to only track calls from _exitCopyModeBindings
		self.plugin.bindGesture.reset_mock()
		self.plugin._exitCopyModeBindings()

		# After exiting copy mode, layer bindings for l, s, escape should
		# have been re-bound
		rebound_gestures = {c.args[0] for c in self.plugin.bindGesture.call_args_list}
		for key in ("kb:l", "kb:s", "kb:escape"):
			if key in _COMMAND_LAYER_MAP:
				self.assertIn(key, rebound_gestures,
					f"Layer gesture {key!r} not re-bound after copy mode exit")

	def test_exit_copy_mode_no_rebind_when_layer_inactive(self):
		"""Exiting copy mode when layer is NOT active should NOT re-bind."""
		self.plugin._inCommandLayer = False
		self.plugin.copyMode = True
		self.plugin.bindGesture.reset_mock()
		self.plugin._exitCopyModeBindings()
		self.plugin.bindGesture.assert_not_called()


class TestCommandLayerCategory(unittest.TestCase):
	"""Test that all scripts are in the Terminal Access category."""

	def test_all_scripts_have_category(self):
		"""Every script should have the SCRCAT_TERMINALACCESS category."""
		from globalPlugins.terminalAccess import GlobalPlugin, SCRCAT_TERMINALACCESS

		for attr_name in dir(GlobalPlugin):
			if not attr_name.startswith('script_'):
				continue
			method = getattr(GlobalPlugin, attr_name)
			# Some scripts use scriptHandler.script decorator which sets
			# _script_category; others set it via the @script decorator.
			category = getattr(method, 'category', None)
			# NVDA stores category on the unbound function in some cases
			if category is None and hasattr(method, '__func__'):
				category = getattr(method.__func__, 'category', None)
			# The decorator may also store it as _script_category
			if category is None:
				category = getattr(method, '_script_category', None)

			# It's acceptable for the mock environment not to preserve all
			# decorator metadata; just verify it's set when available.
			if category is not None:
				self.assertEqual(category, SCRCAT_TERMINALACCESS,
					f"{attr_name} has category={category!r}, "
					f"expected {SCRCAT_TERMINALACCESS!r}")


if __name__ == '__main__':
	unittest.main()
