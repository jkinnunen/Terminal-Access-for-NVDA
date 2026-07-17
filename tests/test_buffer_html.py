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


def _snapshot(lines, name="WindowsTerminal", max_lines=None):
    from unittest.mock import Mock

    from lib.buffer_snapshot import BufferSnapshot

    term = Mock()
    term.appModule.appName = name
    if max_lines is None:
        return BufferSnapshot.capture(term, lines)
    return BufferSnapshot.capture(term, lines, max_lines=max_lines)


class TestRenderPlain:
    """Task 3 renderer: one escaped paragraph per line, no headings yet."""

    def test_each_line_is_a_paragraph(self):
        from lib.buffer_html import render_plain

        out = render_plain(_snapshot(["first", "second"]))
        assert "<p>first</p>" in out
        assert "<p>second</p>" in out

    def test_lines_are_escaped(self):
        from lib.buffer_html import render_plain

        out = render_plain(_snapshot(["<script>boom()</script>"]))
        assert "<script" not in out
        assert "&lt;script&gt;" in out

    def test_blank_lines_keep_their_place(self):
        """A blank buffer row still occupies a line when arrowing."""
        from lib.buffer_html import render_plain

        out = render_plain(_snapshot(["a", "", "b"]))
        assert out.index("<p>a</p>") < out.index("<p>&nbsp;</p>") < out.index("<p>b</p>")

    def test_empty_snapshot_renders_empty_document(self):
        from lib.buffer_html import render_plain

        assert render_plain(_snapshot([])) == ""


class TestRenderSemantic:
    """Task 4 renderer: headings mark structure, output stays plain.

    H1 = the terminal, H2 = each command you ran (prompt lines), H3 = the
    start of each error, warning, or stack trace. Output/progress/
    timestamp spans get NO heading: a heading per output span would make
    the H key useless.
    """

    def _render(self, lines, name="WindowsTerminal"):
        from lib.buffer_html import render
        from lib.section_tokenizer import SectionTokenizer

        snap = _snapshot(lines, name=name)
        tok = SectionTokenizer()
        tok.tokenize(snap.lines)
        return render(snap, tok.get_spans())

    def test_terminal_name_is_h1(self):
        out = self._render(["hello"], name="wt")
        assert "<h1>wt</h1>" in out

    def test_prompt_line_is_h2(self):
        out = self._render(["PS C:\\repo> npm test", "ok"])
        assert "<h2" in out
        assert "npm test" in out.split("<h2", 1)[1].split("</h2>", 1)[0]

    def test_each_prompt_gets_its_own_h2(self):
        out = self._render([
            "PS C:\\repo> build",
            "done",
            "PS C:\\repo> deploy",
            "done again",
        ])
        assert out.count("<h2") == 2

    def test_error_line_starts_an_h3(self):
        out = self._render(["setup", "Error: disk full", "cleanup"])
        assert "<h3" in out
        assert "disk full" in out.split("<h3", 1)[1].split("</h3>", 1)[0]

    def test_stack_trace_heads_once_then_stays_plain(self):
        """A 3-line traceback is ONE H3 stop, not three."""
        out = self._render([
            'Traceback (most recent call last):',
            '  File "app.py", line 10, in main',
            '  File "lib.py", line 4, in helper',
        ])
        assert out.count("<h3") == 1

    def test_plain_output_gets_no_heading(self):
        out = self._render(["just some output", "more output"])
        assert "<h2" not in out
        assert "<h3" not in out

    def test_headings_carry_absolute_line_ids(self):
        out = self._render(["PS C:\\repo> run", "output"])
        assert 'id="L0"' in out

    def test_heading_text_is_escaped(self):
        out = self._render(["PS C:\\repo> echo <b>hi</b>"])
        assert "<b>" not in out
        assert "&lt;b&gt;" in out

    def test_no_prompts_still_renders_every_line(self):
        lines = ["alpha", "beta", "gamma"]
        out = self._render(lines)
        for line in lines:
            assert line in out

    def test_all_lines_present_around_headings(self):
        lines = ["PS C:\\repo> run", "output one", "Error: nope", "after"]
        out = self._render(lines)
        for line in ["run", "output one", "nope", "after"]:
            assert line in out


class TestTableOfContents:
    """A TOC at the top links every command and error heading.

    browseableMessage renders from the top with no scroll parameter, so
    the TOC is how structure is reachable without arrowing through
    thousands of lines.
    """

    def _render(self, lines):
        from lib.buffer_html import render
        from lib.section_tokenizer import SectionTokenizer

        snap = _snapshot(lines)
        tok = SectionTokenizer()
        tok.tokenize(snap.lines)
        return render(snap, tok.get_spans())

    def test_toc_links_every_command_and_error(self):
        out = self._render([
            "PS C:\\repo> npm run build",
            "compiling",
            "Error: build failed",
            "PS C:\\repo> npm test",
        ])
        toc = out.split("</ul>", 1)[0]
        assert 'href="#L0"' in toc
        assert 'href="#L2"' in toc
        assert 'href="#L3"' in toc
        assert "npm run build" in toc
        assert "build failed" in toc

    def test_toc_entries_are_escaped(self):
        out = self._render(["PS C:\\repo> echo <img src=x>"])
        toc = out.split("</ul>", 1)[0]
        assert "<img" not in toc

    def test_no_headings_means_no_toc(self):
        out = self._render(["plain output", "more output"])
        assert "<ul>" not in out
        assert "<li>" not in out

    def test_toc_ids_match_heading_ids(self):
        out = self._render(["PS C:\\repo> go", "done"])
        assert 'href="#L0"' in out
        assert 'id="L0"' in out


class TestWindowTitle:
    """The title names the terminal and never hides truncation."""

    def test_names_the_terminal_and_line_count(self):
        from lib.buffer_html import window_title

        title = window_title(_snapshot(["x"] * 42, name="wt"))
        assert "wt" in title
        assert "42" in title

    def test_truncated_title_admits_what_was_dropped(self):
        from lib.buffer_html import window_title

        snap = _snapshot([str(i) for i in range(30)], max_lines=20)
        title = window_title(snap)
        assert "20" in title
        assert "30" in title

    def test_untruncated_title_does_not_claim_truncation(self):
        from lib.buffer_html import window_title

        snap = _snapshot(["x"] * 5)
        title = window_title(snap)
        assert "5" in title

    def test_title_is_escaped(self):
        """browseableMessage embeds the title in its HTML dialog; a
        terminal name is program-influenced text like any other."""
        from lib.buffer_html import window_title

        title = window_title(_snapshot(["x"], name="<b>evil</b>"))
        assert "<b>" not in title
