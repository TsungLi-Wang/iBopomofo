// Copyright (c) 2026 and onwards The iBopomofo Authors.
//
// Path β delete-and-recompose reselect after hard commit (shadow reading table).
// Single path: Empty + armed → ←/→ move shadow caret; ↓ delete + recompose.
// Shadow model is the only caret truth — no host selectedRange overwrite,
// no synthetic arrow keys (dual-track removed).

import Cocoa
import InputMethodKit

extension McBopomofoInputMethodController {

    func armShadowFromLastHardCommit(client: Any?) {
        // P0-a: never use `as? [[String: String]]` — ObjC NSArray/NSDictionary
        // does not reliably cast to nested Swift dictionaries.
        guard let nsArray = keyHandler.lastHardCommitShadowUnits,
            nsArray.count > 0
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
        shadowReselect.arm(fromNSArray: nsArray as NSArray, docEndCaret: docEnd)
        shadowRecomposePendingIndex = nil
        if !shadowReselect.armed {
            NSLog("i注音 shadow reselect: arm failed (empty units after parse)")
        }
    }

    /// Returns true if the event was fully handled for shadow reselect.
    func tryHandleShadowReselect(input: KeyHandlerInput, client: Any?) -> Bool {
        if keyHandler.inputMode != .bopomofo {
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

        // Fail-safe only: if host caret left the tracked phrase, disarm.
        // Do NOT rewrite shadow caretIndex from host (single-source shadow).
        let live = client.selectedRange().location
        let liveOpt: Int? = live == NSNotFound ? nil : live
        if !shadowReselect.clientCaretStillInTrackedPhrase(liveOpt) {
            shadowReselect.disarm()
            shadowRecomposePendingIndex = nil
            return false // pass key through; no delete
        }

        // Only intercept ←/→/↓ while armed on Empty.
        if input.isLeft {
            if !shadowReselect.moveLeft() {
                signalReselectUnavailable(reason: "already at start of tracked phrase")
            }
            // Shadow-only: do not synthesize host arrow keys.
            return true
        }
        if input.isRight {
            if !shadowReselect.moveRight() {
                signalReselectUnavailable(reason: "already at end of tracked phrase")
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
        // P0-b: if caret at end (no right-of-caret pending), target last char.
        // Capture "at end" *before* resolve snaps caret onto the last unit.
        let atEnd =
            shadowReselect.caretIndex == shadowReselect.units.count
            && !shadowReselect.units.isEmpty
        guard shadowReselect.resolveReselectTarget() != nil,
            let unit = shadowReselect.reselectTargetUnit
        else {
            signalReselectUnavailable(reason: "no reselect target")
            return true
        }
        let range = shadowReselect.reselectTargetDocumentRange
        // When range is known, replacementRange wins (direction ignored).
        // When range nil and host caret is past the char: backspace fallback.
        let deleteDirection: ShadowDelete.Direction =
            (range == nil && atEnd) ? .backward : .forward

        let result = ShadowDelete.deletePendingGrapheme(
            client: client, documentRange: range, direction: deleteDirection)
        switch result {
        case .deleted:
            break
        case .failedNoRangeOrAccess:
            signalReselectUnavailable(
                reason:
                    "this app cannot in-place reselect (no range / Accessibility)"
            )
            return true
        case .failed:
            signalReselectUnavailable(reason: "delete failed")
            return true
        }

        // Drop unit from shadow; recompose with its reading.
        let pendingIndex = shadowReselect.caretIndex
        let reading = unit.reading
        shadowReselect.removePendingUnit()
        shadowRecomposePendingIndex = pendingIndex

        let next = keyHandler.beginRecompose(
            reading: reading, useVerticalMode: useVerticalMode)
        handle(state: next, client: client)
        return true
    }

    /// Explicit, lightweight feedback when reselect cannot proceed (not silent).
    private func signalReselectUnavailable(reason: String) {
        // Always beep for this path so users know the app does not support
        // in-place reselect — not "broken silently".
        NSSound.beep()
        NSLog("i注音 shadow reselect unavailable: \(reason)")
    }
}
