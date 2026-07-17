# Build customizations
# Change this file instead of sconstruct or manifest files, whenever possible.

from site_scons.site_tools.NVDATool.typings import AddonInfo, BrailleTables, SymbolDictionaries

# Since some strings in `addon_info` are translatable,
# we need to include them in the .po files.
# Gettext recognizes only strings given as parameters to the `_` function.
# To avoid initializing translations in this module we simply import a "fake" `_` function
# which returns whatever is given to it as an argument.
from site_scons.site_tools.NVDATool.utils import _


# Add-on information variables
addon_info = AddonInfo(
	# add-on Name/identifier, internal for NVDA
	addon_name="terminalAccess",
	# Add-on summary/title, usually the user visible name of the add-on
	# Translators: Summary/title for this add-on
	# to be shown on installation and add-on information found in add-on store
	addon_summary=_("Terminal Access for NVDA"),
	# Add-on description
	# Translators: Long description to be shown for this add-on on add-on information from add-on store
	addon_description=_("""Provides enhanced terminal accessibility for Windows Terminal and PowerShell, enabling screen reader users to efficiently navigate and interact with command-line interfaces. Inspired by TDSR (Terminal Data Structure Reader) and incorporates functionality from both TDSR and Speakup. Advanced features inspired by community suggestions and discussions."""),
	# version
	addon_version="2.0.3",
	# Brief changelog for this version
	# Translators: what's new content for the add-on version to be shown in the add-on store
	addon_changelog=_("""v2.0.3 is the consolidated 2.x release, covering everything since 1.4.0.

New: support for AI command-line tools (Claude, Aider, Copilot CLI, Gemini CLI, and more) with turn and code-block navigation; semantic navigation of output by section, error, and prompt; table mode for reading columnar output cell by cell; a search results dialog with case-sensitive and regular-expression options; verbosity presets; a command finder; transcript export; and a first-run tutorial.

Changed: the add-on is now pure Python. The native component is gone, the download is about a quarter of its former size, and it runs on ARM64 Windows. Search is much faster on large buffers.

Fixed: find no longer freezes the machine on Windows Terminal; search results and bookmarks survive focus changes and land on the right line; find next and find previous announce your position and refresh against new output; and Key Echo defers to NVDA's own typing echo instead of talking over it.

Requires NVDA 2025.1 or later. Existing settings are preserved on upgrade."""),
	# Author(s)
	addon_author="Pratik Patel",
	# URL for the add-on documentation support
	addon_url="https://github.com/PratikP1/Terminal-Access-for-NVDA",
	# URL for the add-on repository where the source code can be found
	addon_sourceURL="https://github.com/PratikP1/Terminal-Access-for-NVDA",
	# Documentation file name
	addon_docFileName="readme.html",
	# Minimum NVDA version supported (e.g. "2025.1.0", minor version is optional)
	addon_minimumNVDAVersion="2025.1.0",
	# Last NVDA version supported/tested (e.g. "2024.4.0", ideally more recent than minimum version)
	addon_lastTestedNVDAVersion="2026.1.0",
	# Add-on update channel (default is None, denoting stable releases,
	# and for development releases, use "dev".)
	# Do not change unless you know what you are doing!
	addon_updateChannel=None,
	# Add-on license such as GPL 2
	addon_license="GPL v3",
	# URL for the license document the add-on is licensed under
	addon_licenseURL="https://www.gnu.org/licenses/gpl-3.0.html",
)

# Define the python files that are the sources of your add-on.
# You can either list every file (using "/" as a path separator,
# or use glob expressions.
pythonSources: list[str] = [
	"addon/globalPlugins/*.py",
]

# Files that contain strings for translation. Usually your python sources
i18nSources: list[str] = pythonSources + ["addon/lib/*.py", "buildVars.py"]

# Files that will be ignored when building the nvda-addon file
# Paths are relative to the addon directory, not to the root directory of your addon sources.
excludedFiles: list[str] = [
	"**/__pycache__/*",
	"**/*.pyc",
]

# Base language for the NVDA add-on
# If your add-on is written in a language other than english, modify this variable.
baseLanguage: str = "en"

# Markdown extensions for add-on documentation
# tables and fenced_code render the command tables and JSON examples.
# toc adds id attributes to headings so the in-guide Table of Contents
# links resolve in the generated HTML.
markdownExtensions: list[str] = ["tables", "fenced_code", "toc"]

# Custom braille translation tables
brailleTables: BrailleTables = {}

# Custom speech symbol dictionaries
symbolDictionaries: SymbolDictionaries = {}
