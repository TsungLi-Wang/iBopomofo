// Copyright (c) 2026 and onwards The iBopomofo Authors.
//
// Post-commit reselect: after Enter hard-commit, re-pick a character already
// sent to the client. Replacement must actually remove the old grapheme
// (1→1). Many apps ignore insertText(replacementRange:) on committed text,
// so we pull the char into marked composition first, then replace the mark.

import Cocoa
import InputMethodKit
import NSStringUtils

/// Minimal client surface used by post-commit reselect (IMKTextInput subset).
protocol PostCommitTextClient: AnyObject {
    func selectedRange() -> NSRange
    func markedRange() -> NSRange
    func attributedSubstring(from range: NSRange) -> NSAttributedString?
    func setMarkedText(_ string: Any!, selectionRange: NSRange, replacementRange: NSRange)
    func insertText(_ string: Any!, replacementRange: NSRange)
}

extension IMKTextInput {
    /// Bridge IMKTextInput to PostCommitTextClient without a second type eraser.
    fileprivate var asPostCommitClient: PostCommitTextClient {
        IMKTextInputBox(self)
    }
}

private final class IMKTextInputBox: PostCommitTextClient {
    private let client: IMKTextInput
    init(_ client: IMKTextInput) { self.client = client }
    func selectedRange() -> NSRange { client.selectedRange() }
    func markedRange() -> NSRange { client.markedRange() }
    func attributedSubstring(from range: NSRange) -> NSAttributedString? {
        client.attributedSubstring(from: range) as NSAttributedString?
    }
    func setMarkedText(_ string: Any!, selectionRange: NSRange, replacementRange: NSRange) {
        client.setMarkedText(
            string, selectionRange: selectionRange, replacementRange: replacementRange)
    }
    func insertText(_ string: Any!, replacementRange: NSRange) {
        client.insertText(string, replacementRange: replacementRange)
    }
}

/// Helpers for post-commit reconversion. Does not change Enter hard-commit.
enum PostCommitReselect {
    enum ReplaceOutcome: Equatable {
        /// Old grapheme removed, new grapheme inserted (net length change = Δ utf16 of new-old).
        case replaced
        /// Could not remove old grapheme; nothing inserted (no double-char).
        case abortedNoOp
    }

    /// Read the grapheme cluster starting at `location` in the client document.
    static func readCluster(client: IMKTextInput, at location: Int) -> (char: String, range: NSRange)?
    {
        readCluster(client: client.asPostCommitClient, at: location)
    }

    static func readCluster(client: PostCommitTextClient, at location: Int) -> (
        char: String, range: NSRange
    )? {
        guard location >= 0 else { return nil }
        for len in [1, 2, 4] {
            let proposed = NSRange(location: location, length: len)
            guard let attr = client.attributedSubstring(from: proposed),
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

    static func caretLocation(client: IMKTextInput) -> Int? {
        caretLocation(client: client.asPostCommitClient)
    }

    static func caretLocation(client: PostCommitTextClient) -> Int? {
        let sel = client.selectedRange()
        if sel.location == NSNotFound { return nil }
        return sel.location
    }

    static func highlightState(char: String, at documentLocation: Int) -> InputState
        .PostCommitHighlight
    {
        let reading = LanguageModelManager.reading(for: char) ?? ""
        return InputState.PostCommitHighlight(
            character: char, reading: reading, documentLocation: documentLocation)
    }

    static func candidates(forCharacter char: String) -> [InputState.Candidate] {
        let rows = LanguageModelManager.homophoneCandidates(forCharacter: char)
        return rows.compactMap { dict in
            guard let reading = dict["reading"], let value = dict["value"] else { return nil }
            let display = dict["displayText"] ?? value
            return InputState.Candidate(
                reading: reading, value: value, displayText: display, rawValue: value)
        }
    }

    /// Attributed mark for a single pending character (highlight).
    static func markedAttributes(for char: String) -> NSAttributedString {
        let full = NSRange(location: 0, length: (char as NSString).length)
        let result = NSMutableAttributedString(string: char)
        result.addAttribute(.markedClauseSegment, value: 0, range: full)
        result.addAttribute(
            .backgroundColor, value: NSColor.selectedTextBackgroundColor, range: full)
        result.addAttribute(
            .underlineStyle, value: NSUnderlineStyle.single.rawValue, range: full)
        return result
    }

    /// Pull a committed grapheme into marked composition so subsequent
    /// insertText(NSNotFound) replaces it (apps honor mark→insert far more
    /// reliably than replacementRange on committed text).
    @discardableResult
    static func pullCommittedIntoMark(
        client: IMKTextInput, documentRange: NSRange, char: String
    ) -> Bool {
        pullCommittedIntoMark(
            client: client.asPostCommitClient, documentRange: documentRange, char: char)
    }

    @discardableResult
    static func pullCommittedIntoMark(
        client: PostCommitTextClient, documentRange: NSRange, char: String
    ) -> Bool {
        guard documentRange.location != NSNotFound, documentRange.length > 0, !char.isEmpty
        else {
            return false
        }
        client.setMarkedText(
            markedAttributes(for: char),
            selectionRange: NSRange(location: 0, length: 0),
            replacementRange: documentRange)
        let mark = client.markedRange()
        return mark.location != NSNotFound && mark.length > 0
    }

    /// Replace the pending grapheme with `newChar` (1→1). Never leaves both
    /// old and new. If the old char cannot be removed, aborts without insert.
    static func replacePendingCharacter(
        client: IMKTextInput,
        documentRange: NSRange,
        oldChar: String,
        newChar: String
    ) -> ReplaceOutcome {
        replacePendingCharacter(
            client: client.asPostCommitClient,
            documentRange: documentRange,
            oldChar: oldChar,
            newChar: newChar)
    }

    static func replacePendingCharacter(
        client: PostCommitTextClient,
        documentRange: NSRange,
        oldChar: String,
        newChar: String
    ) -> ReplaceOutcome {
        // Iron rule: never insert newChar unless the old grapheme is gone
        // (or replaced atomically). Inserting after a silent no-op delete is
        // what made "sentences grow longer" after each reselect.

        guard documentRange.location != NSNotFound, documentRange.length > 0 else {
            return .abortedNoOp
        }

        // Re-resolve live cluster at stored location (may have drifted).
        let liveRange: NSRange
        if let live = readCluster(client: client, at: documentRange.location),
            live.char == oldChar
        {
            liveRange = live.range
        } else if let live = readCluster(client: client, at: documentRange.location) {
            liveRange = live.range
        } else {
            liveRange = documentRange
        }

        // --- Path 0: atomic insertText(new, replacementRange: old) + verify ---
        // Success only if the grapheme *at the old location* is now newChar
        // (proves replace, not "insert elsewhere while old remains").
        client.insertText(newChar as NSString, replacementRange: liveRange)
        if clusterAt(client, liveRange.location) == newChar {
            return .replaced
        }

        // --- Path A: pull committed char into mark, then insertText replaces mark ---
        var mark = client.markedRange()
        if mark.location == NSNotFound || mark.length == 0 {
            _ = pullCommittedIntoMark(
                client: client, documentRange: liveRange, char: oldChar)
            mark = client.markedRange()
        }
        if mark.location != NSNotFound, mark.length > 0 {
            client.insertText(
                newChar as NSString,
                replacementRange: NSRange(location: NSNotFound, length: NSNotFound))
            // Verify: old must not still sit at original location as committed text.
            if clusterAt(client, liveRange.location) != oldChar {
                return .replaced
            }
            // Mark path claimed success but old still there — fall through.
        }

        // --- Path B: delete (empty insert) then verify, only then insert ---
        client.insertText("" as NSString, replacementRange: liveRange)
        if clusterAt(client, liveRange.location) == oldChar {
            // App ignored empty-insert delete. Try CGEvent if Accessibility on.
            if !deleteOneGraphemeViaCGEvent(
                client: client, liveRange: liveRange, oldChar: oldChar)
            {
                NSLog(
                    "i注音 reselect: delete not verified (insertText empty + CGEvent); abort insert")
                return .abortedNoOp
            }
        }
        // Deleted (or CGEvent deleted). Insert new at hole.
        client.insertText(
            newChar as NSString,
            replacementRange: NSRange(location: NSNotFound, length: NSNotFound))
        return .replaced
    }

    private static func clusterAt(_ client: PostCommitTextClient, _ location: Int) -> String? {
        readCluster(client: client, at: location)?.char
    }

    /// CGEvent forward-delete or backspace when caret appears to sit on the
    /// pending grapheme. Returns true only if oldChar is no longer at liveRange.
    private static func deleteOneGraphemeViaCGEvent(
        client: PostCommitTextClient, liveRange: NSRange, oldChar: String
    ) -> Bool {
        guard AXIsProcessTrusted() else { return false }
        let sel = client.selectedRange()
        let caret = sel.location
        // Forward-delete removes char to the *right* of caret → need caret == start.
        // Backspace removes char to the *left* → need caret == end of grapheme.
        let useForward: Bool
        if caret != NSNotFound {
            if caret == liveRange.location {
                useForward = true
            } else if caret == liveRange.location + liveRange.length {
                useForward = false
            } else {
                // Caret elsewhere: still try forward-delete first (common after 定案).
                useForward = true
            }
        } else {
            useForward = true
        }
        let code: CGKeyCode = useForward ? 0x75 : 0x33
        guard let src = CGEventSource(stateID: .hidSystemState) else { return false }
        guard let down = CGEvent(keyboardEventSource: src, virtualKey: code, keyDown: true),
            let up = CGEvent(keyboardEventSource: src, virtualKey: code, keyDown: false)
        else {
            return false
        }
        down.post(tap: .cghidEventTap)
        up.post(tap: .cghidEventTap)
        // Allow target app to process the synthetic key before we re-read.
        RunLoop.current.run(until: Date(timeIntervalSinceNow: 0.05))
        if clusterAt(client, liveRange.location) == oldChar {
            // Try the other direction once.
            let other: CGKeyCode = useForward ? 0x33 : 0x75
            guard let d2 = CGEvent(keyboardEventSource: src, virtualKey: other, keyDown: true),
                let u2 = CGEvent(keyboardEventSource: src, virtualKey: other, keyDown: false)
            else {
                return false
            }
            d2.post(tap: .cghidEventTap)
            u2.post(tap: .cghidEventTap)
            RunLoop.current.run(until: Date(timeIntervalSinceNow: 0.05))
        }
        return clusterAt(client, liveRange.location) != oldChar
    }
}

// MARK: - In-memory client for logic tests / TextEdit-parity simulation

/// Minimal document model implementing PostCommitTextClient (committed + mark).
final class PostCommitStringDocument: PostCommitTextClient {
    private(set) var text: String
    private var caret: Int
    private var markRange: NSRange = NSRange(location: NSNotFound, length: 0)
    private var markString: String = ""

    init(text: String, caret: Int) {
        self.text = text
        self.caret = min(max(0, caret), (text as NSString).length)
    }

    func selectedRange() -> NSRange {
        // Caret sits after mark if mark is active (IME convention).
        if markRange.location != NSNotFound {
            return NSRange(location: markRange.location + markRange.length, length: 0)
        }
        return NSRange(location: caret, length: 0)
    }

    func markedRange() -> NSRange { markRange }

    func attributedSubstring(from range: NSRange) -> NSAttributedString? {
        let ns = text as NSString
        guard range.location != NSNotFound, range.location >= 0,
            range.location + range.length <= ns.length
        else {
            return nil
        }
        let sub = ns.substring(with: range)
        return NSAttributedString(string: sub)
    }

    func setMarkedText(_ string: Any!, selectionRange: NSRange, replacementRange: NSRange) {
        let incoming: String = {
            if let a = string as? NSAttributedString { return a.string }
            if let s = string as? String { return s }
            if let s = string as? NSString { return s as String }
            return ""
        }()

        let ns = text as NSString
        if replacementRange.location != NSNotFound, replacementRange.length >= 0,
            replacementRange.location + replacementRange.length <= ns.length
        {
            // Replace committed slice with mark (pull into composing).
            text =
                ns.substring(to: replacementRange.location) + incoming
                + ns.substring(from: replacementRange.location + replacementRange.length)
            markRange = NSRange(
                location: replacementRange.location, length: (incoming as NSString).length)
            markString = incoming
            caret = markRange.location + markRange.length
            return
        }

        if incoming.isEmpty {
            // Clear mark: remove marked slice from storage (IME cancel / EmptyIgnoring).
            if markRange.location != NSNotFound {
                let before = (text as NSString).substring(to: markRange.location)
                let after = (text as NSString).substring(
                    from: markRange.location + markRange.length)
                text = before + after
                caret = markRange.location
                markRange = NSRange(location: NSNotFound, length: 0)
                markString = ""
            }
            return
        }

        // replacementRange NSNotFound: update existing mark content in place.
        if markRange.location != NSNotFound {
            let before = (text as NSString).substring(to: markRange.location)
            let after = (text as NSString).substring(from: markRange.location + markRange.length)
            text = before + incoming + after
            markRange = NSRange(
                location: markRange.location, length: (incoming as NSString).length)
            markString = incoming
            caret = markRange.location + markRange.length
            return
        }

        // No mark + NSNotFound: insert at caret as mark.
        let before = (text as NSString).substring(to: caret)
        let after = (text as NSString).substring(from: caret)
        text = before + incoming + after
        markRange = NSRange(location: caret, length: (incoming as NSString).length)
        markString = incoming
        caret = markRange.location + markRange.length
    }

    func insertText(_ string: Any!, replacementRange: NSRange) {
        let incoming: String = {
            if let a = string as? NSAttributedString { return a.string }
            if let s = string as? String { return s }
            if let s = string as? NSString { return s as String }
            return ""
        }()

        let ns = text as NSString

        // Replace mark (IME default when replacementRange is NSNotFound and mark active).
        if replacementRange.location == NSNotFound, markRange.location != NSNotFound {
            let before = ns.substring(to: markRange.location)
            let after = ns.substring(from: markRange.location + markRange.length)
            text = before + incoming + after
            caret = markRange.location + (incoming as NSString).length
            markRange = NSRange(location: NSNotFound, length: 0)
            markString = ""
            return
        }

        if replacementRange.location != NSNotFound,
            replacementRange.location + replacementRange.length <= ns.length
        {
            let before = ns.substring(to: replacementRange.location)
            let after = ns.substring(
                from: replacementRange.location + replacementRange.length)
            text = before + incoming + after
            caret = replacementRange.location + (incoming as NSString).length
            markRange = NSRange(location: NSNotFound, length: 0)
            markString = ""
            return
        }

        // Plain insert at caret.
        let before = ns.substring(to: caret)
        let after = ns.substring(from: caret)
        text = before + incoming + after
        caret += (incoming as NSString).length
        markRange = NSRange(location: NSNotFound, length: 0)
        markString = ""
    }
}
