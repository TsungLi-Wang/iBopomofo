// Copyright (c) 2026 and onwards The iBopomofo Authors.
//
// Post-commit reselect: after Enter hard-commit, re-pick a character already
// sent to the client via NSTextInputClient surrounding text + replace.
// App-dependent: Cocoa text views usually work; some Electron/web fields do not.

import Cocoa
import InputMethodKit
import NSStringUtils

/// Helpers for post-commit reconversion. Does not change Enter hard-commit.
enum PostCommitReselect {
    /// Read the grapheme cluster starting at `location` in the client document.
    /// Returns nil when the client rejects surrounding-text queries (unsupported apps).
    static func readCluster(client: IMKTextInput, at location: Int) -> (char: String, range: NSRange)?
    {
        guard location >= 0 else { return nil }
        // Probe up to 4 UTF-16 units (covers most CJK + rare surrogate pairs).
        for len in [1, 2, 4] {
            let proposed = NSRange(location: location, length: len)
            // IMKTextInput Swift overlay: attributedSubstring(from:) — no actualRange.
            guard let attr = client.attributedSubstring(from: proposed) as NSAttributedString?,
                !attr.string.isEmpty
            else {
                continue
            }
            let full = attr.string
            let end = full.nextUtf16Position(for: 0)
            guard end > 0 else { continue }
            let cluster = (full as NSString).substring(to: end)
            let range = NSRange(location: location, length: (cluster as NSString).length)
            return (cluster, range)
        }
        return nil
    }

    /// Insertion-point (caret) in the client, or nil if unavailable.
    static func caretLocation(client: IMKTextInput) -> Int? {
        let sel = client.selectedRange()
        if sel.location == NSNotFound { return nil }
        return sel.location
    }

    /// Build highlighted marked text for a single pending character.
    static func highlightState(char: String, at documentLocation: Int) -> InputState.PostCommitHighlight
    {
        let reading = LanguageModelManager.reading(for: char) ?? ""
        return InputState.PostCommitHighlight(
            character: char, reading: reading, documentLocation: documentLocation)
    }

    /// Homophone candidates for a character; empty if unreadable / no model hit.
    static func candidates(forCharacter char: String) -> [InputState.Candidate] {
        let rows = LanguageModelManager.homophoneCandidates(forCharacter: char)
        return rows.compactMap { dict in
            guard let reading = dict["reading"], let value = dict["value"] else { return nil }
            let display = dict["displayText"] ?? value
            return InputState.Candidate(reading: reading, value: value, displayText: display, rawValue: value)
        }
    }
}
