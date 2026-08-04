// Copyright (c) 2026 and onwards The iBopomofo Authors.
//
// "Delete-and-recompose" post-hard-commit reselect:
// - Shadow reading table follows caret (actual readings at commit time)
// - ↓: delete pending char (right of caret) + open homophone list for its reading
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
    /// Insertion point in [0, units.count]; pending char is units[caretIndex] if caretIndex < count.
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

    var pendingUnit: ShadowUnit? {
        guard armed, caretIndex >= 0, caretIndex < units.count else { return nil }
        return units[caretIndex]
    }

    /// Document range of the pending grapheme, or nil if unknown.
    var pendingDocumentRange: NSRange? {
        guard let _ = pendingUnit, docBase != NSNotFound else { return nil }
        var loc = docBase
        for i in 0..<caretIndex {
            loc += units[i].utf16Length
        }
        return NSRange(location: loc, length: units[caretIndex].utf16Length)
    }

    func arm(units raw: [[String: String]], docEndCaret: Int?) {
        units = raw.compactMap { d in
            guard let r = d["reading"], let v = d["value"], !v.isEmpty else { return nil }
            return ShadowUnit(reading: r, value: v)
        }
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

    /// Re-sync from live selectedRange; returns false if desynced → caller must disarm.
    func syncFromClientCaret(_ location: Int?) -> Bool {
        guard armed else { return false }
        guard let loc = location, loc != NSNotFound else {
            // Cannot read caret in non-cooperative field — keep shadow-only mode.
            return true
        }
        if docBase == NSNotFound {
            // Infer base if we never had one (caret at end after commit).
            docBase = loc - totalUTF16
            if docBase < 0 {
                return false
            }
        }
        let end = docBase + totalUTF16
        if loc < docBase || loc > end {
            return false // left the phrase
        }
        // Map loc → caretIndex
        var acc = docBase
        var idx = 0
        while idx < units.count, acc + units[idx].utf16Length <= loc {
            acc += units[idx].utf16Length
            idx += 1
        }
        caretIndex = idx
        return true
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
        let oldLen = units[caretIndex].utf16Length
        units[caretIndex].value = newValue
        let newLen = units[caretIndex].utf16Length
        // caret stays before/at this unit; after replace user typically is after char
        caretIndex = min(caretIndex + 1, units.count)
        _ = oldLen
        _ = newLen
    }

    func removePendingUnit() {
        guard armed, caretIndex < units.count else { return }
        units.remove(at: caretIndex)
        // caretIndex stays (now points to next char)
        if units.isEmpty {
            armed = true // keep session shell until pick restores or empty disarm
        }
    }

    func insertUnit(reading: String, value: String, at index: Int) {
        let u = ShadowUnit(reading: reading, value: value)
        let i = max(0, min(index, units.count))
        units.insert(u, at: i)
        caretIndex = min(i + 1, units.count)
        armed = true
    }
}

enum ShadowDelete {
    /// Forward-delete key code (deletes char to the *right* of the caret).
    static let forwardDeleteKeyCode: CGKeyCode = 0x75 // kVK_ForwardDelete

    static var accessibilityTrusted: Bool {
        AXIsProcessTrusted()
    }

    /// Try to delete one grapheme to the right of the caret.
    /// 1) insertText("", replacementRange:) if range known
    /// 2) CGEvent forward-delete if Accessibility trusted
    /// Returns true if a delete was attempted (not guaranteed success in all apps).
    @discardableResult
    static func deletePendingGrapheme(
        client: IMKTextInput,
        documentRange: NSRange?
    ) -> Bool {
        if let range = documentRange, range.location != NSNotFound, range.length > 0 {
            client.insertText(
                "" as NSString,
                replacementRange: range)
            return true
        }
        if accessibilityTrusted {
            return postForwardDelete()
        }
        return false
    }

    static func postForwardDelete() -> Bool {
        guard let src = CGEventSource(stateID: .hidSystemState) else { return false }
        guard let down = CGEvent(
            keyboardEventSource: src, virtualKey: forwardDeleteKeyCode, keyDown: true),
            let up = CGEvent(
                keyboardEventSource: src, virtualKey: forwardDeleteKeyCode, keyDown: false)
        else {
            return false
        }
        down.post(tap: .cghidEventTap)
        up.post(tap: .cghidEventTap)
        return true
    }
}
