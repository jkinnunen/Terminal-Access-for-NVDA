"""Benchmark the native text path against the in-process Python path.

Terminal Access ships a Rust DLL and a helper process for reading and
searching terminal output. That native layer is the source of real
complexity and, historically, of the worst bug (the find-command freeze).
Whether it should stay default-on or become opt-in is a data question, not
an opinion. This harness measures the two things the native layer actually
accelerates on the same inputs: ANSI stripping and buffer search.

Run from the repo root:

    py native/bench/benchmark.py

It prints, per buffer size, the Python time, the native time, and the
speedup (python / native). If the native DLL is not present it reports the
Python timings only and says so.
"""
import os
import re
import sys
import time

# Make `addon/` importable exactly as the add-on does.
_ADDON = os.path.join(os.path.dirname(__file__), "..", "..", "addon")
sys.path.insert(0, os.path.abspath(_ADDON))

# Stub the NVDA modules the add-on imports at load time so this harness can
# run outside NVDA (the same idea as tests/conftest.py, kept minimal here).
from unittest.mock import MagicMock  # noqa: E402

for _nvda_mod in ("characterProcessing", "logHandler", "config"):
    sys.modules.setdefault(_nvda_mod, MagicMock())

# Representative buffer sizes in lines. The largest approximates a deep
# Windows Terminal scrollback.
DEFAULT_SIZES = (100, 1_000, 10_000, 50_000)

_SAMPLE_LINE = "\x1b[32muser@host\x1b[0m:\x1b[34m~/project\x1b[0m$ cargo build --release\n"


def _make_buffer(lines):
    return _SAMPLE_LINE * lines


def _python_strip(text):
    from lib.text_processing import ANSIParser
    return ANSIParser.stripANSI(text)


def _python_search(text, pattern):
    lowered = pattern.lower()
    return sum(1 for line in text.split("\n") if lowered in line.lower())


def _time(fn, *args, repeat=3):
    best = None
    for _ in range(repeat):
        start = time.perf_counter()
        fn(*args)
        elapsed = time.perf_counter() - start
        best = elapsed if best is None else min(best, elapsed)
    return best


def run_benchmark(sizes=DEFAULT_SIZES, pattern="cargo"):
    """Return a list of per-size timing dicts.

    Each entry has: lines, py_strip, nat_strip, py_search, nat_search
    (native fields are None when the native DLL is unavailable).
    """
    try:
        import native.termaccess_bridge as bridge
        native_ok = bridge.native_available()
    except Exception:
        bridge = None
        native_ok = False

    results = []
    for lines in sizes:
        text = _make_buffer(lines)
        row = {
            "lines": lines,
            "py_strip": _time(_python_strip, text),
            "py_search": _time(_python_search, text, pattern),
            "nat_strip": None,
            "nat_search": None,
        }
        if native_ok:
            row["nat_strip"] = _time(bridge.native_strip_ansi, text)
            row["nat_search"] = _time(
                bridge.native_search_text, text, pattern, False, False
            )
        results.append(row)
    return results, native_ok


def _fmt(seconds):
    return "-" if seconds is None else f"{seconds * 1000:8.2f} ms"


def _ratio(py, nat):
    if not nat or nat <= 0:
        return "-"
    return f"{py / nat:5.1f}x"


def main():
    results, native_ok = run_benchmark()
    if not native_ok:
        print("Native DLL not available; showing Python timings only.\n")
    header = f"{'lines':>7}  {'py strip':>11}  {'nat strip':>11}  {'strip x':>7}  {'py search':>11}  {'nat search':>11}  {'search x':>8}"
    print(header)
    print("-" * len(header))
    for r in results:
        print(
            f"{r['lines']:>7}  {_fmt(r['py_strip']):>11}  {_fmt(r['nat_strip']):>11}  "
            f"{_ratio(r['py_strip'], r['nat_strip']):>7}  {_fmt(r['py_search']):>11}  "
            f"{_fmt(r['nat_search']):>11}  {_ratio(r['py_search'], r['nat_search']):>8}"
        )


if __name__ == "__main__":
    main()
