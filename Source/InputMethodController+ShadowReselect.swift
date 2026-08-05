// Copyright (c) 2026 and onwards The iBopomofo Authors.
//
// Delete-and-recompose reselect after hard commit (shadow reading table).
//
// ←/→ after 定案: default to **app-native** caret move. Never eat arrows when
// selectedRange is NSNotFound (LINE / Telegram / many web fields). Only when
// host caret is readable *and* aligns with the shadow phrase may we briefly
// treat arrows as reselect navigation — and even then we prefer pass-through
// so host cursor stays correct (shadow re-maps from selectedRange on ↓).
// ↓: delete + recompose; at end targets last char.

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

        let live = client.selectedRange().location
        let liveOpt: Int? = live == NSNotFound ? nil : live
        let caretReadable = ShadowReselectSession.isReadableDocumentCaret(liveOpt)

        // Outside phrase (only when readable) → disarm, never delete.
        if caretReadable, !shadowReselect.clientCaretStillInTrackedPhrase(liveOpt) {
            shadowReselect.disarm()
            shadowRecomposePendingIndex = nil
            return false
        }

        // ── ← / → ──────────────────────────────────────────────────────────
        // Default: app-native cursor. Never intercept when caret unreadable
        // (LINE / Telegram / most web boxes). When readable and still in phrase,
        // still pass through so the host moves the real caret; ↓ will re-map
        // shadow from selectedRange. Armed stays for ↓ reselect.
        if input.isLeft || input.isRight {
            if !caretReadable {
                // Cannot align → do not eat arrows.
                return false
            }
            if !shadowReselect.canAlignArrowKeysWithHostCaret(liveOpt) {
                // Readable but not alignable (e.g. no docBase) → pass through.
                return false
            }
            // Alignable: still do not consume — native move is required UX.
            // (Reselect navigation is driven by host caret at ↓ time.)
            return false
        }

        if input.isUp {
            // Native line move — invalidate shadow (we cannot track multi-line).
            shadowReselect.disarm()
            shadowRecomposePendingIndex = nil
            return false
        }

        if input.isDown || input.isExtraChooseCandidateKey {
            // Prefer host caret → shadow map when readable; else end = last char.
            if caretReadable {
                if !shadowReselect.mapCaretFromDocumentLocation(liveOpt) {
                    // Caret left phrase between keys.
                    shadowReselect.disarm()
                    shadowRecomposePendingIndex = nil
                    return false
                }
            }
            return beginShadowRecompose(client: client, useVerticalMode: input.useVerticalMode)
        }

        // Any other key: disarm, do not steal.
        shadowReselect.disarm()
        shadowRecomposePendingIndex = nil
        return false
    }

    private func beginShadowRecompose(client: IMKTextInput, useVerticalMode: Bool) -> Bool {
        // P0-b: if caret at end (no right-of-caret pending), target last char.
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
        NSSound.beep()
        NSLog("i注音 shadow reselect unavailable: \(reason)")
    }
}
