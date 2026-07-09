# Native vs in-process benchmark

`benchmark.py` measures the two operations the native layer accelerates,
ANSI stripping and buffer search, against their pure-Python equivalents on
identical inputs. Use it to decide whether native acceleration should stay
default-on or become opt-in.

## Run it

From the repository root:

```
py native/bench/benchmark.py
```

Build and deploy the native DLL first (otherwise you get Python-only
timings and a note saying so):

```
cd native && cargo build --release -p termaccess-ffi
cp target/release/termaccess_ffi.dll ../addon/lib/x64/termaccess.dll
```

## Reading the output

One row per buffer size, from a small buffer to a deep scrollback. The
`strip x` and `search x` columns are the speedup (Python time / native
time). A value near `1.0x` means the native path is not buying much for
that operation at that size and the complexity may not be worth it; a large
value means it is.

## What this does not measure

This times only the CPU-bound string work. It does not measure the helper
process or its UI Automation reads, which are the parts that carry the
deadlock and blocking risk. Weigh the speedup here against that risk and
against the maintenance cost of the Rust workspace and the helper IPC when
deciding the default.
