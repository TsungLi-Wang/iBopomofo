// Copyright (c) 2026 and onwards The iBopomofo Authors.
//
// Delete-and-recompose reselect after hard commit (shadow reading table).
//
// ↓ opens homophone list; old committed char is replaced 1→1 on pick via
// PostCommitReselect.replacePendingCharacter (verify delete / atomic replace).
// Never insert a new char if the old one is still there (would grow the sentence).
// ←/→ after 定案: pass through to app (see prior fix).

import Cocoa
import InputMethodKit

extension McBopomofoInputMethodController {

    func armShadowFromLastHardCommit(client: Any?) {
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
        clearShadowRecomposeContext()
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
            return false
        }

        guard shadowReselect.armed else { return false }
        guard state is InputState.Empty || state is InputState.EmptyIgnoringPreviousState
        else {
            if !(state is InputState.ChoosingCandidate) {
                shadowReselect.disarm()
                clearShadowRecomposeContext()
            }
            return false
        }

        guard let client = client as? IMKTextInput else {
            shadowReselect.disarm()
            return false
        }

        let live = client.selectedRange().location
        let liveOpt: Int? = live == NSNotFound ? nil : live
        let caretReadable = ShadowReselectSession.isReadableDocumentCaret(liveOpt)

        if caretReadable, !shadowReselect.clientCaretStillInTrackedPhrase(liveOpt) {
            shadowReselect.disarm()
            clearShadowRecomposeContext()
            return false
        }

        // ← / → : never intercept (app-native caret).
        if input.isLeft || input.isRight {
            return false
        }

        if input.isUp {
            shadowReselect.disarm()
            clearShadowRecomposeContext()
            return false
        }

        if input.isDown || input.isExtraChooseCandidateKey {
            if caretReadable {
                if !shadowReselect.mapCaretFromDocumentLocation(liveOpt) {
                    shadowReselect.disarm()
                    clearShadowRecomposeContext()
                    return false
                }
            }
            return beginShadowRecompose(client: client, useVerticalMode: input.useVerticalMode)
        }

        shadowReselect.disarm()
        clearShadowRecomposeContext()
        return false
    }

    /// Open homophone list for the pending unit. Does **not** delete yet —
    /// document replace happens on pick (verified 1→1).
    private func beginShadowRecompose(client: IMKTextInput, useVerticalMode: Bool) -> Bool {
        guard shadowReselect.resolveReselectTarget() != nil,
            let unit = shadowReselect.reselectTargetUnit
        else {
            signalReselectUnavailable(reason: "no reselect target")
            return true
        }

        // Prefer live document range at host caret when readable.
        var range = shadowReselect.reselectTargetDocumentRange
        let live = client.selectedRange().location
        if live != NSNotFound {
            if let cluster = PostCommitReselect.readCluster(client: client, at: live),
                cluster.char == unit.value
            {
                // Caret *on* the char (some apps) — use that cluster.
                range = cluster.range
            } else if let cluster = PostCommitReselect.readCluster(client: client, at: live),
                unit.value == cluster.char
            {
                range = cluster.range
            } else if range == nil {
                // Caret left of target (classic): cluster at caret is the pending char.
                if let cluster = PostCommitReselect.readCluster(client: client, at: live) {
                    range = cluster.range
                }
            }
        }

        // Need a usable document range for verified replace. Without it, ↓ cannot
        // safely delete — fail closed (beep) rather than open a list that inserts.
        guard let docRange = range, docRange.location != NSNotFound, docRange.length > 0 else {
            signalReselectUnavailable(
                reason: "no document range for pending char (cannot verify delete)")
            return true
        }

        let pendingIndex = shadowReselect.caretIndex
        shadowRecomposePendingIndex = pendingIndex
        shadowRecomposeDocumentRange = docRange
        shadowRecomposeOldValue = unit.value
        // Keep shadow unit until pick succeeds (do not removePendingUnit yet).

        let next = keyHandler.beginRecompose(
            reading: unit.reading, useVerticalMode: useVerticalMode)
        handle(state: next, client: client)
        return true
    }

    /// Apply chosen homophone: 1→1 replace only. On failure, no insert (no growth).
    func completeShadowRecomposePick(
        client: IMKTextInput?, chosen: String, reading: String
    ) -> Bool {
        guard let pendingIdx = shadowRecomposePendingIndex else { return false }
        guard let imk = client else {
            clearShadowRecomposeContext()
            return false
        }
        let oldValue = shadowRecomposeOldValue ?? ""
        var range = shadowRecomposeDocumentRange
            ?? NSRange(location: NSNotFound, length: 0)

        // Refresh live range if possible (more accurate than arm-time range).
        if range.location != NSNotFound {
            if let live = PostCommitReselect.readCluster(client: imk, at: range.location),
                live.char == oldValue || !oldValue.isEmpty
            {
                if live.char == oldValue {
                    range = live.range
                }
            }
        }

        guard range.location != NSNotFound, range.length > 0, !oldValue.isEmpty else {
            signalReselectUnavailable(reason: "missing range/old value for replace")
            clearShadowRecomposeContext()
            keyHandler.clear()
            return false
        }

        let outcome = PostCommitReselect.replacePendingCharacter(
            client: imk,
            documentRange: range,
            oldChar: oldValue,
            newChar: chosen)

        switch outcome {
        case .replaced:
            // Capture learning context *before* mutating the shadow table.
            let prevForUOM = shadowReselect.previousValue(before: pendingIdx)
            let leftContext = shadowReselect.leftContextString(before: pendingIdx)

            // Update shadow model only after document replace succeeded.
            if shadowReselect.armed {
                // Ensure caretIndex points at the unit we replaced.
                if pendingIdx < shadowReselect.units.count {
                    while shadowReselect.caretIndex > pendingIdx {
                        _ = shadowReselect.moveLeft()
                    }
                    while shadowReselect.caretIndex < pendingIdx {
                        _ = shadowReselect.moveRight()
                    }
                    shadowReselect.updatePendingValue(chosen)
                } else {
                    shadowReselect.insertUnit(
                        reading: reading, value: chosen, at: pendingIdx)
                }
            }

            // R1: feed UOM (soft personalization). Best-effort only — must never
            // undo the successful document replace (seatbelt).
            _ = LanguageModelManager.noteSoftPersonalization(
                previous: prevForUOM, reading: reading, word: chosen)

            // R2: correction log with real left context + wrong_char.
            ManualCorrectionLog.append(
                reading: reading,
                leftContext: leftContext,
                wrongChar: oldValue,
                chosen: chosen)

            clearShadowRecomposeContext()
            keyHandler.clear()
            return true
        case .abortedNoOp:
            signalReselectUnavailable(
                reason: "could not remove old char; not inserting new (no double char)")
            // Clear mark if any so user is not stuck.
            imk.setMarkedText(
                "", selectionRange: NSRange(location: 0, length: 0),
                replacementRange: NSRange(location: NSNotFound, length: NSNotFound))
            clearShadowRecomposeContext()
            keyHandler.clear()
            return false
        }
    }

    func signalReselectUnavailable(reason: String) {
        NSSound.beep()
        NSLog("i注音 shadow reselect unavailable: \(reason)")
    }
}
