"""Runtime dependency registry for Terminal Access.

Holds references to shared functions that lib modules need but cannot
import directly (to avoid circular imports). Populated by
terminalAccess.py during module initialization.
"""

import re

from lib.caching import TextDiffer


# Punctuation keys named by word rather than shown as the symbol.
#
# A screen reader speaks a bare symbol at the user's punctuation level,
# and terminal work is usually done at a low level or with punctuation
# off, so "NVDA+'" is heard as "NVDA plus" and the command cannot be
# learned by ear. Naming the key keeps every command audible whatever the
# punctuation level.
#
# This is the single source of truth: the command finder, the settings
# panel, and the shipped user guide all resolve punctuation through it
# (tests/test_key_words.py, tests/test_doc_gesture_consistency.py), so a
# punctuation key cannot be spoken one way and documented another. Add an
# entry here when binding a new punctuation key.
KEY_WORDS = {
	"'": "apostrophe",
	",": "comma",
	"-": "minus",
	".": "period",
	";": "semicolon",
	"=": "equals",
}


def spell_key(key: str) -> str:
	"""Return the spoken word for a punctuation key.

	Keys that already speak for themselves (letters, digits, named keys
	such as shift or f1) are returned unchanged.
	"""
	return KEY_WORDS.get(key, key)


def _format_single_gesture(gesture: str) -> str:
	"""Format one gesture's keys, naming punctuation."""
	formatted = []
	for p in gesture.replace("kb:", "").split("+"):
		if p.upper() == "NVDA":
			formatted.append("NVDA")
		elif p in KEY_WORDS:
			formatted.append(KEY_WORDS[p])
		elif len(p) > 1:
			formatted.append(p.capitalize())
		else:
			formatted.append(p.upper())
	return "+".join(formatted)


def gesture_label(gesture: str, script_name: str) -> str:
	"""Format a gesture and script name into a human-readable label.

	Example: 'kb:NVDA+c' + 'copyLinearSelection'
	returns 'NVDA+C \u2014 Copy Linear Selection'

	Punctuation keys are named, so "kb:NVDA+'" reads as
	'NVDA+apostrophe' rather than a symbol the reader may not speak.

	A double-press binding joins two gestures with a comma
	('kb:NVDA+k,kb:NVDA+k') and reads as 'NVDA+K twice', since a literal
	comma is silent at most punctuation levels. Comma is also a bound key
	in its own right ('kb:NVDA+,'), so only a comma introducing another
	gesture separates; a trailing comma is the key itself.
	"""
	keys = [_format_single_gesture(g) for g in re.split(r",(?=kb:)", gesture)]
	if len(keys) > 1 and len(set(keys)) == 1:
		# Translators: a command run by pressing one gesture twice in a row.
		# {key} is a key combination such as NVDA+K.
		key_display = _("{key} twice").format(key=keys[0])
	else:
		key_display = ", ".join(keys)
	label = re.sub(r'(?<=[a-z])(?=[A-Z])', ' ', script_name)
	return f"{key_display} \u2014 {label.title()}"

# Text processing
strip_ansi = lambda text: text
make_text_differ = TextDiffer

# Terminal text reading
read_terminal_text = None

# Position caching
make_position_cache = None

# API modules (populated by terminalAccess.py, defaults used in tests)
api_module = None  # set to NVDA's api module at startup
webbrowser_module = None  # set to Python's webbrowser at startup
