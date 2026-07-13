# Diagnostic issue report builder for Terminal Access.
# Pure helper: no NVDA imports, so it is unit-testable on its own.

"""Build a diagnostic report a user can attach to a bug report.

When a feature reads terminal output incorrectly (a table splits a column
in the wrong place, an AI turn is detected at the wrong line, and so on), a
plain-text report with the environment and a buffer sample makes the issue
actionable instead of a guess.
"""

import re

# Newlines and other control characters, stripped from single-line report
# fields so an untrusted value (for example a terminal window title an
# attacker can set) cannot inject additional "key: value" lines.
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")


def _sanitize_single_line(text):
    """Collapse control characters in *text* to spaces and trim it.

    Keeps a field that came from untrusted terminal output on a single
    line so it cannot forge extra header fields in the report.
    """
    return _CONTROL_CHARS.sub(" ", text).strip()

_DESCRIBE_PLACEHOLDER = (
    "Describe what you expected and what actually happened, and which "
    "command or feature misbehaved (for example: table mode split a column "
    "in the wrong place, or an AI turn was detected at the wrong line)."
)


def build_issue_report(context, lines, max_buffer_lines=1000):
    """Return a plain-text diagnostic report.

    Args:
        context: Dict of environment fields (addon_version, nvda_version,
            terminal_app, window_title, profile, verbosity_level,
            review_line). Missing values are shown as "unknown".
        lines: Terminal buffer lines, already ANSI-stripped by the caller.
        max_buffer_lines: Keep only the last this-many buffer lines so the
            report stays a manageable size.

    Returns:
        The report text, ending with a newline.
    """
    def field(key, default="unknown"):
        value = context.get(key, default)
        if value in (None, ""):
            value = default
        if isinstance(value, str):
            value = _sanitize_single_line(value)
        return value

    header = [
        "Terminal Access for NVDA - issue report",
        "",
        f"Add-on version: {field('addon_version')}",
        f"NVDA version: {field('nvda_version')}",
        f"Terminal: {field('terminal_app')}",
        f"Window title: {field('window_title', '')}",
        f"Active profile: {field('profile', 'none')}",
        f"Verbosity level: {field('verbosity_level')}",
        f"Review line: {field('review_line')}",
        "",
        "What happened:",
        _DESCRIBE_PLACEHOLDER,
        "",
        "Terminal buffer (ANSI stripped):",
        "",
    ]

    buffer_lines = list(lines or [])
    if len(buffer_lines) > max_buffer_lines:
        buffer_lines = buffer_lines[-max_buffer_lines:]
        header.append(f"[showing the last {max_buffer_lines} lines]")

    return "\n".join(header + buffer_lines) + "\n"
