//! UIA text reading: read terminal content given an HWND.
//!
//! Uses `IUIAutomation::ElementFromHandle` to get a UIA element,
//! then `IUIAutomationTextPattern::DocumentRange` to read all text.

use std::io;

use windows::core::Interface;
use windows::Win32::Foundation::*;
use windows::Win32::UI::Accessibility::*;

use crate::security;

/// Upper bound on characters read from a terminal in one call.
///
/// `GetText(-1)` reads the entire document; on a pathologically large
/// scrollback that marshals an unbounded string across the process
/// boundary. A positive limit truncates instead, bounding the cost. The
/// cap is generous (well above a normal terminal scrollback) so real
/// content is not lost in practice.
const MAX_TEXT_CHARS: i32 = 5_000_000;

/// A UIA reader that holds a reference to the automation instance.
pub struct UiaReader {
    automation: IUIAutomation,
}

impl UiaReader {
    /// Create a new UIA reader.
    ///
    /// Must be called after `CoInitializeEx` on the same thread.
    pub fn new() -> io::Result<Self> {
        unsafe {
            let automation: IUIAutomation = windows::Win32::System::Com::CoCreateInstance(
                &CUIAutomation,
                None,
                windows::Win32::System::Com::CLSCTX_INPROC_SERVER,
            )
            .map_err(|e| io::Error::new(io::ErrorKind::Other, format!("CoCreateInstance failed: {e}")))?;

            Ok(UiaReader { automation })
        }
    }

    /// Read all text from a terminal identified by its HWND.
    pub fn read_text(&self, hwnd: isize) -> io::Result<String> {
        security::validate_hwnd(hwnd)?;

        unsafe {
            let wnd = HWND(hwnd as *mut _);

            // Get UIA element from HWND
            let element = self
                .automation
                .ElementFromHandle(wnd)
                .map_err(|e| io::Error::new(io::ErrorKind::Other, format!("ElementFromHandle failed: {e}")))?;

            // Get text pattern
            let pattern_obj = element
                .GetCurrentPattern(UIA_TextPatternId)
                .map_err(|e| io::Error::new(io::ErrorKind::Other, format!("GetCurrentPattern(Text) failed: {e}")))?;

            let text_pattern: IUIAutomationTextPattern = pattern_obj
                .cast()
                .map_err(|e| io::Error::new(io::ErrorKind::Other, format!("Cast to TextPattern failed: {e}")))?;

            // Get document range
            let range = text_pattern
                .DocumentRange()
                .map_err(|e| io::Error::new(io::ErrorKind::Other, format!("DocumentRange failed: {e}")))?;

            // Read up to MAX_TEXT_CHARS characters (a positive limit
            // truncates; -1 would read the whole document unbounded).
            let text = range
                .GetText(MAX_TEXT_CHARS)
                .map_err(|e| io::Error::new(io::ErrorKind::Other, format!("GetText failed: {e}")))?;

            Ok(text.to_string())
        }
    }

    /// Get a reference to the underlying IUIAutomation instance.
    pub fn automation(&self) -> &IUIAutomation {
        &self.automation
    }
}
