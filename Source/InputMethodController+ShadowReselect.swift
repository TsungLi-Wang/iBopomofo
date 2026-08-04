// Copyright (c) 2026 and onwards The iBopomofo Authors.
//
// Delete-and-recompose reselect after hard commit (shadow reading table).
// Narrow intercept: only while shadowReselect.armed && Empty (or recompose candidates).

import Cocoa
import InputMethodKit

extension McBopomofoInputMethodController {

    func armShadowFromLastHardCommit(client: Any?) {
        guard let units = keyHandler.lastHardCommitShadowUnits as? [[String: String]],
            !units.isEmpty
        else {
            shadowReselect.disarm()
            return
        }
        var docEnd: Int?
        if let imk = client as? IMKTextInput {
            let sel = imk.selectedRange()
            if sel.location != NSNotFound {
                docEnd = sel.location
            }
        }
        shadowReselect.arm(units: units, docEndCaret: docEnd)
        shadowRecomposePendingIndex = nil
    }

    /// Returns true if the event was fully handled for shadow reselect.
    func tryHandleShadowReselect(input: KeyHandlerInput, client: Any?) -> Bool {
        if keyHandler.inputMode != .bopomofo {
            return false
        }

        // Soft-finalized marked composition: native grid path owns keys.
        if keyHandler.softFinalized, state is InputState.Inputting {
            return false
        }

        let inShadowCandidates =
            (state as? InputState.ChoosingCandidate) != nil
            && shadowRecomposePendingIndex != nil

        if inShadowCandidates {
            // Let KeyHandler / candidate controller handle pick / nav.
            return false
        }

        guard shadowReselect.armed else { return false }
        guard state is InputState.Empty || state is InputState.EmptyIgnoringPreviousState
        else {
            // Left Empty without us → desync.
            if !(state is InputState.ChoosingCandidate) {
                shadowReselect.disarm()
                shadowRecomposePendingIndex = nil
            }
            return false
        }

        guard let client = client as? IMKTextInput else {
            shadowReselect.disarm()
            return false
        }

        // Fail-safe: re-sync from live caret when readable.
        let live = client.selectedRange().location
        let liveOpt: Int? = live == NSNotFound ? nil : live
        if !shadowReselect.syncFromClientCaret(liveOpt) {
            shadowReselect.disarm()
            shadowRecomposePendingIndex = nil
            return false // pass key through; no delete
        }

        // Only intercept ←/→/↓ while armed on Empty.
        if input.isLeft {
            if !shadowReselect.moveLeft() {
                if Preferences.beepUponInputError { NSSound.beep() }
            } else {
                // Move host caret left one grapheme by synthesizing left arrow
                // only when we also own reselect — keeps host in sync when possible.
                postArrowKey(left: true)
            }
            return true
        }
        if input.isRight {
            if !shadowReselect.moveRight() {
                if Preferences.beepUponInputError { NSSound.beep() }
            } else {
                postArrowKey(left: false)
            }
            return true
        }
        if input.isUp {
            // Native line move — invalidate shadow (we cannot track multi-line).
            shadowReselect.disarm()
            shadowRecomposePendingIndex = nil
            return false
        }
        if input.isDown || input.isExtraChooseCandidateKey {
            return beginShadowRecompose(client: client, useVerticalMode: input.useVerticalMode)
        }

        // Any other key: disarm, do not steal.
        shadowReselect.disarm()
        shadowRecomposePendingIndex = nil
        return false
    }

    private func beginShadowRecompose(client: IMKTextInput, useVerticalMode: Bool) -> Bool {
        guard let unit = shadowReselect.pendingUnit else {
            if Preferences.beepUponInputError { NSSound.beep() }
            return true
        }
        let range = shadowReselect.pendingDocumentRange

        // Delete the committed grapheme (right of caret).
        let deleted = ShadowDelete.deletePendingGrapheme(
            client: client, documentRange: range)
        if !deleted {
            // Cannot safely delete — fail closed, no partial recompose.
            if Preferences.beepUponInputError { NSSound.beep() }
            // If Accessibility would help, leave a one-time log.
            if !ShadowDelete.accessibilityTrusted {
                NSLog(
                    "i注音 shadow reselect: delete failed; enable Accessibility for CGEvent forward-delete fallback"
                )
            }
            return true
        }

        // Drop unit from shadow; recompose with its reading.
        let pendingIndex = shadowReselect.caretIndex
        let reading = unit.reading
        shadowReselect.removePendingUnit()
        // After remove, units shifted; keep index for value update on pick.
        shadowRecomposePendingIndex = pendingIndex

        let next = keyHandler.beginRecompose(
            reading: reading, useVerticalMode: useVerticalMode)
        handle(state: next, client: client)
        return true
    }

    private func postArrowKey(left: Bool) {
        // Optional host caret sync. Only when Accessibility trusted to avoid noise.
        guard ShadowDelete.accessibilityTrusted else { return }
        let code: CGKeyCode = left ? 0x7B : 0x7C // left / right arrow
        guard let src = CGEventSource(stateID: .hidSystemState) else { return }
        guard let down = CGEvent(keyboardEventSource: src, virtualKey: code, keyDown: true),
            let up = CGEvent(keyboardEventSource: src, virtualKey: code, keyDown: false)
        else { return }
        down.post(tap: .cghidEventTap)
        up.post(tap: .cghidEventTap)
    }
}
