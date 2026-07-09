//! C ABI FFI layer for Terminal Access native components.
//!
//! This crate wraps `termaccess-core` in C-callable functions for use
//! via Python's ctypes. Memory management: the DLL allocates output
//! buffers; the caller frees them via `ta_free_string`.

use std::ptr;
use std::slice;
use termaccess_core::text_differ::TextDiffer;
use termaccess_core::position_cache::PositionCache;

mod ffi_types;
use ffi_types::*;

/// Check that all given pointers are non-null; return `ERR_NULL_POINTER` if any is null.
macro_rules! check_ptrs {
    ($($p:expr),+ $(,)?) => {
        $(if $p.is_null() { return ERR_NULL_POINTER; })+
    };
}

// ═══════════════════════════════════════════════════════════════
//  Version
// ═══════════════════════════════════════════════════════════════

const VERSION: &str = env!("CARGO_PKG_VERSION");

/// Get the version string of the native library (static, do NOT free).
#[no_mangle]
pub extern "C" fn ta_version() -> *const u8 {
    VERSION.as_ptr()
}

/// Get the version string length.
#[no_mangle]
pub extern "C" fn ta_version_len() -> usize {
    VERSION.len()
}

// ═══════════════════════════════════════════════════════════════
//  Memory management
// ═══════════════════════════════════════════════════════════════

/// Free a string allocated by any ta_* function.
///
/// # Safety
/// `ptr` must have been returned by a ta_* function (allocated via
/// `Box<[u8]>`), and `len` must match the original allocation.
/// Passing null is a no-op.
#[no_mangle]
pub unsafe extern "C" fn ta_free_string(ptr: *mut u8, len: usize) {
    if !ptr.is_null() && len > 0 {
        // Reconstruct the Box<[u8]> and drop it
        let _ = Box::from_raw(std::ptr::slice_from_raw_parts_mut(ptr, len));
    }
}

/// Allocate a Rust String as a C-compatible buffer.
/// Returns (ptr, len). Caller must free via `ta_free_string`.
fn string_to_ffi(s: String) -> (*mut u8, usize) {
    if s.is_empty() {
        return (ptr::null_mut(), 0);
    }
    let bytes: Box<[u8]> = s.into_bytes().into_boxed_slice();
    let len = bytes.len();
    let ptr = Box::into_raw(bytes) as *mut u8;
    (ptr, len)
}

/// Read a UTF-8 string from a raw pointer + length.
///
/// # Safety
/// `ptr` must point to `len` valid UTF-8 bytes that remain valid for `'a`,
/// or be null (returns empty).
unsafe fn read_utf8<'a>(ptr: *const u8, len: usize) -> Result<&'a str, i32> {
    if ptr.is_null() || len == 0 {
        return Ok("");
    }
    let bytes = slice::from_raw_parts(ptr, len);
    std::str::from_utf8(bytes).map_err(|_| ERR_INVALID_UTF8)
}

// ═══════════════════════════════════════════════════════════════
//  TextDiffer
// ═══════════════════════════════════════════════════════════════

/// Create a new TextDiffer. Returns an opaque handle, or null on failure.
#[no_mangle]
pub extern "C" fn ta_text_differ_new() -> *mut TextDiffer {
    Box::into_raw(Box::new(TextDiffer::new()))
}

/// Destroy a TextDiffer.
///
/// # Safety
/// `handle` must be a valid pointer returned by `ta_text_differ_new`,
/// or null (no-op).
#[no_mangle]
pub unsafe extern "C" fn ta_text_differ_free(handle: *mut TextDiffer) {
    if !handle.is_null() {
        let _ = Box::from_raw(handle);
    }
}

/// Feed new text and get the diff result.
///
/// # Safety
/// - `handle` must be a valid TextDiffer handle
/// - `text_ptr` must point to `text_len` valid UTF-8 bytes
/// - `out_kind`, `out_content_ptr`, `out_content_len` must be valid pointers
///
/// Returns 0 on success, nonzero on error.
/// Caller must free `*out_content_ptr` via `ta_free_string`.
#[no_mangle]
pub unsafe extern "C" fn ta_text_differ_update(
    handle: *mut TextDiffer,
    text_ptr: *const u8,
    text_len: usize,
    out_kind: *mut u32,
    out_content_ptr: *mut *mut u8,
    out_content_len: *mut usize,
) -> i32 {
    check_ptrs!(handle, out_kind, out_content_ptr, out_content_len);

    let text = match read_utf8(text_ptr, text_len) {
        Ok(s) => s,
        Err(e) => return e,
    };

    let differ = &mut *handle;
    let result = differ.update(text);

    *out_kind = result.kind as u32;
    let (ptr, len) = string_to_ffi(result.content);
    *out_content_ptr = ptr;
    *out_content_len = len;

    ERR_OK
}

/// Reset the differ state.
///
/// # Safety
/// `handle` must be a valid TextDiffer handle or null (no-op).
#[no_mangle]
pub unsafe extern "C" fn ta_text_differ_reset(handle: *mut TextDiffer) {
    if !handle.is_null() {
        (*handle).reset();
    }
}

/// Get the last text snapshot. Caller must free via `ta_free_string`.
///
/// # Safety
/// `handle`, `out_ptr`, `out_len` must be valid pointers.
/// Returns ERR_OK on success, writes null if no snapshot exists.
#[no_mangle]
pub unsafe extern "C" fn ta_text_differ_last_text(
    handle: *mut TextDiffer,
    out_ptr: *mut *mut u8,
    out_len: *mut usize,
) -> i32 {
    check_ptrs!(handle, out_ptr, out_len);

    let differ = &*handle;
    match differ.last_text() {
        Some(text) => {
            let (ptr, len) = string_to_ffi(text.to_string());
            *out_ptr = ptr;
            *out_len = len;
        }
        None => {
            *out_ptr = ptr::null_mut();
            *out_len = 0;
        }
    }

    ERR_OK
}

// ═══════════════════════════════════════════════════════════════
//  ANSI Stripping
// ═══════════════════════════════════════════════════════════════

// ANSI stripping and text search were removed from the FFI: the round-trip
// measured about 10x slower than Python's re/str, so both are done in
// Python now. termaccess-core still provides them for the helper binary.

// ═══════════════════════════════════════════════════════════════
//  PositionCache
// ═══════════════════════════════════════════════════════════════

/// Create a new PositionCache with given max_size and timeout_ms.
///
/// Returns an opaque handle, or null on failure.
#[no_mangle]
pub extern "C" fn ta_position_cache_new(max_size: u32, timeout_ms: u32) -> *mut PositionCache {
    Box::into_raw(Box::new(PositionCache::new(max_size as usize, timeout_ms)))
}

/// Destroy a PositionCache.
///
/// # Safety
/// `handle` must be a valid pointer from `ta_position_cache_new`, or null.
#[no_mangle]
pub unsafe extern "C" fn ta_position_cache_free(handle: *mut PositionCache) {
    if !handle.is_null() {
        let _ = Box::from_raw(handle);
    }
}

/// Get cached position.
///
/// Returns 0 if found (writes to `out_row`/`out_col`), 1 if not found or expired.
///
/// # Safety
/// All pointers must be valid.
#[no_mangle]
pub unsafe extern "C" fn ta_position_cache_get(
    handle: *mut PositionCache,
    key_ptr: *const u8,
    key_len: usize,
    out_row: *mut i32,
    out_col: *mut i32,
) -> i32 {
    check_ptrs!(handle, out_row, out_col);

    let key = match read_utf8(key_ptr, key_len) {
        Ok(s) => s,
        Err(e) => return e,
    };

    let cache = &*handle;
    match cache.get(key) {
        Some((row, col)) => {
            *out_row = row;
            *out_col = col;
            ERR_OK
        }
        None => ERR_NOT_FOUND,
    }
}

/// Set a cached position.
///
/// # Safety
/// `handle` must be valid. `key_ptr` must point to `key_len` valid UTF-8 bytes.
#[no_mangle]
pub unsafe extern "C" fn ta_position_cache_set(
    handle: *mut PositionCache,
    key_ptr: *const u8,
    key_len: usize,
    row: i32,
    col: i32,
) {
    if handle.is_null() {
        return;
    }

    let key = match read_utf8(key_ptr, key_len) {
        Ok(s) => s,
        Err(_) => return,
    };

    let cache = &*handle;
    cache.set(key, row, col);
}

/// Clear all entries.
///
/// # Safety
/// `handle` must be valid or null.
#[no_mangle]
pub unsafe extern "C" fn ta_position_cache_clear(handle: *mut PositionCache) {
    if !handle.is_null() {
        (*handle).clear();
    }
}

/// Invalidate a specific key.
///
/// # Safety
/// `handle` must be valid. `key_ptr` must be valid UTF-8.
#[no_mangle]
pub unsafe extern "C" fn ta_position_cache_invalidate(
    handle: *mut PositionCache,
    key_ptr: *const u8,
    key_len: usize,
) {
    if handle.is_null() {
        return;
    }

    let key = match read_utf8(key_ptr, key_len) {
        Ok(s) => s,
        Err(_) => return,
    };

    (*handle).invalidate(key);
}

// ═══════════════════════════════════════════════════════════════
//  Unicode Width
// ═══════════════════════════════════════════════════════════════

/// Get display width of a Unicode codepoint.
/// Returns 0, 1, or 2. Returns 0 for invalid codepoints.
#[no_mangle]
pub extern "C" fn ta_char_width(codepoint: u32) -> u32 {
    match char::from_u32(codepoint) {
        Some(c) => termaccess_core::unicode_width::char_width(c),
        None => 0,
    }
}

/// Calculate total display width of a UTF-8 text string.
/// Returns the total width, or u32::MAX on error (null pointer, invalid UTF-8).
///
/// # Safety
/// `text_ptr` must point to `text_len` valid UTF-8 bytes, or be null.
#[no_mangle]
pub unsafe extern "C" fn ta_text_width(
    text_ptr: *const u8,
    text_len: usize,
) -> u32 {
    let text = match read_utf8(text_ptr, text_len) {
        Ok(s) => s,
        Err(_) => return u32::MAX,
    };
    termaccess_core::unicode_width::text_width(text)
}

/// Extract text from a column range (1-based, inclusive).
/// Caller must free *out_ptr via ta_free_string.
///
/// # Safety
/// - `text_ptr` must point to `text_len` valid UTF-8 bytes, or be null.
/// - `out_ptr` and `out_len` must be valid, non-null pointers.
#[no_mangle]
pub unsafe extern "C" fn ta_extract_column_range(
    text_ptr: *const u8,
    text_len: usize,
    start_col: u32,
    end_col: u32,
    out_ptr: *mut *mut u8,
    out_len: *mut usize,
) -> i32 {
    check_ptrs!(out_ptr, out_len);

    let text = match read_utf8(text_ptr, text_len) {
        Ok(s) => s,
        Err(e) => return e,
    };

    let result = termaccess_core::unicode_width::extract_column_range(text, start_col, end_col);
    let (ptr, len) = string_to_ffi(result);
    *out_ptr = ptr;
    *out_len = len;

    ERR_OK
}

/// Find the char index for a target column position (1-based).
/// Returns the 0-based char index, or u32::MAX on error.
///
/// # Safety
/// `text_ptr` must point to `text_len` valid UTF-8 bytes, or be null.
#[no_mangle]
pub unsafe extern "C" fn ta_find_column_position(
    text_ptr: *const u8,
    text_len: usize,
    target_col: u32,
) -> u32 {
    let text = match read_utf8(text_ptr, text_len) {
        Ok(s) => s,
        Err(_) => return u32::MAX,
    };
    termaccess_core::unicode_width::find_column_position(text, target_col)
}

// ═══════════════════════════════════════════════════════════════
//  Fuzzy Search
// ═══════════════════════════════════════════════════════════════

/// Fuzzy search across newline-separated lines.
///
/// The `lines_ptr`/`lines_len` contain newline-separated text.
/// Results are written as JSON to `out_buf` (up to `out_buf_len` bytes).
/// JSON format: `[{"line": N, "text": "..."}]`
///
/// Returns the number of bytes written on success, or a negative
/// error code on failure:
///   -1 = output buffer too small
///   -2 = invalid UTF-8 input
///
/// # Safety
/// - `pattern_ptr` must point to `pattern_len` valid UTF-8 bytes
/// - `lines_ptr` must point to `lines_len` valid UTF-8 bytes
/// - `out_buf` must point to `out_buf_len` writable bytes
#[no_mangle]
pub unsafe extern "C" fn ta_fuzzy_search(
    pattern_ptr: *const u8,
    pattern_len: usize,
    lines_ptr: *const u8,
    lines_len: usize,
    max_distance: u32,
    out_buf: *mut u8,
    out_buf_len: usize,
) -> i32 {
    if out_buf.is_null() {
        return -1;
    }

    let pattern = match read_utf8(pattern_ptr, pattern_len) {
        Ok(s) => s,
        Err(_) => return -2,
    };

    let lines_text = match read_utf8(lines_ptr, lines_len) {
        Ok(s) => s,
        Err(_) => return -2,
    };

    let lines: Vec<String> = lines_text.split('\n').map(|s| s.to_string()).collect();
    let results = termaccess_core::fuzzy_search::fuzzy_search(
        pattern,
        &lines,
        max_distance as usize,
    );

    let json_results: Vec<serde_json::Value> = results
        .iter()
        .map(|(line_num, text)| {
            serde_json::json!({
                "line": line_num,
                "text": text,
            })
        })
        .collect();

    let json_str = serde_json::to_string(&json_results).unwrap_or_else(|_| "[]".to_string());
    let json_bytes = json_str.as_bytes();

    if json_bytes.len() > out_buf_len {
        return -1;
    }

    ptr::copy_nonoverlapping(json_bytes.as_ptr(), out_buf, json_bytes.len());
    json_bytes.len() as i32
}

/// Scoped (bounded) search across newline-separated lines.
///
/// Searches lines from `start` to `end` (inclusive) for the pattern.
/// Results are written as JSON to `out_buf`.
/// JSON format: `[{"line": N, "text": "..."}]`
///
/// Returns the number of bytes written on success, or a negative
/// error code on failure:
///   -1 = output buffer too small
///   -2 = invalid UTF-8 input
///
/// # Safety
/// - `pattern_ptr` must point to `pattern_len` valid UTF-8 bytes
/// - `lines_ptr` must point to `lines_len` valid UTF-8 bytes
/// - `out_buf` must point to `out_buf_len` writable bytes
#[no_mangle]
pub unsafe extern "C" fn ta_scoped_search(
    pattern_ptr: *const u8,
    pattern_len: usize,
    lines_ptr: *const u8,
    lines_len: usize,
    start: u32,
    end: u32,
    case_sensitive: u32,
    out_buf: *mut u8,
    out_buf_len: usize,
) -> i32 {
    if out_buf.is_null() {
        return -1;
    }

    let pattern = match read_utf8(pattern_ptr, pattern_len) {
        Ok(s) => s,
        Err(_) => return -2,
    };

    let lines_text = match read_utf8(lines_ptr, lines_len) {
        Ok(s) => s,
        Err(_) => return -2,
    };

    let lines: Vec<String> = lines_text.split('\n').map(|s| s.to_string()).collect();
    let results = termaccess_core::fuzzy_search::scoped_search(
        pattern,
        &lines,
        start as usize,
        end as usize,
        case_sensitive != 0,
    );

    let json_results: Vec<serde_json::Value> = results
        .iter()
        .map(|(line_num, text)| {
            serde_json::json!({
                "line": line_num,
                "text": text,
            })
        })
        .collect();

    let json_str = serde_json::to_string(&json_results).unwrap_or_else(|_| "[]".to_string());
    let json_bytes = json_str.as_bytes();

    if json_bytes.len() > out_buf_len {
        return -1;
    }

    ptr::copy_nonoverlapping(json_bytes.as_ptr(), out_buf, json_bytes.len());
    json_bytes.len() as i32
}
