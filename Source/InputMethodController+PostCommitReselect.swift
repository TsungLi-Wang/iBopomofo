// Copyright (c) 2026 and onwards The iBopomofo Authors.
//
// Post-commit reselect key handling (←/→/↓) after Enter hard-commit.
// Enter hard-commit itself is not modified here.

import Cocoa
import InputMethodKit
import NSStringUtils

extension McBopomofoInputMethodController {

    /// Returns true if the key was fully handled for post-commit reselect.
    func tryHandlePostCommitReselect(input: KeyHandlerInput, client: Any?) -> Bool {
        // Only Bopomofo mode; never intercept while composing a reading grid
        // (unless we're already in post-commit highlight / its candidate panel).
        if keyHandler.inputMode != .bopomofo {
            return false
        }

        let inHighlight = state is InputState.PostCommitHighlight
        let inPostCandidates =
            (state as? InputState.ChoosingCandidate)?.isPostCommitReselect == true

        // Not armed and not already in a post-commit UI state → ignore.
        if !postCommitReselectArmed && !inHighlight && !inPostCandidates {
            return false
        }

        // Candidate panel keys are handled by KeyHandler / candidate controller.
        if inPostCandidates {
            return false
        }

        // While normal Inputting (grid composition), do not steal keys —
        // except we never arm during composition after hard commit path.
        if state is InputState.Inputting, !inHighlight {
            // User started typing again after commit → disarm.
            if input.charCode != 0 && !input.isLeft && !input.isRight && !input.isDown
                && !input.isUp && !input.isEnter
            {
                postCommitReselectArmed = false
            }
            return false
        }

        guard let client = client as? IMKTextInput else {
            return false
        }

        // Esc: drop highlight back into document, stay armed for another try.
        if input.charCode == 27, let hi = state as? InputState.PostCommitHighlight {
            client.insertText(
                hi.composingBuffer as NSString,
                replacementRange: NSRange(location: NSNotFound, length: NSNotFound))
            handle(state: InputState.Empty(), client: client)
            return true
        }

        if input.isLeft {
            return postCommitMove(client: client, direction: -1)
        }
        if input.isRight {
            return postCommitMove(client: client, direction: 1)
        }
        if input.isDown || input.isExtraChooseCandidateKey {
            return postCommitOpenCandidates(client: client, useVerticalMode: input.useVerticalMode)
        }
        // Up: pass through (line move) — do not intercept.
        if input.isUp {
            // If highlighting, first commit the mark so the app can move.
            if let hi = state as? InputState.PostCommitHighlight {
                client.insertText(
                    hi.composingBuffer as NSString,
                    replacementRange: NSRange(location: NSNotFound, length: NSNotFound))
                handle(state: InputState.Empty(), client: client)
            }
            return false
        }

        // Any other key while highlighting: commit mark, disarm if printable composition.
        if let hi = state as? InputState.PostCommitHighlight {
            client.insertText(
                hi.composingBuffer as NSString,
                replacementRange: NSRange(location: NSNotFound, length: NSNotFound))
            handle(state: InputState.Empty(), client: client)
            // Let the key fall through to KeyHandler for new composition.
            return false
        }

        return false
    }

    /// direction: -1 left, +1 right. Pending char = grapheme at the new caret (right of caret).
    private func postCommitMove(client: IMKTextInput, direction: Int) -> Bool {
        // Flush current highlight into the document first.
        if let hi = state as? InputState.PostCommitHighlight {
            client.insertText(
                hi.composingBuffer as NSString,
                replacementRange: NSRange(location: NSNotFound, length: NSNotFound))
            // After insert, caret is after the restored character.
        }

        guard var loc = PostCommitReselect.caretLocation(client: client) else {
            degradePostCommitUnsupported()
            return true
        }

        if direction < 0 {
            // Move caret one grapheme left, then pending = cluster starting at caret.
            if loc <= 0 {
                beepPostCommit()
                handle(state: InputState.Empty(), client: client)
                return true
            }
            // Walk left: we need the start of the grapheme that ends at `loc`.
            // Read a bit of text before caret to find previous boundary.
            guard let prevStart = previousClusterStart(client: client, before: loc) else {
                degradePostCommitUnsupported()
                return true
            }
            loc = prevStart
        } else {
            // Move caret past current pending (if any) then highlight next.
            // Caret is at loc; pending is at loc; after right, caret = end of that cluster.
            guard let cluster = PostCommitReselect.readCluster(client: client, at: loc) else {
                // Nothing to the right.
                beepPostCommit()
                handle(state: InputState.Empty(), client: client)
                return true
            }
            loc = cluster.range.location + cluster.range.length
        }

        guard let pending = PostCommitReselect.readCluster(client: client, at: loc) else {
            beepPostCommit()
            handle(state: InputState.Empty(), client: client)
            return true
        }

        // Pull pending char into marked text for visual highlight.
        let hi = PostCommitReselect.highlightState(
            char: pending.char, at: pending.range.location)
        client.setMarkedText(
            hi.attributedString,
            selectionRange: NSRange(location: 0, length: 0),
            replacementRange: pending.range)
        handle(state: hi, client: client)
        // handle() will setMarkedText again — ok.
        return true
    }

    private func postCommitOpenCandidates(client: IMKTextInput, useVerticalMode: Bool) -> Bool {
        // Ensure we have a highlighted pending char.
        var char: String
        var reading: String
        if let hi = state as? InputState.PostCommitHighlight {
            char = hi.composingBuffer
            reading = hi.reading
        } else {
            guard let loc = PostCommitReselect.caretLocation(client: client) else {
                degradePostCommitUnsupported()
                return true
            }
            guard let pending = PostCommitReselect.readCluster(client: client, at: loc) else {
                // At end of text: no char to the right — require ← first.
                beepPostCommit()
                return true
            }
            let hi = PostCommitReselect.highlightState(
                char: pending.char, at: pending.range.location)
            client.setMarkedText(
                hi.attributedString,
                selectionRange: NSRange(location: 0, length: 0),
                replacementRange: pending.range)
            handle(state: hi, client: client)
            char = pending.char
            reading = hi.reading
        }

        let cands = PostCommitReselect.candidates(forCharacter: char)
        if cands.isEmpty {
            // No reading / model miss — degrade silently (keep highlight).
            beepPostCommit()
            return true
        }

        let choosing = InputState.ChoosingCandidate(
            composingBuffer: char, cursorIndex: 0, candidates: cands,
            useVerticalMode: useVerticalMode)
        choosing.isPostCommitReselect = true
        choosing.postCommitOriginalChar = char
        choosing.postCommitReading = reading
        handle(state: choosing, client: client)
        return true
    }

    /// Find start index of the grapheme that ends at `end` (caret after that grapheme).
    private func previousClusterStart(client: IMKTextInput, before end: Int) -> Int? {
        // Read up to 4 UTF-16 units before `end`.
        let probeLen = min(4, end)
        let start = end - probeLen
        let proposed = NSRange(location: start, length: probeLen)
        guard let attr = client.attributedSubstring(from: proposed) as NSAttributedString?,
            !attr.string.isEmpty
        else {
            return nil
        }
        let s = attr.string
        let base = start
        // Walk grapheme starts within s; last cluster is the one ending at end.
        var i = 0
        var lastStart = 0
        let ns = s as NSString
        while i < ns.length {
            lastStart = i
            let next = s.nextUtf16Position(for: i)
            if next <= i { break }
            i = next
        }
        return base + lastStart
    }

    private func beepPostCommit() {
        if Preferences.beepUponInputError {
            NSSound.beep()
        }
    }

    private func degradePostCommitUnsupported() {
        // Client has no surrounding-text support — stay silent (no crash).
        postCommitReselectArmed = false
        if !(state is InputState.Empty) {
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
