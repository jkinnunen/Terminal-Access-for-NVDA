"""Tests that all Terminal Access dialogs raise themselves to the foreground.

Without Raise(), dialogs can appear behind the terminal window. Screen reader
users won't know the dialog opened because focus stays on the terminal.
"""
import re


def _file_has_raise_in_class(filepath, class_name):
	"""Check if a class in a file calls self.Raise() anywhere in its body."""
	with open(filepath, 'r') as f:
		source = f.read()
	# Find the class definition and extract its body until the next class
	# or end of indentation block
	pattern = rf'class {class_name}\b.*?(?=\nclass |\n[^\s\n#]|\Z)'
	match = re.search(pattern, source, re.DOTALL)
	if not match:
		return False
	class_body = match.group(0)
	return bool(re.search(r'self\.Raise\(\)', class_body))


def _file_has_delegate(filepath, factory_name):
	"""Check that a factory function delegates to BrowsableListDialog.

	The bookmark, section, AI turn, URL, and search dialogs are factory
	functions that build a BrowsableListDialog. The foreground Raise()
	lives in that shared component, so delegating to it inherits the
	guarantee.
	"""
	with open(filepath, 'r') as f:
		source = f.read()
	pattern = rf'def {factory_name}\b.*?(?=\ndef |\nclass |\n[^\s\n#]|\Z)'
	match = re.search(pattern, source, re.DOTALL)
	if not match:
		return False
	body = match.group(0)
	return 'BrowsableListDialog' in body


class TestDialogForeground:
	"""Every dialog must appear in the foreground.

	Standalone dialog classes call self.Raise() directly. The migrated
	factory dialogs delegate to BrowsableListDialog, which calls Raise()
	itself, so the guarantee is inherited.
	"""

	def test_browsable_list_dialog_raises(self):
		"""The shared BrowsableListDialog must call Raise() for all factories."""
		assert _file_has_raise_in_class(
			'addon/lib/list_dialogs.py', 'BrowsableListDialog'
		), "BrowsableListDialog must call self.Raise()"

	def test_bookmark_list_dialog_delegates(self):
		"""BookmarkListDialog inherits Raise() via BrowsableListDialog."""
		assert _file_has_delegate(
			'addon/lib/navigation.py', 'BookmarkListDialog'
		), "BookmarkListDialog must delegate to BrowsableListDialog"

	def test_ai_turn_list_dialog_delegates(self):
		"""AiTurnListDialog inherits Raise() via BrowsableListDialog."""
		assert _file_has_delegate(
			'addon/lib/navigation.py', 'AiTurnListDialog'
		), "AiTurnListDialog must delegate to BrowsableListDialog"

	def test_search_results_dialog_delegates(self):
		"""SearchResultsDialog inherits Raise() via BrowsableListDialog."""
		assert _file_has_delegate(
			'addon/lib/search.py', 'SearchResultsDialog'
		), "SearchResultsDialog must delegate to BrowsableListDialog"

	def test_url_list_dialog_delegates(self):
		"""UrlListDialog inherits Raise() via BrowsableListDialog."""
		assert _file_has_delegate(
			'addon/lib/search.py', 'UrlListDialog'
		), "UrlListDialog must delegate to BrowsableListDialog"

	def test_profile_selection_dialog_raises(self):
		"""ProfileSelectionDialog must call Raise() to appear above terminal."""
		assert _file_has_raise_in_class(
			'addon/lib/profiles.py', 'ProfileSelectionDialog'
		), "ProfileSelectionDialog must call self.Raise()"


class TestDialogLaunchSites:
	"""Dialog launch sites must use prePopup/postPopup for proper NVDA integration."""

	def _get_plugin_source(self):
		with open('addon/globalPlugins/terminalAccess.py', 'r') as f:
			return f.read()

	def test_bookmark_dialog_uses_pre_post_popup(self):
		"""Bookmark dialog launch must wrap with prePopup/postPopup."""
		source = self._get_plugin_source()
		match = re.search(
			r'def _showBookmarkDialog\(self\):(.*?)(?=\n\tdef |\n\t# Section)',
			source, re.DOTALL
		)
		assert match, "Could not find _showBookmarkDialog method"
		body = match.group(1)
		assert 'prePopup' in body, (
			"_showBookmarkDialog must call gui.mainFrame.prePopup()"
		)
		assert 'postPopup' in body, (
			"_showBookmarkDialog must call gui.mainFrame.postPopup()"
		)

	def test_profile_dialog_uses_pre_post_popup(self):
		"""Profile dialog launch must wrap with prePopup/postPopup."""
		source = self._get_plugin_source()
		idx = source.find('ProfileSelectionDialog(gui.mainFrame')
		assert idx > 0, "Could not find ProfileSelectionDialog launch"
		context = source[max(0, idx-300):idx+300]
		assert 'prePopup' in context, (
			"ProfileSelectionDialog launch must be wrapped with prePopup/postPopup"
		)
