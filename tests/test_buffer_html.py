"""escape_line: the security boundary for the buffer window.

Terminal output is attacker-influenced: any program can print anything.
Because the browse window passes an identity sanitizeHtmlFunc to keep
nh3.clean off NVDA's main thread, this escaping is the SOLE boundary
between printed bytes and rendered markup. These tests are the gate.
"""
import pytest

from lib.buffer_html import escape_line


class TestMarkupIsInert:
    """Nothing a program prints may render as markup."""

    def test_script_tag_is_escaped(self):
        out = escape_line("<script>alert(1)</script>")
        assert "<script" not in out
        assert "&lt;script&gt;" in out

    def test_img_onerror_is_escaped(self):
        out = escape_line('<img src=x onerror="alert(1)">')
        assert "<img" not in out

    @pytest.mark.parametrize(
        "char,entity",
        [
            ("&", "&amp;"),
            ("<", "&lt;"),
            (">", "&gt;"),
            ('"', "&quot;"),
            ("'", "&#x27;"),
        ],
    )
    def test_every_special_character_escapes(self, char, entity):
        assert entity in escape_line(f"a{char}b")

    def test_plain_text_passes_through(self):
        assert escape_line("npm run build") == "npm run build"


class TestAnsiStripping:
    """Colour codes are terminal formatting, not content."""

    def test_color_codes_are_stripped(self):
        out = escape_line("\x1b[31merror\x1b[0m: it broke")
        assert out == "error: it broke"

    def test_unterminated_escape_does_not_leak(self):
        out = escape_line("before\x1b[3")
        assert "\x1b" not in out

    def test_bare_escape_byte_is_removed(self):
        assert "\x1b" not in escape_line("a\x1bb")


class TestControlCharacters:
    """Control bytes that survive ANSI stripping are removed."""

    @pytest.mark.parametrize("ch", ["\x00", "\x07", "\x08", "\x0b", "\x0c"])
    def test_control_bytes_removed(self, ch):
        out = escape_line(f"a{ch}b")
        assert ch not in out
        assert "ab" == out

    def test_tab_is_preserved(self):
        # Tabs are legitimate content (indentation, column alignment).
        assert "\t" in escape_line("a\tb")


class TestBidiOverrides:
    """Trojan-Source-style visual spoofing is neutralized."""

    @pytest.mark.parametrize(
        "ch",
        ["‪", "‫", "‬", "‭", "‮",
         "⁦", "⁧", "⁨", "⁩"],
    )
    def test_bidi_override_characters_removed(self, ch):
        out = escape_line(f"safe{ch}text")
        assert ch not in out
        assert "safetext" == out


class TestRobustness:
    def test_very_long_line(self):
        line = "x" * 10000
        assert escape_line(line) == line

    def test_empty_line(self):
        assert escape_line("") == ""

    def test_non_string_input_returns_empty(self):
        # A Mock terminal or a bad read can hand us non-text; the
        # boundary swallows it rather than rendering repr() output.
        assert escape_line(None) == ""
        assert escape_line(42) == ""

    def test_cjk_and_emoji_pass_through(self):
        assert escape_line("宽字符 ✓") == "宽字符 ✓"
