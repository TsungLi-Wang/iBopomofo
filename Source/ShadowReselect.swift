// Copyright (c) 2026 and onwards The iBopomofo Authors.
//
// Path β "delete-and-recompose" post-hard-commit reselect:
// - Shadow reading table is the single caret truth (not host selectedRange)
// - ↓: delete pending char + open homophone list for its reading
// - At sentence end (no pending right of caret): target last char left of caret
// - Fail-safe: mouse/focus/out-of-range invalidates — never synthesize delete when unsure

import Cocoa
import InputMethodKit
import NSStringUtils

struct ShadowUnit {
    let reading: String
    var value: String
    var utf16Length: Int { (value as NSString).length }
}

/// Tracks one hard-committed phrase for optional reselect.
final class ShadowReselectSession {
    private(set) var units: [ShadowUnit]
    /// Insertion point in [0, units.count]; pending (right-of-caret) is units[caretIndex]
    /// when caretIndex < count. At end, ↓ still targets units[count-1] (left of caret).
    private(set) var caretIndex: Int
    /// Document UTF-16 location of units[0] at arm time (from selectedRange after commit).
    private(set) var docBase: Int
    private(set) var armed: Bool = false

    init() {
        units = []
        caretIndex = 0
        docBase = NSNotFound
    }

    var totalUTF16: Int { units.reduce(0) { $0 + $1.utf16Length } }

    /// Char strictly to the right of caret (classic pending). Nil at sentence end.
    var pendingUnit: ShadowUnit? {
        guard armed, caretIndex >= 0, caretIndex < units.count else { return nil }
        return units[caretIndex]
    }

    /// Index targeted by ↓: right-of-caret if any; else last char when caret at end.
    var reselectTargetIndex: Int? {
        guard armed, !units.isEmpty else { return nil }
        if caretIndex >= 0, caretIndex < units.count {
            return caretIndex
        }
        if caretIndex == units.count {
            return units.count - 1
        }
        return nil
    }

    var reselectTargetUnit: ShadowUnit? {
        guard let idx = reselectTargetIndex else { return nil }
        return units[idx]
    }

    /// Document range of the ↓ target grapheme, or nil if base unknown.
    var reselectTargetDocumentRange: NSRange? {
        guard let idx = reselectTargetIndex, docBase != NSNotFound else { return nil }
        var loc = docBase
        for i in 0..<idx {
            loc += units[i].utf16Length
        }
        return NSRange(location: loc, length: units[idx].utf16Length)
    }

    /// Snap caret to the reselect target so removePendingUnit works after ↓.
    /// Returns the target index, or nil if none.
    @discardableResult
    func resolveReselectTarget() -> Int? {
        guard let idx = reselectTargetIndex else { return nil }
        caretIndex = idx
        return idx
    }

    /// Arm from ObjC `NSArray` of dicts (avoids fragile `as? [[String:String]]`).
    /// Accepts NSDictionary, [String:String], and [AnyHashable:Any] elements.
    func arm(fromNSArray nsArray: NSArray, docEndCaret: Int?) {
        var built: [ShadowUnit] = []
        for item in nsArray {
            let reading: String?
            let value: String?
            if let d = item as? NSDictionary {
                reading = (d["reading"] as? String) ?? (d["reading"] as? NSString).map { $0 as String }
                value = (d["value"] as? String) ?? (d["value"] as? NSString).map { $0 as String }
            } else if let d = item as? [String: String] {
                reading = d["reading"]
                value = d["value"]
            } else if let d = item as? [AnyHashable: Any] {
                reading = d["reading"] as? String
                value = d["value"] as? String
            } else {
                continue
            }
            guard let r = reading, let v = value, !v.isEmpty else { continue }
            built.append(ShadowUnit(reading: r, value: v))
        }
        arm(units: built, docEndCaret: docEndCaret)
    }

    func arm(units raw: [[String: String]], docEndCaret: Int?) {
        let built: [ShadowUnit] = raw.compactMap { d in
            guard let r = d["reading"], let v = d["value"], !v.isEmpty else { return nil }
            return ShadowUnit(reading: r, value: v)
        }
        arm(units: built, docEndCaret: docEndCaret)
    }

    private func arm(units built: [ShadowUnit], docEndCaret: Int?) {
        units = built
        guard !units.isEmpty else {
            disarm()
            return
        }
        caretIndex = units.count // after last char
        if let end = docEndCaret, end != NSNotFound {
            docBase = end - totalUTF16
            if docBase < 0 { docBase = NSNotFound }
        } else {
            docBase = NSNotFound
        }
        armed = true
    }

    func disarm() {
        armed = false
        units = []
        caretIndex = 0
        docBase = NSNotFound
    }

    /// Fail-safe only: true if host caret is still inside the tracked phrase
    /// (or unreadable). Does **not** overwrite shadow caretIndex — shadow is
    /// the single source of truth for ←/→/↓ after arm.
    func clientCaretStillInTrackedPhrase(_ location: Int?) -> Bool {
        guard armed else { return false }
        guard let loc = location, loc != NSNotFound else {
            // Non-cooperative field: keep shadow-only mode.
            return true
        }
        if docBase == NSNotFound {
            // Infer base once if we never had one (caret at end after commit).
            docBase = loc - totalUTF16
            if docBase < 0 {
                return false
            }
            return true
        }
        let end = docBase + totalUTF16
        if loc < docBase || loc > end {
            return false // left the phrase (mouse / other edit)
        }
        return true
    }

    /// Legacy name — maps to fail-safe only; does not re-sync caret from host.
    func syncFromClientCaret(_ location: Int?) -> Bool {
        clientCaretStillInTrackedPhrase(location)
    }

    func moveLeft() -> Bool {
        guard armed, caretIndex > 0 else { return false }
        caretIndex -= 1
        return true
    }

    func moveRight() -> Bool {
        guard armed, caretIndex < units.count else { return false }
        caretIndex += 1
        return true
    }

    func updatePendingValue(_ newValue: String) {
        guard armed, caretIndex < units.count else { return }
        units[caretIndex].value = newValue
        caretIndex = min(caretIndex + 1, units.count)
    }

    func removePendingUnit() {
        guard armed, caretIndex < units.count else { return }
        let removedLen = units[caretIndex].utf16Length
        units.remove(at: caretIndex)
        // caretIndex stays (now points to next char). Shrink doc span only.
        // docBase unchanged (deletion was at this index).
        _ = removedLen
        if units.isEmpty {
            armed = true // keep session shell until pick restores or empty disarm
        }
    }

    func insertUnit(reading: String, value: String, at index: Int) {
        let u = ShadowUnit(reading: reading, value: value)
        let i = max(0, min(index, units.count))
        // After delete, docBase still points at original start; inserted char
        // occupies the hole. totalUTF16 grows again.
        units.insert(u, at: i)
        caretIndex = min(i + 1, units.count)
        armed = true
    }
}

enum ShadowDelete {
    /// Forward-delete key code (deletes char to the *right* of the caret).
    static let forwardDeleteKeyCode: CGKeyCode = 0x75 // kVK_ForwardDelete
    /// Delete/backspace (deletes char to the *left* of the caret).
    static let backwardDeleteKeyCode: CGKeyCode = 0x33 // kVK_Delete

    enum Direction {
        case forward // right of caret
        case backward // left of caret (sentence-end last-char case)
    }

    enum Result {
        case deleted
        case failedNoRangeOrAccess
        case failed
    }

    static var accessibilityTrusted: Bool {
        AXIsProcessTrusted()
    }

    /// Try to delete one grapheme at documentRange (preferred), else CGEvent.
    @discardableResult
    static func deletePendingGrapheme(
        client: IMKTextInput,
        documentRange: NSRange?,
        direction: Direction = .forward
    ) -> Result {
        if let range = documentRange, range.location != NSNotFound, range.length > 0 {
            client.insertText(
                "" as NSString,
                replacementRange: range)
            return .deleted
        }
        if accessibilityTrusted {
            let ok: Bool
            switch direction {
            case .forward:
                ok = postKey(forwardDeleteKeyCode)
            case .backward:
                ok = postKey(backwardDeleteKeyCode)
            }
            return ok ? .deleted : .failed
        }
        return .failedNoRangeOrAccess
    }

    /// Legacy API used by older call sites.
    @discardableResult
    static func deletePendingGrapheme(
        client: IMKTextInput,
        documentRange: NSRange?
    ) -> Bool {
        switch deletePendingGrapheme(client: client, documentRange: documentRange, direction: .forward) {
        case .deleted: return true
        default: return false
        }
    }

    static func postForwardDelete() -> Bool {
        postKey(forwardDeleteKeyCode)
    }

    static func postBackwardDelete() -> Bool {
        postKey(backwardDeleteKeyCode)
    }

    private static func postKey(_ code: CGKeyCode) -> Bool {
        guard let src = CGEventSource(stateID: .hidSystemState) else { return false }
        guard let down = CGEvent(
            keyboardEventSource: src, virtualKey: code, keyDown: true),
            let up = CGEvent(
                keyboardEventSource: src, virtualKey: code, keyDown: false)
        else {
            return false
        }
        down.post(tap: .cghidEventTap)
        up.post(tap: .cghidEventTap)
        return true
    }
}
