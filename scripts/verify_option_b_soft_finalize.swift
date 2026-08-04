#!/usr/bin/env swift
// Option B simulation (TextEdit text system = NSTextView):
// Soft-finalize keeps whole sentence as marked text; reselect replaces one
// grapheme inside the mark; Enter hard-commits mark then app would get Enter.
// Run: swift scripts/verify_option_b_soft_finalize.swift

import AppKit
import Foundation

var fails = 0
func check(_ name: String, _ got: String, _ want: String) {
    if got == want {
        print("PASS \(name): \"\(got)\" len=\((got as NSString).length)")
    } else {
        print("FAIL \(name): got \"\(got)\" want \"\(want)\"")
        fails += 1
    }
}

let tv = NSTextView(frame: NSRect(x: 0, y: 0, width: 400, height: 200))

// 1) Soft-finalize: whole sentence marked (not hard-committed)
let sentence = "我是學生"
tv.setMarkedText(
    NSAttributedString(string: sentence),
    selectedRange: NSRange(location: sentence.utf16.count, length: 0),
    replacementRange: NSRange(location: NSNotFound, length: NSNotFound))
print("SOFT-FINALIZE marked: \"\(tv.string)\" markedRange=\(tv.markedRange())")
check("still marked owned", tv.string, sentence)
check("mark covers sentence", "\(tv.markedRange().length)", "\((sentence as NSString).length)")

// 2) Reselect one char inside mark: replace 是→視 by rewriting full marked string
//    (native grid path does overrideCandidate + rebuild composing buffer)
let revised = "我視學生"
tv.setMarkedText(
    NSAttributedString(string: revised),
    selectedRange: NSRange(location: 2, length: 0),
    replacementRange: NSRange(location: NSNotFound, length: NSNotFound))
check("reselect 是→視 in mark", tv.string, revised)
check("length still 4", "\((tv.string as NSString).length)", "4")

// 3) Continuous reselect 學→血
let revised2 = "我視血生"
tv.setMarkedText(
    NSAttributedString(string: revised2),
    selectedRange: NSRange(location: 3, length: 0),
    replacementRange: NSRange(location: NSNotFound, length: NSNotFound))
check("reselect 學→血", tv.string, revised2)

// 4) Enter hard-commit: insertText replaces mark (leaves committed text)
tv.insertText(revised2, replacementRange: NSRange(location: NSNotFound, length: NSNotFound))
check("after Enter hard-commit", tv.string, revised2)
check("mark cleared", "\(tv.markedRange().location == NSNotFound || tv.markedRange().length == 0)", "true")
print("ENTER: text committed to field; host would also receive Enter for send/newline")

if fails == 0 {
    print("ALL OPTION-B CHECKS PASSED (NSTextView/TextEdit parity)")
    exit(0)
} else {
    print("FAILED \(fails)")
    exit(1)
}
