"""
Tests for tab management functionality in Terminal Access.
"""
import sys
from unittest.mock import Mock, MagicMock, patch
import pytest


def test_tab_manager_initialization():
	"""Test that TabManager initializes correctly."""
	from globalPlugins.terminalAccess import TabManager

	# Create mock terminal
	terminal = Mock()
	terminal.windowHandle = 12345
	terminal.windowText = "Terminal - Tab 1"

	# Create TabManager
	manager = TabManager(terminal)

	# Verify initialization
	assert manager is not None
	assert manager._terminal == terminal
	assert manager._tabs is not None
	assert manager._current_tab_id is not None


def test_tab_manager_generates_unique_ids():
	"""Test that TabManager generates unique IDs for different terminals."""
	from globalPlugins.terminalAccess import TabManager

	# Create two different mock terminals
	terminal1 = Mock()
	terminal1.windowHandle = 12345
	terminal1.windowText = "Terminal - Tab 1"

	terminal2 = Mock()
	terminal2.windowHandle = 67890
	terminal2.windowText = "Terminal - Tab 2"

	# Create TabManagers
	manager1 = TabManager(terminal1)
	manager2 = TabManager(terminal2)

	# Tab IDs should be different
	tab_id1 = manager1.get_current_tab_id()
	tab_id2 = manager2.get_current_tab_id()

	assert tab_id1 != tab_id2


def test_tab_manager_tracks_multiple_tabs():
	"""Test that TabManager can track multiple tabs."""
	from globalPlugins.terminalAccess import TabManager

	# Create mock terminals for different tabs
	terminal1 = Mock()
	terminal1.windowHandle = 12345
	terminal1.windowText = "Terminal - Tab 1"

	terminal2 = Mock()
	terminal2.windowHandle = 12345
	terminal2.windowText = "Terminal - Tab 2"

	# Create TabManager with first terminal
	manager = TabManager(terminal1)
	tab_id1 = manager.get_current_tab_id()

	# Update to second terminal (simulating tab switch)
	manager.update_terminal(terminal2)
	tab_id2 = manager.get_current_tab_id()

	# Should have tracked both tabs
	assert manager.get_tab_count() >= 2
	tabs = manager.list_tabs()
	assert len(tabs) >= 2


def test_tab_manager_detects_tab_changes():
	"""Test that TabManager detects when tabs change."""
	from globalPlugins.terminalAccess import TabManager

	# Create mock terminals
	terminal1 = Mock()
	terminal1.windowHandle = 12345
	terminal1.windowText = "Terminal - Tab 1"

	terminal2 = Mock()
	terminal2.windowHandle = 12345
	terminal2.windowText = "Terminal - Tab 2"

	# Create TabManager
	manager = TabManager(terminal1)

	# Update to different terminal - should detect change
	tab_changed = manager.update_terminal(terminal2)
	assert tab_changed is True


def test_bookmark_manager_tab_aware():
	"""Test that BookmarkManager is tab-aware."""
	from globalPlugins.terminalAccess import BookmarkManager, TabManager

	# Create mock terminal
	terminal = Mock()
	terminal.windowHandle = 12345
	terminal.windowText = "Terminal"

	# Create TabManager and BookmarkManager
	tab_manager = TabManager(terminal)
	bookmark_manager = BookmarkManager(terminal, tab_manager)

	# Create mock TextInfo for bookmark
	mock_textinfo = Mock()
	mock_textinfo.bookmark = "test_bookmark_obj"

	# Set a bookmark
	with patch('api.getReviewPosition', return_value=mock_textinfo):
		result = bookmark_manager.set_bookmark("1")
		assert result is True
		assert bookmark_manager.has_bookmark("1")


def test_bookmarks_isolated_per_window():
	"""Bookmarks are isolated per terminal window (by window handle).

	This replaces the old per-tab isolation test. Bookmark storage used to
	be keyed on a hash of the window title, which isolated Windows Terminal
	tabs but churned on every focus (titles change constantly), orphaning
	bookmarks. Storage is now keyed on the stable window handle. The
	accepted tradeoff: several tabs inside ONE Windows Terminal window share
	a handle and therefore share bookmark storage; separate terminal windows
	remain isolated, which is the guarantee that matters and is verified
	here.
	"""
	from globalPlugins.terminalAccess import BookmarkManager

	# Two separate terminal windows (different handles).
	window1 = Mock()
	window1.windowHandle = 12345
	window1.makeTextInfo = Mock(return_value=Mock())

	window2 = Mock()
	window2.windowHandle = 67890
	window2.makeTextInfo = Mock(return_value=Mock())

	bookmark_manager = BookmarkManager(window1)

	ti1 = Mock()
	ti1.bookmark = "bookmark_win1"
	with patch('api.getReviewPosition', return_value=ti1):
		bookmark_manager.set_bookmark("1")

	# Switch to the second window: its bookmarks are separate.
	bookmark_manager.update_terminal(window2)
	assert not bookmark_manager.has_bookmark("1")

	ti2 = Mock()
	ti2.bookmark = "bookmark_win2"
	with patch('api.getReviewPosition', return_value=ti2):
		bookmark_manager.set_bookmark("2")
	assert bookmark_manager.has_bookmark("2")
	assert not bookmark_manager.has_bookmark("1")

	# Switch back to the first window: its bookmark is restored.
	bookmark_manager.update_terminal(window1)
	assert bookmark_manager.has_bookmark("1")
	assert not bookmark_manager.has_bookmark("2")


def test_bookmarks_shared_across_tabs_in_one_window():
	"""Accepted tradeoff: tabs in a single Windows Terminal window share a
	window handle, so they share bookmark storage. This is preferable to the
	old title-keyed behavior that lost bookmarks on every title change."""
	from globalPlugins.terminalAccess import BookmarkManager

	tab1 = Mock()
	tab1.windowHandle = 12345
	tab1.windowText = "Tab 1"
	tab1.makeTextInfo = Mock(return_value=Mock())

	tab2 = Mock()
	tab2.windowHandle = 12345  # same window, different tab
	tab2.windowText = "Tab 2"
	tab2.makeTextInfo = Mock(return_value=Mock())

	bookmark_manager = BookmarkManager(tab1)
	ti = Mock()
	ti.bookmark = "b"
	with patch('api.getReviewPosition', return_value=ti):
		bookmark_manager.set_bookmark("1")

	bookmark_manager.update_terminal(tab2)
	assert bookmark_manager.has_bookmark("1")
def test_bookmark_manager_legacy_mode():
	"""Test that BookmarkManager works without TabManager (legacy mode)."""
	from globalPlugins.terminalAccess import BookmarkManager

	# Create mock terminal
	terminal = Mock()
	terminal.makeTextInfo = Mock(return_value=Mock())

	# Create BookmarkManager without TabManager
	bookmark_manager = BookmarkManager(terminal, tab_manager=None)

	# Create mock TextInfo
	mock_textinfo = Mock()
	mock_textinfo.bookmark = "test_bookmark"

	# Set bookmark
	with patch('api.getReviewPosition', return_value=mock_textinfo):
		result = bookmark_manager.set_bookmark("1")
		assert result is True

	# Bookmark should exist
	assert bookmark_manager.has_bookmark("1")

	# List bookmarks - now returns list of dicts
	bookmarks = bookmark_manager.list_bookmarks()
	names = [bm["name"] for bm in bookmarks]
	assert "1" in names


def test_tab_manager_get_tab_title():
	"""Test that TabManager can retrieve tab titles."""
	from globalPlugins.terminalAccess import TabManager

	# Create mock terminal with title
	terminal = Mock()
	terminal.windowHandle = 12345
	terminal.windowText = "PowerShell - Administrator"

	# Create TabManager
	manager = TabManager(terminal)

	# Get tab title
	title = manager._get_tab_title()
	assert title == "PowerShell - Administrator"


def test_tab_manager_clear_tabs():
	"""Test that TabManager can clear tab information."""
	from globalPlugins.terminalAccess import TabManager

	# Create mock terminal
	terminal = Mock()
	terminal.windowHandle = 12345
	terminal.windowText = "Terminal"

	# Create TabManager
	manager = TabManager(terminal)
	assert manager.get_tab_count() > 0

	# Clear all tabs
	manager.clear_all_tabs()
	assert manager.get_tab_count() == 0


def test_output_search_manager_with_tab_manager():
	"""Test that OutputSearchManager can work with TabManager."""
	from globalPlugins.terminalAccess import OutputSearchManager, TabManager

	# Create mock terminal
	terminal = Mock()
	terminal.windowHandle = 12345
	terminal.windowText = "Terminal"

	# Create TabManager
	tab_manager = TabManager(terminal)

	# Create OutputSearchManager with TabManager
	search_manager = OutputSearchManager(terminal, tab_manager)

	# Verify initialization
	assert search_manager._tab_manager == tab_manager


def test_tab_manager_handles_missing_properties():
	"""Test that TabManager handles terminals with missing properties."""
	from globalPlugins.terminalAccess import TabManager

	# Create mock terminal without some properties
	terminal = Mock(spec=[])  # No attributes

	# TabManager should still initialize
	manager = TabManager(terminal)
	assert manager is not None

	# Should generate fallback ID
	tab_id = manager.get_current_tab_id()
	assert tab_id is not None
	assert isinstance(tab_id, str)
