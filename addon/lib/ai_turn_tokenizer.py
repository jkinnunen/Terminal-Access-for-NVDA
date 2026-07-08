# AI Turn/Role Tokenizer for terminal output.
#
# Detects AI CLI turns (user/assistant/system/tool) in terminal buffer
# lines and provides navigation helpers for jumping between turns and
# code blocks.  Handles ANSI color codes in role markers and streamed
# or partial output gracefully.
#
# Supported AI CLI tools:
#
# | Tool       | User marker          | Assistant marker     |
# |------------|----------------------|----------------------|
# | Claude CLI | ">" (Unicode arrow)  | "Claude:"            |
# | ChatGPT    | "You:"               | "ChatGPT:"           |
# | Aider      | "> " (command)       | (unmarked response)  |
# | Generic    | "User:"              | "Assistant:"          |

import re
from collections import namedtuple
from typing import Optional

from lib.text_processing import ANSIParser

AITurn = namedtuple("AITurn", ["line_num", "end_line", "role", "has_code_block"])
CodeSpan = namedtuple("CodeSpan", ["line_num", "end_line"])

# Shared AI turn classification patterns with capture groups for preview text.
# Used by both AITurnTokenizer and BookmarkManager._classify_ai_turn.

_CODE_FENCE_RE = re.compile(r'^```(\w*)')

_USER_PATTERNS = [
    re.compile(r'^\u276f\s+(.*)'),
    re.compile(r'^\u276f$'),
    re.compile(r'^You:\s*(.*)', re.IGNORECASE),
    re.compile(r'^User:\s*(.*)', re.IGNORECASE),
    re.compile(r'^>\s+(\S.*)'),
]

_ASSISTANT_PATTERNS = [
    re.compile(r'^Claude:\s*(.*)', re.IGNORECASE),
    re.compile(r'^ChatGPT:\s*(.*)', re.IGNORECASE),
    re.compile(r'^Assistant:\s*(.*)', re.IGNORECASE),
    re.compile(r'^Copilot:\s*(.*)', re.IGNORECASE),
    re.compile(r'^Gemini:\s*(.*)', re.IGNORECASE),
    re.compile(r'^Codex:\s*(.*)', re.IGNORECASE),
]

_TOOL_PATTERNS = [
    re.compile(r'^Tool:\s*(.*)', re.IGNORECASE),
    re.compile(r'^Function:\s*(.*)', re.IGNORECASE),
]

_SYSTEM_PATTERNS = [
    re.compile(r'^(Aider\s+v[\d.]+.*)', re.IGNORECASE),
    re.compile(r'^Model:\s*(.*)', re.IGNORECASE),
    re.compile(r'^System:\s*(.*)', re.IGNORECASE),
]


def classify_ai_line(clean_line: str) -> Optional[tuple[str, str]]:
    """Classify a line as an AI CLI turn.

    Args:
        clean_line: Line text with ANSI codes already stripped and
            leading/trailing whitespace removed.

    Returns:
        A (role, preview) tuple, or None if the line is not an AI turn
        marker.  *role* is one of "user", "assistant", "tool", "system",
        or "code".  *preview* is the captured content after the marker.
    """
    if not clean_line:
        return None

    # Code block fences
    m = _CODE_FENCE_RE.match(clean_line)
    if m is not None:
        lang = m.group(1)
        return ("code", f"{lang} block" if lang else "block")

    # Assistant (check before user since "> " is ambiguous)
    for pat in _ASSISTANT_PATTERNS:
        m = pat.match(clean_line)
        if m:
            return ("assistant", m.group(1).strip()[:40])

    # Tool
    for pat in _TOOL_PATTERNS:
        m = pat.match(clean_line)
        if m:
            return ("tool", m.group(1).strip()[:40])

    # System
    for pat in _SYSTEM_PATTERNS:
        m = pat.match(clean_line)
        if m:
            return ("system", m.group(1).strip()[:40])

    # User (last, since "> " overlaps with shell prompts)
    for pat in _USER_PATTERNS:
        m = pat.match(clean_line)
        if m:
            preview = m.group(1).strip()[:40] if m.lastindex else ""
            return ("user", preview)

    return None


class AITurnTokenizer:
    """Detect AI CLI turns in terminal output and navigate between them.

    Usage::

        tokenizer = AITurnTokenizer()
        turns = tokenizer.tokenize(lines)
        next_t = tokenizer.next_turn(current_line)
        next_cb = tokenizer.next_code_block(current_line)
    """

    # Use module-level classify_ai_line() and _CODE_FENCE_RE for all
    # pattern matching. No duplicate patterns on the class.

    def __init__(self) -> None:
        self._turns: list[AITurn] = []
        self._code_blocks: list[CodeSpan] = []
        self._cache_key: tuple = ()

    @staticmethod
    def _buffer_key(lines: list[str]) -> tuple:
        """Cheap identity key: (line_count, first_line, last_line)."""
        if not lines:
            return (0, "", "")
        return (len(lines), lines[0], lines[-1])

    def tokenize(self, lines: list[str]) -> list[AITurn]:
        """Classify lines into AI conversation turns.

        Results are cached and reused when the buffer hasn't changed
        (same line count and last line content).

        Args:
            lines: Buffer lines to classify.

        Returns:
            List of AITurn namedtuples for detected turns.  Returns an
            empty list when no AI turn markers are found.
        """
        key = self._buffer_key(lines)
        if key == self._cache_key and self._turns is not None:
            return self._turns

        self._cache_key = key
        self._turns = []
        self._code_blocks = []

        if not lines:
            return self._turns

        # First pass: find turn start lines and collect code blocks.
        raw_starts: list[tuple[int, str]] = []  # (line_num, role)
        in_code_block = False
        code_block_start = -1

        for idx, line in enumerate(lines):
            clean = ANSIParser.stripANSI(line).strip()

            # Track code fences.
            if _CODE_FENCE_RE.match(clean):
                if not in_code_block:
                    in_code_block = True
                    code_block_start = idx
                else:
                    in_code_block = False
                    self._code_blocks.append(
                        CodeSpan(line_num=code_block_start, end_line=idx)
                    )
                continue

            # Skip classification inside code blocks.
            if in_code_block:
                continue

            role = self._classify_line(clean)
            if role is not None:
                raw_starts.append((idx, role))

        # If code block was never closed, close at end of input.
        if in_code_block and code_block_start >= 0:
            self._code_blocks.append(
                CodeSpan(line_num=code_block_start, end_line=len(lines) - 1)
            )

        if not raw_starts:
            return self._turns

        # Merge consecutive system lines into one system turn.
        merged: list[tuple[int, str]] = []
        for line_num, role in raw_starts:
            if merged and role == "system" and merged[-1][1] == "system":
                continue  # skip, already started a system span
            merged.append((line_num, role))

        # Build turns with end_line boundaries.
        for i, (start, role) in enumerate(merged):
            if i + 1 < len(merged):
                next_start = merged[i + 1][0]
                # End line is the last non-blank line before the next turn,
                # but at minimum the start line itself.
                end = next_start - 1
                while end > start and not lines[end].strip():
                    end -= 1
            else:
                end = len(lines) - 1

            # Check if any code block falls within this turn.
            has_code = any(
                cb.line_num >= start and cb.end_line <= end
                for cb in self._code_blocks
            )

            self._turns.append(
                AITurn(line_num=start, end_line=end, role=role, has_code_block=has_code)
            )

        # Detect Aider-style unmarked assistant responses: lines between
        # a user turn that used "> " and the next explicit marker.
        self._detect_aider_assistant_responses(lines, merged)

        return self._turns

    def _detect_aider_assistant_responses(
        self, lines: list[str], merged: list[tuple[int, str]]
    ) -> None:
        """Detect unmarked assistant responses in Aider-style transcripts.

        In Aider, the assistant response has no explicit label.  It follows
        a user "> " command and includes any text that is not another turn
        marker.  If there are already explicit assistant turns detected, we
        skip this heuristic.
        """
        if any(t.role == "assistant" for t in self._turns):
            return

        # Check if we have system + user pattern typical of Aider
        has_system = any(t.role == "system" for t in self._turns)
        has_user = any(t.role == "user" for t in self._turns)
        if not (has_system and has_user):
            return

        # Look for gaps after each user turn's start line (not end_line,
        # because end_line may have absorbed the entire response).  We use
        # the merged start positions to find boundaries.
        user_indices = [
            (idx, m) for idx, m in enumerate(merged) if m[1] == "user"
        ]

        new_turns = list(self._turns)
        for mi, (merge_idx, (start, _role)) in enumerate(user_indices):
            # The boundary for scanning is the next merged turn start,
            # or end of input.
            if merge_idx + 1 < len(merged):
                search_end = merged[merge_idx + 1][0]
            else:
                search_end = len(lines)

            # Scan lines after the user prompt line for unmarked content
            search_start = start + 1
            assistant_start = None
            for idx in range(search_start, search_end):
                clean = ANSIParser.stripANSI(lines[idx]).strip()
                if clean and self._classify_line(clean) is None:
                    assistant_start = idx
                    break

            if assistant_start is not None:
                end = search_end - 1
                while end > assistant_start and not lines[end].strip():
                    end -= 1

                has_code = any(
                    cb.line_num >= assistant_start and cb.end_line <= end
                    for cb in self._code_blocks
                )
                new_turns.append(
                    AITurn(
                        line_num=assistant_start,
                        end_line=end,
                        role="assistant",
                        has_code_block=has_code,
                    )
                )

        # Re-sort by line number and rebuild end_line boundaries
        new_turns.sort(key=lambda t: t.line_num)
        # Recalculate end_lines based on new ordering
        rebuilt = []
        for i, turn in enumerate(new_turns):
            if i + 1 < len(new_turns):
                next_start = new_turns[i + 1].line_num
                end = next_start - 1
                while end > turn.line_num and not lines[end].strip():
                    end -= 1
            else:
                end = len(lines) - 1

            has_code = any(
                cb.line_num >= turn.line_num and cb.end_line <= end
                for cb in self._code_blocks
            )
            rebuilt.append(
                AITurn(
                    line_num=turn.line_num,
                    end_line=end,
                    role=turn.role,
                    has_code_block=has_code,
                )
            )
        self._turns = rebuilt

    def get_code_blocks(self) -> list[CodeSpan]:
        """Return all detected code blocks from the last tokenize() call."""
        return list(self._code_blocks)

    def next_turn(
        self, current_line: int, role: Optional[str] = None
    ) -> Optional[AITurn]:
        """Find the next turn after *current_line*.

        Args:
            current_line: The line number to search from.
            role: If given, only return turns with this role.

        Returns:
            The next AITurn, or None if there is no matching turn.
        """
        for turn in self._turns:
            if turn.line_num > current_line:
                if role is None or turn.role == role:
                    return turn
        return None

    def prev_turn(
        self, current_line: int, role: Optional[str] = None
    ) -> Optional[AITurn]:
        """Find the previous turn before *current_line*.

        Args:
            current_line: The line number to search from.
            role: If given, only return turns with this role.

        Returns:
            The previous AITurn, or None if there is no matching turn.
        """
        result = None
        for turn in self._turns:
            if turn.line_num >= current_line:
                break
            if role is None or turn.role == role:
                result = turn
        return result

    def next_code_block(self, current_line: int) -> Optional[CodeSpan]:
        """Find the next code block after *current_line*."""
        for block in self._code_blocks:
            if block.line_num > current_line:
                return block
        return None

    def prev_code_block(self, current_line: int) -> Optional[CodeSpan]:
        """Find the previous code block before *current_line*."""
        result = None
        for block in self._code_blocks:
            if block.line_num >= current_line:
                break
            result = block
        return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _classify_line(clean_line: str) -> Optional[str]:
        """Return the role for a line, or None if it is not a turn marker."""
        result = classify_ai_line(clean_line)
        if result is None:
            return None
        return result[0]  # role only, discard preview
