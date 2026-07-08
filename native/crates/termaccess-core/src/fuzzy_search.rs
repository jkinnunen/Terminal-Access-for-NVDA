//! Fuzzy and scoped search for terminal text.
//!
//! Provides Levenshtein distance calculation, word-level fuzzy matching,
//! and scoped (bounded) substring search. All functions strip ANSI
//! escape sequences before matching.

use crate::ansi_strip;

/// Maximum pattern length accepted by search functions.
const MAX_PATTERN_LEN: usize = 500;

/// Maximum number of results returned by search functions.
const MAX_RESULTS: usize = 1000;

/// Compute the Damerau-Levenshtein (optimal string alignment) distance.
///
/// Counts insertions, deletions, substitutions, and adjacent
/// transpositions as single edits. This matches the Python
/// `_levenshtein_distance` implementation in `search.py`.
pub fn levenshtein_distance(a: &str, b: &str) -> usize {
    let a_chars: Vec<char> = a.chars().collect();
    let b_chars: Vec<char> = b.chars().collect();
    let len_a = a_chars.len();
    let len_b = b_chars.len();

    if len_a == 0 {
        return len_b;
    }
    if len_b == 0 {
        return len_a;
    }

    // Full matrix needed for transposition lookback.
    let mut d = vec![vec![0usize; len_b + 1]; len_a + 1];
    for i in 0..=len_a {
        d[i][0] = i;
    }
    for j in 0..=len_b {
        d[0][j] = j;
    }

    for i in 1..=len_a {
        for j in 1..=len_b {
            let cost = if a_chars[i - 1] == b_chars[j - 1] { 0 } else { 1 };
            d[i][j] = (d[i - 1][j] + 1)       // deletion
                .min(d[i][j - 1] + 1)          // insertion
                .min(d[i - 1][j - 1] + cost);  // substitution

            // Transposition check
            if i > 1
                && j > 1
                && a_chars[i - 1] == b_chars[j - 2]
                && a_chars[i - 2] == b_chars[j - 1]
            {
                d[i][j] = d[i][j].min(d[i - 2][j - 2] + 1);
            }
        }
    }

    d[len_a][len_b]
}

/// Search lines for fuzzy matches of a pattern.
///
/// Each line is stripped of ANSI codes, then split into words.
/// A line matches if any word has Levenshtein distance <= `max_distance`
/// from the pattern (case-insensitive comparison).
///
/// Returns `(line_number, stripped_line_text)` pairs.
/// Returns empty if pattern is empty or exceeds 500 characters.
/// Results are capped at 1000.
pub fn fuzzy_search(
    pattern: &str,
    lines: &[String],
    max_distance: usize,
) -> Vec<(usize, String)> {
    if pattern.is_empty() || pattern.len() > MAX_PATTERN_LEN {
        return Vec::new();
    }

    let pat_lower = pattern.to_lowercase();
    let mut results = Vec::new();

    for (i, line) in lines.iter().enumerate() {
        if results.len() >= MAX_RESULTS {
            break;
        }

        let stripped = ansi_strip::strip_ansi(line);
        let words = split_words(&stripped);

        for word in &words {
            if word.is_empty() {
                continue;
            }
            let word_lower = word.to_lowercase();
            if levenshtein_distance(&pat_lower, &word_lower) <= max_distance {
                results.push((i, stripped.clone()));
                break;
            }
        }
    }

    results
}

/// Search a bounded range of lines for an exact substring match.
///
/// Lines from `start_line` to `end_line` (inclusive) are searched.
/// ANSI codes are stripped before matching. When `case_sensitive` is
/// false, both pattern and line are lowercased before comparison.
///
/// Returns `(line_number, stripped_line_text)` pairs.
/// Returns empty if pattern is empty or exceeds 500 characters.
/// Results are capped at 1000. Out-of-bounds indices are clamped.
pub fn scoped_search(
    pattern: &str,
    lines: &[String],
    start_line: usize,
    end_line: usize,
    case_sensitive: bool,
) -> Vec<(usize, String)> {
    if pattern.is_empty() || pattern.len() > MAX_PATTERN_LEN {
        return Vec::new();
    }

    let effective_end = end_line.min(lines.len().saturating_sub(1));
    if start_line > effective_end || start_line >= lines.len() {
        return Vec::new();
    }

    let normalized_pattern = if case_sensitive {
        pattern.to_string()
    } else {
        pattern.to_lowercase()
    };

    let mut results = Vec::new();

    for i in start_line..=effective_end {
        if results.len() >= MAX_RESULTS {
            break;
        }

        let stripped = ansi_strip::strip_ansi(&lines[i]);
        let haystack = if case_sensitive {
            stripped.clone()
        } else {
            stripped.to_lowercase()
        };

        if haystack.contains(&normalized_pattern) {
            results.push((i, stripped));
        }
    }

    results
}

/// Split text into words on whitespace and common punctuation.
fn split_words(text: &str) -> Vec<&str> {
    text.split(|c: char| {
        c.is_whitespace()
            || matches!(c, ':' | ';' | ',' | '.' | '(' | ')' | '[' | ']'
                | '{' | '}' | '=' | '<' | '>' | '!' | '@' | '#'
                | '$' | '%' | '^' | '&' | '*' | '|' | '/' | '\\')
    })
    .filter(|w| !w.is_empty())
    .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_split_words() {
        let words = split_words("hello world:foo.bar");
        assert_eq!(words, vec!["hello", "world", "foo", "bar"]);
    }

    #[test]
    fn test_split_words_empty() {
        let words = split_words("");
        assert!(words.is_empty());
    }
}
