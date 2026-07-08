//! Integration tests for the fuzzy_search module.

use termaccess_core::fuzzy_search;

// ═══════════════════════════════════════════════════════════════
//  Levenshtein distance
// ═══════════════════════════════════════════════════════════════

#[test]
fn levenshtein_kitten_sitting() {
    assert_eq!(fuzzy_search::levenshtein_distance("kitten", "sitting"), 3);
}

#[test]
fn levenshtein_identical() {
    assert_eq!(fuzzy_search::levenshtein_distance("hello", "hello"), 0);
}

#[test]
fn levenshtein_empty_strings() {
    assert_eq!(fuzzy_search::levenshtein_distance("", ""), 0);
    assert_eq!(fuzzy_search::levenshtein_distance("abc", ""), 3);
    assert_eq!(fuzzy_search::levenshtein_distance("", "abc"), 3);
}

#[test]
fn levenshtein_single_edit() {
    // Substitution
    assert_eq!(fuzzy_search::levenshtein_distance("cat", "bat"), 1);
    // Insertion
    assert_eq!(fuzzy_search::levenshtein_distance("cat", "cats"), 1);
    // Deletion
    assert_eq!(fuzzy_search::levenshtein_distance("cats", "cat"), 1);
}

// ═══════════════════════════════════════════════════════════════
//  Fuzzy search
// ═══════════════════════════════════════════════════════════════

#[test]
fn fuzzy_search_exact_match() {
    let lines = vec!["this has an error".to_string(), "no match here".to_string()];
    let results = fuzzy_search::fuzzy_search("error", &lines, 0);
    assert_eq!(results.len(), 1);
    assert_eq!(results[0].0, 0); // line number
    assert!(results[0].1.contains("error"));
}

#[test]
fn fuzzy_search_distance_1() {
    // "erorr" is distance 1 from "error" (transposition)
    let lines = vec!["there is an error here".to_string()];
    let results = fuzzy_search::fuzzy_search("erorr", &lines, 1);
    assert_eq!(results.len(), 1);
    assert_eq!(results[0].0, 0);
}

#[test]
fn fuzzy_search_distance_too_large() {
    // "xyz" is far from any word in the line
    let lines = vec!["there is an error here".to_string()];
    let results = fuzzy_search::fuzzy_search("xyz", &lines, 1);
    assert!(results.is_empty());
}

#[test]
fn fuzzy_search_empty_pattern() {
    let lines = vec!["hello".to_string()];
    let results = fuzzy_search::fuzzy_search("", &lines, 1);
    assert!(results.is_empty());
}

#[test]
fn fuzzy_search_empty_lines() {
    let lines: Vec<String> = vec![];
    let results = fuzzy_search::fuzzy_search("error", &lines, 1);
    assert!(results.is_empty());
}

#[test]
fn fuzzy_search_ansi_stripped() {
    // ANSI codes around "error" should be stripped before matching
    let lines = vec!["\x1b[31merror\x1b[0m: something failed".to_string()];
    let results = fuzzy_search::fuzzy_search("error", &lines, 0);
    assert_eq!(results.len(), 1);
    // The returned text should be ANSI-stripped
    assert!(!results[0].1.contains("\x1b"));
}

#[test]
fn fuzzy_search_pattern_length_cap() {
    // Pattern longer than 500 chars should return empty results
    let long_pattern: String = "a".repeat(501);
    let lines = vec!["some text".to_string()];
    let results = fuzzy_search::fuzzy_search(&long_pattern, &lines, 1);
    assert!(results.is_empty());
}

#[test]
fn fuzzy_search_result_count_cap() {
    // Generate 1500 matching lines; results should be capped at 1000
    let lines: Vec<String> = (0..1500).map(|i| format!("error on line {}", i)).collect();
    let results = fuzzy_search::fuzzy_search("error", &lines, 0);
    assert!(results.len() <= 1000);
}

#[test]
fn fuzzy_search_case_insensitive() {
    // Fuzzy search should be case-insensitive by default
    let lines = vec!["ERROR in module".to_string()];
    let results = fuzzy_search::fuzzy_search("error", &lines, 0);
    assert_eq!(results.len(), 1);
}

// ═══════════════════════════════════════════════════════════════
//  Scoped search
// ═══════════════════════════════════════════════════════════════

#[test]
fn scoped_search_respects_boundaries() {
    let lines = vec![
        "error on line 0".to_string(),
        "error on line 1".to_string(),
        "error on line 2".to_string(),
        "error on line 3".to_string(),
        "error on line 4".to_string(),
    ];
    // Only search lines 1..3 (inclusive)
    let results = fuzzy_search::scoped_search("error", &lines, 1, 3, false);
    assert_eq!(results.len(), 3);
    assert_eq!(results[0].0, 1);
    assert_eq!(results[1].0, 2);
    assert_eq!(results[2].0, 3);
}

#[test]
fn scoped_search_case_sensitive() {
    let lines = vec![
        "Error on line 0".to_string(),
        "error on line 1".to_string(),
        "ERROR on line 2".to_string(),
    ];
    let results = fuzzy_search::scoped_search("error", &lines, 0, 2, true);
    assert_eq!(results.len(), 1);
    assert_eq!(results[0].0, 1);
}

#[test]
fn scoped_search_case_insensitive() {
    let lines = vec![
        "Error on line 0".to_string(),
        "error on line 1".to_string(),
        "ERROR on line 2".to_string(),
    ];
    let results = fuzzy_search::scoped_search("error", &lines, 0, 2, false);
    assert_eq!(results.len(), 3);
}

#[test]
fn scoped_search_ansi_stripped() {
    let lines = vec![
        "\x1b[31merror\x1b[0m: line 0".to_string(),
        "normal line 1".to_string(),
    ];
    let results = fuzzy_search::scoped_search("error", &lines, 0, 1, false);
    assert_eq!(results.len(), 1);
    assert_eq!(results[0].0, 0);
    assert!(!results[0].1.contains("\x1b"));
}

#[test]
fn scoped_search_empty_pattern() {
    let lines = vec!["hello".to_string()];
    let results = fuzzy_search::scoped_search("", &lines, 0, 0, false);
    assert!(results.is_empty());
}

#[test]
fn scoped_search_out_of_bounds() {
    let lines = vec!["error".to_string(), "hello".to_string()];
    // end_line beyond array length should not panic
    let results = fuzzy_search::scoped_search("error", &lines, 0, 100, false);
    assert_eq!(results.len(), 1);
}

#[test]
fn scoped_search_pattern_length_cap() {
    let long_pattern: String = "a".repeat(501);
    let lines = vec!["some text".to_string()];
    let results = fuzzy_search::scoped_search(&long_pattern, &lines, 0, 0, false);
    assert!(results.is_empty());
}

#[test]
fn scoped_search_result_count_cap() {
    let lines: Vec<String> = (0..1500).map(|i| format!("error on line {}", i)).collect();
    let results = fuzzy_search::scoped_search("error", &lines, 0, 1499, false);
    assert!(results.len() <= 1000);
}
