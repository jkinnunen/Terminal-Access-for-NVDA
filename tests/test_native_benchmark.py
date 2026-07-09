"""Smoke test for the native-vs-Python benchmark harness.

Confirms the harness runs and reports Python timings. The native timings
are only present when the DLL is available, so they are not asserted here.
The harness itself is the deliverable; this guards that it keeps working.
"""
import os
import sys


def test_benchmark_runs_and_reports_python_timings():
    sys.path.insert(0, os.path.abspath(os.path.join("native", "bench")))
    from benchmark import run_benchmark

    results, native_ok = run_benchmark(sizes=(100,))

    assert len(results) == 1
    row = results[0]
    assert row["lines"] == 100
    assert row["py_strip"] is not None and row["py_strip"] >= 0
    assert row["py_search"] is not None and row["py_search"] >= 0
    # native fields are None when the DLL is absent, populated otherwise
    assert isinstance(native_ok, bool)
