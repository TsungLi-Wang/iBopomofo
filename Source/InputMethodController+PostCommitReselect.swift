// Copyright (c) 2026 and onwards The iBopomofo Authors.
//
// Post-commit reselect after Enter hard-commit.
//
// v2.9.6: Direction keys must NOT be intercepted for normal navigation.
// - Empty + armed: only ↓ may enter reselect; ←/→/↑ always pass through to the app.
// - PostCommitHighlight (reselect session): ←/→ move highlight; ↓ candidates; ↑ flush+pass.
// Positioning always uses client.selectedRange() live — no accumulated internal cursor.

import Cocoa
import InputMethodKit
import NSStringUtils

extension McBopomofoInputMethodController {

    /// Returns true if the key was fully handled for post-commit reselect.
    func tryHandlePostCommitReselect(input: KeyHandlerInput, client: Any?) -> Bool {
        if keyHandler.inputMode != .bopomofo {
            return false
        }

        let inHighlight = state is InputState.PostCommitHighlight
        let inPostCandidates =
            (state as? InputState.ChoosingCandidate)?.isPostCommitReselect == true

        // Candidate panel: KeyHandler / candidate controller owns keys.
        if inPostCandidates {
            return false
        }

        // --- Normal Empty (or anything else) while merely "armed" ---
        // First priority: never steal ←/→/↑ for ordinary navigation.
        if !inHighlight {
            // New composition / typing while Empty→Inputting is handled elsewhere;
            // if we see printable activity in Inputting, disarm and never intercept.
            if state is InputState.Inputting {
                disarmPostCommitReselect()
                return false
            }

            if !postCommitReselectArmed {
                return false
            }

            // Armed + Empty: only ↓ can enter reselect. All other keys pass through.
            if input.isLeft || input.isRight || input.isUp {
                return false
            }

            if input.isDown || input.isExtraChooseCandidateKey {
                guard let client = client as? IMKTextInput else { return false }
                // If reselect cannot start (no char / no surrounding text), pass ↓
                // through so the app keeps native behavior (no stuck intercept).
                return postCommitOpenCandidates(
                    client: client, useVerticalMode: input.useVerticalMode,
                    allowPassThrough: true)
            }

            // Other keys (letters, Enter, etc.): leave armed until real composition
            // starts (Inputting) or deactivate; do not intercept.
            return false
        }

        // --- Active reselect session (PostCommitHighlight) ---
        guard let client = client as? IMKTextInput else {
            return false
        }

        // Esc: put char back, leave Empty; disarm so next arrows are fully native
        // until user explicitly presses ↓ again (if still armed) or re-commits.
        if input.charCode == 27, let hi = state as? InputState.PostCommitHighlight {
            flushHighlight(hi, client: client)
            handle(state: InputState.Empty(), client: client)
            // Stay armed so ↓ can re-enter; native ←/→ still pass when Empty.
            return true
        }

        if input.isLeft {
            return postCommitMove(client: client, direction: -1)
        }
        if input.isRight {
            return postCommitMove(client: client, direction: 1)
        }
        if input.isDown || input.isExtraChooseCandidateKey {
            return postCommitOpenCandidates(
                client: client, useVerticalMode: input.useVerticalMode,
                allowPassThrough: false)
        }
        // ↑: end reselect session, restore char, pass through for native line move.
        if input.isUp {
            if let hi = state as? InputState.PostCommitHighlight {
                flushHighlight(hi, client: client)
                handle(state: InputState.Empty(), client: client)
            }
            return false
        }

        // Any other key: end reselect, restore char, fall through to KeyHandler.
        if let hi = state as? InputState.PostCommitHighlight {
            flushHighlight(hi, client: client)
            handle(state: InputState.Empty(), client: client)
            disarmPostCommitReselect()
            return false
        }

        return false
    }

    private func flushHighlight(_ hi: InputState.PostCommitHighlight, client: IMKTextInput) {
        client.insertText(
            hi.composingBuffer as NSString,
            replacementRange: NSRange(location: NSNotFound, length: NSNotFound))
    }

    /// Move highlight by one grapheme. Always re-reads caret via selectedRange().
    private func postCommitMove(client: IMKTextInput, direction: Int) -> Bool {
        // Flush mark so document + caret are real, then re-query selectedRange().
        if let hi = state as? InputState.PostCommitHighlight {
            flushHighlight(hi, client: client)
        }

        guard let caret = PostCommitReselect.caretLocation(client: client) else {
            degradePostCommitUnsupported()
            return true
        }

        let targetLoc: Int
        if direction < 0 {
            // After flush, caret is after the restored char. ← → previous grapheme.
            if caret <= 0 {
                beepPostCommit()
                handle(state: InputState.Empty(), client: client)
                return true
            }
            guard let startOfRestored = previousClusterStart(client: client, before: caret) else {
                degradePostCommitUnsupported()
                return true
            }
            if startOfRestored <= 0 {
                // Already at first char — re-highlight it (or beep).
                targetLoc = startOfRestored
            } else if let prev = previousClusterStart(client: client, before: startOfRestored) {
                targetLoc = prev
            } else {
                targetLoc = startOfRestored
            }
        } else {
            // → : next grapheme after caret (after flush = char following restored).
            targetLoc = caret
        }

        guard let pending = PostCommitReselect.readCluster(client: client, at: targetLoc) else {
            beepPostCommit()
            handle(state: InputState.Empty(), client: client)
            return true
        }

        _ = PostCommitReselect.pullCommittedIntoMark(
            client: client, documentRange: pending.range, char: pending.char)
        let hi = PostCommitReselect.highlightState(
            char: pending.char, at: pending.range.location)
        handle(state: hi, client: client)
        return true
    }

    /// - Parameter allowPassThrough: when true (Empty entry), return false on
    ///   failure so ↓ is not swallowed and the app keeps native scrolling/nav.
    private func postCommitOpenCandidates(
        client: IMKTextInput, useVerticalMode: Bool, allowPassThrough: Bool
    ) -> Bool {
        var char: String
        var reading: String

        if let hi = state as? InputState.PostCommitHighlight {
            char = hi.composingBuffer
            reading = hi.reading
        } else {
            // Enter reselect from Empty: use live selectedRange() only.
            guard let loc = PostCommitReselect.caretLocation(client: client) else {
                if allowPassThrough { return false }
                degradePostCommitUnsupported()
                return true
            }
            guard let pending = PostCommitReselect.readCluster(client: client, at: loc) else {
                // No char to the right — native ↓ (or user moves caret first).
                if allowPassThrough { return false }
                beepPostCommit()
                return true
            }
            // Pull committed grapheme into marked composition (real delete from committed).
            let pulled = PostCommitReselect.pullCommittedIntoMark(
                client: client, documentRange: pending.range, char: pending.char)
            if !pulled, allowPassThrough {
                // App ignored setMarkedText(replacementRange:) — do not fake highlight.
                return false
            }
            let hi = PostCommitReselect.highlightState(
                char: pending.char, at: pending.range.location)
            handle(state: hi, client: client)
            char = pending.char
            reading = hi.reading
            // Capture range for replacePendingCharacter fallback.
            var docLoc = pending.range.location
            var docLen = pending.range.length
            // Prefer live mark range after pull.
            let mark = client.markedRange()
            if mark.location != NSNotFound, mark.length > 0 {
                docLoc = mark.location
                docLen = mark.length
            }
            return finishOpenCandidates(
                client: client, char: char, reading: reading,
                docLoc: docLoc, docLen: docLen, useVerticalMode: useVerticalMode,
                allowPassThrough: allowPassThrough)
        }

        // Already highlighting.
        let docLoc: Int
        let docLen: Int
        if let hi = state as? InputState.PostCommitHighlight {
            let mark = client.markedRange()
            if mark.location != NSNotFound, mark.length > 0 {
                docLoc = mark.location
                docLen = mark.length
            } else {
                docLoc = hi.documentLocation
                docLen = (char as NSString).length
            }
        } else {
            docLoc = NSNotFound
            docLen = 0
        }
        return finishOpenCandidates(
            client: client, char: char, reading: reading,
            docLoc: docLoc, docLen: docLen, useVerticalMode: useVerticalMode,
            allowPassThrough: allowPassThrough)
    }

    private func finishOpenCandidates(
        client: IMKTextInput, char: String, reading: String,
        docLoc: Int, docLen: Int, useVerticalMode: Bool, allowPassThrough: Bool
    ) -> Bool {
        let cands = PostCommitReselect.candidates(forCharacter: char)
        if cands.isEmpty {
            if allowPassThrough, !(state is InputState.PostCommitHighlight) {
                return false
            }
            beepPostCommit()
            return true
        }

        let choosing = InputState.ChoosingCandidate(
            composingBuffer: char, cursorIndex: 0, candidates: cands,
            useVerticalMode: useVerticalMode)
        choosing.isPostCommitReselect = true
        choosing.postCommitOriginalChar = char
        choosing.postCommitReading = reading
        choosing.postCommitDocLocation = docLoc
        choosing.postCommitDocLength = docLen
        handle(state: choosing, client: client)
        return true
    }

    /// Start of the grapheme that ends at `end` (caret just after that grapheme).
    private func previousClusterStart(client: IMKTextInput, before end: Int) -> Int? {
        let probeLen = min(8, end)
        if probeLen <= 0 { return nil }
        let start = end - probeLen
        let proposed = NSRange(location: start, length: probeLen)
        guard let attr = client.attributedSubstring(from: proposed) as NSAttributedString?,
            !attr.string.isEmpty
        else {
            return nil
        }
        let s = attr.string
        var i = 0
        var lastStart = 0
        let ns = s as NSString
        while i < ns.length {
            lastStart = i
            let next = s.nextUtf16Position(for: i)
            if next <= i { break }
            // Stop when this cluster would end at/after `end` relative to base.
            if start + next >= end {
                break
            }
            i = next
        }
        // If we broke because next crosses end, lastStart is the cluster starting before end.
        if start + lastStart < end {
            // Prefer the cluster that ends at end: walk until next == end - start or past.
            i = 0
            lastStart = 0
            while i < ns.length {
                let next = s.nextUtf16Position(for: i)
                if start + next >= end {
                    lastStart = i
                    break
                }
                lastStart = i
                if next <= i { break }
                i = next
            }
        }
        return start + lastStart
    }

    private func beepPostCommit() {
        if Preferences.beepUponInputError {
            NSSound.beep()
        }
    }

    private func degradePostCommitUnsupported() {
        postCommitReselectArmed = false
        if state is InputState.PostCommitHighlight
            || (state as? InputState.ChoosingCandidate)?.isPostCommitReselect == true
        {
            handle(state: InputState.Empty(), client: currentClient)
        }
    }

    func armPostCommitReselect() {
        postCommitReselectArmed = true
    }

    func disarmPostCommitReselect() {
        postCommitReselectArmed = false
    }
}
