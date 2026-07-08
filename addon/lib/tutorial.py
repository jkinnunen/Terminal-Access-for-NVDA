# Terminal Access first-run tutorial.
# Short spoken walkthrough of the essential gestures, offered the first
# time a user ever focuses a supported terminal, and replayable on demand
# from the command layer (NVDA+apostrophe, then Shift+H).

TUTORIAL_STEPS = [
	# Translators: First step of the first-run tutorial, a welcome line.
	_("Welcome to Terminal Access. Here is a quick tour of the essential commands."),
	# Translators: Tutorial step explaining how to enter the command layer.
	_("Press NVDA+apostrophe to enter the command layer, where single keys run Terminal Access commands."),
	# Translators: Tutorial step explaining line navigation in the command layer.
	_("In the command layer, press U, I and O to read the previous, current and next line."),
	# Translators: Tutorial step explaining the output search command.
	_("Press NVDA+F to search the terminal output."),
	# Translators: Tutorial step explaining the bookmark list command.
	_("In the command layer, press B to list your bookmarks."),
	# Translators: Tutorial step explaining how to open the user guide.
	_("Press NVDA+Shift+F1 to open the full user guide."),
	# Translators: Closing step of the tutorial, explaining how to replay it.
	_("To hear this tutorial again, press NVDA+apostrophe and then Shift+H at any time."),
]


def build_tutorial_message():
	"""Join the tutorial steps into one spoken message.

	Each step ends with a period, so joining with a single space
	produces normal sentence spacing.
	"""
	return " ".join(TUTORIAL_STEPS)


def should_offer_tutorial(config_manager):
	"""Return True when the tutorial has never been played for this user."""
	return not config_manager.get("tutorialShown", False)
