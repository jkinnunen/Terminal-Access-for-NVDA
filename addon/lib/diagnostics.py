# Diagnostic issue report builder for Terminal Access.
# Pure helper: no NVDA imports, so it is unit-testable on its own.

"""Build a diagnostic report a user can attach to a bug report.

When a feature reads terminal output incorrectly (a table splits a column
in the wrong place, an AI turn is detected at the wrong line, and so on), a
plain-text report with the environment and a buffer sample makes the issue
actionable instead of a guess.
"""

_DESCRIBE_PLACEHOLDER = (
    "Describe what you expected and what actually happened, and which "
    "command or feature misbehaved (for example: table mode split a column "
    "in the wrong place, or an AI turn was detected at the wrong line)."
)


def build_issue_report(context, lines, max_buffer_lines=1000):
    """Return a plain-text diagnostic report.

    Args:
        context: Dict of environment fields (addon_version, nvda_version,
            terminal_app, window_title, profile, native_available,
            helper_running, verbosity_level, review_line). Missing values
            are shown as "unknown".
        lines: Terminal buffer lines, already ANSI-stripped by the caller.
        max_buffer_lines: Keep only the last this-many buffer lines so the
            report stays a manageable size.

    Returns:
        The report text, ending with a newline.
    """
    def field(key, default="unknown"):
        value = context.get(key, default)
        return default if value in (None, "") else value

    native = "on" if context.get("native_available") else "off"
    helper = "running" if context.get("helper_running") else "not running"

    header = [
        "Terminal Access for NVDA - issue report",
        "",
        f"Add-on version: {field('addon_version')}",
        f"NVDA version: {field('nvda_version')}",
        f"Terminal: {field('terminal_app')}",
        f"Window title: {field('window_title', '')}",
        f"Active profile: {field('profile', 'none')}",
        f"Native acceleration: {native} (helper {helper})",
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
